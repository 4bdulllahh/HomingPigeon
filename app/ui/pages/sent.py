"""Sent emails: the record of everything that actually went out, and what came back.

The Send page shows a campaign while it runs and then forgets it. This is the
history: one row per email, with the address, the time, the subject that was
used and whether it was answered, bounced or failed. It is deliberately shaped
like the contact list, including the spreadsheet's own columns, so what is on
screen can be matched back to the master file the leads came from.
"""
from __future__ import annotations

import tempfile
import webbrowser
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtWidgets import (QDialog, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QMenu,
                             QTextBrowser, QVBoxLayout, QWidget)

from app.core import composer, db, prefs
from app.models.sent_model import FILTERS, SentModel, outcome_of
from app.ui import theme
from app.ui.pages.base import Page
from app.ui.widgets.common import (ChoiceButtons, StatTile, copy_to_clipboard, danger_button,
                                   hint, muted, primary_button, secondary_button)
from app.ui.widgets.dialogs import ConfirmDialog
from app.ui.widgets.inputs import Debouncer, line_edit
from app.ui.widgets.tables import DataTable
from app.workers.base import Task


class SentPage(Page):
    def __init__(self, window):
        super().__init__(window)
        self._build()

    def _build(self) -> None:
        self.add_header(
            "Sent emails",
            "Everything HomingPigeon has sent, newest first. Use it to update the spreadsheet "
            "your leads live in: who was contacted, when, and what came back.")

        tiles_holder = QWidget()
        tiles_holder.setProperty("role", "plain")
        tiles = QHBoxLayout(tiles_holder)
        tiles.setContentsMargins(0, 0, 0, 0)
        tiles.setSpacing(8)
        self.tile_sent = StatTile("Emails sent", "0")
        self.tile_replied = StatTile("Replied", "0", tone="success")
        self.tile_bounced = StatTile("Bounced", "0", tone="error")
        self.tile_failed = StatTile("Failed to send", "0", tone="warning")
        for tile in (self.tile_sent, self.tile_replied, self.tile_bounced, self.tile_failed):
            tiles.addWidget(tile, 1)
        self.root.addWidget(tiles_holder)

        controls_holder = QWidget()
        controls_holder.setProperty("role", "plain")
        controls = QHBoxLayout(controls_holder)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)

        self.search_box = line_edit(
            "Search by email, company, person or subject. Filters as you type")
        self.search_box.setClearButtonEnabled(True)
        self._search_debounce = Debouncer(220, self)
        self._search_debounce.connect(self._apply_search)
        self.search_box.textChanged.connect(lambda _t: self._search_debounce.poke())
        self.search_box.returnPressed.connect(self._search_debounce.flush)
        controls.addWidget(self.search_box, 1)
        self.delete_button = danger_button("Delete selected", self._delete_selected, 150)
        self.delete_button.setEnabled(False)
        self.clear_button = danger_button("Clear history...", self._clear_history, 150)
        controls.addWidget(self.delete_button)
        controls.addWidget(self.clear_button)
        controls.addWidget(secondary_button("Export to Excel...", self._export, 170))
        self.root.addWidget(controls_holder)

        self.filters = ChoiceButtons(FILTERS, "all", on_change=self._apply_filter)
        self.root.addWidget(self.filters)

        self.summary = muted("", wrap=False)
        self.root.addWidget(self.summary)

        self.model = SentModel(self)
        self.model.counts_changed.connect(self._update_tiles)
        self.table = DataTable(
            self.model,
            "Nothing has been sent yet. Once a campaign runs, every email appears here.",
            multi_select=True)
        self.table.set_context_menu(self._row_menu)
        self.table.double_clicked.connect(self._open_email)
        self.table.selection_changed.connect(self._selection_changed)
        self.root.addWidget(self.table, 1)

        self.root.addWidget(hint(
            "Double-click an email to see exactly what was sent. Select rows and press Delete "
            "to remove them from this history, or right-click for more. Scroll sideways for the "
            "rest of your spreadsheet's columns."))

        delete_key = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.table.view)
        delete_key.activated.connect(self._delete_selected)

        self.table.deselect_on_click_outside(self, self.summary)

    # --- filtering ----------------------------------------------------------
    def _apply_search(self) -> None:
        self.model.set_search(self.search_box.text())
        self._update_summary()

    def _apply_filter(self, key: str) -> None:
        self.model.set_filter(key)
        self._update_summary()

    def _update_summary(self) -> None:
        counts = self.model.counts()
        chosen = dict(FILTERS).get(self.filters.get(), "All")
        text = f"{counts['attempted']:,} emails sent in total"
        if self.filters.get() != "all":
            text += f"  ·  showing: {chosen}"
        if self.model.search_text():
            text += f"  ·  matching “{self.model.search_text()}”"
        self.summary.setText(text)

    def _update_tiles(self, counts: dict) -> None:
        total = max(1, counts["attempted"])
        self.tile_sent.update_value(f"{counts['attempted']:,}")
        self.tile_replied.update_value(
            f"{counts['replied']:,}", f"{counts['replied'] / total * 100:.1f}% reply rate")
        self.tile_bounced.update_value(
            f"{counts['bounced']:,}", "keep below 5%"
            if counts["bounced"] / total <= 0.05 else "too high, clean your list")
        self.tile_failed.update_value(f"{counts['failed']:,}", "never reached the server")
        self._update_summary()

    # --- row actions --------------------------------------------------------
    def _row_menu(self, index: int) -> QMenu | None:
        if index < 0:
            return None
        if index not in self.table.selected_rows():
            self.table.view.selectRow(index)
        record = self.model.row_at(index)
        email = record.get("email", "")
        if not email:
            return None

        menu = QMenu(self)
        view = QAction("See the email that was sent", menu)
        view.triggered.connect(lambda: self._open_email(index))
        menu.addAction(view)
        menu.addSeparator()

        copy = QAction(f"Copy {email}", menu)
        copy.triggered.connect(lambda: self._copy(email))
        menu.addAction(copy)

        subject = record.get("subject_used", "")
        if subject:
            copy_subject = QAction("Copy the subject that was used", menu)
            copy_subject.triggered.connect(lambda: self._copy(subject))
            menu.addAction(copy_subject)

        menu.addSeparator()
        find = QAction("Find this person in my contacts", menu)
        find.triggered.connect(lambda: self._open_in_contacts(email))
        menu.addAction(find)

        menu.addSeparator()
        rows = self.table.selected_rows()
        delete = QAction(f"Delete {len(rows)} emails from the history" if len(rows) > 1
                         else "Delete from the history", menu)
        delete.triggered.connect(self._delete_selected)
        menu.addAction(delete)
        return menu

    def _open_email(self, index: int) -> None:
        record = self.model.row_at(index)
        if not record:
            return
        message = db.sent_message(record["_id"])
        if message is None:
            self.notify("That email is no longer in the history", "warn")
            self.model.reload()
            return
        SentEmailDialog(self.window(), message).exec()

    # --- deleting -----------------------------------------------------------
    def _selection_changed(self) -> None:
        count = len(self.table.selected_rows())
        self.delete_button.setEnabled(count > 0)
        self.delete_button.setText(
            f"Delete {count} selected" if count > 1 else "Delete selected")

    def _delete_selected(self) -> None:
        rows = self.table.selected_rows()
        if not rows:
            return
        if len(rows) == 1:
            question = f"Delete the email to {self.model.email_at(rows[0])} from this history?"
        else:
            question = f"Delete these {len(rows):,} emails from this history?"
        if not ConfirmDialog.ask(
            self, "Delete from the history", question + HISTORY_NOTE,
            confirm_text="Delete", danger=True,
        ):
            return
        removed = self.model.delete_rows(rows)
        self.table.clear_selection()
        self._selection_changed()
        self.notify(f"{removed:,} email(s) deleted from the history", "success")

    def _clear_history(self) -> None:
        total = self.model.counts()["attempted"]
        if not total:
            self.notify("The history is already empty", "info")
            return
        if not ConfirmDialog.ask(
            self, "Clear the whole history?",
            f"All {total:,} emails will be removed from this list." + HISTORY_NOTE
            + "\n\nThis cannot be undone. Use 'Export to Excel...' first if you want a copy.",
            confirm_text="Clear history", danger=True,
        ):
            return
        removed = db.clear_sent()
        self.table.clear_selection()
        self.model.reload()
        self._selection_changed()
        self.notify(f"{removed:,} emails removed from the history", "success")

    def _copy(self, text: str) -> None:
        copy_to_clipboard(text)
        self.notify("Copied to clipboard", "success", 2000)

    def _open_in_contacts(self, email: str) -> None:
        page = self.window_.ensure_page("contacts")
        self.go("contacts")
        if page is not None and hasattr(page, "search_for"):
            page.search_for(email)

    # --- export -------------------------------------------------------------
    def _export(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self, "Export the sent emails", "sent emails.xlsx", "Excel (*.xlsx)")
        if not path:
            return
        from app.core import exporter

        self.notify("Building the spreadsheet...", "info", 2000)
        Task(exporter.export_sent, path).start(
            on_result=lambda saved: self.notify(f"Saved to {Path(saved).name}", "success"),
            on_error=lambda message: self.notify(f"Export failed: {message}", "error"))

    # --- lifecycle ----------------------------------------------------------
    def on_show(self) -> None:
        self.model.reload()
        self._selection_changed()
        self.table.fit_columns()


