"""IMAP inbox scanning: bounces, unsubscribe requests and genuine replies.

Bounces are parsed from the standard delivery-status report rather than guessed
from subject lines, so hard failures are classified accurately and only hard
failures go to the suppression list.
"""
from __future__ import annotations

import email
import imaplib
import re
import socket
import ssl
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.message import Message

from app.core import db

UNSUBSCRIBE_PHRASES = [
    "unsubscribe", "remove me", "opt out", "opt-out", "take me off", "stop emailing",
    "do not contact", "don't contact", "no longer wish", "remove from your list",
    "stop sending", "not interested",
]

BOUNCE_SENDERS = {
    "mailer-daemon", "postmaster", "mail delivery subsystem", "mail delivery system",
    "microsoftexchange", "noreply-dmarc",
}

BOUNCE_SUBJECTS = [
    "undeliverable", "delivery status notification", "returned mail", "delivery failure",
    "failure notice", "mail delivery failed", "undelivered mail", "delivery has failed",
]

EMAIL_IN_TEXT = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


@dataclass
class ImapSettings:
    host: str
    port: int = 993
    username: str = ""
    password: str = ""
    use_ssl: bool = True
    folder: str = "INBOX"
    timeout: int = 30


@dataclass
class SyncResult:
    scanned: int = 0
    hard_bounces: list[tuple[str, str]] = field(default_factory=list)
    soft_bounces: list[tuple[str, str]] = field(default_factory=list)
    unsubscribes: list[str] = field(default_factory=list)
    replies: list[tuple[str, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if not self.scanned:
            return "No new messages since the last check."
        parts = [f"{self.scanned} message(s) scanned"]
        if self.hard_bounces:
            parts.append(f"{len(self.hard_bounces)} hard bounce(s)")
        if self.soft_bounces:
            parts.append(f"{len(self.soft_bounces)} soft bounce(s)")
        if self.unsubscribes:
            parts.append(f"{len(self.unsubscribes)} unsubscribe(s)")
        if self.replies:
            parts.append(f"{len(self.replies)} reply(ies)")
        return " · ".join(parts)


# --- Connection -------------------------------------------------------------
def connect(settings: ImapSettings) -> imaplib.IMAP4:
    if settings.use_ssl:
        client = imaplib.IMAP4_SSL(settings.host, settings.port,
                                   ssl_context=ssl.create_default_context(),
                                   timeout=settings.timeout)
    else:
        client = imaplib.IMAP4(settings.host, settings.port, timeout=settings.timeout)
        client.starttls(ssl.create_default_context())
    client.login(settings.username, settings.password)
    return client


def test_connection(settings: ImapSettings) -> tuple[bool, str]:
    try:
        client = connect(settings)
        try:
            status, data = client.select(settings.folder, readonly=True)
            if status != "OK":
                return False, f"Signed in, but folder '{settings.folder}' could not be opened."
            count = int(data[0]) if data and data[0] else 0
            return True, f"Connected to {settings.host} — {count:,} messages in {settings.folder}."
        finally:
            try:
                client.logout()
            except Exception:
                pass
    except imaplib.IMAP4.error as error:
        text = str(error)
        if "AUTHENTICATIONFAILED" in text.upper():
            return False, ("Sign-in rejected. If this is Gmail or Outlook with 2-step verification, "
                           "you need an app password here too.")
        return False, f"IMAP error: {text}"
    except (socket.gaierror, socket.timeout, OSError) as error:
        return False, f"Could not reach {settings.host}:{settings.port} — {error}"


# --- Parsing ----------------------------------------------------------------
def _decode_header(value: str | None) -> str:
    if not value:
        return ""
    parts = []
    for text, charset in email.header.decode_header(value):
        if isinstance(text, bytes):
            parts.append(text.decode(charset or "utf-8", "replace"))
        else:
            parts.append(text)
    return "".join(parts)


def _body_text(message: Message, limit: int = 20000) -> str:
    chunks: list[str] = []
    for part in message.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if part.get_content_type() in ("text/plain", "text/html", "message/delivery-status"):
            try:
                payload = part.get_payload(decode=True)
            except Exception:
                continue
            if payload:
                charset = part.get_content_charset() or "utf-8"
                chunks.append(payload.decode(charset, "replace"))
        elif part.get_content_type() == "message/rfc822":
            for attached in part.get_payload():
                if isinstance(attached, Message):
                    chunks.append(str(attached.get("To", "")))
        if sum(len(c) for c in chunks) > limit:
            break
    return "\n".join(chunks)[:limit]


def is_bounce(message: Message) -> bool:
    sender = _decode_header(message.get("From", "")).lower()
    subject = _decode_header(message.get("Subject", "")).lower()

    if any(name in sender for name in BOUNCE_SENDERS):
        return True
    if any(phrase in subject for phrase in BOUNCE_SUBJECTS):
        return True
    if message.get_content_type() == "multipart/report":
        return True
    if message.get("Auto-Submitted", "").lower().startswith("auto-replied"):
        return any(phrase in subject for phrase in BOUNCE_SUBJECTS)
    return False


def parse_bounce(message: Message) -> tuple[str | None, bool, str]:
    """Return (failed address, is_hard, detail) from a delivery-status report."""
    failed: str | None = None
    status_code = ""
    diagnostic = ""

    for part in message.walk():
        if part.get_content_type() != "message/delivery-status":
            continue
        payload = part.get_payload()
        blocks = payload if isinstance(payload, list) else []
        for block in blocks:
            if not isinstance(block, Message):
                continue
            recipient = block.get("Final-Recipient") or block.get("Original-Recipient")
            if recipient and not failed:
                match = EMAIL_IN_TEXT.search(recipient)
                if match:
                    failed = match.group(0).lower()
            status = block.get("Status")
            if status:
                status_code = status.strip()
            diag = block.get("Diagnostic-Code")
            if diag:
                diagnostic = diag.strip()[:300]

    text = _body_text(message)

    if not failed:
        # Fall back to the first address in the body that we actually mailed
        for candidate in EMAIL_IN_TEXT.findall(text):
            candidate = candidate.lower()
            row = db.query_one("SELECT 1 FROM contacts WHERE email = ?", (candidate,))
            if row:
                failed = candidate
                break

    if status_code.startswith("5"):
        hard = True
    elif status_code.startswith("4"):
        hard = False
    else:
        lowered = (diagnostic + " " + text).lower()
        hard_markers = ["user unknown", "no such user", "does not exist", "unknown recipient",
                        "mailbox unavailable", "address rejected", "recipient not found",
                        "invalid recipient", "no mailbox", "550", "account has been disabled",
                        "domain not found"]
        soft_markers = ["quota", "mailbox full", "over quota", "temporarily", "try again",
                        "greylist", "deferred", "timed out", "451", "452", "rate limit"]
        if any(m in lowered for m in soft_markers):
            hard = False
        else:
            hard = any(m in lowered for m in hard_markers)

    detail = diagnostic or (status_code and f"Status {status_code}") or "Delivery failed"
    return failed, hard, detail


def is_unsubscribe(message: Message) -> bool:
    subject = _decode_header(message.get("Subject", "")).lower()
    if any(phrase in subject for phrase in UNSUBSCRIBE_PHRASES):
        return True
    body = _body_text(message, limit=4000).lower()
    # Only the first part of a reply counts; quoted history contains our own footer
    head = body.split(">")[0][:1500]
    return any(phrase in head for phrase in UNSUBSCRIBE_PHRASES)


def sender_address(message: Message) -> str:
    raw = _decode_header(message.get("Reply-To") or message.get("From", ""))
    match = EMAIL_IN_TEXT.search(raw)
    return match.group(0).lower() if match else ""


# --- Sync -------------------------------------------------------------------
def _state() -> dict:
    row = db.query_one("SELECT * FROM imap_state WHERE id = 1")
    if row is None:
        db.execute("INSERT INTO imap_state(id, last_uid, folder) VALUES (1, 0, 'INBOX')")
        return {"last_uid": 0, "last_sync_at": None, "folder": "INBOX"}
    return dict(row)


def sync(settings: ImapSettings, days_back: int = 30, progress=None) -> SyncResult:
    """Scan new mail and apply bounces / unsubscribes to the database."""
    result = SyncResult()
    state = _state()
    last_uid = int(state.get("last_uid") or 0)

    try:
        client = connect(settings)
    except Exception as error:  # noqa: BLE001
        result.errors.append(f"Could not connect: {error}")
        return result

    try:
        status, _ = client.select(settings.folder, readonly=True)
        if status != "OK":
            result.errors.append(f"Could not open folder '{settings.folder}'.")
            return result

        if last_uid:
            criteria = f"(UID {last_uid + 1}:*)"
        else:
            since = (datetime.now() - timedelta(days=days_back)).strftime("%d-%b-%Y")
            criteria = f'(SINCE "{since}")'

        status, data = client.uid("SEARCH", None, criteria)
        if status != "OK":
            result.errors.append("Search failed on the mail server.")
            return result

        uids = [u for u in (data[0].split() if data and data[0] else [])]
        # An open-ended UID range always returns the last message; drop it if already seen
        uids = [u for u in uids if int(u) > last_uid]
        highest = last_uid

        for index, uid in enumerate(uids):
            if progress:
                progress(index, len(uids))
            highest = max(highest, int(uid))

            status, payload = client.uid("FETCH", uid, "(RFC822)")
            if status != "OK" or not payload or not isinstance(payload[0], tuple):
                continue

            try:
                message = email.message_from_bytes(payload[0][1])
            except Exception:
                continue

            result.scanned += 1
            _classify(message, result)

        db.execute(
            "UPDATE imap_state SET last_uid = ?, last_sync_at = ?, folder = ? WHERE id = 1",
            (highest, db.now(), settings.folder),
        )
        if progress:
            progress(len(uids), len(uids))
    except Exception as error:  # noqa: BLE001
        result.errors.append(f"{type(error).__name__}: {error}")
    finally:
        try:
            client.close()
        except Exception:
            pass
        try:
            client.logout()
        except Exception:
            pass

    db.log_event("info", "imap", result.summary())
    return result


def _classify(message: Message, result: SyncResult) -> None:
    if is_bounce(message):
        address, hard, detail = parse_bounce(message)
        if not address:
            return
        if hard:
            result.hard_bounces.append((address, detail))
            db.suppress(address, f"Hard bounce: {detail}"[:200], source="bounce")
            db.execute("UPDATE contacts SET bounced_at = ?, valid = 0 WHERE email = ?",
                       (db.now(), address))
            db.execute(
                "UPDATE campaign_recipients SET status = 'bounced', last_error = ? "
                "WHERE contact_id = (SELECT id FROM contacts WHERE email = ?) AND status = 'sent'",
                (detail[:400], address),
            )
        else:
            result.soft_bounces.append((address, detail))
            db.execute("UPDATE contacts SET bounced_at = ? WHERE email = ?", (db.now(), address))
        return

    address = sender_address(message)
    if not address:
        return

    known = db.query_one("SELECT id FROM contacts WHERE email = ?", (address,))
    if not known:
        return  # not one of ours; ignore ordinary inbox traffic

    if is_unsubscribe(message):
        result.unsubscribes.append(address)
        db.suppress(address, "Requested unsubscribe by reply", source="reply")
        db.execute("UPDATE contacts SET valid = 0 WHERE email = ?", (address,))
        return

    subject = _decode_header(message.get("Subject", ""))
    result.replies.append((address, subject))
    db.execute("UPDATE contacts SET replied_at = ? WHERE email = ?", (db.now(), address))


def replied_contacts(limit: int = 200) -> list:
    return db.query(
        "SELECT * FROM contacts WHERE replied_at IS NOT NULL ORDER BY replied_at DESC LIMIT ?",
        (limit,),
    )


def bounce_rate() -> float:
    row = db.query_one(
        "SELECT SUM(status = 'sent') AS sent, SUM(status = 'bounced') AS bounced "
        "FROM campaign_recipients"
    )
    if not row or not row["sent"]:
        return 0.0
    total = (row["sent"] or 0) + (row["bounced"] or 0)
    return (row["bounced"] or 0) / total if total else 0.0
