"""Delivery reports from the sending service: delivered, opened, clicked, bounced, spam.

HomingPigeon has no server, so it cannot see an email being opened. A sending
service such as Brevo can, because the email goes out through it. The user
pastes that service's API key on My email account and this module asks the
service what happened to recent emails, then writes it onto the sent history.

Brevo, SendGrid, Mailgun and Postmark each report differently; each one's events
are turned into the same plain tuple, ``(email, kind, when, detail)``, and
``apply`` does the rest. Kinds: delivered, opened, clicked, hard_bounce,
blocked, spam, unsubscribed.

Temporary ("soft") bounces are left alone on purpose: the service keeps trying
by itself, and resending from here could email the same person twice.

Only emails HomingPigeon sent are touched. Events for other mail the user sends
through the same service find no match in ``sent_log`` and are skipped.
"""
from __future__ import annotations

import base64
import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app import config
from app.core import credentials, db, imap_sync, tls
from app.i18n import t

SERVICES = {"brevo": "Brevo", "sendgrid": "SendGrid", "mailgun": "Mailgun",
            "postmark": "Postmark"}
API_KEY = "stats_api_key"

FIRST_CHECK_DAYS = 30
MAX_DAYS = 89              # Brevo answers for 90 days at most
MAX_PAGES = 20
# The service's clock and this computer's can disagree by a little
CLOCK_SLACK = timedelta(minutes=10)

_lock = threading.Lock()


class ServiceError(Exception):
    def __init__(self, message: str, code: int = 0):
        super().__init__(message)
        self.code = code


@dataclass
class DeliveryResult:
    counts: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def add(self, kind: str) -> None:
        self.counts[kind] = self.counts.get(kind, 0) + 1

    @property
    def removed(self) -> int:
        """Addresses newly put on the do-not-email list."""
        return sum(self.counts.get(kind, 0)
                   for kind in ("hard_bounce", "blocked", "spam", "unsubscribed"))

    def summary(self) -> str:
        if self.errors:
            return self.errors[0]
        parts = []
        for kind, label in (
                ("delivered", "{count} delivered"), ("opened", "{count} opened"),
                ("clicked", "{count} clicked"), ("hard_bounce", "{count} bounced"),
                ("blocked", "{count} blocked"), ("spam", "{count} marked as spam"),
                ("unsubscribed", "{count} unsubscribed")):
            if self.counts.get(kind):
                parts.append(t(label, count=self.counts[kind]))
        return " · ".join(parts) if parts else t("No new delivery reports.")


# --- what was set up --------------------------------------------------------------
def configured() -> tuple[str, str] | None:
    """(service, API key) when delivery reports are set up, else None."""
    service = db.get_setting("stats_service", "")
    key = credentials.load_secret(API_KEY)
    return (service, key) if service in SERVICES and key else None


def _mailgun_domain() -> str:
    # Mailgun's SMTP login is postmaster@<sending domain>, which is the domain it reports on
    for value in (db.get_setting("smtp_username", ""), db.get_setting("sender_email", "")):
        if "@" in (value or ""):
            return value.rsplit("@", 1)[1].strip().lower()
    return ""


