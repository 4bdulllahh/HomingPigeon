"""A table model for the contact list, backed by SQLite rather than by memory.

A spreadsheet import can easily be 100,000 rows. Building a widget per row (what
the old build did) makes the page take many seconds to open and eats hundreds of
megabytes. Here the model holds only the rows that have actually been scrolled
to: ``canFetchMore``/``fetchMore`` pulls the next page from SQLite as the view
needs it, so the page opens instantly however long the list is.

Searching re-runs the query with a LIKE rather than filtering in Python, so the
work stays in SQLite's index and the model never materialises the whole table.
"""
from __future__ import annotations

import json

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt, pyqtSignal

from app.core import db, merge
from app.ui import theme

PAGE_SIZE = 300

# (heading, key) for the columns every import has
BASE_COLUMNS = [
    ("Email", "email"),
    ("Company", "company"),
    ("Contact person", "person"),
    ("Status", "_status"),
    ("Flags", "risk_flags"),
    ("Source file", "source_file"),
    ("Imported", "imported_at"),
]

# Extra spreadsheet columns are shown after those, so nothing imported is hidden
MAX_EXTRA_COLUMNS = 14


class ContactsModel(QAbstractTableModel):
    """Rows come from the contacts table; extra spreadsheet columns are included."""

    counts_changed = pyqtSignal(int, int, int)  # total, sendable, shown

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []
        self._extras: list[str] = []
        self._columns = list(BASE_COLUMNS)
        self._search = ""
        self._matching = 0
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
            if key == "_status":
                return theme.qcolor(row.get("_status_tone", "fg_muted"))
            if key == "risk_flags" and row.get("risk_flags"):
                return theme.qcolor("warning")
            if key == "email" and not row.get("_valid"):
                return theme.qcolor("fg_muted")
        return None

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return (Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)

    # --- paging -------------------------------------------------------------
    def canFetchMore(self, parent=QModelIndex()) -> bool:  # noqa: B008
        return not parent.isValid() and not self._exhausted

    def fetchMore(self, parent=QModelIndex()) -> None:  # noqa: B008
        # Fetching can be triggered from inside another model signal; inserting
        # rows while a reset or an insert is already in progress is what turns a
        # slow list operation into a hard Qt abort.
        if parent.isValid() or self._exhausted or self._fetching:
            return
        self._fetching = True
        try:
            self._fetch_page()
        finally:
            self._fetching = False

    def _fetch_page(self) -> None:
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
        self._emit_counts()

    # --- loading ------------------------------------------------------------
    def set_search(self, text: str) -> None:
        """Filter the list. Called from a debounced timer as the user types."""
        text = (text or "").strip()
        if text == self._search:
            return
        self._search = text
        self.reload()

    def search_text(self) -> str:
        return self._search

    def set_rows_empty(self) -> None:
        """Drop every row without touching the database.

        Used while a long delete runs on a worker thread: the view stops asking
        for records that are in the middle of being removed.
        """
        self.beginResetModel()
        self._rows = []
        self._exhausted = True
        self._matching = 0
        self.endResetModel()

    def reload(self) -> None:
        """Re-read the columns and the first page. Cheap: one COUNT plus 300 rows."""
        self.beginResetModel()
        self._refresh_columns()
        self._rows = self._query(0, PAGE_SIZE)
        self._exhausted = len(self._rows) < PAGE_SIZE
        self._matching = self._count_matching()
        self.endResetModel()
        self._emit_counts()

    def _refresh_columns(self) -> None:
        extras: list[str] = []
        builtin = {name.lower() for name in merge.BUILTIN_TAGS}
        for row in db.query("SELECT extra_json FROM contacts "
                            "WHERE extra_json IS NOT NULL AND extra_json != '' LIMIT 40"):
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

    def _where(self) -> tuple[str, list]:
        if not self._search:
            return "", []
        like = f"%{self._search}%"
        return ("WHERE email LIKE ? OR company LIKE ? OR person LIKE ?", [like, like, like])

    def _count_matching(self) -> int:
        clause, params = self._where()
        row = db.query_one(f"SELECT COUNT(*) AS n FROM contacts {clause}", params)
        return row["n"] if row else 0

    def _query(self, offset: int, limit: int) -> list[dict]:
        from app.core import prefs

        clause, params = self._where()
        rows = db.query(
            f"SELECT * FROM contacts {clause} ORDER BY id LIMIT ? OFFSET ?",
            [*params, limit, offset])

        out: list[dict] = []
        for row in rows:
            if row["bounced_at"]:
                status, tone = "Bounced", "error"
            elif row["replied_at"]:
                status, tone = "Replied", "success"
            elif not row["valid"]:
                status, tone = "Excluded", "fg_muted"
            else:
                status, tone = "Active", "fg_muted"

            item = {
                "_id": row["id"],
                "_valid": bool(row["valid"]),
                "_status": status,
                "_status_tone": tone,
                "email": row["email"] or "",
                "company": row["company"] or "",
                "person": row["person"] or "",
                "risk_flags": (row["risk_flags"] or "").replace(",", ", "),
                "source_file": row["source_file"] or "",
                "imported_at": prefs.format_date(row["imported_at"]),
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

    # --- counts -------------------------------------------------------------
    def _emit_counts(self) -> None:
        total = self._count_all(valid_only=False)
        sendable = self._count_all(valid_only=True)
        self.counts_changed.emit(total, sendable, self._matching)

    @staticmethod
    def _count_all(valid_only: bool) -> int:
        sql = "SELECT COUNT(*) AS n FROM contacts"
        if valid_only:
            sql += " WHERE valid = 1"
        row = db.query_one(sql)
        return row["n"] if row else 0

    def matching_count(self) -> int:
        return self._matching

    # --- editing ------------------------------------------------------------
    def email_at(self, row: int) -> str:
        return self._rows[row]["email"] if 0 <= row < len(self._rows) else ""

    def emails_for_rows(self, rows: list[int]) -> list[str]:
        return [self._rows[r]["email"] for r in sorted(set(rows)) if 0 <= r < len(self._rows)]

    def delete_rows(self, rows: list[int]) -> int:
        """Remove these contacts outright, including any campaign history for them."""
        ids = [self._rows[r]["_id"] for r in sorted(set(rows)) if 0 <= r < len(self._rows)]
        if not ids:
            return 0
        placeholders = ",".join("?" * len(ids))
        connection = db.connect()
        with connection:
            connection.execute(
                f"DELETE FROM campaign_recipients WHERE contact_id IN ({placeholders})", ids)
            connection.execute(f"DELETE FROM contacts WHERE id IN ({placeholders})", ids)
        self.reload()
        return len(ids)

    @staticmethod
    def clear_all() -> int:
        """Empty the contact list so another spreadsheet can be imported cleanly.

        The do-not-contact list is deliberately left alone: those addresses must
        survive a re-import, or suppressed people start receiving mail again.
        """
        connection = db.connect()
        row = connection.execute("SELECT COUNT(*) AS n FROM contacts").fetchone()
        count = row["n"] if row else 0
        # One transaction, not three: a failure part-way through then leaves the
        # list exactly as it was rather than half deleted.
        with connection:
            connection.execute("DELETE FROM campaign_recipients")
            connection.execute("DELETE FROM contacts")
            connection.execute("DELETE FROM campaigns WHERE status IN ('draft', 'paused')")
        return count


def all_contact_emails(limit: int = 20000) -> list[str]:
    """Every address on the list, for the do-not-contact box's auto-complete."""
    return [row["email"] for row in
            db.query("SELECT email FROM contacts ORDER BY email LIMIT ?", (limit,))]
