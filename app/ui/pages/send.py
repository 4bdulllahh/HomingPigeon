"""Send page: pre-flight checks, live activity log, start / pause / stop."""
from __future__ import annotations

import queue
from datetime import datetime

from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QHBoxLayout, QProgressBar, QVBoxLayout, QWidget

from app.core import composer, credentials, db, importer, prefs, scorer, sender, warmup
from app.ui import theme
from app.ui.pages.base import Page
from app.ui.widgets.common import (Card, Section, StatTile, clear_layout, confirm_button,
                                   danger_button, hint, muted, secondary_button, set_tone,
                                   small_button)
from app.ui.widgets.dialogs import ConfirmDialog
from app.ui.widgets.inputs import text_box
from app.ui.widgets.range_slider import format_seconds
from app.workers.jobs import SendPump

# The activity log is capped so a long campaign cannot grow it without limit
MAX_LOG_BLOCKS = 4000

LEVEL_TOKENS = {"info": "fg", "success": "success", "warn": "warning", "error": "error"}

STATE_LABELS = {
    "running": "Sending", "paused": "Paused", "waiting": "Waiting",
    "error": "Stopped, problem detected", "stopped": "Stopped",
    "finished": "Finished", "idle": "Idle",
}
STATE_TONES = {
    "running": "success", "paused": "warning", "waiting": "warning",
    "error": "error", "stopped": "muted", "finished": "success",
}