# --- talking to the services ------------------------------------------------------
def _get(url: str, headers: dict) -> dict | list:
    request = urllib.request.Request(url, headers={"Accept": "application/json", **headers})
    try:
        with urllib.request.urlopen(request, timeout=30, context=tls.secure_context()) as reply:
            return json.loads(reply.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise ServiceError(t("The API key was not accepted. Copy it again from your "
                                 "sending service and paste it on My email account."),
                               error.code) from error
        raise ServiceError(t("The sending service answered with an error ({code}).",
                             code=error.code), error.code) from error
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise ServiceError(t("Could not reach the sending service: {error}",
                             error=error)) from error


def local_time(value) -> str | None:
    """A service's timestamp (ISO text or seconds since 1970) as this computer's local time."""
    try:
        if isinstance(value, (int, float)):
            moment = datetime.fromtimestamp(value, tz=timezone.utc)
        else:
            text = str(value).strip().replace("Z", "+00:00")
            # Postmark sends seven decimal places, more than Python reads
            text = re.sub(r"(\.\d{6})\d+", r"\1", text)
            moment = datetime.fromisoformat(text)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    return moment.astimezone().replace(tzinfo=None).isoformat(timespec="seconds")


BREVO_KINDS = {"delivered": "delivered", "opened": "opened", "uniqueOpened": "opened",
               "clicks": "clicked", "hardBounces": "hard_bounce", "invalid": "hard_bounce",
               "blocked": "blocked", "spam": "spam", "unsubscribed": "unsubscribed"}


def brevo_events(key: str, since: datetime, _domain: str = "") -> tuple[list, list]:
    found = []
    query = {"limit": 2500, "startDate": since.date().isoformat(),
             "endDate": datetime.now().date().isoformat(), "sort": "asc"}
    for page in range(MAX_PAGES):
        data = _get("https://api.brevo.com/v3/smtp/statistics/events?"
                    + urllib.parse.urlencode({**query, "offset": page * 2500}), {"api-key": key})
        items = data.get("events", []) if isinstance(data, dict) else []
        for item in items:
            kind = BREVO_KINDS.get(item.get("event", ""))
            if kind:
                found.append((item.get("email"), kind, item.get("date"),
                              item.get("reason") or ""))
        if len(items) < 2500:
            break
    return found, []


SENDGRID_LISTS = (("bounces", "hard_bounce"), ("invalid_emails", "hard_bounce"),
                  ("blocks", "blocked"), ("spam_reports", "spam"),
                  ("unsubscribes", "unsubscribed"))


def sendgrid_events(key: str, since: datetime, _domain: str = "") -> tuple[list, list]:
    base, headers = "https://api.sendgrid.com/v3", {"Authorization": f"Bearer {key}"}
    found, notes = [], []
    for path, kind in SENDGRID_LISTS:
        data = _get(f"{base}/suppression/{path}?start_time={int(since.timestamp())}&limit=500",
                    headers)
        for item in data if isinstance(data, list) else []:
            found.append((item.get("email"), kind, item.get("created"), item.get("reason") or ""))

    # Opens and clicks come from Email Activity, which SendGrid sells as an add-on
    utc = "%Y-%m-%dT%H:%M:%SZ"
    query = (f'last_event_time BETWEEN TIMESTAMP "{since.astimezone(timezone.utc):{utc}}" '
             f'AND TIMESTAMP "{datetime.now(timezone.utc):{utc}}"')
    try:
        data = _get(f"{base}/messages?" + urllib.parse.urlencode({"limit": 1000, "query": query}),
                    headers)
    except ServiceError as error:
        if error.code not in (400, 403, 404):
            raise
        notes.append(t("SendGrid shares opens and clicks only with its Email Activity add-on. "
                       "Bounces and spam reports still come through."))
        data = {}
    for message in data.get("messages", []) if isinstance(data, dict) else []:
        email, when = message.get("to_email"), message.get("last_event_time")
        if message.get("status") == "delivered":
            found.append((email, "delivered", when, ""))
        if message.get("opens_count"):
            found.append((email, "opened", when, ""))
        if message.get("clicks_count"):
            found.append((email, "clicked", when, ""))
    return found, notes


MAILGUN_KINDS = {"delivered": "delivered", "opened": "opened", "clicked": "clicked",
                 "complained": "spam", "unsubscribed": "unsubscribed"}


def mailgun_event(item: dict):
    kind = MAILGUN_KINDS.get(item.get("event", ""))
    if item.get("event") == "failed" and item.get("severity") == "permanent":
        kind = "hard_bounce"
    if not kind:
        return None
    status = item.get("delivery-status") or {}
    detail = status.get("message") or status.get("description") or item.get("reason") or ""
    return item.get("recipient"), kind, item.get("timestamp"), detail


def mailgun_events(key: str, since: datetime, domain: str = "") -> tuple[list, list]:
    if not domain:
        raise ServiceError(t("Mailgun needs your sending domain: use your Mailgun SMTP login "
                             "(postmaster@your-domain) as the username on this page."))
    headers = {"Authorization": "Basic " + base64.b64encode(f"api:{key}".encode()).decode()}
    query = urllib.parse.urlencode({"begin": int(since.timestamp()), "ascending": "yes",
                                    "limit": 300})
    data: dict = {}
    # Accounts live in the US or in the EU, and each only answers for its own
    for region in ("https://api.mailgun.net", "https://api.eu.mailgun.net"):
        try:
            data = _get(f"{region}/v3/{domain}/events?{query}", headers)
            break
        except ServiceError as error:
            if error.code not in (401, 404) or region.endswith("eu.mailgun.net"):
                raise
    found = []
    for _ in range(MAX_PAGES):
        items = data.get("items", []) if isinstance(data, dict) else []
        if not items:
            break
        found += [event for event in map(mailgun_event, items) if event]
        following = (data.get("paging") or {}).get("next")
        if not following:
            break
        data = _get(following, headers)
    return found, []


POSTMARK_BOUNCES = {"HardBounce": "hard_bounce", "BadEmailAddress": "hard_bounce",
                    "Blocked": "blocked", "SpamComplaint": "spam", "Unsubscribe": "unsubscribed",
                    "ManuallyDeactivated": "blocked"}


def postmark_events(key: str, since: datetime, _domain: str = "") -> tuple[list, list]:
    base, headers = "https://api.postmarkapp.com", {"X-Postmark-Server-Token": key}
    oldest = since.replace(tzinfo=None).isoformat(timespec="seconds")

    def pages(path: str, rows_key: str, extra: str = ""):
        for page in range(MAX_PAGES):
            data = _get(f"{base}/{path}?count=500&offset={page * 500}{extra}", headers)
            rows = data.get(rows_key) or [] if isinstance(data, dict) else []
            yield from rows
            # Newest first, so once a page is older than the last check there is nothing new
            if len(rows) < 500 or all((local_time(r.get("ReceivedAt")) or "") < oldest
                                      for r in rows):
                return

    found = []
    for row in pages("bounces", "Bounces", f"&fromdate={since.date().isoformat()}"):
        kind = POSTMARK_BOUNCES.get(row.get("Type", ""))
        if kind:
            found.append((row.get("Email"), kind, row.get("BouncedAt"),
                          row.get("Description") or ""))
    for path, rows_key, kind in (("messages/outbound/opens", "Opens", "opened"),
                                 ("messages/outbound/clicks", "Clicks", "clicked")):
        for row in pages(path, rows_key):
            found.append((row.get("Recipient"), kind, row.get("ReceivedAt"), ""))
    return found, []


FETCHERS = {"brevo": brevo_events, "sendgrid": sendgrid_events, "mailgun": mailgun_events,
            "postmark": postmark_events}


# --- writing it down ----------------------------------------------------------------
# What each kind marks on the sent email: a click means it was opened and delivered too
STAMPS = {"delivered": ("delivered_at",), "opened": ("opened_at", "delivered_at"),
          "clicked": ("clicked_at", "opened_at", "delivered_at")}


def _sent_row(email: str, when: str, timed: bool):
    """The email this report is about: the latest one sent to that address.

    Opens and deliveries must come after the email went out. Bounces and spam
    reports need not: a service that already had the address blocked drops the
    email without a new event.
    """
    if timed:
        limit = (datetime.fromisoformat(when) + CLOCK_SLACK).isoformat(timespec="seconds")
        return db.query_one(
            "SELECT id, status FROM sent_log WHERE email = ? AND status IN ('sent', 'bounced') "
            "AND sent_at <= ? ORDER BY sent_at DESC LIMIT 1", (email, limit))
    return db.query_one("SELECT id, status FROM sent_log WHERE email = ? AND sent_at IS NOT NULL "
                        "ORDER BY sent_at DESC LIMIT 1", (email,))


def apply(events: list, service: str, result: DeliveryResult | None = None) -> DeliveryResult:
    result = result or DeliveryResult()
    label = SERVICES.get(service, service)
    conn = db.connect()
    for email, kind, when, detail in events:
        email, when = str(email or "").strip().lower(), local_time(when)
        if not email or not when:
            continue
        row = _sent_row(email, when, timed=kind in STAMPS)
        if row is None:
            continue
        if kind in STAMPS:
            first, *rest = STAMPS[kind]
            with conn:
                changed = conn.execute(f"UPDATE sent_log SET {first} = ? WHERE id = ? "
                                       f"AND {first} IS NULL", (when, row["id"])).rowcount
                for column in rest:
                    conn.execute(f"UPDATE sent_log SET {column} = COALESCE({column}, ?) "
                                 "WHERE id = ?", (when, row["id"]))
            if changed:
                result.add(kind)
            continue

        if kind == "spam":
            db.execute("UPDATE sent_log SET complained_at = COALESCE(complained_at, ?) "
                       "WHERE id = ?", (when, row["id"]))
        if db.is_suppressed(email):
            continue        # already dealt with, on this check or an earlier one
        detail = str(detail or "").strip()
        if kind == "hard_bounce":
            imap_sync.record_hard_bounce(email, detail or t("Reported by {service}",
                                                            service=label))
        elif kind == "blocked":
            imap_sync.record_hard_bounce(
                email, detail or t("Blocked by {service}", service=label),
                reason=t("Blocked by {service}", service=label))
        elif kind == "spam":
            db.suppress(email, t("Marked your email as spam"), source="complaint")
            db.execute("UPDATE contacts SET valid = 0 WHERE email = ?", (email,))
        elif kind == "unsubscribed":
            db.suppress(email, t("Unsubscribed through {service}", service=label),
                        source="unsubscribe")
            db.execute("UPDATE contacts SET valid = 0 WHERE email = ?", (email,))
        else:
            continue
        result.add(kind)
    return result


def check(service: str | None = None, key: str | None = None) -> DeliveryResult:
    """Ask the sending service what happened since the last check. Runs on a worker thread."""
    result = DeliveryResult()
    if service is None or key is None:
        setup = configured()
        if setup is None:
            return result
        service, key = setup
    if service not in FETCHERS:
        return result
    if not _lock.acquire(blocking=False):
        return result
    try:
        started = datetime.now()
        try:
            last = datetime.fromisoformat(db.get_setting("stats_checked_at", "") or "")
            since = last - timedelta(days=1)
        except ValueError:
            since = started - timedelta(days=FIRST_CHECK_DAYS)
        since = max(since, started - timedelta(days=MAX_DAYS)).astimezone()
        try:
            events, result.notes = FETCHERS[service](key, since, _mailgun_domain())
        except ServiceError as error:
            result.errors.append(str(error))
            return result
        apply(events, service, result)
        db.set_setting("stats_checked_at", started.isoformat(timespec="seconds"))
        db.log_event("info", "delivery", result.summary())
        return result
    finally:
        _lock.release()


# --- reading it back -------------------------------------------------------------------
def _value(row, key: str):
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


def outcome(row) -> tuple[str, str]:
    """(label, colour) for one sent email: the most telling thing that happened to it."""
    if _value(row, "replied_at"):
        return "Replied", "success"
    if _value(row, "complained_at"):
        return "Marked as spam", "error"
    if _value(row, "status") == "bounced" or _value(row, "bounced_at"):
        return "Bounced", "error"
    if _value(row, "status") == "failed":
        return "Failed", "error"
    if _value(row, "clicked_at"):
        return "Clicked", "success"
    if _value(row, "opened_at"):
        return "Opened", "accent"
    if _value(row, "delivered_at"):
        return "Delivered", "fg"
    return "Sent", "fg"


def campaign_results(limit: int = 5) -> list[dict]:
    """Totals for the latest campaigns, for the Dashboard."""
    rows = db.query(
        "SELECT c.name, COUNT(*) AS sent, "
        "SUM(s.delivered_at IS NOT NULL) AS delivered, "
        "SUM(s.opened_at IS NOT NULL) AS opened, SUM(s.clicked_at IS NOT NULL) AS clicked, "
        "SUM(s.replied_at IS NOT NULL) AS replied, SUM(s.status = 'bounced') AS bounced, "
        "SUM(s.complained_at IS NOT NULL) AS spam "
        "FROM sent_log s JOIN campaigns c ON c.id = s.campaign_id "
        "WHERE s.status IN ('sent', 'bounced') GROUP BY c.id ORDER BY c.id DESC LIMIT ?",
        (limit,))
    return [{key: row[key] or 0 for key in row.keys()} | {"name": row["name"]} for row in rows]


def history(email: str) -> list:
    """Everything sent to one person, newest first, with what happened to each."""
    return db.query(
        "SELECT s.subject, s.sent_at, s.status, s.last_error, s.delivered_at, s.opened_at, "
        "s.clicked_at, s.complained_at, COALESCE(s.replied_at, c.replied_at) AS replied_at, "
        "COALESCE(s.bounced_at, c.bounced_at) AS bounced_at "
        "FROM sent_log s LEFT JOIN contacts c ON c.email = s.email "
        "WHERE s.email = ? AND s.status IN ('sent', 'failed', 'bounced') "
        "ORDER BY s.sent_at DESC", (email.strip().lower(),))


def complaint_rate(campaign_id: int, since: str, attempted: int) -> float:
    """Spam complaints in a send run, for the safety brake."""
    if attempted < config.MIN_SAMPLE_FOR_BOUNCE_RATE:
        return 0.0
    row = db.query_one("SELECT COUNT(*) AS n FROM sent_log WHERE campaign_id = ? "
                       "AND complained_at IS NOT NULL AND sent_at >= ?", (campaign_id, since))
    return (row["n"] if row else 0) / attempted
