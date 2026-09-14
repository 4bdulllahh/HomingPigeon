"""Application shell: sidebar navigation, page router, status bar."""
from __future__ import annotations

import sys
import tkinter as tk

import customtkinter as ctk
from PIL import Image

from app import config, theme
from app.core import db, prefs, warmup
from app.ui.widgets.common import toast

# (key, icon, title, subtitle)
NAV_ITEMS = [
    ("dashboard", "home", "Home", "How things are going"),
    ("guide", "guide", "Start here", "Step-by-step setup"),
    ("account", "account", "My email account", "Connect your email"),
    ("deliverability", "shield", "Domain check", "Stay out of spam"),
    ("contacts", "contacts", "My contacts", "Your list of people"),
    ("templates", "message", "My message", "What you want to say"),
    ("campaign", "options", "Sending options", "Speed, timing, brochure"),
    ("send", "send", "Send emails", "Start and watch it run"),
    ("inbox", "inbox", "Replies & bounces", "Who answered, who failed"),
]
SETTINGS_ITEM = ("settings", "settings", "Settings", "Theme, text size, uninstall")

# Above this text size the subtitles are hidden so the menu still fits on screen
SUBTITLE_MAX_SCALE = 1.15


class SidebarButton(ctk.CTkFrame):
    """One menu entry: an icon, a title and a short hint, drawn as a rounded button."""

    def __init__(self, master, key: str, icon: str, title: str, subtitle: str, command):
        show_subtitle = prefs.text_scale() <= SUBTITLE_MAX_SCALE
        super().__init__(master, fg_color="transparent", corner_radius=theme.RADIUS,
                         border_width=1, border_color=theme.BG_SIDEBAR,
                         height=54 if show_subtitle else 42)
        self.key = key
        self.command = command
        self.active = False
        self.grid_propagate(False)
        self.grid_columnconfigure(1, weight=1)

        # Rounded accent bar on the left edge of the selected entry
        self.indicator = ctk.CTkFrame(self, fg_color="transparent", width=4, corner_radius=2)
        self.indicator.grid(row=0, column=0, rowspan=2, sticky="nsw", padx=(3, 0), pady=10)

        self.icon_label = ctk.CTkLabel(self, text=theme.icon(icon), font=theme.icon_font(17),
                                       text_color=theme.FG_MUTED, width=30)
        self.icon_label.grid(row=0, column=0, rowspan=2, padx=(12, 6))

        self.title_label = ctk.CTkLabel(self, text=title, font=theme.font(13, "bold"),
                                        text_color=theme.FG, anchor="w", height=20)
        self.subtitle_label = ctk.CTkLabel(self, text=subtitle, font=theme.font(11),
                                           text_color=theme.FG_MUTED, anchor="w", height=18)
        if show_subtitle:
            self.grid_rowconfigure((0, 1), weight=1)
            self.title_label.grid(row=0, column=1, sticky="sw", pady=(7, 0))
            self.subtitle_label.grid(row=1, column=1, sticky="nw", pady=(0, 7))
        else:
            self.grid_rowconfigure(0, weight=1)
            self.title_label.grid(row=0, column=1, rowspan=2, sticky="w")

        self.badge = ctk.CTkLabel(self, text="", font=theme.font(11, "bold"),
                                  text_color=theme.WARNING, width=18)
        self.badge.grid(row=0, column=2, rowspan=2, padx=(0, 10))

        for widget in [self, self.icon_label, self.title_label, self.subtitle_label, self.badge]:
            widget.bind("<Button-1>", lambda e: self.command(self.key))
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)
            widget.configure(cursor="hand2")

    def _on_enter(self, _event=None) -> None:
        if not self.active:
            self.configure(fg_color=theme.BG_HOVER, border_color=theme.BORDER)

    def _on_leave(self, _event=None) -> None:
        if not self.active:
            self.configure(fg_color="transparent", border_color=theme.BG_SIDEBAR)

    def set_active(self, active: bool) -> None:
        self.active = active
        self.configure(fg_color=theme.BG_SELECTED if active else "transparent",
                       border_color=theme.BORDER if active else theme.BG_SIDEBAR)
        self.indicator.configure(fg_color=theme.ACCENT if active else "transparent")
        self.icon_label.configure(text_color=theme.ACCENT if active else theme.FG_MUTED)
        self.title_label.configure(text_color=theme.FG_BRIGHT if active else theme.FG)

    def set_badge(self, text: str, color=None) -> None:
        self.badge.configure(text=text, text_color=color or theme.WARNING)


