"""IMAP inbox scanning: bounces, unsubscribe requests and genuine replies.

Bounces are parsed from the standard delivery-status report rather than guessed
from subject lines, so hard failures are classified accurately and only hard
failures go to the suppression list.

Every message read is also saved to ``inbox_messages`` as plain text, so the
app has a real inbox to show rather than only the counts it acted on.
"""
from __future__ import annotations

import email
import email.header
import email.utils
import imaplib
import re
import socket
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.message import Message

from app.core import composer, db, tls
from app.i18n import t

UNSUBSCRIBE_PHRASES = [
    "unsubscribe", "remove me", "opt out", "opt-out", "take me off", "stop emailing",
    "do not contact", "don't contact", "no longer wish", "remove from your list",
    "stop sending", "not interested",
    # The other app languages, so a reply to a German or Arabic email is caught too
    "abmelden", "austragen", "keine e-mails mehr", "kein interesse",
    "darse de baja", "darme de baja", "baja", "no me interesa", "no deseo recibir",
    "désabonner", "désinscrire", "desinscrire", "désabonnement", "pas intéressé",
    "ne plus recevoir",
    "إلغاء الاشتراك", "الغاء الاشتراك", "أزلني", "لا أرغب", "غير مهتم", "توقفوا عن",
]

BOUNCE_SENDERS = {
    "mailer-daemon", "postmaster", "mail delivery subsystem", "mail delivery system",
    "microsoftexchange", "noreply-dmarc",
}

BOUNCE_SUBJECTS = [
    "undeliverable", "delivery status notification", "returned mail", "delivery failure",
    "failure notice", "mail delivery failed", "undelivered mail", "delivery has failed",
    "not delivered", "could not be delivered", "couldn't be delivered", "message blocked",
    "delivery incomplete", "returned to sender", "nondeliverable", "non-delivery",
    "unzustellbar", "nicht zugestellt", "no se pudo entregar", "non remis", "non distribuable",
]

# "Still trying" notices. The email may yet arrive, so these are not bounces.
DELAY_SUBJECTS = [
    "delayed", "(delay)", "delivery delay", "warning: message", "not yet been delivered",
    "still trying", "will retry", "verzögert", "retrasado", "retardé",
]

# Out-of-office and other automatic answers: real mail from the person's
# mailbox, but not a reply from the person
AUTO_REPLY_SUBJECTS = (
    "automatic reply", "auto reply", "autoreply", "auto-reply", "auto:", "out of office",
    "out of the office", "away from the office", "on vacation", "on holiday",
    "abwesenheitsnotiz", "automatische antwort", "respuesta automática", "fuera de la oficina",
    "réponse automatique", "absence du bureau", "رد تلقائي", "خارج المكتب",
)

# Wording that means the address is dead, from Gmail, Outlook and Microsoft 365,
# Yahoo, Zoho and the common mail servers
HARD_MARKERS = [
    "user unknown", "no such user", "does not exist", "doesn't exist", "unknown recipient",
    "mailbox unavailable", "address rejected", "recipient not found", "recipientnotfound",
    "invalid recipient", "no mailbox", "account has been disabled", "account is disabled",
    "mailbox is disabled", "domain not found", "wasn't found at", "was not found at",
    "couldn't be found", "could not be found", "address not found", "unrouteable address",
    "invalid address", "no such address", "mailbox not found", "user doesn't have",
    "is not a valid mailbox", "bad destination mailbox", "unknown user", "invalid mailbox",
    "550", "554 delivery error", "5.1.1", "5.1.10", "5.4.1", "5.1.2",
]
SOFT_MARKERS = [
    "quota", "mailbox full", "mailbox is full", "over quota", "insufficient storage",
    "temporarily", "temporary", "try again", "greylist", "deferred", "timed out", "451",
    "452", "rate limit", "too many", "5.2.2", "4.2.2",
]

MESSAGE_ID = re.compile(r"<[^<>\s]+@[^<>\s]+>")
JUNK_NAMES = ("junk", "junk email", "junk e-mail", "spam", "[gmail]/spam", "bulk mail",
              "inbox.junk", "inbox.spam", "junk-e-mail", "spam-verdacht")

