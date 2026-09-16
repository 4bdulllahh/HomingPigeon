"""A table model for the record of every email the app has actually sent.

The data already existed — ``campaign_recipients`` has carried the status, the
timestamp, the subject used and the error text since the first version — but
there was nowhere to read it. This turns it into a list the user can scan,
filter and export back into the spreadsheet their leads live in.

Paged from SQLite exactly like the contact list, for the same reason: a finished
campaign is as long as the list it was sent to.
"""
from __future__ import annotations

import json

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt, pyqtSignal

from app.core import db, merge
from app.ui import theme

PAGE_SIZE = 300
MAX_EXTRA_COLUMNS = 12

# Only rows the app actually attempted. 'pending' has not been tried yet and
# 'skipped' was never sent at all, so neither belongs in a record of what went out.
ATTEMPTED = ("sent", "failed", "bounced")

BASE_COLUMNS = [
    ("Email", "email"),
    ("Company", "company"),
    ("Contact person", "person"),
    ("Outcome", "_outcome"),
    ("When", "_when"),
    ("Subject used", "subject_used"),
    ("Tries", "attempts"),
    ("Details", "last_error"),
]

# (key, label) for the filter buttons above the list
FILTERS = [
    ("all", "All"),
    ("sent", "Sent, no reply"),
    ("replied", "Replied"),
    ("bounced", "Bounced"),
    ("failed", "Failed"),
]

_FILTER_CLAUSE = {
    "all": "",
    "sent": "AND r.status = 'sent' AND c.replied_at IS NULL",
    "replied": "AND c.replied_at IS NOT NULL",
    "bounced": "AND (r.status = 'bounced' OR c.bounced_at IS NOT NULL)",
    "failed": "AND r.status = 'failed'",
}


def outcome_of(row) -> tuple[str, str]:
    """(label, colour token) for one row. A reply outranks everything else."""
    if row["replied_at"]:
        return "Replied", "success"
    if row["status"] == "bounced" or row["bounced_at"]:
        return "Bounced", "error"
    if row["status"] == "failed":
        return "Failed", "error"
    return "Sent", "fg"


