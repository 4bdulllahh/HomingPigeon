"""Dashboard: at-a-glance health of the account, the list and the campaign."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QProgressBar, QVBoxLayout, QWidget

from app.core import db, imap_sync, importer, prefs, scorer, warmup
from app.models.table_model import SimpleTableModel
from app.ui import theme
from app.ui.pages.base import Page
from app.ui.widgets.common import (Section, StatTile, clear_layout, hint, muted, primary_button,
                                   row, secondary_button, separator, status_glyph, subheading)
from app.ui.widgets.tables import DataTable


class DashboardPage(Page):
    def __init__(self, window):
        super().__init__(window)
        self._health_rows = 0
        self._build()

    def _build(self) -> None:
        self.root.addWidget(self._title_row())
        self.greeting = muted("")
        self.root.addWidget(self.greeting)

        area = self.scroll_body()

        # The holder comes first and owns the layout from the start. A widget
        # added to a layout that has no parent yet stays a top-level window
        # until setLayout() adopts it, and Qt shows it: that is what made four
        # small empty windows blink open before the app appeared.
        holder = QWidget()
        holder.setProperty("role", "plain")
        tiles = QHBoxLayout(holder)
        tiles.setContentsMargins(0, 0, 0, 0)
        tiles.setSpacing(8)
        self.tile_today = StatTile("Sent today", "0")
        self.tile_contacts = StatTile("Sendable contacts", "0")
        self.tile_replies = StatTile("Replies", "0", tone="success")
        self.tile_bounces = StatTile("Bounce rate", "0%")
        for tile in (self.tile_today, self.tile_contacts, self.tile_replies, self.tile_bounces):
            tiles.addWidget(tile, 1)
        area.add(holder)

        health = Section("Sending health")
        self.health_body = QVBoxLayout()
        self.health_body.setContentsMargins(0, 0, 0, 0)
        # Each check is a separate thing to act on, so they are spaced apart and
        # divided by a hairline rather than running together as one block.
        self.health_body.setSpacing(round(10 * theme.text_scale()))
        health.add_layout(self.health_body)
        area.add(health)

        campaign = Section("Current campaign")
        self.campaign_body = QVBoxLayout()
        self.campaign_body.setContentsMargins(0, 0, 0, 0)
        self.campaign_body.setSpacing(8)
        campaign.add_layout(self.campaign_body)
        area.add(campaign)

        activity = Section("Recent activity")
        self.activity_model = SimpleTableModel(["When", "Type", "Detail"])
        self.activity_table = DataTable(self.activity_model, "Nothing has happened yet.")
        self.activity_table.setMinimumHeight(round(220 * theme.text_scale()))
        activity.add(self.activity_table)
        area.add(activity)
        area.add_stretch()

    def _title_row(self) -> QWidget:
        holder = QWidget()
        holder.setProperty("role", "plain")
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        from app.ui.widgets.common import heading

        layout.addWidget(heading("Dashboard"))
        layout.addStretch(1)
        layout.addWidget(secondary_button("Setup guide", lambda: self.go("guide"), 140))
        return holder

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
        tone = "error" if bounce_rate > 0.05 else ("warning" if bounce_rate > 0.02 else "success")
        self.tile_bounces.update_value(
            f"{bounce_rate * 100:.1f}%",
            "keep below 5%" if bounce_rate <= 0.05 else "too high — clean your list",
            tone=tone)

        email = db.get_setting("sender_email", "")
        self.greeting.setText(
            f"Sending as {email}" if email
            else "No account configured yet — start with the setup guide.")

    def _row(self, label: str, status: str, detail: str, action=None,
             action_label: str = "Fix") -> None:
        if self._health_rows:
            self.health_body.addWidget(separator())
        self._health_rows += 1

        holder = QWidget()
        holder.setProperty("role", "plain")
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(round(10 * theme.text_scale()))
        layout.addWidget(status_glyph(status), 0, Qt.AlignmentFlag.AlignTop)

        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(subheading(label))
        if detail:
            text.addWidget(muted(detail))
        layout.addLayout(text, 1)

        if action and status != "pass":
            button = secondary_button(action_label, action, 110)
            layout.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
        self.health_body.addWidget(holder)

    def _refresh_health(self) -> None:
        clear_layout(self.health_body)
        self._health_rows = 0

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
                self._row(name, state, messages.get(state, f"{name} not checked"),
                          action=lambda: self.go("deliverability"))
            self._row("Last checked", "info", prefs.format_datetime(checked_at))
        else:
            self._row("Domain authentication", "fail",
                      "Not checked yet. SPF, DKIM and DMARC decide whether your mail is trusted.",
                      action=lambda: self.go("deliverability"), action_label="Check")

        report = scorer.latest_report()
        if report:
            self._row(f"Content score: {report.score}/100 ({report.grade})", report.status,
                      report.verdict, action=lambda: self.go("templates"), action_label="Review")
            if scorer.is_stale():
                self._row("Score is out of date", "warn",
                          "Re-run the check — DNS and content drift over time.",
                          action=lambda: self.go("templates"), action_label="Re-check")
        else:
            self._row("Content not scored yet", "warn",
                      "Run the spam check before your first send.",
                      action=lambda: self.go("templates"), action_label="Check")

        status = warmup.status()
        self._row(f"Warm-up: day {status.day_index}, {status.cap} emails/day",
                  "pass" if status.enabled else "warn",
                  "Volume rises gradually so receiving servers learn to trust you."
                  if status.enabled
                  else "Warm-up is off — you are sending at a fixed manual limit.",
                  action=lambda: self.go("campaign"), action_label="Settings")

        if not db.get_setting("imap_host", ""):
            self._row("Bounce detection is off", "warn",
                      "Without IMAP, bounced addresses stay on your list and keep damaging your "
                      "reputation.", action=lambda: self.go("account"), action_label="Set up")

    def _refresh_campaign(self) -> None:
        clear_layout(self.campaign_body)

        record = db.query_one(
            "SELECT * FROM campaigns WHERE status IN ('running', 'paused', 'draft') "
            "ORDER BY id DESC LIMIT 1")
        if record is None:
            self.campaign_body.addWidget(muted("No active campaign."))
            self.campaign_body.addWidget(
                row(primary_button("Go to Send", lambda: self.go("send"), 150), None))
            return

        stats = db.campaign_stats(record["id"])
        pending = stats.get("pending", 0) + stats.get("retry", 0)
        sent = stats.get("sent", 0)
        total = stats.get("total", 0)

        self.campaign_body.addWidget(muted(
            f"{record['name']} — {sent:,} sent, {pending:,} pending, "
            f"{stats.get('bounced', 0):,} bounced"))

        bar = QProgressBar()
        bar.setRange(0, max(1, total))
        bar.setValue(sent)
        bar.setTextVisible(False)
        self.campaign_body.addWidget(bar)

        if pending:
            days = max(1, -(-pending // max(1, warmup.status().cap)))
            self.campaign_body.addWidget(hint(
                f"At the current daily limit this takes about {days} more sending day(s)."))
            self.campaign_body.addWidget(
                row(primary_button("Continue sending", lambda: self.go("send"), 170), None))

    def _refresh_activity(self) -> None:
        events = db.recent_events(40)
        tones = {"error": "error", "warn": "warning"}
        rows, colours = [], []
        for event in events:
            tone = tones.get(event["level"])
            rows.append([prefs.format_datetime(event["ts"]), event["category"] or "",
                         event["message"] or ""])
            colours.append(["muted", tone or "muted", tone])
        self.activity_model.set_rows(rows, colours)