EMAIL_IN_TEXT = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# How much of each message body to keep for reading in the app.
STORED_BODY_LIMIT = 8000


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
        parts = [t("{scanned} message(s) scanned", scanned=self.scanned)]
        if self.hard_bounces:
            parts.append(t("{count} hard bounce(s)", count=len(self.hard_bounces)))
        if self.soft_bounces:
            parts.append(t("{count} soft bounce(s)", count=len(self.soft_bounces)))
        if self.unsubscribes:
            parts.append(t("{count} unsubscribe(s)", count=len(self.unsubscribes)))
        if self.replies:
            parts.append(t("{count} reply(ies)", count=len(self.replies)))
        return " · ".join(parts)


# --- Connection -------------------------------------------------------------
def connect(settings: ImapSettings) -> imaplib.IMAP4:
    if settings.use_ssl:
        client = imaplib.IMAP4_SSL(settings.host, settings.port,
                                   ssl_context=tls.secure_context(),
                                   timeout=settings.timeout)
    else:
        client = imaplib.IMAP4(settings.host, settings.port, timeout=settings.timeout)
        client.starttls(tls.secure_context())
    client.login(settings.username, settings.password)
    return client


def test_connection(settings: ImapSettings) -> tuple[bool, str]:
    try:
        client = connect(settings)
        try:
            status, data = client.select(settings.folder, readonly=True)
            if status != "OK":
                return False, t("Signed in, but folder '{folder}' could not be opened.",
                                folder=settings.folder)
            count = int(data[0]) if data and data[0] else 0
            return True, t("Connected to {host}, {count:,} messages in {folder}.",
                           host=settings.host, count=count, folder=settings.folder)
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
        return False, t("IMAP error: {text}", text=text)
    except (socket.gaierror, socket.timeout, OSError) as error:
        return False, t("Could not reach {host}:{port}: {error}",
                        host=settings.host, port=settings.port, error=error)


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


def _decode_part(part: Message) -> str:
    """The text of one message part, whatever it claims its encoding is.

    Mail in the wild lies about charsets. A made-up charset name makes
    ``bytes.decode`` raise LookupError rather than UnicodeDecodeError, which
    used to escape the sync and abandon the whole inbox check over one bad
    message. A part labelled ASCII that is not ASCII is almost always UTF-8,
    and guessing that beats showing a line of replacement characters.
    """
    try:
        payload = part.get_payload(decode=True)
    except Exception:  # noqa: BLE001 - an unreadable part is worth skipping, not raising
        return ""
    if not payload:
        return ""

    charset = (part.get_content_charset() or "utf-8").strip().lower()
    if charset in ("ascii", "us-ascii", "ansi_x3.4-1968", "646"):
        charset = "utf-8"
    for candidate in (charset, "utf-8", "cp1252"):
        try:
            return payload.decode(candidate)
        except (UnicodeDecodeError, LookupError):
            continue
    return payload.decode("utf-8", "replace")


def _body_text(message: Message, limit: int = 20000) -> str:
    chunks: list[str] = []
    for part in message.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if part.get_content_type() in ("text/plain", "text/html", "message/delivery-status"):
            text = _decode_part(part)
            if text:
                chunks.append(text)
        elif part.get_content_type() == "message/rfc822":
            for attached in part.get_payload():
                if isinstance(attached, Message):
                    chunks.append(str(attached.get("To", "")))
        if sum(len(c) for c in chunks) > limit:
            break
    return "\n".join(chunks)[:limit]


def sender_name(message: Message) -> str:
    """The display name on the From line, without the address."""
    raw = _decode_header(message.get("From", ""))
    name = re.sub(r"<[^>]*>", "", raw).strip().strip('"').strip()
    return name if name and "@" not in name else ""


def received_at(message: Message) -> str:
    """The message date as an ISO string, falling back to now if it is unreadable."""
    try:
        moment = email.utils.parsedate_to_datetime(message.get("Date", ""))
    except (TypeError, ValueError):
        moment = None
    if moment is None:
        return db.now()
    if moment.tzinfo is not None:
        moment = moment.astimezone().replace(tzinfo=None)
    return moment.isoformat(timespec="seconds")


