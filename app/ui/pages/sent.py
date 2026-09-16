"""Sent emails: the record of everything that actually went out, and what came back.

The Send page shows a campaign while it runs and then forgets it. This is the
history — one row per email, with the address, the time, the subject that was
used and whether it was answered, bounced or failed. It is deliberately shaped
like the contact list, including the spreadsheet's own columns, so what is on
screen can be matched back to the master file the leads came from.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QMenu, QWidget

from app.models.sent_model import FILTERS, SentModel
from app.ui.pages.base import Page
from app.ui.widgets.common import (ChoiceButtons, StatTile, copy_to_clipboard, hint, muted,
                                   secondary_button)
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
            "Search by email, company, person or subject — filters as you type")
        self.search_box.setClearButtonEnabled(True)
        self._search_debounce = Debouncer(220, self)
        self._search_debounce.connect(self._apply_search)
        self.search_box.textChanged.connect(lambda _t: self._search_debounce.poke())
        self.search_box.returnPressed.connect(self._search_debounce.flush)
        controls.addWidget(self.search_box, 1)
        controls.addWidget(secondary_button("Export to Excel…", self._export, 170))
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
        self.root.addWidget(self.table, 1)

        self.root.addWidget(hint(
            "Scroll sideways for the rest of your spreadsheet's columns. Right-click a row to "
            "copy the address. 'Export to Excel…' saves the whole list, filter and all."))

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
            if counts["bounced"] / total <= 0.05 else "too high — clean your list")
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
        return menu

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

        self.notify("Building the spreadsheet…", "info", 2000)
        Task(exporter.export_sent, path).start(
            on_result=lambda saved: self.notify(f"Saved to {Path(saved).name}", "success"),
            on_error=lambda message: self.notify(f"Export failed: {message}", "error"))

    # --- lifecycle ----------------------------------------------------------
    def on_show(self) -> None:
        self.model.reload()
        self.table.fit_columns()
