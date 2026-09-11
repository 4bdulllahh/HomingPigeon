"""Replies and bounces: IMAP sync results and what the app did about them."""
from __future__ import annotations

import threading

import customtkinter as ctk

from app import theme
from app.core import credentials, db, imap_sync
from app.ui.widgets.common import DataTable, Section, StatTile, toast


class InboxPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self._syncing = False
        self._build()

    def _build(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=theme.PAD_LARGE, pady=(theme.PAD, 0))
        theme.heading(header, "Replies & bounces").pack(anchor="w")
        theme.label(header,
                    "Reads your inbox to find bounced addresses, unsubscribe requests and real "
                    "replies. Bounced and opted-out addresses are removed from future sends "
                    "automatically — this is what keeps your domain out of trouble.",
                    muted=True, wrap=True).pack(anchor="w", pady=(2, 12))

        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.pack(fill="x", padx=theme.PAD_LARGE, pady=(0, 10))

        self.sync_button = theme.primary_button(controls, "Check inbox now", self._sync, width=170)
        self.sync_button.pack(side="left")

        self.auto_sync = ctk.BooleanVar(value=bool(db.get_setting("auto_imap_sync", True)))
        theme.checkbox(controls, "Check automatically every 30 minutes", variable=self.auto_sync,
                       command=self._toggle_auto).pack(side="left", padx=16)

        self.sync_status = theme.label(controls, "", muted=True)
        self.sync_status.pack(side="left", padx=8)

        tiles = ctk.CTkFrame(self, fg_color="transparent")
        tiles.pack(fill="x", padx=theme.PAD_LARGE, pady=(0, 12))
        for index in range(3):
            tiles.grid_columnconfigure(index, weight=1)

        self.tile_replies = StatTile(tiles, "Replies", "0", accent=theme.SUCCESS)
        self.tile_replies.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.tile_bounces = StatTile(tiles, "Bounced addresses", "0", accent=theme.ERROR)
        self.tile_bounces.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        self.tile_unsubs = StatTile(tiles, "Unsubscribes", "0", accent=theme.WARNING)
        self.tile_unsubs.grid(row=0, column=2, sticky="ew")

        self.tabs = ctk.CTkTabview(
            self, fg_color=theme.BG_PANEL, segmented_button_fg_color=theme.BG_SIDEBAR,
            segmented_button_selected_color=theme.ACCENT,
            segmented_button_selected_hover_color=theme.ACCENT_HOVER,
            segmented_button_unselected_color=theme.BG_SIDEBAR, text_color=theme.FG,
            border_width=1, border_color=theme.BORDER, corner_radius=theme.RADIUS_CARD)
        self.tabs.pack(fill="both", expand=True, padx=theme.PAD_LARGE, pady=(0, theme.PAD))
        self.tabs.add("Replies")
        self.tabs.add("Bounces & opt-outs")

        replies_tab = self.tabs.tab("Replies")
        theme.label(replies_tab,
                    "People who answered. These are your leads — and the ones worth sending the "
                    "brochure attachment to on a follow-up.",
                    muted=True).pack(anchor="w", pady=(10, 8))
        self.replies_table = DataTable(
            replies_tab, [("Email", 260), ("Company", 240), ("Person", 180), ("Replied", 150)],
            height=380)
        self.replies_table.pack(fill="both", expand=True, pady=(0, 10))

        bounces_tab = self.tabs.tab("Bounces & opt-outs")
        theme.label(bounces_tab,
                    "Removed from all future sends. A bounce rate above 5% is what gets domains "
                    "blacklisted, so these are dropped permanently.",
                    muted=True).pack(anchor="w", pady=(10, 8))
        self.bounces_table = DataTable(
            bounces_tab, [("Email", 260), ("Reason", 340), ("Source", 110), ("When", 150)],
            height=380)
        self.bounces_table.pack(fill="both", expand=True, pady=(0, 10))

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

    def _sync(self) -> None:
        if self._syncing:
            return
        settings = self._settings()
        if settings is None:
            toast(self, "Add your IMAP details on the 'Email account' page first", "warn")
            self.app.show("account")
            return

        self._syncing = True
        self.sync_button.configure(state="disabled", text="Checking…")
        self.sync_status.configure(text="Connecting to your mailbox…", text_color=theme.FG_MUTED)

        def work() -> None:
            result = imap_sync.sync(settings)
            self.after(0, lambda: self._sync_done(result))

        threading.Thread(target=work, daemon=True).start()

    def _sync_done(self, result: imap_sync.SyncResult) -> None:
        self._syncing = False
        self.sync_button.configure(state="normal", text="Check inbox now")

        if result.errors:
            self.sync_status.configure(text=result.errors[0], text_color=theme.ERROR)
        else:
            self.sync_status.configure(text=result.summary(), text_color=theme.FG_MUTED)
            if result.hard_bounces or result.unsubscribes:
                toast(self,
                      f"{len(result.hard_bounces)} bounced and {len(result.unsubscribes)} "
                      f"opted-out addresses removed", "success")
            elif result.replies:
                toast(self, f"{len(result.replies)} new reply(ies)", "success")

        self._load()

    def _toggle_auto(self) -> None:
        db.set_setting("auto_imap_sync", self.auto_sync.get())

    # --- data ---------------------------------------------------------------
    def _load(self) -> None:
        replies = imap_sync.replied_contacts()
        self.tile_replies.update_value(f"{len(replies):,}")
        self.replies_table.clear()
        if replies:
            for row in replies:
                self.replies_table.add_row(
                    [row["email"], row["company"] or "", row["person"] or "",
                     (row["replied_at"] or "").replace("T", " ")[:16]])
        else:
            self.replies_table.set_empty_message(
                "No replies detected yet. Run a check after your first batch.")

        rows = db.suppression_list()
        bounced = [r for r in rows if r["source"] in ("bounce", "send")]
        unsubs = [r for r in rows if r["source"] == "reply"]
        self.tile_bounces.update_value(f"{len(bounced):,}")
        self.tile_unsubs.update_value(f"{len(unsubs):,}")

        self.bounces_table.clear()
        if rows:
            labels = {"bounce": "Bounce", "reply": "Opted out", "manual": "Manual",
                      "import": "Imported", "send": "Rejected"}
            for row in rows:
                self.bounces_table.add_row(
                    [row["email"], row["reason"] or "", labels.get(row["source"], row["source"] or ""),
                     (row["added_at"] or "").replace("T", " ")[:16]],
                    colors=[theme.FG, theme.FG_MUTED, theme.WARNING, theme.FG_MUTED])
        else:
            self.bounces_table.set_empty_message("Nothing suppressed yet.")

        state = db.query_one("SELECT last_sync_at FROM imap_state WHERE id = 1")
        if state and state["last_sync_at"]:
            self.sync_status.configure(
                text=f"Last checked {state['last_sync_at'].replace('T', ' ')[:16]}")

    def on_show(self) -> None:
        self._load()
