"""Contacts: import a spreadsheet, map columns, validate, manage suppression."""
from __future__ import annotations

import threading
from pathlib import Path

import customtkinter as ctk
from tkinter import filedialog

from app import theme
from app.core import db, exporter, importer
from app.ui.widgets.common import (ConfirmDialog, DataTable, FormRow, Section, toast)


class ContactsPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self._path: Path | None = None
        self._dataframe = None
        self._column_menus: dict[str, ctk.CTkOptionMenu] = {}
        self._build()

    def _build(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=theme.PAD_LARGE, pady=(theme.PAD, 0))
        theme.heading(header, "Contacts").pack(anchor="w")
        theme.label(header, "Import your spreadsheet. The app finds the email, company and contact "
                            "columns automatically, then removes duplicates, invalid addresses and "
                            "dead domains before anything is sent.",
                    muted=True, wrap=True).pack(anchor="w", pady=(2, 10))

        self.tabs = ctk.CTkTabview(
            self, fg_color=theme.BG_PANEL, segmented_button_fg_color=theme.BG_SIDEBAR,
            segmented_button_selected_color=theme.ACCENT,
            segmented_button_selected_hover_color=theme.ACCENT_HOVER,
            segmented_button_unselected_color=theme.BG_SIDEBAR, text_color=theme.FG,
            border_width=1, border_color=theme.BORDER, corner_radius=theme.RADIUS_CARD)
        self.tabs.pack(fill="both", expand=True, padx=theme.PAD_LARGE, pady=(0, theme.PAD))
        for name in ("Import", "My contacts", "Do not contact"):
            self.tabs.add(name)

        self._build_import(self.tabs.tab("Import"))
        self._build_list(self.tabs.tab("My contacts"))
        self._build_suppression(self.tabs.tab("Do not contact"))

    # --- import -------------------------------------------------------------
    def _build_import(self, parent) -> None:
        scroll = theme.scroll_frame(parent)
        scroll.pack(fill="both", expand=True)

        picker = Section(scroll, "1. Choose your file",
                         "Excel (.xlsx, .xls) or CSV. The original file is only read, never changed.")
        picker.pack(fill="x", pady=(10, 12))

        row = ctk.CTkFrame(picker.body, fg_color="transparent")
        row.pack(fill="x")
        self.file_label = theme.label(row, "No file selected", muted=True)
        self.file_label.pack(side="left", fill="x", expand=True)
        theme.primary_button(row, "Browse…", self._browse, width=120).pack(side="right")

        self.sheet_row = FormRow(picker.body, "Sheet")
        self.sheet_menu = theme.option_menu(self.sheet_row.input_area, ["—"],
                                            command=lambda _: self._load_preview())
        self.sheet_menu.pack(fill="x")

        self.mapping_section = Section(
            scroll, "2. Check the columns",
            "Detected automatically — change any that are wrong. Every other column is kept and "
            "becomes available as a merge tag in your templates.")
        self.mapping_section.pack(fill="x", pady=(0, 12))
        self.mapping_section.pack_forget()

        self.preview_table = DataTable(
            self.mapping_section.body,
            [("Email", 260), ("Company", 240), ("Contact person", 200)], height=140)

        self.options_section = Section(scroll, "3. Import")
        self.options_section.pack(fill="x", pady=(0, 12))
        self.options_section.pack_forget()

        self.check_mx = ctk.BooleanVar(value=True)
        theme.checkbox(self.options_section.body,
                       "Check that each domain can actually receive mail (recommended)",
                       variable=self.check_mx).pack(anchor="w")
        theme.label(self.options_section.body,
                    "Looks up the mail server for every domain and drops addresses that cannot "
                    "receive mail. This is slower on a large list but prevents the bounces that "
                    "get domains blacklisted.", muted=True, size=11).pack(anchor="w", pady=(2, 10))

        self.import_button = theme.primary_button(self.options_section.body, "Import contacts",
                                                  self._start_import, width=180)
        self.import_button.pack(anchor="w")

        self.progress = ctk.CTkProgressBar(self.options_section.body, progress_color=theme.ACCENT,
                                           fg_color=theme.BORDER, height=6)
        self.progress.set(0)
        self.import_status = theme.label(self.options_section.body, "", muted=True)
        self.import_status.pack(anchor="w", pady=(8, 0))

        self.result_section = Section(scroll, "Import result")
        self.result_section.pack(fill="x", pady=(0, 12))
        self.result_section.pack_forget()
        self.result_label = theme.label(self.result_section.body, "")
        self.result_label.pack(anchor="w")
        self.problems_box = ctk.CTkTextbox(
            self.result_section.body, height=130, font=theme.mono(11), fg_color=theme.BG_INPUT,
            text_color=theme.FG_MUTED, wrap="none", border_width=1, border_color=theme.BORDER)

    def _browse(self) -> None:
        path = filedialog.askopenfilename(
            title="Select your contact list",
            filetypes=[("Spreadsheets", "*.xlsx *.xls *.csv"), ("All files", "*.*")])
        if not path:
            return
        self._path = Path(path)
        self.file_label.configure(text=self._path.name, text_color=theme.FG)

        try:
            sheets = importer.list_sheets(self._path)
        except Exception as error:  # noqa: BLE001
            toast(self, f"Could not open the file: {error}", "error")
            return

        self.sheet_menu.configure(values=sheets)
        self.sheet_menu.set(sheets[0])
        if len(sheets) > 1:
            self.sheet_row.pack(fill="x", pady=(12, 0))
        else:
            self.sheet_row.pack_forget()
        self._load_preview()

    def _load_preview(self) -> None:
        if not self._path:
            return
        sheet = self.sheet_menu.get()
        try:
            self._dataframe = importer.read_sheet(self._path, None if sheet == "CSV" else sheet)
        except Exception as error:  # noqa: BLE001
            toast(self, f"Could not read the sheet: {error}", "error")
            return

        mapping = importer.detect_columns(self._dataframe)
        columns = ["(none)"] + list(self._dataframe.columns)

        for widget in self.mapping_section.body.winfo_children():
            widget.destroy()

        grid = ctk.CTkFrame(self.mapping_section.body, fg_color="transparent")
        grid.pack(fill="x", pady=(0, 12))
        for index in range(3):
            grid.grid_columnconfigure(index, weight=1)

        self._column_menus = {}
        for index, (key, title, detected) in enumerate([
            ("email", "Email address (required)", mapping.email),
            ("company", "Company name", mapping.company),
            ("person", "Contact person", mapping.person),
        ]):
            row = FormRow(grid, title)
            row.grid(row=0, column=index, sticky="ew", padx=(0, 10) if index < 2 else 0)
            menu = theme.option_menu(row.input_area, columns,
                                     command=lambda _: self._refresh_preview_rows())
            menu.set(detected or "(none)")
            menu.pack(fill="x")
            self._column_menus[key] = menu

        found = sum(1 for m in (mapping.email, mapping.company, mapping.person) if m)
        theme.label(self.mapping_section.body,
                    f"{len(self._dataframe):,} rows · {len(self._dataframe.columns)} columns · "
                    f"{found} of 3 mapped automatically",
                    muted=True).pack(anchor="w", pady=(0, 8))

        self.preview_table = DataTable(
            self.mapping_section.body,
            [("Email", 260), ("Company", 240), ("Contact person", 200)], height=140)
        self.preview_table.pack(fill="x")
        self._refresh_preview_rows()

        self.mapping_section.pack(fill="x", pady=(0, 12))
        self.options_section.pack(fill="x", pady=(0, 12))

    def _current_mapping(self) -> importer.ColumnMapping:
        def value(key: str) -> str | None:
            chosen = self._column_menus[key].get()
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
        self.preview_table.clear()
        for _, row in self._dataframe.head(5).iterrows():
            email = str(row.get(mapping.email, "") or "") if mapping.email else ""
            valid, _ = importer.validate_email(email)
            self.preview_table.add_row(
                [email,
                 str(row.get(mapping.company, "") or "") if mapping.company else "",
                 str(row.get(mapping.person, "") or "") if mapping.person else ""],
                colors=[theme.FG if valid else theme.ERROR, None, None])

    def _start_import(self) -> None:
        if self._dataframe is None:
            return
        mapping = self._current_mapping()
        if not mapping.email:
            toast(self, "Select which column holds the email addresses", "warn")
            return

        self.import_button.configure(state="disabled", text="Importing…")
        self.progress.pack(fill="x", pady=(12, 0))
        self.progress.set(0)
        self.import_status.configure(text="Starting…")

        dataframe = self._dataframe
        check_mx = self.check_mx.get()
        source = self._path.name if self._path else ""

        def report(done: int, total: int) -> None:
            self.after(0, lambda: self._update_progress(done, total))

        def work() -> None:
            try:
                result = importer.import_dataframe(dataframe, mapping, source_file=source,
                                                   check_mx=check_mx, progress=report)
            except Exception as error:  # noqa: BLE001
                self.after(0, lambda: self._import_failed(str(error)))
                return
            self.after(0, lambda: self._import_done(result))

        threading.Thread(target=work, daemon=True).start()

    def _update_progress(self, done: int, total: int) -> None:
        self.progress.set(done / total if total else 0)
        self.import_status.configure(text=f"Checked {done:,} of {total:,} rows…")

    def _import_failed(self, message: str) -> None:
        self.import_button.configure(state="normal", text="Import contacts")
        self.progress.pack_forget()
        self.import_status.configure(text=f"Import failed: {message}", text_color=theme.ERROR)

    def _import_done(self, result: importer.ImportResult) -> None:
        self.import_button.configure(state="normal", text="Import contacts")
        self.progress.pack_forget()
        self.import_status.configure(text="Done.", text_color=theme.SUCCESS)

        self.result_section.pack(fill="x", pady=(0, 12))
        self.result_label.configure(text=result.summary())

        if result.problems:
            lines = [f"{email or '(blank)':40} {reason}" for email, reason in result.problems[:200]]
            if len(result.problems) > 200:
                lines.append(f"… and {len(result.problems) - 200:,} more")
            self.problems_box.pack(fill="x", pady=(10, 0))
            self.problems_box.configure(state="normal")
            self.problems_box.delete("1.0", "end")
            self.problems_box.insert("1.0", "\n".join(lines))
            self.problems_box.configure(state="disabled")
        else:
            self.problems_box.pack_forget()

        toast(self, f"{result.imported:,} contacts imported", "success")
        self.app._refresh_status()
        self._load_contacts()

    # --- list ---------------------------------------------------------------
    def _build_list(self, parent) -> None:
        top = ctk.CTkFrame(parent, fg_color="transparent")
        top.pack(fill="x", pady=(10, 8))

        self.search_entry = theme.entry(top, "Search by email, company or person…")
        self.search_entry.pack(side="left", fill="x", expand=True)
        self.search_entry.bind("<Return>", lambda e: self._load_contacts())
        theme.secondary_button(top, "Search", self._load_contacts, width=100).pack(
            side="left", padx=(8, 0))
        theme.secondary_button(top, "Export", self._export_contacts, width=100).pack(
            side="left", padx=(8, 0))

        self.contacts_summary = theme.label(parent, "", muted=True)
        self.contacts_summary.pack(anchor="w", pady=(0, 6))

        self.contacts_table = DataTable(
            parent,
            [("Email", 250), ("Company", 220), ("Person", 160), ("Status", 110), ("Flags", 120)],
            height=420)
        self.contacts_table.pack(fill="both", expand=True, pady=(0, 10))

    def _load_contacts(self) -> None:
        search = self.search_entry.get().strip()
        rows = importer.list_contacts(limit=400, search=search)
        total = importer.contact_count(valid_only=False)
        valid = importer.contact_count(valid_only=True)

        self.contacts_summary.configure(
            text=f"{total:,} contacts · {valid:,} sendable · showing {len(rows):,}")

        self.contacts_table.clear()
        if not rows:
            self.contacts_table.set_empty_message(
                "No contacts yet — import a spreadsheet on the Import tab.")
            return

        for row in rows:
            if row["bounced_at"]:
                status, color = "Bounced", theme.ERROR
            elif row["replied_at"]:
                status, color = "Replied", theme.SUCCESS
            elif not row["valid"]:
                status, color = "Excluded", theme.FG_MUTED
            else:
                status, color = "Active", theme.FG_MUTED
            self.contacts_table.add_row(
                [row["email"], row["company"] or "", row["person"] or "", status,
                 (row["risk_flags"] or "").replace(",", ", ")],
                colors=[theme.FG, theme.FG, theme.FG, color, theme.WARNING])

    def _export_contacts(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")],
            initialfile="contacts.xlsx")
        if not path:
            return
        try:
            exporter.export_campaign(None, path)
            toast(self, f"Exported to {Path(path).name}", "success")
        except Exception as error:  # noqa: BLE001
            toast(self, f"Export failed: {error}", "error")

    # --- suppression --------------------------------------------------------
    def _build_suppression(self, parent) -> None:
        theme.label(parent,
                    "Addresses here are never contacted. Hard bounces and anyone replying "
                    "'unsubscribe' are added automatically.",
                    muted=True).pack(anchor="w", pady=(10, 8))

        top = ctk.CTkFrame(parent, fg_color="transparent")
        top.pack(fill="x", pady=(0, 8))
        self.suppress_entry = theme.entry(top, "email@example.com")
        self.suppress_entry.pack(side="left", fill="x", expand=True)
        self.suppress_entry.bind("<Return>", lambda e: self._add_suppression())
        theme.primary_button(top, "Add", self._add_suppression, width=90).pack(
            side="left", padx=(8, 0))
        theme.secondary_button(top, "Import list", self._import_suppression, width=110).pack(
            side="left", padx=(8, 0))
        theme.secondary_button(top, "Export", self._export_suppression, width=90).pack(
            side="left", padx=(8, 0))

        self.suppression_table = DataTable(
            parent, [("Email", 260), ("Reason", 300), ("Source", 110), ("Added", 150)], height=420)
        self.suppression_table.pack(fill="both", expand=True, pady=(0, 10))

    def _load_suppression(self) -> None:
        rows = db.suppression_list()
        self.suppression_table.clear()
        if not rows:
            self.suppression_table.set_empty_message("No suppressed addresses.")
            return
        for row in rows:
            self.suppression_table.add_row(
                [row["email"], row["reason"] or "", row["source"] or "",
                 (row["added_at"] or "")[:16].replace("T", " ")])

    def _add_suppression(self) -> None:
        email = self.suppress_entry.get().strip().lower()
        if "@" not in email:
            toast(self, "Enter a valid email address", "warn")
            return
        db.suppress(email, "Added manually", source="manual")
        db.execute("UPDATE contacts SET valid = 0 WHERE email = ?", (email,))
        self.suppress_entry.delete(0, "end")
        self._load_suppression()
        toast(self, f"{email} will never be contacted", "success")

    def _import_suppression(self) -> None:
        path = filedialog.askopenfilename(
            title="Select a do-not-contact list",
            filetypes=[("Spreadsheets", "*.xlsx *.xls *.csv"), ("All files", "*.*")])
        if not path:
            return
        try:
            count = exporter.import_suppression(path)
        except Exception as error:  # noqa: BLE001
            toast(self, f"Could not import: {error}", "error")
            return
        self._load_suppression()
        toast(self, f"{count:,} addresses suppressed", "success")

    def _export_suppression(self) -> None:
        try:
            path = exporter.export_suppression()
            toast(self, f"Exported to {path.name}", "success")
        except Exception as error:  # noqa: BLE001
            toast(self, f"Export failed: {error}", "error")

    def on_show(self) -> None:
        self._load_contacts()
        self._load_suppression()
