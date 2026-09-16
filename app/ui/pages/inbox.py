"""The inbox: mail that arrived, plus what the app did about it.

The IMAP check has always read the mailbox to find bounces and opt-outs. It now
keeps what it read, so this page has three views of the same sync: the messages
themselves, the people who answered, and the addresses that were dropped.
"""
from __future__ import annotations

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import QHBoxLayout, QPlainTextEdit, QSplitter, QVBoxLayout, QWidget

from app.core import credentials, db, imap_sync, prefs
from app.models.table_model import SimpleTableModel
from app.ui import theme
from app.ui.pages.base import Page
from app.ui.widgets.common import (ChoiceButtons, StatTile, TabBar, muted, primary_button,
                                   secondary_button, set_tone, subheading)
from app.ui.widgets.inputs import checkbox
from app.ui.widgets.tables import DataTable
from app.workers import jobs
from app.workers.base import Task

AUTO_SYNC_MINUTES = 30

SOURCE_LABELS = {"bounce": "Bounce", "reply": "Opted out", "manual": "Manual",
                 "import": "Imported", "send": "Rejected"}

# What the check decided each message was, in words a non-technical reader gets
KIND_LABELS = {"reply": "Reply", "bounce": "Bounce", "optout": "Opt-out request",
               "other": "Other mail"}
KIND_TONES = {"reply": "success", "bounce": "error", "optout": "warning", "other": None}
# The table colours cells by theme token, so these are token names, not QSS tones.

# The filter buttons above the message list
FILTERS = [("all", "Everything"), ("reply", "Replies"), ("bounce", "Bounces"),
           ("optout", "Opt-outs"), ("other", "Other mail")]


