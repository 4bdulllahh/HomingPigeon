"""Email account setup: SMTP for sending, IMAP for bounce/reply detection."""
from __future__ import annotations

import threading

import customtkinter as ctk

from app import theme
from app.core import credentials, db, imap_sync, sender
from app.ui.widgets.common import FormRow, Section, toast

PRESETS: dict[str, dict] = {
    "Custom / other": {},
    "Google Workspace / Gmail": {
        "smtp_host": "smtp.gmail.com", "smtp_port": 587, "security": "starttls",
        "imap_host": "imap.gmail.com", "imap_port": 993,
        "note": "Gmail requires an App Password when 2-step verification is on: "
                "Google Account → Security → 2-Step Verification → App passwords. "
                "Your normal password will not work.",
    },
    "Microsoft 365 / Outlook": {
        "smtp_host": "smtp.office365.com", "smtp_port": 587, "security": "starttls",
        "imap_host": "outlook.office365.com", "imap_port": 993,
        "note": "An administrator must enable 'Authenticated SMTP' for this mailbox in the "
                "Microsoft 365 admin centre, otherwise sign-in is rejected.",
    },
    "Zoho Mail": {
        "smtp_host": "smtp.zoho.com", "smtp_port": 465, "security": "ssl",
        "imap_host": "imap.zoho.com", "imap_port": 993,
        "note": "Zoho requires an app-specific password when two-factor authentication is enabled.",
    },
    "Titan Email": {
        "smtp_host": "smtp.titan.email", "smtp_port": 465, "security": "ssl",
        "imap_host": "imap.titan.email", "imap_port": 993,
    },
    "GoDaddy": {
        "smtp_host": "smtpout.secureserver.net", "smtp_port": 465, "security": "ssl",
        "imap_host": "imap.secureserver.net", "imap_port": 993,
    },
    "Hostinger": {
        "smtp_host": "smtp.hostinger.com", "smtp_port": 465, "security": "ssl",
        "imap_host": "imap.hostinger.com", "imap_port": 993,
    },
    "cPanel / shared hosting": {
        "smtp_host": "mail.yourdomain.com", "smtp_port": 465, "security": "ssl",
        "imap_host": "mail.yourdomain.com", "imap_port": 993,
        "note": "Replace 'yourdomain.com' with your own domain. Your host may also use "
                "a server name such as server123.web-hosting.com.",
    },
}


class AccountPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self._build()
        self.load()

    def _build(self) -> None:
        scroll = theme.scroll_frame(self)
        scroll.pack(fill="both", expand=True, padx=theme.PAD_LARGE, pady=theme.PAD)

        theme.heading(scroll, "Email account").pack(anchor="w", pady=(0, 4))
        theme.label(scroll, "Your password is encrypted on this computer using "
                            f"{credentials.backend_name()} and never leaves it.",
                    muted=True, wrap=True).pack(anchor="w", pady=(0, 16))

        # --- identity -------------------------------------------------------
        identity = Section(scroll, "Who the emails come from")
        identity.pack(fill="x", pady=(0, 14))

        row = FormRow(identity.body, "Your name",
                      "Shown as the sender name, e.g. Abdullah Kamran")
        row.pack(fill="x", pady=(0, 12))
        self.name_entry = theme.entry(row.input_area, "Abdullah Kamran")
        self.name_entry.pack(fill="x")

        row = FormRow(identity.body, "Email address",
                      "The address people see and reply to. Use your company domain, not a free "
                      "Gmail or Hotmail address.")
        row.pack(fill="x", pady=(0, 12))
        self.email_entry = theme.entry(row.input_area, "you@yourcompany.com")
        self.email_entry.pack(fill="x")

        row = FormRow(identity.body, "Reply-To address (optional)",
                      "Leave blank to use the address above. It must be on the same domain.")
        row.pack(fill="x")
        self.reply_entry = theme.entry(row.input_area, "")
        self.reply_entry.pack(fill="x")

        # --- smtp -----------------------------------------------------------
        smtp = Section(scroll, "Outgoing mail (SMTP)",
                       "These settings come from your email provider. Pick a preset to fill them in.")
        smtp.pack(fill="x", pady=(0, 14))

        row = FormRow(smtp.body, "Provider preset")
        row.pack(fill="x", pady=(0, 12))
        self.preset_menu = theme.option_menu(row.input_area, list(PRESETS.keys()),
                                             command=self._apply_preset)
        self.preset_menu.pack(fill="x")

        self.preset_note = theme.label(smtp.body, "", muted=True)
        self.preset_note.pack(anchor="w", pady=(0, 10))

        grid = ctk.CTkFrame(smtp.body, fg_color="transparent")
        grid.pack(fill="x", pady=(0, 12))
        grid.grid_columnconfigure(0, weight=3)
        grid.grid_columnconfigure(1, weight=1)
        grid.grid_columnconfigure(2, weight=2)

        host_row = FormRow(grid, "SMTP server")
        host_row.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.smtp_host_entry = theme.entry(host_row.input_area, "smtp.yourprovider.com")
        self.smtp_host_entry.pack(fill="x")

        port_row = FormRow(grid, "Port")
        port_row.grid(row=0, column=1, sticky="ew", padx=(0, 10))
        self.smtp_port_entry = theme.entry(port_row.input_area, "587")
        self.smtp_port_entry.pack(fill="x")

        security_row = FormRow(grid, "Security")
        security_row.grid(row=0, column=2, sticky="ew")
        self.security_menu = theme.option_menu(
            security_row.input_area,
            ["Automatic", "STARTTLS (587)", "SSL/TLS (465)", "None (testing only)"])
        self.security_menu.pack(fill="x")

        row = FormRow(smtp.body, "Username",
                      "Usually your full email address.")
        row.pack(fill="x", pady=(0, 12))
        self.username_entry = theme.entry(row.input_area, "you@yourcompany.com")
        self.username_entry.pack(fill="x")

        row = FormRow(smtp.body, "Password",
                      "If your provider uses two-factor authentication, this must be an "
                      "app-specific password, not your normal login password.")
        row.pack(fill="x", pady=(0, 12))
        password_wrap = ctk.CTkFrame(row.input_area, fg_color="transparent")
        password_wrap.pack(fill="x")
        self.password_entry = theme.entry(password_wrap, "")
        self.password_entry.configure(show="•")
        self.password_entry.pack(side="left", fill="x", expand=True)
        self.show_password = theme.secondary_button(password_wrap, "Show", self._toggle_password,
                                                    width=70)
        self.show_password.pack(side="left", padx=(8, 0))

        buttons = ctk.CTkFrame(smtp.body, fg_color="transparent")
        buttons.pack(fill="x", pady=(4, 0))
        self.test_button = theme.primary_button(buttons, "Test connection", self._test_smtp,
                                                width=160)
        self.test_button.pack(side="left")
        theme.secondary_button(buttons, "Save", self.save, width=110).pack(side="left", padx=8)

        self.smtp_result = theme.label(smtp.body, "", muted=True)
        self.smtp_result.pack(anchor="w", pady=(10, 0))

        # --- imap -----------------------------------------------------------
        imap = Section(
            scroll, "Incoming mail (IMAP) — optional but strongly recommended",
            "Lets the app read your inbox to detect bounces, unsubscribe replies and genuine "
            "replies. Bounced addresses are removed automatically, which is the single most "
            "effective way to protect your sending reputation.")
        imap.pack(fill="x", pady=(0, 14))

        grid = ctk.CTkFrame(imap.body, fg_color="transparent")
        grid.pack(fill="x", pady=(0, 12))
        grid.grid_columnconfigure(0, weight=3)
        grid.grid_columnconfigure(1, weight=1)
        grid.grid_columnconfigure(2, weight=2)

        host_row = FormRow(grid, "IMAP server")
        host_row.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.imap_host_entry = theme.entry(host_row.input_area, "imap.yourprovider.com")
        self.imap_host_entry.pack(fill="x")

        port_row = FormRow(grid, "Port")
        port_row.grid(row=0, column=1, sticky="ew", padx=(0, 10))
        self.imap_port_entry = theme.entry(port_row.input_area, "993")
        self.imap_port_entry.pack(fill="x")

        folder_row = FormRow(grid, "Folder")
        folder_row.grid(row=0, column=2, sticky="ew")
        self.imap_folder_entry = theme.entry(folder_row.input_area, "INBOX")
        self.imap_folder_entry.pack(fill="x")

        row = FormRow(imap.body, "IMAP password",
                      "Usually the same as above. Leave blank to reuse the SMTP password.")
        row.pack(fill="x", pady=(0, 12))
        self.imap_password_entry = theme.entry(row.input_area, "")
        self.imap_password_entry.configure(show="•")
        self.imap_password_entry.pack(fill="x")

        imap_buttons = ctk.CTkFrame(imap.body, fg_color="transparent")
        imap_buttons.pack(fill="x")
        self.imap_test_button = theme.primary_button(imap_buttons, "Test IMAP", self._test_imap,
                                                     width=160)
        self.imap_test_button.pack(side="left")

        self.imap_result = theme.label(imap.body, "", muted=True)
        self.imap_result.pack(anchor="w", pady=(10, 0))

        # --- provider limit -------------------------------------------------
        limits = Section(scroll, "Provider sending limit",
                         "Every provider caps how many recipients you may contact per day. The "
                         "app never exceeds this, whatever the warm-up schedule says.")
        limits.pack(fill="x", pady=(0, 20))

        from app.core.warmup import PROVIDER_LIMITS
        row = FormRow(limits.body, "Your plan")
        row.pack(fill="x")
        self.limit_menu = theme.option_menu(row.input_area, list(PROVIDER_LIMITS.keys()),
                                            command=self._change_limit)
        self.limit_menu.pack(fill="x")
        self.limit_note = theme.label(limits.body, "", muted=True)
        self.limit_note.pack(anchor="w", pady=(8, 0))

    # -- helpers -------------------------------------------------------------
    def _toggle_password(self) -> None:
        hidden = self.password_entry.cget("show") == "•"
        self.password_entry.configure(show="" if hidden else "•")
        self.show_password.configure(text="Hide" if hidden else "Show")

    def _apply_preset(self, name: str) -> None:
        preset = PRESETS.get(name, {})
        if not preset:
            self.preset_note.configure(text="")
            return
        self.smtp_host_entry.delete(0, "end")
        self.smtp_host_entry.insert(0, preset["smtp_host"])
        self.smtp_port_entry.delete(0, "end")
        self.smtp_port_entry.insert(0, str(preset["smtp_port"]))
        self.imap_host_entry.delete(0, "end")
        self.imap_host_entry.insert(0, preset["imap_host"])
        self.imap_port_entry.delete(0, "end")
        self.imap_port_entry.insert(0, str(preset["imap_port"]))

        security = preset.get("security", "starttls")
        self.security_menu.set("SSL/TLS (465)" if security == "ssl" else "STARTTLS (587)")
        self.preset_note.configure(text=preset.get("note", ""))

    def _change_limit(self, name: str) -> None:
        from app.core.warmup import PROVIDER_LIMITS

        limit = PROVIDER_LIMITS.get(name, 500)
        db.set_setting("provider_limit_name", name)
        db.set_setting("provider_limit", limit)
        self.limit_note.configure(text=f"Daily ceiling: {limit:,} recipients per day.")

    def _security_value(self) -> str:
        return {
            "Automatic": "auto",
            "STARTTLS (587)": "starttls",
            "SSL/TLS (465)": "ssl",
            "None (testing only)": "none",
        }.get(self.security_menu.get(), "auto")

    def _smtp_settings(self) -> sender.SmtpSettings:
        try:
            port = int(self.smtp_port_entry.get().strip() or 587)
        except ValueError:
            port = 587
        return sender.SmtpSettings(
            host=self.smtp_host_entry.get().strip(),
            port=port,
            # Same fallback the send worker uses, so a passing test guarantees a
            # working send — otherwise a blank username would test one way and send another.
            username=self.username_entry.get().strip() or self.email_entry.get().strip(),
            password=self.password_entry.get(),
            security=self._security_value(),
        )

    def _imap_settings(self) -> imap_sync.ImapSettings:
        try:
            port = int(self.imap_port_entry.get().strip() or 993)
        except ValueError:
            port = 993
        password = self.imap_password_entry.get() or self.password_entry.get()
        return imap_sync.ImapSettings(
            host=self.imap_host_entry.get().strip(),
            port=port,
            username=self.username_entry.get().strip() or self.email_entry.get().strip(),
            password=password,
            use_ssl=port == 993,
            folder=self.imap_folder_entry.get().strip() or "INBOX",
        )

    # -- actions -------------------------------------------------------------
    def _test_smtp(self) -> None:
        settings = self._smtp_settings()
        if not settings.host:
            self.smtp_result.configure(text="Enter the SMTP server first.", text_color=theme.ERROR)
            return

        self.test_button.configure(state="disabled", text="Testing…")
        self.smtp_result.configure(text="Connecting…", text_color=theme.FG_MUTED)

        def work() -> None:
            ok, message = sender.test_connection(settings)
            self.after(0, lambda: self._show_smtp_result(ok, message))

        threading.Thread(target=work, daemon=True).start()

    def _show_smtp_result(self, ok: bool, message: str) -> None:
        self.test_button.configure(state="normal", text="Test connection")
        self.smtp_result.configure(text=("✓ " if ok else "✕ ") + message,
                                   text_color=theme.SUCCESS if ok else theme.ERROR)
        if ok:
            self.save(silent=True)
            toast(self, "Connection successful — settings saved", "success")

    def _test_imap(self) -> None:
        settings = self._imap_settings()
        if not settings.host:
            self.imap_result.configure(text="Enter the IMAP server first.", text_color=theme.ERROR)
            return

        self.imap_test_button.configure(state="disabled", text="Testing…")
        self.imap_result.configure(text="Connecting…", text_color=theme.FG_MUTED)

        def work() -> None:
            ok, message = imap_sync.test_connection(settings)
            self.after(0, lambda: self._show_imap_result(ok, message))

        threading.Thread(target=work, daemon=True).start()

    def _show_imap_result(self, ok: bool, message: str) -> None:
        self.imap_test_button.configure(state="normal", text="Test IMAP")
        self.imap_result.configure(text=("✓ " if ok else "✕ ") + message,
                                   text_color=theme.SUCCESS if ok else theme.ERROR)
        if ok:
            self.save(silent=True)

    def save(self, silent: bool = False) -> None:
        db.set_setting("sender_name", self.name_entry.get().strip())
        db.set_setting("sender_email", self.email_entry.get().strip())
        db.set_setting("reply_to", self.reply_entry.get().strip())
        db.set_setting("smtp_host", self.smtp_host_entry.get().strip())
        db.set_setting("smtp_port", self.smtp_port_entry.get().strip())
        db.set_setting("smtp_security", self._security_value())
        db.set_setting("smtp_username", self.username_entry.get().strip())
        db.set_setting("imap_host", self.imap_host_entry.get().strip())
        db.set_setting("imap_port", self.imap_port_entry.get().strip())
        db.set_setting("imap_folder", self.imap_folder_entry.get().strip() or "INBOX")
        db.set_setting("smtp_preset", self.preset_menu.get())

        if self.password_entry.get():
            credentials.save_secret(credentials.SMTP_PASSWORD, self.password_entry.get())
        if self.imap_password_entry.get():
            credentials.save_secret(credentials.IMAP_PASSWORD, self.imap_password_entry.get())

        self.app._refresh_status()
        if not silent:
            toast(self, "Account settings saved", "success")

    def load(self) -> None:
        def fill(entry, value):
            entry.delete(0, "end")
            if value:
                entry.insert(0, str(value))

        fill(self.name_entry, db.get_setting("sender_name", ""))
        fill(self.email_entry, db.get_setting("sender_email", ""))
        fill(self.reply_entry, db.get_setting("reply_to", ""))
        fill(self.smtp_host_entry, db.get_setting("smtp_host", ""))
        fill(self.smtp_port_entry, db.get_setting("smtp_port", "587"))
        fill(self.username_entry, db.get_setting("smtp_username", ""))
        fill(self.imap_host_entry, db.get_setting("imap_host", ""))
        fill(self.imap_port_entry, db.get_setting("imap_port", "993"))
        fill(self.imap_folder_entry, db.get_setting("imap_folder", "INBOX"))

        preset = db.get_setting("smtp_preset", "Custom / other")
        if preset in PRESETS:
            self.preset_menu.set(preset)
            self.preset_note.configure(text=PRESETS[preset].get("note", ""))

        security = db.get_setting("smtp_security", "auto")
        self.security_menu.set({
            "auto": "Automatic", "starttls": "STARTTLS (587)",
            "ssl": "SSL/TLS (465)", "none": "None (testing only)",
        }.get(security, "Automatic"))

        password = credentials.load_secret(credentials.SMTP_PASSWORD)
        if password:
            self.password_entry.delete(0, "end")
            self.password_entry.insert(0, password)

        imap_password = credentials.load_secret(credentials.IMAP_PASSWORD)
        if imap_password:
            self.imap_password_entry.delete(0, "end")
            self.imap_password_entry.insert(0, imap_password)

        limit_name = db.get_setting("provider_limit_name", "Other / shared hosting")
        self.limit_menu.set(limit_name)
        self._change_limit(limit_name)

    def on_show(self) -> None:
        self.load()
