"""Replies and bounces: IMAP sync results and what the app did about them."""
from __future__ import annotations

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from app.core import credentials, db, imap_sync, prefs
from app.models.table_model import SimpleTableModel
from app.ui.pages.base import Page
from app.ui.widgets.common import StatTile, TabBar, muted, primary_button, set_tone
from app.ui.widgets.inputs import checkbox
from app.ui.widgets.tables import DataTable
from app.workers import jobs
from app.workers.base import Task

AUTO_SYNC_MINUTES = 30

SOURCE_LABELS = {"bounce": "Bounce", "reply": "Opted out", "manual": "Manual",
                 "import": "Imported", "send": "Rejected"}


class InboxPage(Page):
    def __init__(self, window):
        super().__init__(window)
        self._syncing = False
        self._build()

        # Background polling: a timer on the UI thread that starts a worker.
        # The IMAP call itself never touches the UI thread.
        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(AUTO_SYNC_MINUTES * 60 * 1000)
        self._auto_timer.timeout.connect(self._auto_sync)
        if self.auto_sync.isChecked():
            self._auto_timer.start()

    def _build(self) -> None:
        self.add_header(
            "Replies & bounces",
            "Reads your inbox to find bounced addresses, unsubscribe requests and real replies. "
            "Bounced and opted-out addresses are removed from future sends automatically — "
            "this is what keeps your domain out of trouble.")

        holder = QWidget()
        holder.setProperty("role", "plain")
        controls = QHBoxLayout(holder)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(12)
        self.sync_button = primary_button("Check inbox now", self._sync, 180)
        controls.addWidget(self.sync_button)
        self.auto_sync = checkbox(
            f"Check automatically every {AUTO_SYNC_MINUTES} minutes",
            bool(db.get_setting("auto_imap_sync", True)), on_change=self._toggle_auto)
        controls.addWidget(self.auto_sync)
        self.sync_status = muted("", wrap=False)
        controls.addWidget(self.sync_status)
        controls.addStretch(1)
        self.root.addWidget(holder)

        tiles_holder = QWidget()
        tiles_holder.setProperty("role", "plain")
        tiles = QHBoxLayout(tiles_holder)
        tiles.setContentsMargins(0, 0, 0, 0)
        tiles.setSpacing(8)
        self.tile_replies = StatTile("Replies", "0", tone="success")
        self.tile_bounces = StatTile("Bounced addresses", "0", tone="error")
        self.tile_unsubs = StatTile("Unsubscribes", "0", tone="warning")
        for tile in (self.tile_replies, self.tile_bounces, self.tile_unsubs):
            tiles.addWidget(tile, 1)
        self.root.addWidget(tiles_holder)

        self.replies_model = SimpleTableModel(["Email", "Company", "Person", "Replied"])
        self.bounces_model = SimpleTableModel(["Email", "Reason", "Source", "When"])

        self.tabs = TabBar()
        self.tabs.add("Replies", self._build_replies)
        self.tabs.add("Bounces & opt-outs", self._build_bounces)
        self.root.addWidget(self.tabs, 1)
        self.tabs.set("Replies")

    def _build_replies(self) -> QWidget:
        holder = QWidget()
        holder.setProperty("role", "plain")
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(muted(
            "People who answered. These are your leads — and the ones worth sending the "
            "brochure attachment to on a follow-up."))
        self.replies_table = DataTable(
            self.replies_model, "No replies detected yet. Run a check after your first batch.")
        layout.addWidget(self.replies_table, 1)
        return holder

    def _build_bounces(self) -> QWidget:
        holder = QWidget()
        holder.setProperty("role", "plain")
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(muted(
            "Removed from all future sends. A bounce rate above 5% is what gets domains "
            "blacklisted, so these are dropped permanently."))
        self.bounces_table = DataTable(self.bounces_model, "Nothing suppressed yet.")
        layout.addWidget(self.bounces_table, 1)
        return holder

    # --- sync ---------------------------------------------------------------
    def _settings(self) -> imap_sync.ImapSettings | None:
        host = db.get_setting("imap_host", "")
        if not host:
            return None
        password = (credentials.load_secret(credentials.IMAP_PASSWORD)
                    or credentials.load_secret(credentials.SMTP_PASSWORD))
        try:
            port = int(db.get_setting("imap_port", 993))
        except (TypeError, ValueError):
            port = 993
        return imap_sync.ImapSettings(
            host=host, port=port,
            username=db.get_setting("smtp_username", "") or db.get_setting("sender_email", ""),
            password=password, use_ssl=port == 993,
            folder=db.get_setting("imap_folder", "INBOX"),
        )

    def _auto_sync(self) -> None:
        if self.auto_sync.isChecked() and not self._syncing and self._settings() is not None:
            self._sync(quiet=True)

    def _sync(self, quiet: bool = False) -> None:
        if self._syncing:
            return
        settings = self._settings()
        if settings is None:
            if not quiet:
                self.notify("Add your IMAP details on the 'My email account' page first", "warn")
                self.go("account")
            return

        self._syncing = True
        self.sync_button.setEnabled(False)
        self.sync_button.setText("Checking…")
        self.sync_status.setText("Connecting to your mailbox…")
        set_tone(self.sync_status, "muted")

        Task(jobs.sync_inbox, settings).start(
            on_result=lambda result: self._sync_done(result, quiet),
            on_error=lambda message: self._sync_failed(message))

    def _sync_failed(self, message: str) -> None:
        self._syncing = False
        self.sync_button.setEnabled(True)
        self.sync_button.setText("Check inbox now")
        self.sync_status.setText(message)
        set_tone(self.sync_status, "error")

    def _sync_done(self, result: imap_sync.SyncResult, quiet: bool = False) -> None:
        self._syncing = False
        self.sync_button.setEnabled(True)
        self.sync_button.setText("Check inbox now")

        if result.errors:
            self.sync_status.setText(result.errors[0])
            set_tone(self.sync_status, "error")
        else:
            self.sync_status.setText(result.summary())
            set_tone(self.sync_status, "muted")
            if result.hard_bounces or result.unsubscribes:
                self.notify(
                    f"{len(result.hard_bounces)} bounced and {len(result.unsubscribes)} "
                    f"opted-out addresses removed", "success")
            elif result.replies and not quiet:
                self.notify(f"{len(result.replies)} new reply(ies)", "success")

        self._load()
        self.window_.refresh_status()

    def _toggle_auto(self, enabled: bool) -> None:
        db.set_setting("auto_imap_sync", enabled)
        if enabled:
            self._auto_timer.start()
        else:
            self._auto_timer.stop()

    # --- data ---------------------------------------------------------------
    def _load(self) -> None:
        replies = imap_sync.replied_contacts()
        self.tile_replies.update_value(f"{len(replies):,}")
        self.replies_model.set_rows(
            [[r["email"], r["company"] or "", r["person"] or "",
              prefs.format_datetime(r["replied_at"])] for r in replies])

        rows = db.suppression_list()
        bounced = [r for r in rows if r["source"] in ("bounce", "send")]
        unsubs = [r for r in rows if r["source"] == "reply"]
        self.tile_bounces.update_value(f"{len(bounced):,}")
        self.tile_unsubs.update_value(f"{len(unsubs):,}")

        self.bounces_model.set_rows(
            [[r["email"], r["reason"] or "", SOURCE_LABELS.get(r["source"], r["source"] or ""),
              prefs.format_datetime(r["added_at"])] for r in rows],
            [[None, "muted", "warning", "muted"] for _ in rows])

        state = db.query_one("SELECT last_sync_at FROM imap_state WHERE id = 1")
        if state and state["last_sync_at"] and not self._syncing:
            self.sync_status.setText(
                f"Last checked {prefs.format_datetime(state['last_sync_at'])}")
            set_tone(self.sync_status, "muted")

    def on_show(self) -> None:
        self._load()