def readable_body(message: Message, limit: int = STORED_BODY_LIMIT) -> str:
    """The message as plain text: the text part if there is one, else the HTML converted.

    Delivery-status blocks are skipped here. They are what :func:`parse_bounce`
    reads, and they are machine noise to anyone looking at a bounce on screen.
    """
    plain: list[str] = []
    html: list[str] = []
    for part in message.walk():
        kind = part.get_content_type()
        if kind not in ("text/plain", "text/html"):
            continue
        text = _decode_part(part)
        if text:
            (plain if kind == "text/plain" else html).append(text)

    body = "\n".join(plain).strip() or composer.html_to_text("\n".join(html)).strip()
    if not body:
        body = _body_text(message, limit=limit).strip()
    body = body.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body[:limit]


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


def _status_blocks(message: Message):
    """The per-recipient blocks of a standard delivery-status report."""
    for part in message.walk():
        if part.get_content_type() != "message/delivery-status":
            continue
        payload = part.get_payload()
        for block in payload if isinstance(payload, list) else []:
            if isinstance(block, Message):
                yield block


def is_delay(message: Message) -> bool:
    """A "still trying to deliver" notice rather than a failure."""
    # The report's first block is about the server, not a recipient, and has no Action
    actions = [str(block["Action"]).strip().lower() for block in _status_blocks(message)
               if block.get("Action")]
    if actions:
        return all(action == "delayed" for action in actions)
    subject = _decode_header(message.get("Subject", "")).lower()
    return any(phrase in subject for phrase in DELAY_SUBJECTS)


def is_auto_reply(message: Message) -> bool:
    """Out-of-office and other automatic answers, from the standard headers or the subject."""
    auto = str(message.get("Auto-Submitted", "")).strip().lower()
    if auto and auto != "no":
        return True
    if message.get("X-Autoreply") or message.get("X-Autorespond"):
        return True
    if str(message.get("Precedence", "")).strip().lower() in ("auto_reply", "auto-reply"):
        return True
    subject = _decode_header(message.get("Subject", "")).lower().strip()
    return any(phrase in subject for phrase in AUTO_REPLY_SUBJECTS)


def original_message_id(message: Message) -> str:
    """The Message-ID of our email that bounced, from the copy the bounce carries."""
    for part in message.walk():
        kind = part.get_content_type()
        if kind in ("message/rfc822", "message/global"):
            payload = part.get_payload()
            for inner in payload if isinstance(payload, list) else []:
                if isinstance(inner, Message) and inner.get("Message-ID"):
                    match = MESSAGE_ID.search(str(inner["Message-ID"]))
                    if match:
                        return match.group(0)
        elif kind in ("text/rfc822-headers", "message/rfc822-headers"):
            found = re.search(r"^message-id:\s*(<[^>]+>)", _decode_part(part), re.I | re.M)
            if found:
                return found.group(1)
    for header in ("In-Reply-To", "References"):
        match = MESSAGE_ID.search(str(message.get(header, "") or ""))
        if match:
            return match.group(0)
    return ""


def parse_bounce(message: Message) -> tuple[str | None, bool, str]:
    """Return (failed address, is_hard, detail) from a delivery-status report.

    The surest match is the Message-ID: a bounce carries a copy of the email it
    returns, and every email the app sends has its ID saved in the history. The
    address in the report comes next, and a guess from the text is the last resort.
    """
    failed: str | None = None
    status_code = ""
    diagnostic = ""

    mid = original_message_id(message)
    if mid:
        row = db.query_one("SELECT email FROM sent_log WHERE message_id = ? LIMIT 1", (mid,))
        if row:
            failed = row["email"].lower()

    for block in _status_blocks(message):
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

    lowered = (diagnostic + " " + text).lower()
    if status_code.startswith("5.2.2"):
        hard = False        # a full mailbox: worth another try later
    elif status_code.startswith("5"):
        hard = True
    elif status_code.startswith("4"):
        hard = False
    elif any(m in lowered for m in SOFT_MARKERS):
        hard = False
    else:
        hard = any(m in lowered for m in HARD_MARKERS)

    detail = diagnostic or (status_code and t("Status {status_code}",
                                              status_code=status_code)) or "Delivery failed"
    return failed, hard, detail