HISTORY_NOTE = ("\n\nThis only tidies the list. Nobody is emailed again because of it, and "
                "replies and bounces are still picked up.")


class SentEmailDialog(QDialog):
    """The email exactly as it went out: who to, when, the subject and the message."""

    def __init__(self, parent: QWidget | None, message: dict):
        super().__init__(parent)
        self.setWindowTitle("Sent email")
        self.setModal(True)
        scale = theme.text_scale()
        self.setMinimumWidth(round(600 * scale))
        self.resize(round(760 * scale), round(720 * scale))
        self._html = message.get("body_html") or ""

        pad = round(20 * scale)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(pad, pad, pad, pad)
        layout.setSpacing(round(10 * scale))

        subject = QLabel(message.get("subject") or "(no subject)")
        subject.setProperty("role", "subheading")
        subject.setWordWrap(True)
        subject.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(subject)

        label, _tone = outcome_of(message)
        to = message.get("email") or ""
        if message.get("person"):
            to = f"{message['person']} <{to}>"
        details = [
            ("To", to),
            ("From", message.get("from_addr") or ""),
            ("Sent", prefs.format_datetime(message["sent_at"]) if message.get("sent_at") else "-"),
            ("Outcome", label),
        ]
        if message.get("company"):
            details.insert(1, ("Company", message["company"]))
        if message.get("attachment"):
            details.append(("Attached", message["attachment"]))
        if message.get("last_error"):
            details.append(("Details", message["last_error"]))

        grid_holder = QWidget()
        grid_holder.setProperty("role", "plain")
        grid = QGridLayout(grid_holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(round(14 * scale))
        grid.setVerticalSpacing(round(4 * scale))
        grid.setColumnStretch(1, 1)
        for row_index, (name, value) in enumerate(d for d in details if d[1]):
            grid.addWidget(muted(name, wrap=False), row_index, 0, Qt.AlignmentFlag.AlignTop)
            text = QLabel(value)
            text.setWordWrap(True)
            text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(text, row_index, 1)
        layout.addWidget(grid_holder)

        if self._html:
            body = QTextBrowser()
            body.setOpenExternalLinks(True)
            # An email is read on white whatever the app's theme, so show it that way
            body.setStyleSheet("QTextBrowser { background: #ffffff; color: #333333; "
                               "border: 1px solid #cccccc; border-radius: 6px; padding: 8px; }")
            body.setHtml(self._html)
            layout.addWidget(body, 1)
        else:
            layout.addWidget(muted(
                "Only the details above were kept for this email. It was sent before "
                "HomingPigeon v0.6.2, which is when the app started saving a copy of every "
                "message. Everything sent from now on can be opened here in full."))
            layout.addStretch(1)

        buttons = QHBoxLayout()
        if self._html:
            buttons.addWidget(secondary_button("Open in browser", self._open_in_browser, 160))
            buttons.addWidget(secondary_button("Copy the text", self._copy_text, 140))
        buttons.addStretch(1)
        buttons.addWidget(primary_button("Close", self.accept, width=120))
        layout.addLayout(buttons)

    def _open_in_browser(self) -> None:
        path = Path(tempfile.gettempdir()) / "homingpigeon_sent_email.html"
        path.write_text(self._html, encoding="utf-8")
        webbrowser.open(path.as_uri())

    def _copy_text(self) -> None:
        copy_to_clipboard(composer.html_to_text(self._html))
