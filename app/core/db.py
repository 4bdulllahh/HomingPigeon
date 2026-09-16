"""SQLite storage: schema, migrations and query helpers.

The database is the source of truth for contacts, campaigns and send status.
Source spreadsheets are never modified; results go out through exporter.py.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, date
from pathlib import Path
from typing import Any, Iterable, Sequence

from app import config

SCHEMA_VERSION = 1

_local = threading.local()
_db_path: Path | None = None


# --- Connection -------------------------------------------------------------
def init(db_path: Path | None = None) -> None:
    """Prepare the data directory and create/upgrade the schema."""
    global _db_path
    config.ensure_dirs()
    _db_path = Path(db_path) if db_path else config.DB_PATH
    conn = connect()
    conn.executescript(_SCHEMA)
    _migrate(conn)
    conn.commit()


# How long a write waits for another thread's write before giving up. Only one
# connection can write at a time. A long wait on the UI thread is a frozen
# window, which is worse than a setting that fails to save, so the wait here is
# short and callers that can shrug it off use execute_soft().
BUSY_TIMEOUT_SECONDS = 5.0


def connect() -> sqlite3.Connection:
    """One connection per thread; the send worker and UI each get their own."""
    conn = getattr(_local, "conn", None)
    if conn is not None and getattr(_local, "path", None) == _db_path:
        return conn
    if _db_path is None:
        raise RuntimeError("db.init() must be called before db.connect()")
    conn = sqlite3.connect(str(_db_path), timeout=BUSY_TIMEOUT_SECONDS, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    _local.conn = conn
    _local.path = _db_path
    return conn


def close() -> None:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_info (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS contacts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    company     TEXT,
    person      TEXT,
    extra_json  TEXT,
    source_file TEXT,
    imported_at TEXT,
    valid       INTEGER DEFAULT 1,
    risk_flags  TEXT,
    replied_at  TEXT,
    bounced_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_contacts_valid ON contacts(valid);

CREATE TABLE IF NOT EXISTS template_sets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    signature_html TEXT DEFAULT '',
    created_at    TEXT
);

CREATE TABLE IF NOT EXISTS subjects (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    set_id  INTEGER NOT NULL REFERENCES template_sets(id) ON DELETE CASCADE,
    text    TEXT NOT NULL,
    enabled INTEGER DEFAULT 1,
    position INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS bodies (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    set_id  INTEGER NOT NULL REFERENCES template_sets(id) ON DELETE CASCADE,
    name    TEXT NOT NULL,
    html    TEXT NOT NULL,
    enabled INTEGER DEFAULT 1,
    position INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS campaigns (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL,
    status            TEXT DEFAULT 'draft',
    template_set_id   INTEGER REFERENCES template_sets(id),
    attach_mode       TEXT DEFAULT 'link',
    attachment_path   TEXT,
    link_url          TEXT,
    link_text         TEXT,
    delay_min_s       INTEGER DEFAULT 75,
    delay_max_s       INTEGER DEFAULT 150,
    window_start      TEXT DEFAULT '09:00',
    window_end        TEXT DEFAULT '18:00',
    weekdays_only     INTEGER DEFAULT 1,
    skip_holidays     INTEGER DEFAULT 1,
    daily_cap_override INTEGER,
    created_at        TEXT,
    started_at        TEXT,
    finished_at       TEXT
);

CREATE TABLE IF NOT EXISTS campaign_recipients (
    campaign_id  INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    contact_id   INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    status       TEXT DEFAULT 'pending',
    attempts     INTEGER DEFAULT 0,
    subject_used TEXT,
    body_variant TEXT,
    message_id   TEXT,
    sent_at      TEXT,
    last_error   TEXT,
    PRIMARY KEY (campaign_id, contact_id)
);
CREATE INDEX IF NOT EXISTS idx_recip_status ON campaign_recipients(campaign_id, status);

CREATE TABLE IF NOT EXISTS suppression (
    email    TEXT PRIMARY KEY COLLATE NOCASE,
    reason   TEXT,
    source   TEXT,
    added_at TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT,
    level       TEXT,
    category    TEXT,
    message     TEXT,
    campaign_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts DESC);

CREATE TABLE IF NOT EXISTS warmup_state (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    started_on TEXT,
    day_index  INTEGER DEFAULT 1,
    sent_date  TEXT,
    sent_today INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS scores (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT,
    set_id        INTEGER,
    score         INTEGER,
    grade         TEXT,
    findings_json TEXT
);

CREATE TABLE IF NOT EXISTS imap_state (
    id             INTEGER PRIMARY KEY CHECK (id = 1),
    last_uid       INTEGER DEFAULT 0,
    last_sync_at   TEXT,
    folder         TEXT DEFAULT 'INBOX'
);

-- Every message the inbox check read, so it can be reread in the app instead of
-- only counted. The body is stored as plain text and capped when it is saved.
CREATE TABLE IF NOT EXISTS inbox_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    folder      TEXT,
    uid         INTEGER,
    from_name   TEXT,
    from_email  TEXT COLLATE NOCASE,
    subject     TEXT,
    body        TEXT,
    received_at TEXT,
    kind        TEXT,
    known       INTEGER DEFAULT 0,
    seen        INTEGER DEFAULT 0,
    saved_at    TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_inbox_uid ON inbox_messages(folder, uid);
CREATE INDEX IF NOT EXISTS idx_inbox_when ON inbox_messages(received_at DESC, id DESC);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT version FROM schema_info").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_info(version) VALUES (?)", (SCHEMA_VERSION,))
        return
    # Future schema upgrades are applied here, stepping version by version.
    if row["version"] < SCHEMA_VERSION:
        conn.execute("UPDATE schema_info SET version = ?", (SCHEMA_VERSION,))


# --- Generic helpers --------------------------------------------------------
def query(sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
    return connect().execute(sql, params).fetchall()


def query_one(sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
    return connect().execute(sql, params).fetchone()


def execute(sql: str, params: Sequence[Any] = ()) -> int:
    conn = connect()
    cur = conn.execute(sql, params)
    conn.commit()
    return cur.lastrowid if cur.lastrowid is not None else cur.rowcount


def execute_soft(sql: str, params: Sequence[Any] = ()) -> bool:
    """Like execute(), but a busy database is not an error.

    For writes nobody would miss if they were skipped, such as remembering
    which page was open last. Raising here would abort whatever the user was
    doing, and the only cause is another thread mid-write.
    """
    try:
        execute(sql, params)
        return True
    except sqlite3.OperationalError:
        return False


def execute_many(sql: str, rows: Iterable[Sequence[Any]]) -> None:
    conn = connect()
    conn.executemany(sql, rows)
    conn.commit()


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# --- Settings ---------------------------------------------------------------
def get_setting(key: str, default: Any = None) -> Any:
    row = query_one("SELECT value FROM settings WHERE key = ?", (key,))
    if row is None:
        return default
    try:
        return json.loads(row["value"])
    except (json.JSONDecodeError, TypeError):
        return row["value"]


_SET_SETTING_SQL = ("INSERT INTO settings(key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value")


def set_setting(key: str, value: Any) -> None:
    execute(_SET_SETTING_SQL, (key, json.dumps(value)))


def set_setting_soft(key: str, value: Any) -> bool:
    """Save a setting, or skip it if another thread is mid-write. See execute_soft()."""
    return execute_soft(_SET_SETTING_SQL, (key, json.dumps(value)))


# --- Events / logging -------------------------------------------------------
def log_event(level: str, category: str, message: str, campaign_id: int | None = None) -> None:
    execute(
        "INSERT INTO events(ts, level, category, message, campaign_id) VALUES (?, ?, ?, ?, ?)",
        (now(), level, category, message, campaign_id),
    )


def recent_events(limit: int = 100) -> list[sqlite3.Row]:
    return query("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))


# --- Suppression ------------------------------------------------------------
def is_suppressed(email: str) -> bool:
    return query_one("SELECT 1 FROM suppression WHERE email = ?", (email.strip(),)) is not None


def suppress(email: str, reason: str, source: str = "manual") -> None:
    execute(
        "INSERT INTO suppression(email, reason, source, added_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(email) DO UPDATE SET reason = excluded.reason, source = excluded.source",
        (email.strip(), reason, source, now()),
    )


def unsuppress(email: str) -> None:
    execute("DELETE FROM suppression WHERE email = ?", (email.strip(),))


def suppression_list() -> list[sqlite3.Row]:
    return query("SELECT * FROM suppression ORDER BY added_at DESC")


# --- Inbox ------------------------------------------------------------------
# How many messages to keep. A year of checking a busy mailbox would otherwise
# grow the database without limit, and nobody scrolls back past a few hundred.
INBOX_KEEP = 800


def save_message(folder: str, uid: int, *, from_name: str, from_email: str, subject: str,
                 body: str, received_at: str, kind: str, known: bool) -> None:
    """Record one message. Re-reading the same UID updates it rather than duplicating."""
    execute(
        "INSERT INTO inbox_messages(folder, uid, from_name, from_email, subject, body, "
        "received_at, kind, known, seen, saved_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?) "
        "ON CONFLICT(folder, uid) DO UPDATE SET "
        "from_name = excluded.from_name, from_email = excluded.from_email, "
        "subject = excluded.subject, body = excluded.body, kind = excluded.kind, "
        "known = excluded.known",
        (folder, int(uid), from_name, from_email, subject, body, received_at, kind,
         1 if known else 0, now()),
    )


def inbox_messages(kind: str | None = None, limit: int = INBOX_KEEP) -> list[sqlite3.Row]:
    if kind:
        return query(
            "SELECT * FROM inbox_messages WHERE kind = ? "
            "ORDER BY received_at DESC, id DESC LIMIT ?", (kind, limit))
    return query("SELECT * FROM inbox_messages ORDER BY received_at DESC, id DESC LIMIT ?",
                 (limit,))


def inbox_unseen() -> int:
    row = query_one("SELECT COUNT(*) AS n FROM inbox_messages WHERE seen = 0")
    return row["n"] if row else 0


def mark_message_seen(message_id: int, seen: bool = True) -> None:
    execute("UPDATE inbox_messages SET seen = ? WHERE id = ?", (1 if seen else 0, message_id))


def mark_all_messages_seen() -> None:
    execute("UPDATE inbox_messages SET seen = 1 WHERE seen = 0")


def trim_inbox(keep: int = INBOX_KEEP) -> None:
    execute(
        "DELETE FROM inbox_messages WHERE id NOT IN ("
        "SELECT id FROM inbox_messages ORDER BY received_at DESC, id DESC LIMIT ?)", (keep,))


def clear_inbox() -> None:
    execute("DELETE FROM inbox_messages")


# --- Campaign stats ---------------------------------------------------------
def campaign_stats(campaign_id: int) -> dict[str, int]:
    rows = query(
        "SELECT status, COUNT(*) AS n FROM campaign_recipients WHERE campaign_id = ? GROUP BY status",
        (campaign_id,),
    )
    stats = {r["status"]: r["n"] for r in rows}
    stats["total"] = sum(stats.values())
    return stats


def sent_today_count() -> int:
    today = date.today().isoformat()
    row = query_one(
        "SELECT COUNT(*) AS n FROM campaign_recipients WHERE status = 'sent' AND sent_at LIKE ?",
        (f"{today}%",),
    )
    return row["n"] if row else 0