# Whole words only: "baja" must not match inside "trabajamos", or an ordinary
# Spanish reply would take the sender off the list
_UNSUBSCRIBE = re.compile(
    "|".join(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)" for phrase in UNSUBSCRIBE_PHRASES))


def is_unsubscribe(message: Message) -> bool:
    subject = _decode_header(message.get("Subject", "")).lower()
    if _UNSUBSCRIBE.search(subject):
        return True
    body = _body_text(message, limit=4000).lower()
    # Only the first part of a reply counts; quoted history contains our own footer
    head = body.split(">")[0][:1500]
    return bool(_UNSUBSCRIBE.search(head))


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


# Only one inbox check at a time: the automatic one and the button can overlap,
# and two checks reading the same messages would count every bounce twice
_sync_lock = threading.Lock()


def _folder_marks() -> dict:
    """{folder: [uidvalidity, last uid read]} for every folder the check reads."""
    marks = db.get_setting("imap_folder_marks", {}) or {}
    return marks if isinstance(marks, dict) else {}


def find_junk_folder(client: imaplib.IMAP4) -> str | None:
    """The Junk or Spam folder: the one the server marks as Junk, else a usual name."""
    status, lines = client.list()
    if status != "OK" or not lines:
        return None
    named = None
    for raw in lines:
        line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        match = re.match(r'\((?P<flags>[^)]*)\)\s+(?:"[^"]*"|NIL)\s+(?P<name>.+)$', line)
        if not match:
            continue
        name = match.group("name").strip().strip('"')
        if "\\junk" in match.group("flags").lower():
            return name
        if named is None and name.lower() in JUNK_NAMES:
            named = name
    return named


def _uidvalidity(client: imaplib.IMAP4) -> str:
    _kind, data = client.response("UIDVALIDITY")
    value = data[0] if data else None
    return value.decode() if isinstance(value, bytes) else str(value or "")


def _quoted(folder: str) -> str:
    return f'"{folder}"' if " " in folder and not folder.startswith('"') else folder


def _scan_folder(client: imaplib.IMAP4, folder: str, result: SyncResult, days_back: int,
                 only_bounces: bool = False, progress=None) -> None:
    """Read the new mail in one folder and act on it.

    Each folder remembers the last message number it read. Servers renumber a
    folder now and then (after a mailbox move, say) and announce it with a new
    UIDVALIDITY; the old number then means nothing, so the recent days are read
    again instead of silently skipping everything.
    """
    status, _ = client.select(_quoted(folder), readonly=True)
    if status != "OK":
        if not only_bounces:
            result.errors.append(t("Could not open folder '{folder}'.", folder=folder))
        return
    validity = _uidvalidity(client)
    marks = _folder_marks()
    known_validity, last_uid = (marks.get(folder) or [None, 0])[:2]
    if folder not in marks and folder == (_state().get("folder") or "INBOX"):
        last_uid = int(_state().get("last_uid") or 0)     # read before v0.7.2
        known_validity = validity
    if validity and known_validity and str(validity) != str(known_validity):
        last_uid = 0
        db.execute("DELETE FROM inbox_messages WHERE folder = ?", (folder,))
    last_uid = int(last_uid or 0)

    if last_uid:
        criteria = f"(UID {last_uid + 1}:*)"
    else:
        since = (datetime.now() - timedelta(days=days_back)).strftime("%d-%b-%Y")
        criteria = f'(SINCE "{since}")'

    status, data = client.uid("SEARCH", None, criteria)
    if status != "OK":
        result.errors.append("Search failed on the mail server.")
        return

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

        # In Junk only bounces matter; everything else there stays junk
        if only_bounces and not is_bounce(message):
            continue
        result.scanned += 1
        kind, known = _classify(message, result)
        try:
            db.save_message(
                folder, int(uid),
                from_name=sender_name(message),
                from_email=sender_address(message),
                subject=_decode_header(message.get("Subject", "")) or "(no subject)",
                body=readable_body(message),
                received_at=received_at(message),
                kind=kind, known=known)
        except Exception as error:  # noqa: BLE001 - never lose a sync over one message
            db.log_event("warn", "imap", t("Could not save a message: {error}", error=error))

    marks = _folder_marks()
    marks[folder] = [validity, highest]
    db.set_setting("imap_folder_marks", marks)
    if progress:
        progress(len(uids), len(uids))


def sync(settings: ImapSettings, days_back: int = 30, progress=None) -> SyncResult:
    """Scan new mail and apply bounces / unsubscribes to the database."""
    result = SyncResult()
    if not _sync_lock.acquire(blocking=False):
        return result
    try:
        try:
            client = connect(settings)
        except Exception as error:  # noqa: BLE001
            result.errors.append(t("Could not connect: {error}", error=error))
            return result

        try:
            _state()
            _scan_folder(client, settings.folder, result, days_back, progress=progress)
            # Some providers file bounces under Junk, so that is read too, bounces only
            if not result.errors:
                junk = find_junk_folder(client)
                if junk and junk != settings.folder:
                    try:
                        _scan_folder(client, junk, result, days_back, only_bounces=True)
                    except imaplib.IMAP4.error:
                        pass        # an unreadable Junk folder must not spoil the inbox check
            db.execute("UPDATE imap_state SET last_sync_at = ?, folder = ? WHERE id = 1",
                       (db.now(), settings.folder))
            db.trim_inbox()
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
    finally:
        _sync_lock.release()


def _classify(message: Message, result: SyncResult) -> tuple[str, bool]:
    """Act on one message and report ``(kind, is_a_known_contact)`` for the inbox list."""
    if is_bounce(message):
        if is_delay(message):
            return "delay", False
        address, hard, detail = parse_bounce(message)
        if not address:
            return "bounce", False
        if hard:
            result.hard_bounces.append((address, detail))
            db.suppress(address, t("Hard bounce: {detail}", detail=detail)[:200], source="bounce")
            db.execute("UPDATE contacts SET bounced_at = ?, valid = 0 WHERE email = ?",
                       (db.now(), address))
            db.execute(
                "UPDATE campaign_recipients SET status = 'bounced', last_error = ? "
                "WHERE contact_id = (SELECT id FROM contacts WHERE email = ?) AND status = 'sent'",
                (detail[:400], address),
            )
            db.execute(
                "UPDATE sent_log SET status = 'bounced', bounced_at = ?, last_error = ? "
                "WHERE email = ? AND status = 'sent'",
                (db.now(), detail[:400], address.lower()),
            )
            db.execute("UPDATE contacted SET status = 'bounced' WHERE email = ? AND status = 'sent'",
                       (address,))
        else:
            result.soft_bounces.append((address, detail))
            _retry_later(address, detail)
        return "bounce", True

    address = sender_address(message)
    if not address:
        return "other", False

    known = db.query_one("SELECT id FROM contacts WHERE email = ?", (address,))
    if not known:
        # Not one of ours. It is still saved and readable in the app; it just
        # does not count as a reply and nothing is done about it.
        return "other", False

    # An out-of-office answer comes from the person's mailbox, not from the person
    if is_auto_reply(message):
        return "autoreply", True

    if is_unsubscribe(message):
        result.unsubscribes.append(address)
        db.suppress(address, "Requested unsubscribe by reply", source="reply")
        db.execute("UPDATE contacts SET valid = 0 WHERE email = ?", (address,))
        return "optout", True

    subject = _decode_header(message.get("Subject", ""))
    result.replies.append((address, subject))
    db.execute("UPDATE contacts SET replied_at = ? WHERE email = ?", (db.now(), address))
    db.execute("UPDATE sent_log SET replied_at = COALESCE(replied_at, ?) WHERE email = ?",
               (db.now(), address.lower()))
    return "reply", True


def _retry_later(address: str, detail: str) -> None:
    """A temporary bounce: try that person again on a later run, within the attempt limit."""
    from app import config

    note = t("Temporary problem, will try again: {detail}", detail=detail)[:400]
    connection = db.connect()
    with connection:
        connection.execute(
            "UPDATE campaign_recipients SET status = CASE WHEN attempts < ? THEN 'retry' "
            "ELSE 'failed' END, last_error = ? WHERE status = 'sent' "
            "AND contact_id IN (SELECT id FROM contacts WHERE email = ?)",
            (config.MAX_SEND_ATTEMPTS, note, address))
        # The record of who was emailed follows: a retry is not emailed yet, a last failure failed
        connection.execute(
            "DELETE FROM contacted WHERE email = ? AND status = 'sent' AND campaign_id IN "
            "(SELECT r.campaign_id FROM campaign_recipients r JOIN contacts c "
            "ON c.id = r.contact_id WHERE c.email = ? AND r.status = 'retry')",
            (address, address))
        connection.execute(
            "UPDATE contacted SET status = 'failed' WHERE email = ? AND status = 'sent'",
            (address,))
        connection.execute(
            "UPDATE sent_log SET status = 'failed', last_error = ? WHERE email = ? "
            "AND status = 'sent'", (note, address.lower()))


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