class SendPage(Page):
    def __init__(self, window):
        super().__init__(window)
        self.worker: sender.SendWorker | None = None
        self.pump: SendPump | None = None
        self.events: queue.Queue = queue.Queue()
        self.campaign_id: int | None = None
        self._build()

    def _build(self) -> None:
        self.add_header("Send", "Checks everything first, then sends at your chosen pace.")

        self.preflight = Section("Before you send")
        self.checks_layout = QVBoxLayout()
        self.checks_layout.setContentsMargins(0, 0, 0, 0)
        self.checks_layout.setSpacing(3)
        self.preflight.add_layout(self.checks_layout)
        self.root.addWidget(self.preflight)

        tiles_holder = QWidget()
        tiles_holder.setProperty("role", "plain")
        tiles = QHBoxLayout(tiles_holder)
        tiles.setContentsMargins(0, 0, 0, 0)
        tiles.setSpacing(8)
        self.tile_queue = StatTile("In this batch", "-")
        self.tile_sent = StatTile("Sent", "0", tone="success")
        self.tile_failed = StatTile("Failed", "0", tone="error")
        self.tile_next = StatTile("Next email in", "-")
        for tile in (self.tile_queue, self.tile_sent, self.tile_failed, self.tile_next):
            tiles.addWidget(tile, 1)
        self.root.addWidget(tiles_holder)

        controls_holder = QWidget()
        controls_holder.setProperty("role", "plain")
        controls = QHBoxLayout(controls_holder)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)
        self.start_button = confirm_button("Start Emailing", self._start, 220)
        self.pause_button = secondary_button("Pause", self._toggle_pause, 120)
        self.stop_button = danger_button("Stop", self._stop, 120)
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        controls.addWidget(self.start_button)
        controls.addWidget(self.pause_button)
        controls.addWidget(self.stop_button)
        self.state_label = muted("Idle", wrap=False)
        controls.addWidget(self.state_label)
        controls.addStretch(1)
        self.root.addWidget(controls_holder)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.root.addWidget(self.progress)

        console = Card(kind="console", padding=10)
        header = QHBoxLayout()
        header.addWidget(hint("Activity"))
        header.addStretch(1)
        header.addWidget(small_button("Clear", self._clear_console))
        console.add_layout(header)

        self.console = text_box("", monospace=True)
        self.console.setProperty("role", "console")
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(MAX_LOG_BLOCKS)
        console.add(self.console, 1)
        self.root.addWidget(console, 1)

    # --- preflight ----------------------------------------------------------
    def _gather_checks(self) -> list[tuple[str, bool, str]]:
        checks: list[tuple[str, bool, str]] = []

        email = db.get_setting("sender_email", "")
        host = db.get_setting("smtp_host", "")
        has_password = credentials.has_secret(credentials.SMTP_PASSWORD)
        checks.append(("Email account configured", bool(email and host and has_password),
                       "Set your SMTP details on the 'My email account' page"))

        count = importer.contact_count()
        checks.append((f"Contacts imported ({count:,} sendable)", count > 0,
                       "Import your spreadsheet on the 'My contacts' page"))

        templates = db.query_one("SELECT 1 FROM bodies WHERE enabled = 1")
        checks.append(("Templates written", templates is not None,
                       "Write at least one subject and message on the 'My message' page"))

        dns_status = db.get_setting("dns_last_status", {}) or {}
        if dns_status:
            failures = [name for name, state in dns_status.items() if state == "fail"]
            checks.append(
                ("Domain authentication (SPF / DKIM / DMARC)", not failures,
                 f"Failing: {', '.join(failures)}. Fix these on the 'Domain check' page"
                 if failures else ""))
        else:
            checks.append(("Domain authentication checked", False,
                           "Run the checks on the 'Domain check' page. Without SPF and "
                           "DMARC your mail is very likely to be filtered"))

        report = scorer.latest_report()
        if report:
            checks.append((f"Spam score {report.score}/100 ({report.grade})", report.score >= 70,
                           "Improve the content on the 'My message' page"
                           if report.score < 70 else ""))
        else:
            checks.append(("Spam score checked", False,
                           "Open 'My message' → 'Preview & score' to run the check"))

        status = warmup.status()
        checks.append((f"Daily limit: {status.sent_today}/{status.cap} used", not status.at_limit,
                       "Today's limit is reached. Sending resumes tomorrow"))
        return checks

    def _render_checks(self) -> None:
        clear_layout(self.checks_layout)
        for label, ok, fix in self._gather_checks():
            holder = QWidget()
            holder.setProperty("role", "plain")
            line = QHBoxLayout(holder)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(8)

            glyph = muted("✓" if ok else "✕", wrap=False)
            glyph.setStyleSheet(
                f"color: {theme.color('success') if ok else theme.color('error')}; "
                f"font-weight: 700;")
            glyph.setFixedWidth(round(18 * theme.text_scale()))
            line.addWidget(glyph)

            text = muted(label, wrap=False)
            set_tone(text, "muted" if ok else "bright")
            line.addWidget(text)
            if not ok and fix:
                line.addWidget(hint(f"Fix: {fix}", wrap=False))
            line.addStretch(1)
            self.checks_layout.addWidget(holder)

    # --- console ------------------------------------------------------------
    def _log(self, message: str, level: str = "info") -> None:
        stamp = prefs.format_time(datetime.now(), seconds=True)
        colour = theme.color(LEVEL_TOKENS.get(level, "fg"))
        self.console.appendHtml(
            f'<span style="color:{theme.color("fg_muted")}">{stamp}</span>&nbsp;&nbsp;'
            f'<span style="color:{colour}">{_escape(message)}</span>')
        self.console.moveCursor(QTextCursor.MoveOperation.End)

    def _clear_console(self) -> None:
        self.console.clear()

    # --- campaign assembly --------------------------------------------------
    def _build_plan(self) -> sender.SendPlan | None:
        email = db.get_setting("sender_email", "")
        host = db.get_setting("smtp_host", "")
        password = credentials.load_secret(credentials.SMTP_PASSWORD)

        if not (email and host and password):
            self.notify("Finish setting up your email account first", "warn")
            self.go("account")
            return None

        subjects = [r["text"] for r in
                    db.query("SELECT text FROM subjects WHERE enabled = 1 ORDER BY position")]
        bodies = [r["html"] for r in
                  db.query("SELECT html FROM bodies WHERE enabled = 1 ORDER BY position")]
        if not subjects or not bodies:
            self.notify("Write at least one subject and one body first", "warn")
            self.go("templates")
            return None

        signature_row = db.query_one("SELECT signature_html FROM template_sets ORDER BY id LIMIT 1")
        content = composer.Content(
            subject_variants=subjects,
            body_variants=bodies,
            signature_html=signature_row["signature_html"] if signature_row else "",
            attach_mode=db.get_setting("attach_mode", "link"),
            attachment_path=db.get_setting("attachment_path", ""),
            link_url=db.get_setting("link_url", ""),
            link_text=db.get_setting("link_text", "View our brochure"),
            unsubscribe_note=bool(db.get_setting("unsubscribe_note", True)),
        )

        try:
            port = int(db.get_setting("smtp_port", 587))
        except (TypeError, ValueError):
            port = 587

        identity = composer.SenderIdentity(
            name=db.get_setting("sender_name", ""),
            email=email,
            reply_to=db.get_setting("reply_to", ""),
        )

        return sender.SendPlan(
            campaign_id=self._ensure_campaign(),
            sender=identity,
            content=content,
            smtp=sender.SmtpSettings(
                host=host, port=port,
                username=db.get_setting("smtp_username", "") or email,
                password=password,
                security=db.get_setting("smtp_security", "auto"),
            ),
            delay_min_s=int(db.get_setting("delay_min_s", 75)),
            delay_max_s=int(db.get_setting("delay_max_s", 150)),
            window_start=db.get_setting("window_start", "09:00"),
            window_end=db.get_setting("window_end", "18:00"),
            weekdays_only=bool(db.get_setting("weekdays_only", True)),
            skip_holidays=bool(db.get_setting("skip_holidays", True)),
        )

    def _ensure_campaign(self) -> int:
        """Reuse an unfinished campaign so a stopped run resumes where it left off."""
        record = db.query_one(
            "SELECT id FROM campaigns WHERE status IN ('draft', 'running', 'paused') "
            "ORDER BY id DESC LIMIT 1")
        if record:
            campaign_id = record["id"]
        else:
            campaign_id = db.execute(
                "INSERT INTO campaigns(name, status, created_at) VALUES (?, 'draft', ?)",
                (f"Campaign {prefs.format_date(datetime.now())}", db.now()))

        db.execute(
            "INSERT OR IGNORE INTO campaign_recipients(campaign_id, contact_id, status) "
            "SELECT ?, id, 'pending' FROM contacts WHERE valid = 1 "
            "AND email NOT IN (SELECT email FROM suppression)",
            (campaign_id,))
        self.campaign_id = campaign_id
        return campaign_id

    # --- actions ------------------------------------------------------------
    def _start(self) -> None:
        if self.is_running():
            return

        plan = self._build_plan()
        if plan is None:
            return

        stats = db.campaign_stats(plan.campaign_id)
        pending = stats.get("pending", 0) + stats.get("retry", 0)
        if not pending:
            self.notify("Every contact in this campaign has already been processed", "info")
            return

        report = scorer.latest_report()
        if report and report.score < 70:
            if not ConfirmDialog.ask(
                self, "Your content scored poorly",
                f"The last spam check scored {report.score}/100 (grade {report.grade}).\n\n"
                f"{report.verdict}\n\nSending anyway risks your domain's reputation. You can fix "
                f"the issues on the 'My message' page, or continue if you have already reviewed "
                f"them.", confirm_text="Send anyway", danger=True,
            ):
                self.go("templates")
                return

        dns_status = db.get_setting("dns_last_status", {}) or {}
        failures = [name for name, state in dns_status.items() if state == "fail"]
        if failures:
            if not ConfirmDialog.ask(
                self, "Domain authentication is failing",
                f"These checks are failing: {', '.join(failures)}.\n\n"
                f"Mail from a domain without working authentication is very likely to be "
                f"spam-foldered or rejected, and repeated attempts damage your domain's "
                f"reputation for months.\n\nFix them on the 'Domain check' page first.",
                confirm_text="Send anyway", danger=True,
            ):
                self.go("deliverability")
                return

        limit = warmup.remaining_today()
        batch = min(pending, limit)
        if not ConfirmDialog.ask(
            self, "Start sending?",
            f"{pending:,} contacts are waiting.\n\n"
            f"Today's limit allows {limit}, so {batch} will be sent now, at "
            f"{format_seconds(plan.delay_min_s)} to {format_seconds(plan.delay_max_s)} intervals "
            f"between {plan.window_start} and {plan.window_end}.\n\n"
            f"You can pause or stop at any time; progress is saved after every email.",
            confirm_text=f"Send {batch} emails",
        ):
            return

        self._clear_console()
        self.events = queue.Queue()
        self.worker = sender.SendWorker(plan, self.events)
        self.worker.start()

        # A dedicated thread drains the worker's queue and re-emits each event as
        # a signal, so the UI is woken only when something actually happened.
        self.pump = SendPump(self.worker, self.events, self)
        self.pump.event.connect(self._handle_event)
        # Qt aborts the process if a running QThread is destroyed, and the page
        # can be torn down (a text-size change, closing) moments after the last
        # event arrives. Dropping the reference once it has finished avoids that.
        self.pump.finished.connect(self._pump_finished)
        self.pump.start()

        self.start_button.setEnabled(False)
        self.start_button.setText("Sending...")
        self.pause_button.setEnabled(True)
        self.pause_button.setText("Pause")
        self.stop_button.setEnabled(True)
        self.tile_sent.update_value("0")
        self.tile_failed.update_value("0")
        self.progress.setValue(0)

    def _toggle_pause(self) -> None:
        if not self.is_running():
            return
        if self.worker.is_paused:
            self.worker.request_resume()
            self.pause_button.setText("Pause")
        else:
            self.worker.request_pause()
            self.pause_button.setText("Resume")

    def _stop(self) -> None:
        if not self.is_running():
            return
        if not ConfirmDialog.ask(
            self, "Stop sending?",
            "Everything already sent is saved. The remaining contacts stay pending and you can "
            "continue later from where this stopped.",
            confirm_text="Stop", danger=True,
        ):
            return
        self.worker.request_stop()
        self.stop_button.setEnabled(False)

    def _pump_finished(self) -> None:
        pump, self.pump = self.pump, None
        if pump is not None:
            pump.deleteLater()

    def stop_worker(self) -> None:
        if self.worker and self.worker.is_alive():
            self.worker.request_stop()
            self.worker.join(timeout=5)
        pump, self.pump = self.pump, None
        if pump is not None:
            pump.stop()
            pump.wait(2000)
            pump.deleteLater()

    def busy_reason(self) -> str | None:
        return "a campaign is running" if self.is_running() else None

    def is_running(self) -> bool:
        return bool(self.worker and self.worker.is_alive())

    # --- events -------------------------------------------------------------
    def _handle_event(self, event: sender.Event) -> None:
        if event.type == sender.EventType.LOG:
            self._log(event.message, event.level)

        elif event.type == sender.EventType.SENT:
            self._log(f"Sent → {event.message}", "success")
            self.tile_sent.update_value(str(self.worker.sent if self.worker else 0))

        elif event.type == sender.EventType.PROGRESS:
            data = event.data or {}
            done, total = data.get("done", 0), data.get("total", 1)
            self.progress.setRange(0, max(1, total))
            self.progress.setValue(done)
            self.tile_queue.update_value(f"{done}/{total}")
            self.tile_sent.update_value(str(data.get("sent", 0)))
            self.tile_failed.update_value(str(data.get("failed", 0)))

        elif event.type == sender.EventType.COUNTDOWN:
            seconds = (event.data or {}).get("seconds", 0)
            self.tile_next.update_value(format_seconds(seconds))

        elif event.type == sender.EventType.STATE:
            state = (event.data or {}).get("state", "")
            self.state_label.setText(STATE_LABELS.get(state, state))
            set_tone(self.state_label, STATE_TONES.get(state, "muted"))

        elif event.type == sender.EventType.DONE:
            data = event.data or {}
            self.start_button.setEnabled(True)
            self.start_button.setText("Start Emailing")
            self.pause_button.setEnabled(False)
            self.pause_button.setText("Pause")
            self.stop_button.setEnabled(False)
            self.tile_next.update_value("-")
            self._render_checks()
            self.window_.refresh_status()

            # The record of what went out is the first thing people look at
            # afterwards; refresh it now rather than on the next visit.
            history = self.window_.page("sent")
            if history is not None:
                history.on_show()

            sent = data.get("sent", 0)
            if sent:
                self.notify(
                    f"Finished: {sent} sent, {data.get('failed', 0)} failed",
                    "success" if not data.get("failed") else "warn")

    # --- lifecycle ----------------------------------------------------------
    def on_show(self) -> None:
        self._render_checks()
        if self.is_running():
            return
        self._ensure_campaign()
        stats = db.campaign_stats(self.campaign_id) if self.campaign_id else {}
        pending = stats.get("pending", 0) + stats.get("retry", 0)
        limit = warmup.remaining_today()
        self.tile_queue.update_value(f"{min(pending, limit)}", f"{pending:,} pending overall")
        self.tile_sent.update_value(str(stats.get("sent", 0)))
        self.tile_failed.update_value(
            str(stats.get("failed", 0) + stats.get("bounced", 0)))


def _escape(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
