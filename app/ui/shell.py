"""Application shell: sidebar navigation, page router, status bar."""
from __future__ import annotations

import customtkinter as ctk

from app import config, theme
from app.core import db, warmup
from app.ui.widgets.common import toast

NAV_ITEMS = [
    ("dashboard", "Dashboard", "Overview and activity"),
    ("guide", "Setup guide", "Step-by-step checklist"),
    ("account", "Email account", "SMTP and IMAP settings"),
    ("deliverability", "Deliverability", "SPF, DKIM, DMARC tools"),
    ("contacts", "Contacts", "Import and clean your list"),
    ("templates", "Templates", "Subjects, bodies, signature"),
    ("campaign", "Campaign", "Pacing and brochure"),
    ("send", "Send", "Run and monitor"),
    ("inbox", "Replies & bounces", "IMAP sync results"),
]


class SidebarButton(ctk.CTkFrame):
    def __init__(self, master, key: str, title: str, subtitle: str, command):
        super().__init__(master, fg_color="transparent", corner_radius=theme.RADIUS, height=46)
        self.key = key
        self.command = command
        self.active = False
        # Without this the frame grows to fit its children's requested height
        self.pack_propagate(False)

        self.indicator = ctk.CTkFrame(self, fg_color="transparent", width=3, height=46,
                                      corner_radius=0)
        self.indicator.pack(side="left", fill="y")

        text = ctk.CTkFrame(self, fg_color="transparent")
        text.pack(side="left", fill="both", expand=True, padx=(9, 6), pady=5)

        self.title_label = ctk.CTkLabel(text, text=title, font=theme.font(13),
                                        text_color=theme.FG, anchor="w")
        self.title_label.pack(anchor="w")
        self.subtitle_label = ctk.CTkLabel(text, text=subtitle, font=theme.font(10),
                                           text_color=theme.FG_MUTED, anchor="w")
        self.subtitle_label.pack(anchor="w")

        self.badge = ctk.CTkLabel(self, text="", font=theme.font(11, "bold"),
                                  text_color=theme.WARNING, width=18)
        self.badge.pack(side="right", padx=(0, 10))

        for widget in [self, text, self.title_label, self.subtitle_label, self.badge]:
            widget.bind("<Button-1>", lambda e: self.command(self.key))
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)
            widget.configure(cursor="hand2")

    def _on_enter(self, _event=None) -> None:
        if not self.active:
            self.configure(fg_color=theme.BG_HOVER)

    def _on_leave(self, _event=None) -> None:
        if not self.active:
            self.configure(fg_color="transparent")

    def set_active(self, active: bool) -> None:
        self.active = active
        self.configure(fg_color=theme.BG_SELECTED if active else "transparent")
        self.indicator.configure(fg_color=theme.ACCENT if active else "transparent")
        self.title_label.configure(text_color=theme.FG_BRIGHT if active else theme.FG,
                                   font=theme.font(13, "bold" if active else "normal"))

    def set_badge(self, text: str, color=None) -> None:
        self.badge.configure(text=text, text_color=color or theme.WARNING)


