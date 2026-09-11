"""Dashboard: at-a-glance health of the account, list and campaign."""
from __future__ import annotations

import customtkinter as ctk

from app import theme
from app.core import db, imap_sync, importer, scorer, warmup
from app.ui.widgets.common import DataTable, Section, StatTile


class DashboardPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self._build()

    def _build(self) -> None:
        scroll = theme.scroll_frame(self)
        scroll.pack(fill="both", expand=True, padx=theme.PAD_LARGE, pady=theme.PAD)

        header = ctk.CTkFrame(scroll, fg_color="transparent")
        header.pack(fill="x")
        theme.heading(header, "Dashboard").pack(side="left")
        theme.secondary_button(header, "Setup guide", lambda: self.app.show("guide"),
                               width=130).pack(side="right")

        self.greeting = theme.label(scroll, "", muted=True)
        self.greeting.pack(anchor="w", pady=(2, 16))

        # --- tiles ----------------------------------------------------------
        tiles = ctk.CTkFrame(scroll, fg_color="transparent")
        tiles.pack(fill="x", pady=(0, 14))
        for index in range(4):
            tiles.grid_columnconfigure(index, weight=1)

        self.tile_today = StatTile(tiles, "Sent today", "0")
        self.tile_today.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.tile_contacts = StatTile(tiles, "Sendable contacts", "0")
        self.tile_contacts.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        self.tile_replies = StatTile(tiles, "Replies", "0", accent=theme.SUCCESS)
        self.tile_replies.grid(row=0, column=2, sticky="ew", padx=(0, 8))
        self.tile_bounces = StatTile(tiles, "Bounce rate", "0%", accent=theme.FG_BRIGHT)
        self.tile_bounces.grid(row=0, column=3, sticky="ew")

        # --- health ---------------------------------------------------------
        health = Section(scroll, "Sending health")
        health.pack(fill="x", pady=(0, 14))
        self.health_frame = ctk.CTkFrame(health.body, fg_color="transparent")
        self.health_frame.pack(fill="x")

        # --- campaign -------------------------------------------------------
        self.campaign_section = Section(scroll, "Current campaign")
        self.campaign_section.pack(fill="x", pady=(0, 14))
        self.campaign_body = ctk.CTkFrame(self.campaign_section.body, fg_color="transparent")
        self.campaign_body.pack(fill="x")

        # --- activity -------------------------------------------------------
        activity = Section(scroll, "Recent activity")
        activity.pack(fill="x", pady=(0, 20))
        self.activity_table = DataTable(
            activity.body, [("When", 140), ("Type", 90), ("Detail", 520)], height=200)
        self.activity_table.pack(fill="x")

    # --- refresh ------------------------------------------------------------
    def on_show(self) -> None:
        self._refresh_tiles()
        self._refresh_health()
        self._refresh_campaign()
        self._refresh_activity()

    def _refresh_tiles(self) -> None:
        status = warmup.status()
        self.tile_today.update_value(f"{status.sent_today}", f"of {status.cap} allowed today")

        total = importer.contact_count()
        suppressed = len(db.suppression_list())
        self.tile_contacts.update_value(f"{total:,}", f"{suppressed:,} suppressed")

        replies = db.query_one("SELECT COUNT(*) AS n FROM contacts WHERE replied_at IS NOT NULL")
        sent = db.query_one("SELECT COUNT(*) AS n FROM campaign_recipients WHERE status = 'sent'")
        reply_count = replies["n"] if replies else 0
        sent_count = sent["n"] if sent else 0
        rate = f"{reply_count / sent_count * 100:.1f}% reply rate" if sent_count else "none yet"
        self.tile_replies.update_value(f"{reply_count:,}", rate)

        bounce_rate = imap_sync.bounce_rate()
        color = theme.ERROR if bounce_rate > 0.05 else (
            theme.WARNING if bounce_rate > 0.02 else theme.SUCCESS)
        self.tile_bounces.update_value(
            f"{bounce_rate * 100:.1f}%",
            "keep below 5%" if bounce_rate <= 0.05 else "too high — clean your list",
            accent=color)

        email = db.get_setting("sender_email", "")
        self.greeting.configure(
            text=f"Sending as {email}" if email
            else "No account configured yet — start with the setup guide.")

    def _row(self, parent, label: str, status: str, detail: str, action=None,
             action_label: str = "Fix") -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=3)
        ctk.CTkLabel(row, text=theme.STATUS_ICONS.get(status, "○"), font=theme.font(14, "bold"),
                     text_color=theme.status_color(status), width=24).pack(side="left")
        text = ctk.CTkFrame(row, fg_color="transparent")
        text.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(text, text=label, font=theme.font(12, "bold"), text_color=theme.FG,
                     anchor="w").pack(anchor="w")
        if detail:
            ctk.CTkLabel(text, text=detail, font=theme.font(11), text_color=theme.FG_MUTED,
                         anchor="w", wraplength=620, justify="left").pack(anchor="w")
        if action and status != "pass":
            theme.secondary_button(row, action_label, action, width=90, height=26).pack(side="right")

    def _refresh_health(self) -> None:
        for widget in self.health_frame.winfo_children():
            widget.destroy()

        dns_status = db.get_setting("dns_last_status", {}) or {}
        checked_at = db.get_setting("dns_checked_at", "")
        if dns_status:
            for name in ("SPF", "DKIM", "DMARC"):
                state = dns_status.get(name, "info")
                messages = {
                    "pass": f"{name} is published and valid.",
                    "warn": f"{name} needs attention.",
                    "fail": f"{name} is missing or broken — this is why mail lands in spam.",
                }
                self._row(self.health_frame, name, state,
                          messages.get(state, f"{name} not checked"),
                          action=lambda: self.app.show("deliverability"))
            self._row(self.health_frame, "Last checked", "info",
                      (checked_at or "").replace("T", " ")[:16])
        else:
            self._row(self.health_frame, "Domain authentication", "fail",
                      "Not checked yet. SPF, DKIM and DMARC decide whether your mail is trusted.",
                      action=lambda: self.app.show("deliverability"), action_label="Check")

        report = scorer.latest_report()
        if report:
            self._row(self.health_frame, f"Content score: {report.score}/100 ({report.grade})",
                      report.status, report.verdict,
                      action=lambda: self.app.show("templates"), action_label="Review")
            if scorer.is_stale():
                self._row(self.health_frame, "Score is out of date", "warn",
                          "Re-run the check — DNS and content drift over time.",
                          action=lambda: self.app.show("templates"), action_label="Re-check")
        else:
            self._row(self.health_frame, "Content not scored yet", "warn",
                      "Run the spam check before your first send.",
                      action=lambda: self.app.show("templates"), action_label="Check")

        status = warmup.status()
        self._row(self.health_frame,
                  f"Warm-up: day {status.day_index}, {status.cap} emails/day", "pass"
                  if status.enabled else "warn",
                  "Volume rises gradually so receiving servers learn to trust you."
                  if status.enabled else "Warm-up is off — you are sending at a fixed manual limit.",
                  action=lambda: self.app.show("campaign"), action_label="Settings")

        if not db.get_setting("imap_host", ""):
            self._row(self.health_frame, "Bounce detection is off", "warn",
                      "Without IMAP, bounced addresses stay on your list and keep damaging your "
                      "reputation.", action=lambda: self.app.show("account"), action_label="Set up")

    def _refresh_campaign(self) -> None:
        for widget in self.campaign_body.winfo_children():
            widget.destroy()

        row = db.query_one(
            "SELECT * FROM campaigns WHERE status IN ('running', 'paused', 'draft') "
            "ORDER BY id DESC LIMIT 1")
        if row is None:
            theme.label(self.campaign_body, "No active campaign.", muted=True).pack(anchor="w")
            theme.primary_button(self.campaign_body, "Go to Send",
                                 lambda: self.app.show("send"), width=140).pack(anchor="w", pady=8)
            return

        stats = db.campaign_stats(row["id"])
        pending = stats.get("pending", 0) + stats.get("retry", 0)
        sent = stats.get("sent", 0)
        total = stats.get("total", 0)

        theme.label(self.campaign_body,
                    f"{row['name']} — {sent:,} sent, {pending:,} pending, "
                    f"{stats.get('bounced', 0):,} bounced").pack(anchor="w")

        bar = ctk.CTkProgressBar(self.campaign_body, progress_color=theme.ACCENT,
                                 fg_color=theme.BORDER, height=6)
        bar.pack(fill="x", pady=(8, 10))
        bar.set(sent / total if total else 0)

        if pending:
            days = max(1, -(-pending // max(1, warmup.status().cap)))
            theme.label(self.campaign_body,
                        f"At the current daily limit this takes about {days} more sending day(s).",
                        muted=True, size=11).pack(anchor="w")
            theme.primary_button(self.campaign_body, "Continue sending",
                                 lambda: self.app.show("send"), width=160).pack(anchor="w", pady=8)

    def _refresh_activity(self) -> None:
        self.activity_table.clear()
        events = db.recent_events(40)
        if not events:
            self.activity_table.set_empty_message("Nothing has happened yet.")
            return
        colors = {"error": theme.ERROR, "warn": theme.WARNING}
        for event in events:
            self.activity_table.add_row(
                [(event["ts"] or "").replace("T", " ")[:16], event["category"] or "",
                 event["message"] or ""],
                colors=[theme.FG_MUTED, colors.get(event["level"], theme.FG_MUTED),
                        colors.get(event["level"], theme.FG)])
