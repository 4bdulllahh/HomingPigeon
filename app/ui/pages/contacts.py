"""Contacts: import a spreadsheet, map columns, manage the list and the do-not-contact list."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtWidgets import QFileDialog, QGridLayout, QHBoxLayout, QMenu, QVBoxLayout, QWidget

from app.core import db, importer, prefs
from app.models.contacts_model import ContactsModel, all_contact_emails
from app.models.table_model import SimpleTableModel
from app.ui import theme
from app.ui.pages.base import Page
from app.ui.widgets.common import (FormRow, ProgressRow, ScrollPage, Section, TabBar,
                                   clear_layout, danger_button, hint, muted, primary_button, row,
                                   secondary_button, set_tone)
from app.ui.widgets.dialogs import ConfirmDialog
from app.ui.widgets.inputs import (Debouncer, checkbox, combo, line_edit, read_only_box,
                                   set_combo_values, update_completer)
from app.ui.widgets.tables import DataTable
from app.workers import jobs
from app.workers.base import Task

PREVIEW_HEADERS = ["Email", "Company", "Contact person"]


class ContactsPage(Page):
    def __init__(self, window):
        super().__init__(window)
        self._path: Path | None = None
        self._dataframe = None
        self._import_worker: jobs.ImportWorker | None = None
        self._column_pickers: dict[str, object] = {}

        self.add_header(
            "Contacts",
            "Import your spreadsheet. The app finds the email, company and contact columns "
            "automatically, then removes duplicates, invalid addresses and dead domains before "
            "anything is sent.")

        self.tabs = TabBar()
        self.tabs.add("Import", self._build_import)
        self.tabs.add("My contacts", self._build_list)
        self.tabs.add("Do not contact", self._build_suppression)
        self.root.addWidget(self.tabs, 1)
        self.tabs.set("Import")

    # =======================================================================
    # Import
    # =======================================================================
    def _build_import(self) -> QWidget:
        area = ScrollPage(spacing=12)

        picker = Section("1. Choose your file",
                         "Excel (.xlsx, .xls) or CSV. The original file is only read, never changed.")
        self.file_label = muted("No file selected", wrap=False)
        picker.add(row(self.file_label, None, primary_button("Browse...", self._browse, 120)))

        self.sheet_row = FormRow("Sheet")
        self.sheet_picker = combo(["-"], on_change=lambda _t: self._load_preview())
        self.sheet_row.add(self.sheet_picker)
        self.sheet_row.setVisible(False)
        picker.add(self.sheet_row)
        area.add(picker)

        self.mapping_section = Section(
            "2. Check the columns",
            "Detected automatically. Change any that are wrong. Every other column is kept "
            "and becomes available as a merge tag in your templates.")
        self.mapping_section.setVisible(False)
        area.add(self.mapping_section)

        self.options_section = Section("3. Import")
        self.options_section.setVisible(False)
        self.check_mx = checkbox(
            "Check that each domain can actually receive mail (recommended)", True)
        self.options_section.add(self.check_mx)
        self.options_section.add(hint(
            "Looks up the mail server for every domain and drops addresses that cannot receive "
            "mail. This is slower on a large list but prevents the bounces that get domains "
            "blacklisted."))

        self.import_button = primary_button("Import contacts", self._start_import, 180)
        self.cancel_button = secondary_button("Cancel", self._cancel_import, 110)
        self.cancel_button.setVisible(False)
        self.options_section.add(row(self.import_button, self.cancel_button, None))

        self.progress = ProgressRow()
        self.progress.setVisible(False)
        self.options_section.add(self.progress)
        self.import_status = muted("")
        self.options_section.add(self.import_status)
        area.add(self.options_section)

        self.result_section = Section("Import result")
        self.result_section.setVisible(False)
        self.result_label = muted("")
        self.result_section.add(self.result_label)
        self.problems_box = read_only_box("", role="mono", lines=8)
        self.problems_box.setVisible(False)
        self.result_section.add(self.problems_box)
        area.add(self.result_section)

        area.add_stretch()
        return area

    def _browse(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, "Select your contact list", "",
            "Spreadsheets (*.xlsx *.xls *.csv);;All files (*.*)")
        if not path:
            return
        self._path = Path(path)
        self.file_label.setText(self._path.name)
        set_tone(self.file_label, "bright")
        self.import_status.setText("Opening the file...")

        Task(jobs.read_sheet_names, self._path).start(
            on_result=self._sheets_ready,
            on_error=lambda message: self._fail(f"Could not open the file: {message}"))

    def _sheets_ready(self, sheets: list[str]) -> None:
        set_combo_values(self.sheet_picker, sheets, sheets[0] if sheets else None)
        self.sheet_row.setVisible(len(sheets) > 1)
        self._load_preview()

    def _load_preview(self) -> None:
        if not self._path:
            return
        sheet = self.sheet_picker.currentText()
        self.import_status.setText("Reading the sheet...")
        set_tone(self.import_status, "muted")

        Task(jobs.read_preview, self._path, None if sheet in ("CSV", "-") else sheet).start(
            on_result=self._preview_ready,
            on_error=lambda message: self._fail(f"Could not read the sheet: {message}"))

    def _preview_ready(self, result) -> None:
        self._dataframe, mapping = result
        self.import_status.setText("")

        clear_layout(self.mapping_section.body_layout)
        self._column_pickers = {}

        columns = ["(none)"] + [str(c) for c in self._dataframe.columns]
        grid_holder = QWidget()
        grid_holder.setProperty("role", "plain")
        grid = QGridLayout(grid_holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)
        for index in range(3):
            grid.setColumnStretch(index, 1)

        for index, (key, title, detected) in enumerate([
            ("email", "Email address (required)", mapping.email),
            ("company", "Company name", mapping.company),
            ("person", "Contact person", mapping.person),
        ]):
            form = FormRow(title)
            picker = combo(columns, str(detected) if detected else "(none)",
                           on_change=lambda _t: self._refresh_preview_rows())
            form.add(picker)
            grid.addWidget(form, 0, index)
            self._column_pickers[key] = picker
        self.mapping_section.add(grid_holder)

        found = sum(1 for m in (mapping.email, mapping.company, mapping.person) if m)
        self.mapping_section.add(muted(
            f"{len(self._dataframe):,} rows · {len(self._dataframe.columns)} columns · "
            f"{found} of 3 mapped automatically"))

        self.preview_model = SimpleTableModel(PREVIEW_HEADERS)
        self.preview_table = DataTable(self.preview_model, "No rows to preview.")
        self.preview_table.setMinimumHeight(round(170 * theme.text_scale()))
        self.preview_table.setMaximumHeight(round(200 * theme.text_scale()))
        self.mapping_section.add(self.preview_table)
        self._refresh_preview_rows()

        self.mapping_section.setVisible(True)
        self.options_section.setVisible(True)

    def _current_mapping(self) -> importer.ColumnMapping:
        def value(key: str) -> str | None:
            chosen = self._column_pickers[key].currentText()
            return None if chosen == "(none)" else chosen

        mapping = importer.ColumnMapping(email=value("email"), company=value("company"),
                                         person=value("person"))
        chosen = {mapping.email, mapping.company, mapping.person}
        mapping.extras = [c for c in self._dataframe.columns if c not in chosen]
        return mapping

    def _refresh_preview_rows(self) -> None:
        if self._dataframe is None:
            return
        mapping = self._current_mapping()
        rows, tones = [], []
        for _index, record in self._dataframe.head(6).iterrows():
            email = str(record.get(mapping.email, "") or "") if mapping.email else ""
            valid, _reason = importer.validate_email(email)
            rows.append([
                email,
                str(record.get(mapping.company, "") or "") if mapping.company else "",
                str(record.get(mapping.person, "") or "") if mapping.person else "",
            ])
            tones.append([None if valid else "error", None, None])
        self.preview_model.set_rows(rows, tones)
        self.preview_table.fit_columns()

    def _start_import(self) -> None:
        if self._dataframe is None:
            return
        mapping = self._current_mapping()
        if not mapping.email:
            self.notify("Select which column holds the email addresses", "warn")
            return

        self.import_button.setEnabled(False)
        self.import_button.setText("Importing...")
        self.cancel_button.setVisible(True)
        self.progress.setVisible(True)
        self.progress.set_busy()              # sweeping until the first report
        self.import_status.setText("Starting...")
        set_tone(self.import_status, "muted")

        worker = jobs.ImportWorker(self._dataframe, mapping,
                                   self._path.name if self._path else "",
                                   self.check_mx.isChecked())
        worker.signals.progress.connect(self._import_progress)
        worker.signals.finished.connect(self._import_done)
        worker.signals.failed.connect(self._import_failed)
        self._import_worker = worker
        worker.start()

    def _cancel_import(self) -> None:
        if self._import_worker is not None:
            self._import_worker.cancel()
            self._import_worker = None
        self._reset_import_controls()
        self.import_status.setText("Import cancelled. Nothing already imported was removed.")
        set_tone(self.import_status, "warning")

    def _import_progress(self, done: int, total: int, detail: str) -> None:
        self.progress.set_progress(done, total)
        self.import_status.setText(detail)

    def _reset_import_controls(self) -> None:
        self.import_button.setEnabled(True)
        self.import_button.setText("Import contacts")
        self.cancel_button.setVisible(False)
        self.progress.setVisible(False)
        self.progress.reset()

    def _import_failed(self, message: str) -> None:
        self._import_worker = None
        self._reset_import_controls()
        self.import_status.setText(f"Import failed: {message}")
        set_tone(self.import_status, "error")

    def _import_done(self, result: importer.ImportResult) -> None:
        self._import_worker = None
        self._reset_import_controls()
        self.import_status.setText("Done.")
        set_tone(self.import_status, "success")

        self.result_section.setVisible(True)
        self.result_label.setText(result.summary())

        if result.problems:
            lines = [f"{email or '(blank)':40} {reason}" for email, reason in result.problems[:200]]
            if len(result.problems) > 200:
                lines.append(f"... and {len(result.problems) - 200:,} more")
            self.problems_box.setPlainText("\n".join(lines))
            self.problems_box.setVisible(True)
        else:
            self.problems_box.setVisible(False)

        self.notify(f"{result.imported:,} contacts imported", "success")
        self.window_.refresh_status()
        self._reload_list()
        self._refresh_completer()

    def _fail(self, message: str) -> None:
        self.import_status.setText(message)
        set_tone(self.import_status, "error")
        self.notify(message, "error")

    # =======================================================================
    # My contacts
    # =======================================================================
    def _build_list(self) -> QWidget:
        holder = QWidget()
        holder.setProperty("role", "plain")
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Filtering happens as you type, debounced so a long list is not
        # re-queried on every keystroke.
        self.search_box = line_edit("Search by email, company or person. Filters as you type")
        self.search_box.setClearButtonEnabled(True)
        self._search_debounce = Debouncer(220, self)
        self._search_debounce.connect(self._apply_search)
        self.search_box.textChanged.connect(lambda _t: self._search_debounce.poke())
        self.search_box.returnPressed.connect(self._search_debounce.flush)

        self.delete_button = danger_button("Delete selected", self._delete_selected, 150)
        self.delete_button.setEnabled(False)
        self.clear_button = danger_button("Clear whole list...", self._clear_list, 160)
        export_button = secondary_button("Export...", self._export_contacts, 110)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addWidget(self.search_box, 1)
        for button in (self.delete_button, self.clear_button, export_button):
            controls.addWidget(button)
        layout.addLayout(controls)

        self.contacts_summary = muted("", wrap=False)
        layout.addWidget(self.contacts_summary)

        self.contacts_model = ContactsModel(self)
        self.contacts_model.counts_changed.connect(self._update_counts)
        self.contacts_table = DataTable(
            self.contacts_model,
            "No contacts yet. Import a spreadsheet on the Import tab.",
            multi_select=True)
        self.contacts_table.selection_changed.connect(self._selection_changed)
        self.contacts_table.set_context_menu(self._contact_menu)
        layout.addWidget(self.contacts_table, 1)

        layout.addWidget(hint(
            "Tip: scroll sideways to see every column from your spreadsheet. Drag a column edge to "
            "widen it, select rows and press Delete to remove them, or right-click for more. "
            "Click any empty space to let go of a selection."))

        delete_key = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.contacts_table.view)
        delete_key.activated.connect(self._delete_selected)

        # Clicking off the list clears the selection, so a row picked by mistake
        # can be un-picked the way people expect.
        self.contacts_table.deselect_on_click_outside(holder, self.contacts_summary)

        self.contacts_model.reload()
        return holder

    def _apply_search(self) -> None:
        self.contacts_model.set_search(self.search_box.text())
        self.contacts_table.fit_columns()

    def _selection_changed(self) -> None:
        count = len(self.contacts_table.selected_rows())
        self.delete_button.setEnabled(count > 0)
        self.delete_button.setText(
            f"Delete {count} selected" if count > 1 else "Delete selected")

    def _update_counts(self, total: int, sendable: int, matching: int) -> None:
        if self.contacts_model.search_text():
            self.contacts_summary.setText(
                f"{matching:,} match “{self.contacts_model.search_text()}”  ·  "
                f"{total:,} contacts in total  ·  {sendable:,} sendable")
        else:
            self.contacts_summary.setText(f"{total:,} contacts  ·  {sendable:,} sendable")

    def _contact_menu(self, index: int) -> QMenu | None:
        if index < 0:
            return None
        if index not in self.contacts_table.selected_rows():
            self.contacts_table.view.selectRow(index)
        rows = self.contacts_table.selected_rows()
        email = self.contacts_model.email_at(index)

        menu = QMenu(self)
        delete = QAction(f"Delete {len(rows)} contacts" if len(rows) > 1
                         else f"Delete {email}", menu)
        delete.triggered.connect(self._delete_selected)
        menu.addAction(delete)

        suppress = QAction("Delete and never contact again", menu)
        suppress.triggered.connect(lambda: self._delete_selected(suppress_too=True))
        menu.addAction(suppress)

        menu.addSeparator()
        copy = QAction("Copy email address", menu)
        copy.triggered.connect(lambda: self._copy_email(email))
        menu.addAction(copy)
        return menu

    def _copy_email(self, email: str) -> None:
        from app.ui.widgets.common import copy_to_clipboard

        if email:
            copy_to_clipboard(email)
            self.notify("Copied to clipboard", "success", 2000)

    def _delete_selected(self, suppress_too: bool = False) -> None:
        rows = self.contacts_table.selected_rows()
        if not rows:
            return
        emails = self.contacts_model.emails_for_rows(rows)
        if len(emails) == 1:
            question = f"Remove {emails[0]} from your contact list?"
        else:
            question = f"Remove these {len(emails):,} contacts from your list?"
        extra = ("\n\nThey will also be added to the do-not-contact list, so a future import "
                 "cannot put them back." if suppress_too else
                 "\n\nThis only removes them from the list here; the original spreadsheet is "
                 "not changed.")
        if not ConfirmDialog.ask(self, "Delete contacts", question + extra,
                                 confirm_text="Delete", danger=True):
            return

        if suppress_too:
            for email in emails:
                db.suppress(email, "Deleted from the contact list", source="manual")

        removed = self.contacts_model.delete_rows(rows)
        self.contacts_table.clear_selection()
        self._selection_changed()
        self.window_.refresh_status()
        self._refresh_completer()
        if suppress_too:
            self._reload_suppression()
        self.notify(f"{removed:,} contact(s) deleted", "success")

    def _clear_list(self) -> None:
        total = importer.contact_count(valid_only=False)
        if not total:
            self.notify("The contact list is already empty", "info")
            return
        if not ConfirmDialog.ask(
            self, "Clear the whole contact list?",
            f"All {total:,} contacts will be removed, along with the progress of any campaign "
            f"that has not finished.\n\nYour do-not-contact list is kept, so anyone who has "
            f"unsubscribed or bounced stays protected when you import a new spreadsheet.\n\n"
            f"This cannot be undone. Export first if you want a copy.",
            confirm_text="Clear the list", danger=True,
        ):
            return
        if self.window_.is_sending():
            self.notify("Stop sending before clearing the list.", "warn")
            return

        # Deleting 100,000 rows and their campaign history takes seconds, and
        # doing it on the UI thread froze the window, which is what looked
        # like a crash. It runs on a worker, and the view lets go of its rows
        # first so nothing is left pointing at records that no longer exist.
        self.contacts_table.clear_selection()
        self.contacts_model.set_rows_empty()
        self.clear_button.setEnabled(False)
        self.clear_button.setText("Clearing...")
        self.contacts_summary.setText("Clearing the contact list...")

        Task(ContactsModel.clear_all).start(
            on_result=self._clear_done, on_error=self._clear_failed,
            on_done=self._clear_finished)

    def _clear_finished(self) -> None:
        self.clear_button.setEnabled(True)
        self.clear_button.setText("Clear whole list...")

    def _clear_done(self, removed: int) -> None:
        self.contacts_model.reload()
        self._selection_changed()
        self.window_.refresh_status()
        self._refresh_completer()
        self.notify(f"{removed:,} contacts removed, ready for a new import", "success")

    def _clear_failed(self, message: str) -> None:
        self.contacts_model.reload()
        self._selection_changed()
        self.notify(f"The list could not be cleared: {message}", "error", 8000)

    def _export_contacts(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self, "Export contacts", "contacts.xlsx", "Excel (*.xlsx)")
        if not path:
            return
        Task(jobs.export_contacts, path).start(
            on_result=lambda saved: self.notify(f"Exported to {Path(saved).name}", "success"),
            on_error=lambda message: self.notify(f"Export failed: {message}", "error"))

    def search_for(self, text: str) -> None:
        """Open the list tab filtered to one address. Used by the Sent emails page."""
        self.tabs.set("My contacts")
        box = getattr(self, "search_box", None)
        if box is not None:
            box.setText(text)
            self._search_debounce.flush()

    def _reload_list(self) -> None:
        model = getattr(self, "contacts_model", None)
        if model is not None:
            model.reload()

    # =======================================================================
    # Do not contact
    # =======================================================================
    def _build_suppression(self) -> QWidget:
        holder = QWidget()
        holder.setProperty("role", "plain")
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(muted(
            "Addresses here are never contacted. Hard bounces and anyone replying "
            "'unsubscribe' are added automatically."))

        # Suggests addresses from the contact list as you type, so an address can
        # be found and suppressed without hunting for the exact spelling.
        self.suppress_box = line_edit("Start typing an address. Suggestions come from your "
                                      "contact list")
        self.suppress_box.returnPressed.connect(self._add_suppression)
        update_completer(self.suppress_box, [])

        add_button = primary_button("Add", self._add_suppression, 90)
        remove_button = secondary_button("Remove selected", self._remove_suppression, 160)
        import_button = secondary_button("Import list...", self._import_suppression, 130)
        export_button = secondary_button("Export", self._export_suppression, 100)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addWidget(self.suppress_box, 1)
        for button in (add_button, remove_button, import_button, export_button):
            controls.addWidget(button)
        layout.addLayout(controls)

        self.suppression_model = SimpleTableModel(["Email", "Reason", "Source", "Added"])
        self.suppression_table = DataTable(self.suppression_model, "No suppressed addresses.",
                                           multi_select=True)
        layout.addWidget(self.suppression_table, 1)
        layout.addWidget(hint(
            "Removing an address here lets it be contacted again. Only do that if the person "
            "asked you to."))

        self._reload_suppression()
        self._refresh_completer()
        return holder

    def _refresh_completer(self) -> None:
        """Reload the type-ahead list off the UI thread; it can be large."""
        box = getattr(self, "suppress_box", None)
        if box is None:
            return
        Task(all_contact_emails).start(
            on_result=lambda emails: update_completer(self.suppress_box, emails))

    def _reload_suppression(self) -> None:
        model = getattr(self, "suppression_model", None)
        if model is None:
            return
        rows = db.suppression_list()
        model.set_rows(
            [[r["email"], r["reason"] or "", r["source"] or "",
              prefs.format_datetime(r["added_at"])] for r in rows],
            [[None, "muted", "warning", "muted"] for _ in rows])

    def _add_suppression(self) -> None:
        email = self.suppress_box.text().strip().lower()
        if "@" not in email:
            self.notify("Enter a valid email address", "warn")
            return
        db.suppress(email, "Added manually", source="manual")
        db.execute("UPDATE contacts SET valid = 0 WHERE email = ?", (email,))
        self.suppress_box.clear()
        self._reload_suppression()
        self._reload_list()
        self.window_.refresh_status()
        self.notify(f"{email} will never be contacted", "success")

    def _remove_suppression(self) -> None:
        rows = self.suppression_table.selected_rows()
        if not rows:
            self.notify("Select an address in the list first", "warn")
            return
        emails = [self.suppression_model.value(r, 0) for r in rows]
        if not ConfirmDialog.ask(
            self, "Allow contact again?",
            f"{len(emails):,} address(es) will be taken off the do-not-contact list and may "
            f"receive email again.\n\nOnly do this if they asked you to.",
            confirm_text="Remove from list", danger=True,
        ):
            return
        for email in emails:
            db.unsuppress(email)
        self._reload_suppression()
        self.notify(f"{len(emails):,} address(es) removed", "success")

    def _import_suppression(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, "Select a do-not-contact list", "",
            "Spreadsheets (*.xlsx *.xls *.csv);;All files (*.*)")
        if not path:
            return

        def done(count: int) -> None:
            self._reload_suppression()
            self._reload_list()
            self.notify(f"{count:,} addresses suppressed", "success")

        Task(jobs.import_suppression, path).start(
            on_result=done,
            on_error=lambda message: self.notify(f"Could not import: {message}", "error"))

    def _export_suppression(self) -> None:
        Task(jobs.export_suppression).start(
            on_result=lambda saved: self.notify(f"Exported to {Path(saved).name}", "success"),
            on_error=lambda message: self.notify(f"Export failed: {message}", "error"))

    # =======================================================================
    def on_show(self) -> None:
        if self.tabs.page("My contacts") is not None:
            self._reload_list()
        if self.tabs.page("Do not contact") is not None:
            self._reload_suppression()