class AppShell(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"{config.APP_TITLE}  {config.APP_VERSION}")
        self.geometry("1180x780")
        self.minsize(1000, 660)
        self.configure(fg_color=theme.BG)

        self.pages: dict[str, ctk.CTkFrame] = {}
        self.nav_buttons: dict[str, SidebarButton] = {}
        self.current: str | None = None

        self._build_layout()
        self._build_sidebar()
        self._build_status_bar()
        self._register_pages()

        self.show("dashboard")
        self.after(1000, self._refresh_status)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # -- layout --------------------------------------------------------------
    def _build_layout(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkFrame(self, fg_color=theme.BG_SIDEBAR, corner_radius=0,
                                    width=theme.SIDEBAR_WIDTH)
        self.sidebar.grid(row=0, column=0, sticky="nsw")
        self.sidebar.grid_propagate(False)

        self.content = ctk.CTkFrame(self, fg_color=theme.BG, corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

    def _build_sidebar(self) -> None:
        header = ctk.CTkFrame(self.sidebar, fg_color="transparent", height=64)
        header.pack(fill="x", pady=(16, 10))
        ctk.CTkLabel(header, text=config.APP_TITLE, font=theme.font(15, "bold"),
                     text_color=theme.FG_BRIGHT, anchor="w").pack(anchor="w", padx=16)
        ctk.CTkLabel(header, text="Safe bulk email for offices", font=theme.font(10),
                     text_color=theme.FG_MUTED, anchor="w").pack(anchor="w", padx=16)

        theme.separator(self.sidebar).pack(fill="x", padx=12, pady=(0, 8))

        nav = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        nav.pack(fill="both", expand=True, padx=8)
        for key, title, subtitle in NAV_ITEMS:
            button = SidebarButton(nav, key, title, subtitle, self.show)
            button.pack(fill="x", pady=1)
            self.nav_buttons[key] = button

        footer = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        footer.pack(fill="x", side="bottom", pady=12, padx=12)
        theme.separator(footer).pack(fill="x", pady=(0, 10))

        self.appearance_menu = theme.option_menu(
            footer, ["Dark", "Light", "System"], command=self._change_appearance, height=28)
        self.appearance_menu.set(db.get_setting("appearance", "Dark"))
        self.appearance_menu.pack(fill="x")

    def _build_status_bar(self) -> None:
        self.status_bar = ctk.CTkFrame(self, fg_color=theme.STATUS_BAR, corner_radius=0, height=24)
        self.status_bar.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.status_bar.grid_propagate(False)

        self.status_account = ctk.CTkLabel(self.status_bar, text="No account configured",
                                           font=theme.font(11), text_color="#ffffff")
        self.status_account.pack(side="left", padx=12)

        self.status_right = ctk.CTkLabel(self.status_bar, text="", font=theme.font(11),
                                         text_color="#ffffff")
        self.status_right.pack(side="right", padx=12)

        self.status_middle = ctk.CTkLabel(self.status_bar, text="", font=theme.font(11),
                                          text_color="#ffffff")
        self.status_middle.pack(side="right", padx=12)

    # -- pages ---------------------------------------------------------------
    def _register_pages(self) -> None:
        from app.ui import (page_account, page_campaign, page_contacts, page_dashboard,
                            page_deliverability, page_guide, page_inbox, page_send, page_templates)

        builders = {
            "dashboard": page_dashboard.DashboardPage,
            "guide": page_guide.GuidePage,
            "account": page_account.AccountPage,
            "deliverability": page_deliverability.DeliverabilityPage,
            "contacts": page_contacts.ContactsPage,
            "templates": page_templates.TemplatesPage,
            "campaign": page_campaign.CampaignPage,
            "send": page_send.SendPage,
            "inbox": page_inbox.InboxPage,
        }
        for key, builder in builders.items():
            page = builder(self.content, self)
            page.grid(row=0, column=0, sticky="nsew")
            page.grid_remove()
            self.pages[key] = page

    def show(self, key: str) -> None:
        if key not in self.pages:
            return
        if self.current:
            self.pages[self.current].grid_remove()
            self.nav_buttons[self.current].set_active(False)

        self.current = key
        page = self.pages[key]
        page.grid()
        self.nav_buttons[key].set_active(True)

        if hasattr(page, "on_show"):
            try:
                page.on_show()
            except Exception as error:  # noqa: BLE001 - a broken page must not kill navigation
                toast(self, f"Could not refresh this page: {error}", "error")
        self._refresh_status()

    def notify(self, message: str, level: str = "info") -> None:
        toast(self, message, level)

    # -- status --------------------------------------------------------------
    def _refresh_status(self) -> None:
        email = db.get_setting("sender_email", "")
        host = db.get_setting("smtp_host", "")
        if email:
            self.status_account.configure(text=f"{email}" + (f"  ·  {host}" if host else ""))
        else:
            self.status_account.configure(text="No account configured — open 'Email account'")

        try:
            status = warmup.status()
            self.status_middle.configure(text=status.describe())
        except Exception:
            self.status_middle.configure(text="")

        from app.core import importer
        try:
            count = importer.contact_count()
            self.status_right.configure(text=f"{count:,} contacts")
        except Exception:
            self.status_right.configure(text="")

        self._refresh_badges()

    def _refresh_badges(self) -> None:
        """A dot next to steps that are not done yet, so setup is self-guiding."""
        from app.core import importer

        incomplete = {
            "account": not bool(db.get_setting("sender_email", "")),
            "contacts": importer.contact_count() == 0,
            "templates": db.query_one("SELECT 1 FROM bodies WHERE enabled = 1") is None,
        }
        for key, button in self.nav_buttons.items():
            button.set_badge("●" if incomplete.get(key) else "")

    def _change_appearance(self, mode: str) -> None:
        db.set_setting("appearance", mode)
        theme.apply_appearance(mode)
        # Canvas-drawn widgets do not follow the theme automatically
        for page in self.pages.values():
            for widget in _walk(page):
                if hasattr(widget, "refresh_theme"):
                    try:
                        widget.refresh_theme()
                    except Exception:
                        pass

    def _on_close(self) -> None:
        send_page = self.pages.get("send")
        if send_page is not None and getattr(send_page, "is_running", lambda: False)():
            from app.ui.widgets.common import ConfirmDialog
            if not ConfirmDialog.ask(
                self, "A campaign is still running",
                "Closing now stops sending. Everything already sent is saved, and you can resume "
                "the campaign next time you open the app.\n\nClose anyway?",
                confirm_text="Close and stop", danger=True,
            ):
                return
            send_page.stop_worker()
        db.close()
        self.destroy()


def _walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk(child)
