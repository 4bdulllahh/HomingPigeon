"""Send page: pre-flight checks, live console, pause/resume/stop."""
from __future__ import annotations

import queue
from datetime import datetime

import customtkinter as ctk

from app import theme
from app.core import composer, credentials, db, importer, prefs, scorer, sender, warmup
from app.ui.widgets.common import ConfirmDialog, Section, StatTile, toast
from app.ui.widgets.range_slider import format_seconds

LEVEL_COLORS = {
    "info": theme.FG,
    "success": theme.SUCCESS,
    "warn": theme.WARNING,
    "error": theme.ERROR,
}


class SendPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.worker: sender.SendWorker | None = None
        self.events: queue.Queue = queue.Queue()
        self.campaign_id: int | None = None
        self._build()
        self._poll()

    def _build(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=theme.PAD_LARGE, pady=(theme.PAD, 0))
        theme.heading(header, "Send").pack(anchor="w")
        theme.label(header, "Checks everything first, then sends at your chosen pace.",
                    muted=True, wrap=True).pack(anchor="w", pady=(2, 12))

        # --- preflight ------------------------------------------------------
        self.preflight = Section(self, "Before you send")
        self.preflight.pack(fill="x", padx=theme.PAD_LARGE, pady=(0, 12))
        self.checks_frame = ctk.CTkFrame(self.preflight.body, fg_color="transparent")
        self.checks_frame.pack(fill="x")

        # --- stats ----------------------------------------------------------
        stats = ctk.CTkFrame(self, fg_color="transparent")
        stats.pack(fill="x", padx=theme.PAD_LARGE, pady=(0, 12))
        for index in range(4):
            stats.grid_columnconfigure(index, weight=1)

        self.tile_queue = StatTile(stats, "In this batch", "—")
        self.tile_queue.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.tile_sent = StatTile(stats, "Sent", "0", accent=theme.SUCCESS)
        self.tile_sent.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        self.tile_failed = StatTile(stats, "Failed", "0", accent=theme.ERROR)
        self.tile_failed.grid(row=0, column=2, sticky="ew", padx=(0, 8))
        self.tile_next = StatTile(stats, "Next email in", "—")
        self.tile_next.grid(row=0, column=3, sticky="ew")

        # --- controls -------------------------------------------------------
        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.pack(fill="x", padx=theme.PAD_LARGE, pady=(0, 10))

        self.start_button = theme.confirm_button(controls, "Start Emailing", self._start, width=210)
        self.start_button.pack(side="left")
        self.pause_button = theme.secondary_button(controls, "Pause", self._toggle_pause, width=110)
        self.pause_button.pack(side="left", padx=8)
        self.pause_button.configure(state="disabled")
        self.stop_button = theme.danger_button(controls, "Stop", self._stop, width=110)
        self.stop_button.pack(side="left")
        self.stop_button.configure(state="disabled")

        self.state_label = theme.label(controls, "Idle", muted=True)
        self.state_label.pack(side="left", padx=16)

        self.progress = ctk.CTkProgressBar(self, progress_color=theme.ACCENT,
                                           fg_color=theme.BORDER, height=6)
        self.progress.set(0)
        self.progress.pack(fill="x", padx=theme.PAD_LARGE, pady=(0, 10))

        # --- console --------------------------------------------------------
        console_wrap = ctk.CTkFrame(self, fg_color=theme.BG_CONSOLE, corner_radius=theme.RADIUS,
                                    border_width=1, border_color=theme.BORDER)
        console_wrap.pack(fill="both", expand=True, padx=theme.PAD_LARGE, pady=(0, theme.PAD))

        bar = ctk.CTkFrame(console_wrap, fg_color="transparent")
        bar.pack(fill="x", padx=12, pady=(8, 0))
        ctk.CTkLabel(bar, text="Activity", font=theme.font(12, "bold"),
                     text_color=theme.FG_MUTED).pack(side="left")
        theme.secondary_button(bar, "Clear", self._clear_console, width=70, height=24).pack(
            side="right")

        self.console = ctk.CTkTextbox(console_wrap, font=theme.mono(11), fg_color="transparent",
                                      text_color=theme.FG, wrap="word", border_width=0)
        self.console.pack(fill="both", expand=True, padx=8, pady=8)
        self.console.configure(state="disabled")

        for level, color in LEVEL_COLORS.items():
            resolved = color[1] if ctk.get_appearance_mode() == "Dark" else color[0]
            self.console._textbox.tag_configure(level, foreground=resolved)

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
                 f"Failing: {', '.join(failures)} — fix on the 'Domain check' page"
                 if failures else ""))
        else:
            checks.append(("Domain authentication checked", False,
                           "Run the checks on the 'Domain check' page — without SPF and DMARC "
                           "your mail is very likely to be filtered"))

        report = scorer.latest_report()
        if report:
            checks.append((f"Spam score {report.score}/100 ({report.grade})", report.score >= 70,
                           "Improve the content on the 'My message' page" if report.score < 70 else ""))
        else:
            checks.append(("Spam score checked", False,
                           "Open 'My message' → 'Preview & score' to run the check"))

        status = warmup.status()
        checks.append((f"Daily limit: {status.sent_today}/{status.cap} used", not status.at_limit,
                       "Today's limit is reached — sending resumes tomorrow"))
        return checks

    def _render_checks(self) -> None:
        for widget in self.checks_frame.winfo_children():
            widget.destroy()

        for label, ok, fix in self._gather_checks():
            row = ctk.CTkFrame(self.checks_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text="✓" if ok else "✕", font=theme.font(14, "bold"),
                         text_color=theme.SUCCESS if ok else theme.ERROR, width=22).pack(side="left")
            ctk.CTkLabel(row, text=label, font=theme.font(12),
                         text_color=theme.FG if ok else theme.FG_BRIGHT, anchor="w").pack(side="left")
            if not ok and fix:
                ctk.CTkLabel(row, text=f"— {fix}", font=theme.font(11), text_color=theme.FG_MUTED,
                             anchor="w").pack(side="left", padx=(8, 0))

    # --- console ------------------------------------------------------------
    def _log(self, message: str, level: str = "info") -> None:
        stamp = prefs.format_time(datetime.now(), seconds=True)
        self.console.configure(state="normal")
        self.console._textbox.insert("end", f"{stamp}  {message}\n", level)
        self.console.configure(state="disabled")
        self.console.see("end")

    def _clear_console(self) -> None:
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")

    # --- campaign assembly --------------------------------------------------
    def _build_plan(self) -> sender.SendPlan | None:
        email = db.get_setting("sender_email", "")
        host = db.get_setting("smtp_host", "")
        password = credentials.load_secret(credentials.SMTP_PASSWORD)

        if not (email and host and password):
            toast(self, "Finish setting up your email account first", "warn")
            self.app.show("account")
            return None

        subjects = [r["text"] for r in
                    db.query("SELECT text FROM subjects WHERE enabled = 1 ORDER BY position")]
        bodies = [r["html"] for r in
                  db.query("SELECT html FROM bodies WHERE enabled = 1 ORDER BY position")]
        if not subjects or not bodies:
            toast(self, "Write at least one subject and one body first", "warn")
            self.app.show("templates")
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
        row = db.query_one(
            "SELECT id FROM campaigns WHERE status IN ('draft', 'running', 'paused') "
            "ORDER BY id DESC LIMIT 1")
        if row:
            campaign_id = row["id"]
        else:
            campaign_id = db.execute(
                "INSERT INTO campaigns(name, status, created_at) VALUES (?, 'draft', ?)",
                (f"Campaign {prefs.format_date(datetime.now())}", db.now()))

        # Add any contacts that are not in the campaign yet
        db.execute(
            "INSERT OR IGNORE INTO campaign_recipients(campaign_id, contact_id, status) "
            "SELECT ?, id, 'pending' FROM contacts WHERE valid = 1 "
            "AND email NOT IN (SELECT email FROM suppression)",
            (campaign_id,))
        self.campaign_id = campaign_id
        return campaign_id

    # --- actions ------------------------------------------------------------
    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        plan = self._build_plan()
        if plan is None:
            return

        stats = db.campaign_stats(plan.campaign_id)
        pending = stats.get("pending", 0) + stats.get("retry", 0)
        if not pending:
            toast(self, "Every contact in this campaign has already been processed", "info")
            return

        report = scorer.latest_report()
        if report and report.score < 70:
            if not ConfirmDialog.ask(
                self, "Your content scored poorly",
                f"The last spam check scored {report.score}/100 (grade {report.grade}).\n\n"
                f"{report.verdict}\n\nSending anyway risks your domain's reputation. You can fix "
                f"the issues on the 'My message' page, or continue if you have already reviewed them.",
                confirm_text="Send anyway", danger=True,
            ):
                self.app.show("templates")
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
                self.app.show("deliverability")
                return

        limit = warmup.remaining_today()
        batch = min(pending, limit)
        if not ConfirmDialog.ask(
            self, "Start sending?",
            f"{pending:,} contacts are waiting.\n\n"
            f"Today's limit allows {limit}, so {batch} will be sent now, at "
            f"{format_seconds(plan.delay_min_s)}–{format_seconds(plan.delay_max_s)} intervals "
            f"between {plan.window_start} and {plan.window_end}.\n\n"
            f"You can pause or stop at any time; progress is saved after every email.",
            confirm_text=f"Send {batch} emails",
        ):
            return

        self._clear_console()
        self.events = queue.Queue()
        self.worker = sender.SendWorker(plan, self.events)
        self.worker.start()

        self.start_button.configure(state="disabled", text="Sending…")
        self.pause_button.configure(state="normal", text="Pause")
        self.stop_button.configure(state="normal")
        self.tile_sent.update_value("0")
        self.tile_failed.update_value("0")
        self.progress.set(0)

    def _toggle_pause(self) -> None:
        if not self.worker or not self.worker.is_alive():
            return
        if self.worker.is_paused:
            self.worker.request_resume()
            self.pause_button.configure(text="Pause")
        else:
            self.worker.request_pause()
            self.pause_button.configure(text="Resume")

    def _stop(self) -> None:
        if not self.worker or not self.worker.is_alive():
            return
        if not ConfirmDialog.ask(
            self, "Stop sending?",
            "Everything already sent is saved. The remaining contacts stay pending and you can "
            "continue later from where this stopped.",
            confirm_text="Stop", danger=True,
        ):
            return
        self.worker.request_stop()
        self.stop_button.configure(state="disabled")

    def stop_worker(self) -> None:
        if self.worker and self.worker.is_alive():
            self.worker.request_stop()
            self.worker.join(timeout=5)

    def is_running(self) -> bool:
        return bool(self.worker and self.worker.is_alive())

    # --- event pump ---------------------------------------------------------
    def _poll(self) -> None:
        drained = 0
        while drained < 60:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            drained += 1
            self._handle_event(event)
        self.after(100, self._poll)

    def _handle_event(self, event: sender.Event) -> None:
        if event.type == sender.EventType.LOG:
            self._log(event.message, event.level)

        elif event.type == sender.EventType.SENT:
            self._log(f"Sent → {event.message}", "success")
            self.tile_sent.update_value(str(self.worker.sent if self.worker else 0))

        elif event.type == sender.EventType.PROGRESS:
            data = event.data or {}
            done, total = data.get("done", 0), data.get("total", 1)
            self.progress.set(done / total if total else 0)
            self.tile_queue.update_value(f"{done}/{total}")
            self.tile_sent.update_value(str(data.get("sent", 0)))
            self.tile_failed.update_value(str(data.get("failed", 0)))

        elif event.type == sender.EventType.COUNTDOWN:
            seconds = (event.data or {}).get("seconds", 0)
            self.tile_next.update_value(format_seconds(seconds))

        elif event.type == sender.EventType.STATE:
            state = (event.data or {}).get("state", "")
            colors = {
                "running": theme.SUCCESS, "paused": theme.WARNING, "waiting": theme.WARNING,
                "error": theme.ERROR, "stopped": theme.FG_MUTED, "finished": theme.SUCCESS,
            }
            labels = {
                "running": "Sending", "paused": "Paused", "waiting": "Waiting",
                "error": "Stopped — problem detected", "stopped": "Stopped",
                "finished": "Finished", "idle": "Idle",
            }
            self.state_label.configure(text=labels.get(state, state),
                                       text_color=colors.get(state, theme.FG_MUTED))

        elif event.type == sender.EventType.DONE:
            data = event.data or {}
            self.start_button.configure(state="normal", text="Start Emailing")
            self.pause_button.configure(state="disabled", text="Pause")
            self.stop_button.configure(state="disabled")
            self.tile_next.update_value("—")
            self._render_checks()
            self.app._refresh_status()

            sent = data.get("sent", 0)
            if sent:
                toast(self, f"Finished — {sent} sent, {data.get('failed', 0)} failed",
                      "success" if not data.get("failed") else "warn")

    # --- lifecycle ----------------------------------------------------------
    def on_show(self) -> None:
        self._render_checks()
        if not self.is_running():
            self._ensure_campaign()
            stats = db.campaign_stats(self.campaign_id) if self.campaign_id else {}
            pending = stats.get("pending", 0) + stats.get("retry", 0)
            limit = warmup.remaining_today()
            self.tile_queue.update_value(f"{min(pending, limit)}",
                                         f"{pending:,} pending overall")
            self.tile_sent.update_value(str(stats.get("sent", 0)))
            self.tile_failed.update_value(
                str(stats.get("failed", 0) + stats.get("bounced", 0)))