class InboxPage(Page):
    def __init__(self, window):
        super().__init__(window)
        self._syncing = False
        self._filter = "all"
        self._shown: list = []
        self._reading = False
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
            "My inbox",
            "Reads your mailbox so you can see what came back. Bounced addresses and people "
            "who ask to be taken off are dropped from future sends automatically.")

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
        self.tile_unread = StatTile("Unread", "0", tone="accent")
        self.tile_replies = StatTile("Replies", "0", tone="success")
        self.tile_bounces = StatTile("Bounced addresses", "0", tone="error")
        self.tile_unsubs = StatTile("Unsubscribes", "0", tone="warning")
        for tile in (self.tile_unread, self.tile_replies, self.tile_bounces, self.tile_unsubs):
            tiles.addWidget(tile, 1)
        self.root.addWidget(tiles_holder)

        self.messages_model = SimpleTableModel(["New", "From", "Subject", "What it is", "When"])
        self.replies_model = SimpleTableModel(["Email", "Company", "Person", "Replied"])
        self.bounces_model = SimpleTableModel(["Email", "Reason", "Source", "When"])

        self.tabs = TabBar()
        self.tabs.add("Inbox", self._build_messages)
        self.tabs.add("Replies", self._build_replies)
        self.tabs.add("Bounces & opt-outs", self._build_bounces)
        self.root.addWidget(self.tabs, 1)
        self.tabs.set("Inbox")

    # --- the message list and its reading pane ------------------------------
    def _build_messages(self) -> QWidget:
        scale = theme.text_scale()
        holder = QWidget()
        holder.setProperty("role", "plain")
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(round(8 * scale))

        bar = QWidget()
        bar.setProperty("role", "plain")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(0, 0, 0, 0)
        bar_layout.setSpacing(round(6 * scale))
        # The filter row must get the spare width, not a stretch item: its
        # flow layout wraps to the width it is given, and a hungry stretch
        # next to it squeezed all five buttons into a vertical stack.
        bar_layout.addWidget(ChoiceButtons(FILTERS, self._filter, on_change=self._set_filter), 1)
        bar_layout.addWidget(secondary_button("Mark all as read", self._mark_all_read, 160), 0,
                             Qt.AlignmentFlag.AlignTop)
        layout.addWidget(bar)

        # A splitter, not a fixed split: on a short screen the list matters
        # more, on a tall one the message does, and the user decides.
        split = QSplitter(Qt.Orientation.Vertical)
        split.setChildrenCollapsible(False)

        self.messages_table = DataTable(
            self.messages_model,
            "No messages yet. Press 'Check inbox now' once your email account is connected.")
        self.messages_table.selection_changed.connect(self._show_selected)
        split.addWidget(self.messages_table)

        reader = QWidget()
        reader.setProperty("role", "plain")
        reader_layout = QVBoxLayout(reader)
        reader_layout.setContentsMargins(0, round(6 * scale), 0, 0)
        reader_layout.setSpacing(round(4 * scale))
        self.reader_from = subheading("Pick a message to read it")
        reader_layout.addWidget(self.reader_from)
        self.reader_meta = muted("")
        reader_layout.addWidget(self.reader_meta)
        self.reader_body = QPlainTextEdit()
        self.reader_body.setReadOnly(True)
        self.reader_body.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.reader_body.setPlaceholderText(
            "The message you pick above is shown here in plain text.")
        reader_layout.addWidget(self.reader_body, 1)
        split.addWidget(reader)

        split.setSizes([round(300 * scale), round(240 * scale)])
        layout.addWidget(split, 1)
        return holder

    def _set_filter(self, key: str) -> None:
        self._filter = key
        self._load_messages()
        self._show_selected()

    def _build_replies(self) -> QWidget:
        holder = QWidget()
        holder.setProperty("role", "plain")
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(muted(
            "People who answered. These are your leads, and the ones worth sending the "
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
        self.sync_button.setText("Checking...")
        self.sync_status.setText("Connecting to your mailbox...")
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
            elif result.scanned and not quiet:
                self.notify(f"{result.scanned} new message(s) in your inbox", "info")

        self._load()
        self.window_.refresh_status()

    def _toggle_auto(self, enabled: bool) -> None:
        db.set_setting("auto_imap_sync", enabled)
        if enabled:
            self._auto_timer.start()
        else:
            self._auto_timer.stop()

    # --- reading ------------------------------------------------------------
    def _show_selected(self) -> None:
        row = self.messages_table.selected_row()
        if row < 0 or row >= len(self._shown):
            self.reader_from.setText("Pick a message to read it")
            self.reader_meta.setText("")
            self.reader_body.setPlainText("")
            return

        message = self._shown[row]
        name = message["from_name"] or message["from_email"] or "Unknown sender"
        self.reader_from.setText(message["subject"] or "(no subject)")
        self.reader_meta.setText(
            f"From {name} <{message['from_email']}>   ·   "
            f"{prefs.format_datetime(message['received_at'])}   ·   "
            f"{KIND_LABELS.get(message['kind'], 'Mail')}")
        self.reader_body.setPlainText(message["body"] or "(this message had no readable text)")

        if not message["seen"] and not self._reading:
            # Marking it read redraws the list, which re-selects the row and
            # lands back here. The flag keeps that to one pass.
            self._reading = True
            try:
                db.mark_message_seen(message["id"])
                self._load_messages(keep_row=row)
                self._refresh_unread()
            finally:
                self._reading = False

    def _mark_all_read(self) -> None:
        if not db.inbox_unseen():
            return
        db.mark_all_messages_seen()
        self._load_messages(keep_row=self.messages_table.selected_row())
        self._refresh_unread()

    def _refresh_unread(self) -> None:
        unread = db.inbox_unseen()
        self.tile_unread.update_value(f"{unread:,}")
        self.window_.refresh_status()

    # --- data ---------------------------------------------------------------
    def _load_messages(self, keep_row: int = -1) -> None:
        kind = None if self._filter == "all" else self._filter
        self._shown = db.inbox_messages(kind)
        rows, tones = [], []
        for message in self._shown:
            unread = not message["seen"]
            kind_key = message["kind"] or "other"
            rows.append([
                "New" if unread else "",
                message["from_name"] or message["from_email"] or "",
                message["subject"] or "(no subject)",
                KIND_LABELS.get(kind_key, "Mail"),
                prefs.format_datetime(message["received_at"]),
            ])
            # Unread lines are tinted rather than bold: the model holds plain
            # strings, and one colour reads as clearly as two font weights.
            tones.append(["accent" if unread else None,
                          "fg_bright" if unread else None,
                          "fg_bright" if unread else None,
                          KIND_TONES.get(kind_key), "fg_muted"])
        self.messages_model.set_rows(rows, tones)

        if 0 <= keep_row < len(rows):
            self.messages_table.view.selectRow(keep_row)

        self.messages_table.set_empty_message(
            "No messages yet. Press 'Check inbox now' once your email account is connected."
            if self._filter == "all" else
            "Nothing of this kind yet. Try 'Everything'.")

    def _load(self) -> None:
        self._refresh_unread()
        if hasattr(self, "messages_model"):
            self._load_messages(keep_row=self.messages_table.selected_row()
                                if hasattr(self, "messages_table") else -1)

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