class SentModel(QAbstractTableModel):
    """Every attempted send, newest first, with the spreadsheet's own columns kept."""

    counts_changed = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []
        self._extras: list[str] = []
        self._columns = list(BASE_COLUMNS)
        self._search = ""
        self._filter = "all"
        self._exhausted = False
        self._fetching = False

    # --- shape --------------------------------------------------------------
    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._columns)

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._rows)

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self._columns[section][0]
        return section + 1

    # --- data ---------------------------------------------------------------
    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        key = self._columns[index.column()][1]

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return row.get(key, "")
        if role == Qt.ItemDataRole.ForegroundRole:
            if key == "_outcome":
                return theme.qcolor(row.get("_tone", "fg"))
            if key == "last_error" and row.get("last_error"):
                return theme.qcolor("error")
            if key in ("_when", "attempts"):
                return theme.qcolor("fg_muted")
        return None

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    # --- paging -------------------------------------------------------------
    def canFetchMore(self, parent=QModelIndex()) -> bool:  # noqa: B008
        return not parent.isValid() and not self._exhausted

    def fetchMore(self, parent=QModelIndex()) -> None:  # noqa: B008
        if parent.isValid() or self._exhausted or self._fetching:
            return
        self._fetching = True
        try:
            rows = self._query(len(self._rows), PAGE_SIZE)
            if not rows:
                self._exhausted = True
                return
            first = len(self._rows)
            self.beginInsertRows(QModelIndex(), first, first + len(rows) - 1)
            self._rows.extend(rows)
            self.endInsertRows()
            if len(rows) < PAGE_SIZE:
                self._exhausted = True
        finally:
            self._fetching = False

    # --- loading ------------------------------------------------------------
    def set_search(self, text: str) -> None:
        text = (text or "").strip()
        if text == self._search:
            return
        self._search = text
        self.reload()

    def set_filter(self, key: str) -> None:
        if key == self._filter or key not in _FILTER_CLAUSE:
            return
        self._filter = key
        self.reload()

    def search_text(self) -> str:
        return self._search

    def reload(self) -> None:
        self.beginResetModel()
        self._refresh_columns()
        self._rows = self._query(0, PAGE_SIZE)
        self._exhausted = len(self._rows) < PAGE_SIZE
        self.endResetModel()
        self.counts_changed.emit(self.counts())

    def _refresh_columns(self) -> None:
        """Carry the spreadsheet's own columns across, so a row can be matched
        back to the line it came from in the user's master file."""
        extras: list[str] = []
        builtin = {name.lower() for name in merge.BUILTIN_TAGS}
        for row in db.query(
            "SELECT c.extra_json FROM campaign_recipients r "
            "JOIN contacts c ON c.id = r.contact_id "
            f"WHERE r.status IN ({','.join('?' * len(ATTEMPTED))}) "
            "AND c.extra_json IS NOT NULL AND c.extra_json != '' LIMIT 40",
            list(ATTEMPTED),
        ):
            try:
                keys = json.loads(row["extra_json"])
            except (json.JSONDecodeError, TypeError):
                continue
            for key in keys:
                if key.lower() not in builtin and key not in extras:
                    extras.append(key)
            if len(extras) >= MAX_EXTRA_COLUMNS:
                break
        self._extras = extras[:MAX_EXTRA_COLUMNS]
        self._columns = list(BASE_COLUMNS) + [(name, name) for name in self._extras]

    # --- queries ------------------------------------------------------------
    def _where(self) -> tuple[str, list]:
        params: list = list(ATTEMPTED)
        clause = f"WHERE r.status IN ({','.join('?' * len(ATTEMPTED))})"
        clause += " " + _FILTER_CLAUSE[self._filter]
        if self._search:
            like = f"%{self._search}%"
            clause += (" AND (c.email LIKE ? OR c.company LIKE ? OR c.person LIKE ? "
                       "OR r.subject_used LIKE ?)")
            params += [like, like, like, like]
        return clause, params

    def _query(self, offset: int, limit: int) -> list[dict]:
        from app.core import prefs

        clause, params = self._where()
        rows = db.query(
            "SELECT c.email, c.company, c.person, c.extra_json, c.replied_at, c.bounced_at, "
            "r.status, r.attempts, r.subject_used, r.sent_at, r.last_error "
            "FROM campaign_recipients r JOIN contacts c ON c.id = r.contact_id "
            f"{clause} ORDER BY r.sent_at IS NULL, r.sent_at DESC, r.rowid DESC "
            "LIMIT ? OFFSET ?",
            [*params, limit, offset],
        )

        out: list[dict] = []
        for row in rows:
            label, tone = outcome_of(row)
            item = {
                "email": row["email"] or "",
                "company": row["company"] or "",
                "person": row["person"] or "",
                "_outcome": label,
                "_tone": tone,
                "_when": prefs.format_datetime(row["sent_at"]) if row["sent_at"] else "—",
                "subject_used": row["subject_used"] or "",
                "attempts": str(row["attempts"] or 0),
                "last_error": row["last_error"] or "",
            }
            if self._extras:
                try:
                    extra = json.loads(row["extra_json"] or "{}")
                except (json.JSONDecodeError, TypeError):
                    extra = {}
                for name in self._extras:
                    value = extra.get(name, "")
                    item[name] = "" if value is None else str(value)
            out.append(item)
        return out

    def email_at(self, row: int) -> str:
        return self._rows[row]["email"] if 0 <= row < len(self._rows) else ""

    def row_at(self, row: int) -> dict:
        return self._rows[row] if 0 <= row < len(self._rows) else {}

    # --- totals -------------------------------------------------------------
    @staticmethod
    def counts() -> dict:
        """One pass over the table for the four tiles above the list."""
        row = db.query_one(
            "SELECT "
            "  COUNT(*) AS attempted, "
            "  SUM(CASE WHEN r.status = 'sent' THEN 1 ELSE 0 END) AS sent, "
            "  SUM(CASE WHEN c.replied_at IS NOT NULL THEN 1 ELSE 0 END) AS replied, "
            "  SUM(CASE WHEN r.status = 'bounced' OR c.bounced_at IS NOT NULL "
            "           THEN 1 ELSE 0 END) AS bounced, "
            "  SUM(CASE WHEN r.status = 'failed' THEN 1 ELSE 0 END) AS failed "
            "FROM campaign_recipients r JOIN contacts c ON c.id = r.contact_id "
            f"WHERE r.status IN ({','.join('?' * len(ATTEMPTED))})",
            list(ATTEMPTED),
        )
        if row is None:
            return {"attempted": 0, "sent": 0, "replied": 0, "bounced": 0, "failed": 0}
        return {key: int(row[key] or 0)
                for key in ("attempted", "sent", "replied", "bounced", "failed")}