class AppShell(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"{config.APP_TITLE} {config.APP_VERSION} — {config.APP_TAGLINE}")
        self._set_window_icon()
        width = min(1280, self.winfo_screenwidth() - 80)
        height = min(860, self.winfo_screenheight() - 120)
        self.geometry(f"{width}x{height}")
        self.minsize(min(1000, width), min(640, height))
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.pages: dict[str, ctk.CTkFrame] = {}
        self.nav_buttons: dict[str, SidebarButton] = {}
        self.current: str | None = None
        self._build_all()

        start = prefs.get("start_page")
        if start == "last":
            start = db.get_setting("last_page", "dashboard")
        self.show(start if start in self.pages else "dashboard")
        self.after(1000, self._refresh_status)

    def _set_window_icon(self) -> None:
        """The pigeon in the title bar and taskbar (must run before CustomTkinter sets its own)."""
        try:
            if sys.platform == "win32":
                self.iconbitmap(str(config.resource_path("assets/icon.ico")))
            else:
                self._icon_photo = tk.PhotoImage(file=str(config.resource_path("assets/logo-256.png")))
                self.iconphoto(True, self._icon_photo)
        except (tk.TclError, OSError):
            pass

    def _build_all(self) -> None:
        self.configure(fg_color=theme.BG)
        self._build_layout()
        self._build_sidebar()
        self._build_status_bar()
        self._register_pages()

    def rebuild(self, page: str | None = None, before_build=None) -> bool:
        """Rebuild every page, so colour, size and format changes from Settings apply everywhere.

        before_build runs after the old widgets are gone and before the new ones are made
        (resizing thousands of widgets that are about to be destroyed would be slow).
        Refused while a campaign is sending, because that would stop it.
        """
        if self.is_sending():
            toast(self, "This change applies once sending has finished (or next time you open "
                        "the app).", "warn", 6000)
            return False
        page = page or self.current or "dashboard"
        for child in self.winfo_children():
            child.destroy()
        self.pages.clear()
        self.nav_buttons.clear()
        self.current = None
        if before_build:
            before_build()
        self._build_all()
        self.show(page)
        return True

    def is_sending(self) -> bool:
        send_page = self.pages.get("send")
        return bool(send_page is not None and getattr(send_page, "is_running", lambda: False)())

    # -- layout --------------------------------------------------------------
    def _build_layout(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkFrame(self, fg_color=theme.BG_SIDEBAR, corner_radius=0,
                                    width=theme.SIDEBAR_WIDTH + 16)
        self.sidebar.grid(row=0, column=0, sticky="nsw")
        self.sidebar.grid_propagate(False)
        self.sidebar.pack_propagate(False)

        theme.separator(self, width=1, height=1).grid(row=0, column=0, sticky="nse")

        self.content = ctk.CTkFrame(self, fg_color=theme.BG, corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

    def _build_sidebar(self) -> None:
        header = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(16, 10))
        try:
            logo = Image.open(config.resource_path("assets/logo-96.png"))
            self._logo = ctk.CTkImage(light_image=logo, dark_image=logo, size=(44, 44))
            ctk.CTkLabel(header, text="", image=self._logo).pack(side="left", padx=(0, 10))
        except OSError:
            ctk.CTkLabel(header, text="🕊", font=theme.font(22), text_color=theme.ACCENT).pack(
                side="left", padx=(0, 10))
        names = ctk.CTkFrame(header, fg_color="transparent")
        names.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(names, text=config.APP_TITLE, font=theme.font(18, "bold"),
                     text_color=theme.FG_BRIGHT, anchor="w", height=24).pack(anchor="w")
        ctk.CTkLabel(names, text=config.APP_VERSION, font=theme.font(11),
                     text_color=theme.FG_MUTED, anchor="w", height=18).pack(anchor="w")

        theme.separator(self.sidebar).pack(fill="x", padx=14, pady=(0, 8))

        # Settings sits at the bottom, below a divider; packed before the menu so it always fits
        footer = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        footer.pack(fill="x", side="bottom", padx=10, pady=(0, 10))
        theme.separator(footer).pack(fill="x", padx=4, pady=(0, 8))
        key, icon, title, subtitle = SETTINGS_ITEM
        settings_button = SidebarButton(footer, key, icon, title, subtitle, self.show)
        settings_button.pack(fill="x")
        self.nav_buttons[key] = settings_button

        nav = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        nav.pack(fill="both", expand=True, padx=10)
        for key, icon, title, subtitle in NAV_ITEMS:
            button = SidebarButton(nav, key, icon, title, subtitle, self.show)
            button.pack(fill="x", pady=2)
            self.nav_buttons[key] = button

    def _build_status_bar(self) -> None:
        self.status_bar = ctk.CTkFrame(self, fg_color=theme.STATUS_BAR, corner_radius=0, height=26)
        self.status_bar.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.status_bar.grid_propagate(False)

        self.status_account = ctk.CTkLabel(self.status_bar, text="No account configured",
                                           font=theme.font(12), text_color="#ffffff")
        self.status_account.pack(side="left", padx=12)

        self.status_right = ctk.CTkLabel(self.status_bar, text="", font=theme.font(12),
                                         text_color="#ffffff")
        self.status_right.pack(side="right", padx=12)

        self.status_middle = ctk.CTkLabel(self.status_bar, text="", font=theme.font(12),
                                          text_color="#ffffff")
        self.status_middle.pack(side="right", padx=12)

    # -- pages ---------------------------------------------------------------
    def _register_pages(self) -> None:
        from app.ui import (page_account, page_campaign, page_contacts, page_dashboard,
                            page_deliverability, page_guide, page_inbox, page_send, page_settings,
                            page_templates)

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
            "settings": page_settings.SettingsPage,
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
        db.set_setting("last_page", key)

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
        if not self.winfo_exists() or not self.pages:
            return
        email = db.get_setting("sender_email", "")
        host = db.get_setting("smtp_host", "")
        if email:
            self.status_account.configure(text=f"{email}" + (f"  ·  {host}" if host else ""))
        else:
            self.status_account.configure(text="No account configured — open 'My email account'")

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

    def change_appearance(self, mode: str) -> None:
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

    def quit_app(self) -> None:
        """Close without questions (used by the uninstaller and restore)."""
        if self.is_sending():
            self.pages["send"].stop_worker()
        db.close()
        self.destroy()

    def _on_close(self) -> None:
        if self.is_sending():
            from app.ui.widgets.common import ConfirmDialog
            if not ConfirmDialog.ask(
                self, "A campaign is still running",
                "Closing now stops sending. Everything already sent is saved, and you can resume "
                "the campaign next time you open the app.\n\nClose anyway?",
                confirm_text="Close and stop", danger=True,
            ):
                return
            self.pages["send"].stop_worker()
        db.close()
        self.destroy()


def _walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk(child)
