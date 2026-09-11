"""The send worker.

Runs on its own thread and reports progress through a queue. Status is committed
to SQLite after every single message, so a crash, a closed laptop or a power cut
never loses track of who was already contacted.

Safety behaviour that matters more than speed:
  * randomised delay drawn from the user's min/max range
  * business-hours window; outside it the run waits instead of dying
  * daily cap from the warm-up ramp
  * circuit breaker on consecutive failures and on the hard-bounce rate
"""
from __future__ import annotations

import queue
import random
import smtplib
import socket
import ssl
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta
from enum import Enum

from app import config
from app.core import composer, db, merge, warmup


class State(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING = "waiting"      # outside the send window / cap reached
    STOPPED = "stopped"
    FINISHED = "finished"
    ERROR = "error"


class EventType(str, Enum):
    LOG = "log"
    SENT = "sent"
    FAILED = "failed"
    PROGRESS = "progress"
    STATE = "state"
    COUNTDOWN = "countdown"
    DONE = "done"


@dataclass
class Event:
    type: EventType
    message: str = ""
    level: str = "info"          # info | success | warn | error
    data: dict | None = None


@dataclass
class SmtpSettings:
    host: str
    port: int
    username: str
    password: str
    security: str = "auto"       # auto | starttls | ssl | none
    timeout: int = 30

    def resolved_security(self) -> str:
        if self.security != "auto":
            return self.security
        if self.port == 465:
            return "ssl"
        if self.port in (587, 25, 2525):
            return "starttls"
        return "starttls"


@dataclass
class SendPlan:
    campaign_id: int
    sender: composer.SenderIdentity
    content: composer.Content
    smtp: SmtpSettings
    delay_min_s: int = 75
    delay_max_s: int = 150
    window_start: str = "09:00"
    window_end: str = "18:00"
    weekdays_only: bool = True
    skip_holidays: bool = True
    daily_cap_override: int | None = None


# --- SMTP helpers -----------------------------------------------------------
def friendly_smtp_error(error: Exception, settings: SmtpSettings) -> str:
    """Turn an SMTP exception into something an office user can act on."""
    if isinstance(error, smtplib.SMTPAuthenticationError):
        code = error.smtp_code
        text = (error.smtp_error or b"").decode("utf-8", "replace") if isinstance(error.smtp_error, bytes) \
            else str(error.smtp_error)
        lowered = text.lower()
        if "application-specific password" in lowered or "app password" in lowered:
            return ("Google rejected the password. With 2-step verification on, you must create an "
                    "App Password (Google Account → Security → App passwords) and use that here, "
                    "not your normal login password.")
        if "basic authentication is disabled" in lowered or "smtpclientauthentication" in lowered.replace(" ", ""):
            return ("Microsoft 365 has SMTP AUTH disabled for this mailbox. An administrator must "
                    "enable 'Authenticated SMTP' for the user in the Microsoft 365 admin centre.")
        if "username and password not accepted" in lowered:
            return ("The server did not accept this username/password. Check the address is the full "
                    "mailbox name, and whether your provider requires an app-specific password.")
        return f"Authentication failed ({code}): {text.strip() or 'check the username and password'}"

    if isinstance(error, smtplib.SMTPConnectError):
        return (f"Could not connect to {settings.host}:{settings.port}. The port may be blocked by "
                f"your network or firewall — many ISPs block port 25. Try 587.")
    if isinstance(error, smtplib.SMTPServerDisconnected):
        return "The server closed the connection unexpectedly. This often means the wrong port or security setting."
    if isinstance(error, smtplib.SMTPNotSupportedError):
        return f"The server does not support the requested feature: {error}"
    if isinstance(error, ssl.SSLError):
        return (f"TLS handshake failed. Port 465 needs SSL and port 587 needs STARTTLS — "
                f"you currently have {settings.resolved_security()} on port {settings.port}.")
    if isinstance(error, socket.timeout):
        return f"Timed out connecting to {settings.host}:{settings.port}. Check the host name and your connection."
    if isinstance(error, socket.gaierror):
        return f"Host name '{settings.host}' could not be resolved. Check it for typos."
    if isinstance(error, ConnectionRefusedError):
        return f"{settings.host} refused the connection on port {settings.port}."
    return f"{type(error).__name__}: {error}"


def open_smtp(settings: SmtpSettings) -> smtplib.SMTP:
    security = settings.resolved_security()
    if security == "ssl":
        context = ssl.create_default_context()
        server = smtplib.SMTP_SSL(settings.host, settings.port,
                                  timeout=settings.timeout, context=context)
    else:
        server = smtplib.SMTP(settings.host, settings.port, timeout=settings.timeout)
        server.ehlo()
        if security == "starttls":
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
    if settings.username:
        server.login(settings.username, settings.password)
    return server


def test_connection(settings: SmtpSettings) -> tuple[bool, str]:
    """Used by the Account page's Test button."""
    try:
        server = open_smtp(settings)
        try:
            server.noop()
        finally:
            try:
                server.quit()
            except Exception:
                pass
        return True, f"Connected to {settings.host}:{settings.port} and signed in successfully."
    except Exception as error:  # noqa: BLE001 - surfaced to the user verbatim
        return False, friendly_smtp_error(error, settings)


# --- Send window ------------------------------------------------------------
def _parse_time(value: str, fallback: dtime) -> dtime:
    try:
        hour, minute = value.split(":")
        return dtime(int(hour), int(minute))
    except (ValueError, AttributeError):
        return fallback


def holidays() -> set[str]:
    return set(db.get_setting("holidays", []) or [])


def in_send_window(plan: SendPlan, moment: datetime | None = None) -> tuple[bool, str]:
    moment = moment or datetime.now()
    start = _parse_time(plan.window_start, dtime(9, 0))
    end = _parse_time(plan.window_end, dtime(18, 0))

    if plan.weekdays_only and moment.weekday() >= 5:
        return False, "Weekend — sending is paused until Monday"
    if plan.skip_holidays and moment.date().isoformat() in holidays():
        return False, "Public holiday — sending is paused"

    current = moment.time()
    if start <= end:
        inside = start <= current <= end
    else:  # window crosses midnight
        inside = current >= start or current <= end
    if not inside:
        return False, f"Outside the sending window ({plan.window_start}–{plan.window_end})"
    return True, ""


def next_window_open(plan: SendPlan, moment: datetime | None = None) -> datetime:
    moment = moment or datetime.now()
    start = _parse_time(plan.window_start, dtime(9, 0))
    candidate = datetime.combine(moment.date(), start)
    if candidate <= moment:
        candidate += timedelta(days=1)
    for _ in range(14):
        ok = True
        if plan.weekdays_only and candidate.weekday() >= 5:
            ok = False
        if plan.skip_holidays and candidate.date().isoformat() in holidays():
            ok = False
        if ok:
            return candidate
        candidate += timedelta(days=1)
    return candidate


# --- Worker -----------------------------------------------------------------
class SendWorker(threading.Thread):
    def __init__(self, plan: SendPlan, events: queue.Queue):
        super().__init__(daemon=True, name="SendWorker")
        self.plan = plan
        self.events = events
        self.state = State.IDLE
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._server: smtplib.SMTP | None = None
        self._since_reconnect = 0
        self._consecutive_failures = 0
        self.sent = 0
        self.failed = 0
        self.skipped = 0

    # -- control -------------------------------------------------------------
    def request_stop(self) -> None:
        self._stop_event.set()
        self._pause_event.clear()

    def request_pause(self) -> None:
        self._pause_event.set()
        self._set_state(State.PAUSED)

    def request_resume(self) -> None:
        self._pause_event.clear()
        self._set_state(State.RUNNING)

    @property
    def is_paused(self) -> bool:
        return self._pause_event.is_set()

    # -- event helpers -------------------------------------------------------
    def _emit(self, event: Event) -> None:
        self.events.put(event)

    def _log(self, message: str, level: str = "info") -> None:
        self._emit(Event(EventType.LOG, message, level))

    def _set_state(self, state: State, message: str = "") -> None:
        self.state = state
        self._emit(Event(EventType.STATE, message or state.value, data={"state": state.value}))

    def _sleep_interruptible(self, seconds: float, countdown: bool = True) -> bool:
        """Sleep in slices so pause/stop stay responsive. False if stopped."""
        deadline = time.monotonic() + seconds
        while True:
            if self._stop_event.is_set():
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            if countdown:
                self._emit(Event(EventType.COUNTDOWN, data={"seconds": int(remaining)}))
            time.sleep(min(1.0, remaining))

    def _wait_while_paused(self) -> bool:
        was_paused = False
        while self._pause_event.is_set() and not self._stop_event.is_set():
            was_paused = True
            time.sleep(0.3)
        if was_paused and not self._stop_event.is_set():
            self._set_state(State.RUNNING)
        return not self._stop_event.is_set()

    # -- SMTP ----------------------------------------------------------------
    def _ensure_server(self) -> smtplib.SMTP:
        if self._server is not None and self._since_reconnect < config.SMTP_RECONNECT_EVERY:
            try:
                status = self._server.noop()[0]
                if status == 250:
                    return self._server
            except Exception:
                pass  # fall through and reconnect
        self._close_server()
        self._log(f"Connecting to {self.plan.smtp.host}:{self.plan.smtp.port}…")
        self._server = open_smtp(self.plan.smtp)
        self._since_reconnect = 0
        self._log("Connected and authenticated.", "success")
        return self._server

    def _close_server(self) -> None:
        if self._server is not None:
            try:
                self._server.quit()
            except Exception:
                pass
            self._server = None

    # -- recipients ----------------------------------------------------------
    def _pending(self) -> list:
        return db.query(
            "SELECT c.* FROM campaign_recipients r JOIN contacts c ON c.id = r.contact_id "
            "WHERE r.campaign_id = ? AND r.status IN ('pending', 'retry') AND c.valid = 1 "
            "ORDER BY r.rowid",
            (self.plan.campaign_id,),
        )

    def _mark(self, contact_id: int, status: str, **fields) -> None:
        sets = ["status = ?", "attempts = attempts + 1"]
        params: list = [status]
        for key, value in fields.items():
            sets.append(f"{key} = ?")
            params.append(value)
        params.extend([self.plan.campaign_id, contact_id])
        db.execute(
            f"UPDATE campaign_recipients SET {', '.join(sets)} "
            f"WHERE campaign_id = ? AND contact_id = ?",
            params,
        )

    def _hard_bounce_rate(self) -> float:
        attempted = self.sent + self.failed
        if attempted < config.MIN_SAMPLE_FOR_BOUNCE_RATE:
            return 0.0
        return self.failed / attempted

    # -- main loop -----------------------------------------------------------
    def run(self) -> None:
        try:
            self._run()
        except Exception as error:  # noqa: BLE001 - the thread must never die silently
            self._set_state(State.ERROR)
            self._log(f"Unexpected error: {type(error).__name__}: {error}", "error")
            db.log_event("error", "send", f"{type(error).__name__}: {error}", self.plan.campaign_id)
        finally:
            self._close_server()
            self._emit(Event(EventType.DONE, data={
                "sent": self.sent, "failed": self.failed, "skipped": self.skipped,
                "state": self.state.value,
            }))

    def _run(self) -> None:
        recipients = self._pending()
        if not recipients:
            self._log("No pending recipients in this campaign.", "warn")
            self._set_state(State.FINISHED)
            return

        cap_remaining = warmup.remaining_today(self.plan.daily_cap_override)
        if cap_remaining <= 0:
            status = warmup.status()
            self._log(f"Today's limit is already reached ({status.sent_today}/{status.cap}). "
                      f"Sending resumes tomorrow.", "warn")
            self._set_state(State.WAITING)
            return

        total = min(len(recipients), cap_remaining)
        self._log(f"{len(recipients):,} pending · today's limit allows {cap_remaining} · "
                  f"sending {total} now.")
        self._set_state(State.RUNNING)
        db.execute("UPDATE campaigns SET status = 'running', started_at = COALESCE(started_at, ?) "
                   "WHERE id = ?", (db.now(), self.plan.campaign_id))

        subject_cycler = merge.VariantCycler(self.plan.content.subject_variants)
        body_cycler = merge.VariantCycler(self.plan.content.body_variants)
        rng = random.Random()

        processed = 0
        for contact in recipients:
            if self._stop_event.is_set():
                break
            if not self._wait_while_paused():
                break
            if processed >= cap_remaining:
                self._log(f"Daily limit of {cap_remaining} reached. Sending stops here and "
                          f"resumes tomorrow.", "warn")
                self._set_state(State.WAITING)
                break

            # Window check before each message, so a run started at 17:55 stops cleanly
            open_now, reason = in_send_window(self.plan)
            if not open_now:
                resume_at = next_window_open(self.plan)
                self._log(f"{reason}. Waiting until {resume_at:%a %d %b %H:%M}.", "warn")
                self._set_state(State.WAITING)
                wait_seconds = max(30, (resume_at - datetime.now()).total_seconds())
                if not self._sleep_interruptible(wait_seconds, countdown=False):
                    break
                self._set_state(State.RUNNING)

            email = (contact["email"] or "").strip()

            if db.is_suppressed(email):
                self._mark(contact["id"], "skipped", last_error="On the suppression list")
                self.skipped += 1
                self._log(f"Skipped {email} — on the suppression list.", "warn")
                continue

            try:
                server = self._ensure_server()
            except Exception as error:  # noqa: BLE001
                message = friendly_smtp_error(error, self.plan.smtp)
                self._log(f"Cannot connect: {message}", "error")
                db.log_event("error", "send", message, self.plan.campaign_id)
                self._set_state(State.ERROR)
                break

            context = merge.build_context(contact)
            local_content = composer.Content(
                subject_variants=[subject_cycler.next()],
                body_variants=[body_cycler.next()],
                signature_html=self.plan.content.signature_html,
                attach_mode=self.plan.content.attach_mode,
                attachment_path=self.plan.content.attachment_path,
                link_url=self.plan.content.link_url,
                link_text=self.plan.content.link_text,
                unsubscribe_note=self.plan.content.unsubscribe_note,
            )

            try:
                message, subject, variant = composer.build_message(
                    self.plan.sender, email, context, local_content, rng=rng
                )
            except Exception as error:  # noqa: BLE001
                self._mark(contact["id"], "failed", last_error=f"Compose error: {error}")
                self.failed += 1
                self._log(f"Could not build the message for {email}: {error}", "error")
                continue

            try:
                server.send_message(message)
            except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused) as error:
                code = getattr(error, "smtp_code", 0) or 0
                detail = str(error)[:400]
                permanent = 500 <= code < 600
                self._mark(contact["id"], "bounced" if permanent else "retry", last_error=detail)
                self.failed += 1
                self._consecutive_failures += 1
                if permanent:
                    db.suppress(email, f"Rejected by server ({code})", source="send")
                    self._log(f"Rejected permanently: {email} — {detail}", "error")
                else:
                    self._log(f"Temporary failure: {email} — {detail}", "warn")
            except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError) as error:
                self._mark(contact["id"], "retry", last_error=str(error)[:400])
                self._consecutive_failures += 1
                self._close_server()
                self._log(f"Connection lost on {email}; will reconnect. ({error})", "warn")
            except Exception as error:  # noqa: BLE001
                self._mark(contact["id"], "failed", last_error=f"{type(error).__name__}: {error}"[:400])
                self.failed += 1
                self._consecutive_failures += 1
                self._log(f"Failed to send to {email}: {error}", "error")
            else:
                self.sent += 1
                self._since_reconnect += 1
                self._consecutive_failures = 0
                self._mark(contact["id"], "sent", sent_at=db.now(), subject_used=subject,
                           body_variant=variant, message_id=message["Message-ID"], last_error=None)
                warmup.record_sent(1)
                self._emit(Event(EventType.SENT, f"{email} — {subject}", "success",
                                 data={"email": email, "subject": subject}))

            processed += 1
            self._emit(Event(EventType.PROGRESS, data={
                "done": processed, "total": total, "sent": self.sent,
                "failed": self.failed, "skipped": self.skipped,
            }))

            # --- circuit breakers -------------------------------------------
            if self._consecutive_failures >= config.MAX_CONSECUTIVE_FAILURES:
                self._log(
                    f"Stopped: {self._consecutive_failures} failures in a row. Something is wrong "
                    f"with the connection or the account — continuing would damage your sending "
                    f"reputation.", "error")
                self._set_state(State.ERROR)
                break

            rate = self._hard_bounce_rate()
            if rate > config.MAX_HARD_BOUNCE_RATE:
                self._log(
                    f"Stopped: {rate:.0%} of messages are failing (limit {config.MAX_HARD_BOUNCE_RATE:.0%}). "
                    f"A bounce rate this high gets domains blacklisted. Clean the list before "
                    f"continuing.", "error")
                self._set_state(State.ERROR)
                db.log_event("error", "send", f"Circuit breaker: bounce rate {rate:.0%}",
                             self.plan.campaign_id)
                break

            if processed < total and not self._stop_event.is_set():
                delay = rng.uniform(self.plan.delay_min_s, self.plan.delay_max_s)
                if not self._sleep_interruptible(delay):
                    break

        self._close_server()

        remaining = db.query_one(
            "SELECT COUNT(*) AS n FROM campaign_recipients WHERE campaign_id = ? "
            "AND status IN ('pending', 'retry')", (self.plan.campaign_id,)
        )
        left = remaining["n"] if remaining else 0

        if self._stop_event.is_set():
            self._set_state(State.STOPPED)
            self._log(f"Stopped by user. Sent {self.sent}, {left:,} still pending.", "warn")
            db.execute("UPDATE campaigns SET status = 'paused' WHERE id = ?", (self.plan.campaign_id,))
        elif self.state in (State.ERROR, State.WAITING):
            db.execute("UPDATE campaigns SET status = 'paused' WHERE id = ?", (self.plan.campaign_id,))
        elif left == 0:
            self._set_state(State.FINISHED)
            self._log(f"Campaign complete. Sent {self.sent}, failed {self.failed}.", "success")
            db.execute("UPDATE campaigns SET status = 'finished', finished_at = ? WHERE id = ?",
                       (db.now(), self.plan.campaign_id))
        else:
            self._set_state(State.FINISHED)
            self._log(f"Batch complete. Sent {self.sent}; {left:,} remain for the next run.", "success")
            db.execute("UPDATE campaigns SET status = 'paused' WHERE id = ?", (self.plan.campaign_id,))

        db.log_event("info", "send",
                     f"Campaign {self.plan.campaign_id}: sent {self.sent}, failed {self.failed}, "
                     f"skipped {self.skipped}", self.plan.campaign_id)
