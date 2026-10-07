"""A table model for the record of every email the app has actually sent.

Reads ``sent_log``, the permanent history written by the send worker. It keeps
its own copy of each recipient's details and of the message itself, so it
survives the contact being deleted or the whole list being cleared. Replies and
bounces are read from both the history and the live contact, whichever knows.

Paged from SQLite exactly like the contact list, for the same reason: a finished
campaign is as long as the list it was sent to.
"""
from __future__ import annotations

import json

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt, pyqtSignal

from app.core import db, merge
from app.ui import theme

PAGE_SIZE = 300
MAX_EXTRA_COLUMNS = 40

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

# The live contact may know about a reply or bounce the history has not been
# told about (and the other way round once the contact is deleted).
_REPLIED = "COALESCE(s.replied_at, c.replied_at)"
_BOUNCED = "COALESCE(s.bounced_at, c.bounced_at)"
_FROM = "FROM sent_log s LEFT JOIN contacts c ON c.email = s.email"

_FILTER_CLAUSE = {
    "all": "",
    "sent": f"AND s.status = 'sent' AND {_REPLIED} IS NULL",
    "replied": f"AND {_REPLIED} IS NOT NULL",
    "bounced": f"AND (s.status = 'bounced' OR {_BOUNCED} IS NOT NULL)",
    "failed": "AND s.status = 'failed'",
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
            "SELECT DISTINCT extra_json FROM sent_log "
            "WHERE extra_json IS NOT NULL AND extra_json != '' LIMIT 400"):
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
        clause = f"WHERE s.status IN ({','.join('?' * len(ATTEMPTED))})"
        clause += " " + _FILTER_CLAUSE[self._filter]
        if self._search:
            like = f"%{self._search}%"
            clause += (" AND (s.email LIKE ? OR s.company LIKE ? OR s.person LIKE ? "
                       "OR s.subject LIKE ?)")
            params += [like, like, like, like]
        return clause, params

    def _query(self, offset: int, limit: int) -> list[dict]:
        from app.core import prefs

        clause, params = self._where()
        rows = db.query(
            "SELECT s.id, s.email, s.company, s.person, s.extra_json, s.status, s.attempts, "
            "s.subject, s.sent_at, s.last_error, s.body_z IS NOT NULL AS has_body, "
            f"{_REPLIED} AS replied_at, {_BOUNCED} AS bounced_at "
            f"{_FROM} {clause} ORDER BY s.sent_at IS NULL, s.sent_at DESC, s.id DESC "
            "LIMIT ? OFFSET ?",
            [*params, limit, offset],
        )

        out: list[dict] = []
        for row in rows:
            label, tone = outcome_of(row)
            item = {
                "_id": row["id"],
                "_has_body": bool(row["has_body"]),
                "email": row["email"] or "",
                "company": row["company"] or "",
                "person": row["person"] or "",
                "_outcome": label,
                "_tone": tone,
                "_when": prefs.format_datetime(row["sent_at"]) if row["sent_at"] else "-",
                "subject_used": row["subject"] or "",
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

    def ids_for_rows(self, rows: list[int]) -> list[int]:
        return [self._rows[r]["_id"] for r in sorted(set(rows)) if 0 <= r < len(self._rows)]

    def delete_rows(self, rows: list[int]) -> int:
        """Remove these entries from the history. Nobody is emailed again because of it."""
        removed = db.delete_sent(self.ids_for_rows(rows))
        self.reload()
        return removed

    # --- totals -------------------------------------------------------------
    @staticmethod
    def counts() -> dict:
        """One pass over the table for the four tiles above the list."""
        row = db.query_one(
            "SELECT "
            "  COUNT(*) AS attempted, "
            "  SUM(CASE WHEN s.status = 'sent' THEN 1 ELSE 0 END) AS sent, "
            f"  SUM(CASE WHEN {_REPLIED} IS NOT NULL THEN 1 ELSE 0 END) AS replied, "
            f"  SUM(CASE WHEN s.status = 'bounced' OR {_BOUNCED} IS NOT NULL "
            "           THEN 1 ELSE 0 END) AS bounced, "
            "  SUM(CASE WHEN s.status = 'failed' THEN 1 ELSE 0 END) AS failed "
            f"{_FROM} WHERE s.status IN ({','.join('?' * len(ATTEMPTED))})",
            list(ATTEMPTED),
        )
        if row is None:
            return {"attempted": 0, "sent": 0, "replied": 0, "bounced": 0, "failed": 0}
        return {key: int(row[key] or 0)
                for key in ("attempted", "sent", "replied", "bounced", "failed")}
