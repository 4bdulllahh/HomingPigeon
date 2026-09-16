"""A small in-memory table model for the app's short lists.

Suppression, replies, recent activity and the import preview are all at most a
few thousand rows and are replaced wholesale, so they do not need the paging the
contact list has. One model class covers all of them.
"""
from __future__ import annotations

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt

from app.ui import theme


class SimpleTableModel(QAbstractTableModel):
    """Rows of plain strings, with an optional per-cell colour token."""

    def __init__(self, headers: list[str], parent=None):
        super().__init__(parent)
        self._headers = headers
        self._rows: list[list[str]] = []
        self._tones: list[list[str | None]] = []

    # --- shape --------------------------------------------------------------
    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._headers)

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self._headers[section]
        return section + 1

    # --- data ---------------------------------------------------------------
    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row, column = index.row(), index.column()
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            values = self._rows[row]
            return values[column] if column < len(values) else ""
        if role == Qt.ItemDataRole.ForegroundRole:
            tones = self._tones[row]
            token = tones[column] if column < len(tones) else None
            if token:
                return theme.qcolor(token)
        return None

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    # --- loading ------------------------------------------------------------
    def set_rows(self, rows: list[list[str]], tones: list[list[str | None]] | None = None) -> None:
        self.beginResetModel()
        self._rows = [[("" if v is None else str(v)) for v in row] for row in rows]
        self._tones = tones or [[None] * len(self._headers) for _ in self._rows]
        self.endResetModel()

    def clear(self) -> None:
        self.set_rows([])

    def value(self, row: int, column: int) -> str:
        if 0 <= row < len(self._rows) and column < len(self._rows[row]):
            return self._rows[row][column]
        return ""
