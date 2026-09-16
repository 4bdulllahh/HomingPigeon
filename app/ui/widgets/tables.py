"""Table views.

``QTableView`` draws only the cells that are actually on screen, so a 100,000
row contact list costs the same to display as a 20 row one. Everything the app
shows in a grid goes through here.
"""
from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import QAbstractTableModel, QEvent, Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (QAbstractItemView, QHeaderView, QLabel, QStackedWidget, QTableView,
                             QVBoxLayout, QWidget)

from app.ui import theme

# Columns are sized from the first N rows only. Measuring every row of a large
# import would take longer than drawing the table.
SAMPLE_ROWS = 60
MIN_COLUMN_WIDTH = 70
MAX_COLUMN_WIDTH = 460


class DataTable(QWidget):
    """A table with an empty-state message, auto-fitted columns and both scrollbars.

    Columns are fitted to their contents and stay user-resizable by dragging the
    header, and the horizontal scrollbar is always available, so a wide import
    can be read across rather than being squeezed into the window width.
    """

    double_clicked = pyqtSignal(int)
    selection_changed = pyqtSignal()

    def __init__(self, model: QAbstractTableModel, empty_message: str = "Nothing to show yet.",
                 multi_select: bool = False, parent=None):
        super().__init__(parent)
        self.setProperty("role", "plain")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack)

        self.view = QTableView()
        self.view.setModel(model)
        self._configure(multi_select)
        self._stack.addWidget(self.view)

        self.empty_label = QLabel(empty_message)
        self.empty_label.setProperty("role", "muted")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self._stack.addWidget(self.empty_label)

        self.model = model
        model.modelReset.connect(self._after_change)
        model.rowsInserted.connect(self._after_change)
        model.rowsRemoved.connect(self._after_change)
        self.view.doubleClicked.connect(lambda index: self.double_clicked.emit(index.row()))
        selection = self.view.selectionModel()
        if selection is not None:
            selection.selectionChanged.connect(lambda *_: self.selection_changed.emit())

        # Clicking the blank area under the last row, or pressing Escape, lets
        # go of a selection. Without either there is no way to undo a click
        # except picking a different row.
        self.view.viewport().installEventFilter(self)
        escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self.view)
        escape.activated.connect(self.clear_selection)

        self._after_change()

    def _configure(self, multi_select: bool) -> None:
        view = self.view
        view.setAlternatingRowColors(True)
        view.setShowGrid(True)
        view.setWordWrap(False)
        view.setSortingEnabled(False)
        view.setCornerButtonEnabled(False)
        view.setTextElideMode(Qt.TextElideMode.ElideRight)
        view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        view.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection if multi_select
            else QAbstractItemView.SelectionMode.SingleSelection)

        # Per-pixel scrolling in both directions: the default jumps a whole row
        # or column at a time, which reads as stutter on a slow machine.
        view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        view.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        view.horizontalScrollBar().setSingleStep(24)
        view.verticalScrollBar().setSingleStep(24)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        header = view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        header.setHighlightSections(False)
        # Only look at a sample of rows when measuring: O(rows) measuring is the
        # classic reason a big table takes seconds to appear.
        header.setResizeContentsPrecision(SAMPLE_ROWS)
        header.setMinimumSectionSize(MIN_COLUMN_WIDTH)
        header.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        rows = view.verticalHeader()
        rows.setVisible(False)
        rows.setDefaultSectionSize(round(26 * theme.text_scale()))
        rows.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)

    # --- sizing -------------------------------------------------------------
    def fit_columns(self) -> None:
        """Size every column to its content, clamped so one long cell cannot take over."""
        if self.model.rowCount() == 0:
            return
        view = self.view
        view.setUpdatesEnabled(False)
        try:
            view.resizeColumnsToContents()
            header = view.horizontalHeader()
            for index in range(self.model.columnCount()):
                width = header.sectionSize(index)
                padded = width + round(16 * theme.text_scale())
                header.resizeSection(
                    index,
                    max(MIN_COLUMN_WIDTH,
                        min(padded, round(MAX_COLUMN_WIDTH * theme.text_scale()))))

            # If everything fits, let the last column take the spare width rather
            # than leaving a dead strip; if it does not, the scrollbar takes over.
            columns = self.model.columnCount()
            if columns:
                used = sum(header.sectionSize(i) for i in range(columns))
                spare = view.viewport().width() - used
                if spare > 0:
                    header.resizeSection(columns - 1, header.sectionSize(columns - 1) + spare)
        finally:
            view.setUpdatesEnabled(True)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self.fit_columns()

    def _after_change(self, *_args) -> None:
        empty = self.model.rowCount() == 0
        self._stack.setCurrentIndex(1 if empty else 0)
        if not empty:
            self.fit_columns()

    def set_empty_message(self, message: str) -> None:
        self.empty_label.setText(message)

    # --- selection ----------------------------------------------------------
    def selected_rows(self) -> list[int]:
        selection = self.view.selectionModel()
        if selection is None:
            return []
        return sorted({index.row() for index in selection.selectedRows()})

    def selected_row(self) -> int:
        rows = self.selected_rows()
        return rows[0] if rows else -1

    def clear_selection(self) -> None:
        selection = self.view.selectionModel()
        if selection is not None:
            selection.clearSelection()
            # Also drop the current cell, or Qt keeps drawing its focus outline
            # on a row that is no longer selected.
            selection.clearCurrentIndex()

    def deselect_on_click_outside(self, *watched: QWidget) -> None:
        """Also give up the selection when the user clicks elsewhere on the page.

        A press on a child widget is delivered to that child, so buttons and
        inputs keep working; only presses that reach the page background — the
        empty space around the table — arrive here.
        """
        for widget in watched:
            widget.installEventFilter(self)

    def eventFilter(self, obj, event):  # noqa: N802 - Qt naming
        if event.type() == QEvent.Type.MouseButtonPress:
            if obj is self.view.viewport():
                if not self.view.indexAt(event.position().toPoint()).isValid():
                    self.clear_selection()
            else:
                self.clear_selection()
        return False

    def set_context_menu(self, builder: Callable[[int], object]) -> None:
        """``builder(row)`` returns a QMenu, or None for no menu on that row."""
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        def show(point) -> None:
            index = self.view.indexAt(point)
            menu = builder(index.row() if index.isValid() else -1)
            if menu is not None:
                menu.exec(self.view.viewport().mapToGlobal(point))

        self.view.customContextMenuRequested.connect(show)
