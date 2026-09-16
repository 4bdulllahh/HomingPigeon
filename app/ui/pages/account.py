"""Email account setup: SMTP for sending, IMAP for bounce and reply detection."""
from __future__ import annotations

from PyQt6.QtWidgets import QGridLayout, QWidget

from app.core import credentials, db, imap_sync, sender
from app.core.warmup import PROVIDER_LIMITS
from app.ui.pages.base import Page
from app.ui.widgets.common import (FormRow, Section, muted, primary_button, row, secondary_button,
                                   set_tone)
from app.ui.widgets.inputs import combo, line_edit, password_edit
from app.workers import jobs
from app.workers.base import Task

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

SECURITY_LABELS = {
    "auto": "Automatic",
    "starttls": "STARTTLS (587)",
    "ssl": "SSL/TLS (465)",
    "none": "None (testing only)",
}
SECURITY_VALUES = {label: key for key, label in SECURITY_LABELS.items()}


class AccountPage(Page):
    def __init__(self, window):
        super().__init__(window)
        self._build()
        self.load()

    def _build(self) -> None:
        self.add_header(
            "Email account",
            f"Your password is encrypted on this computer using {credentials.backend_name()} "
            f"and never leaves it.")
        area = self.scroll_body()

        # --- identity -------------------------------------------------------
        identity = Section("Who the emails come from")
        self.name_box = self._field(identity, "Your name",
                                    "The name people see in their inbox, e.g. Sarah Miller",
                                    "Your full name")
        self.email_box = self._field(
            identity, "Email address",
            "The address people see and reply to. Use your company domain, not a free Gmail or "
            "Hotmail address.", "you@yourcompany.com")
        self.reply_box = self._field(
            identity, "Reply-To address (optional)",
            "Leave blank to use the address above. It must be on the same domain.", "")
        area.add(identity)

        # --- smtp -----------------------------------------------------------
        smtp = Section("Outgoing mail (SMTP)",
                       "These settings come from your email provider. Pick a preset to fill them in.")
        preset_row = FormRow("Provider preset")
        self.preset_picker = combo(list(PRESETS.keys()), on_change=self._apply_preset)
        preset_row.add(self.preset_picker)
        smtp.add(preset_row)
        self.preset_note = muted("")
        smtp.add(self.preset_note)

        grid_holder = QWidget()
        grid_holder.setProperty("role", "plain")
        grid = QGridLayout(grid_holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 2)

        host_row = FormRow("SMTP server")
        self.smtp_host_box = line_edit("smtp.yourprovider.com")
        host_row.add(self.smtp_host_box)
        grid.addWidget(host_row, 0, 0)

        port_row = FormRow("Port")
        self.smtp_port_box = line_edit("587")
        port_row.add(self.smtp_port_box)
        grid.addWidget(port_row, 0, 1)

        security_row = FormRow("Security")
        self.security_picker = combo(list(SECURITY_LABELS.values()))
        security_row.add(self.security_picker)
        grid.addWidget(security_row, 0, 2)
        smtp.add(grid_holder)

        self.username_box = self._field(smtp, "Username", "Usually your full email address.",
                                        "you@yourcompany.com")

        password_row = FormRow(
            "Password",
            "If your provider uses two-factor authentication, this must be an app-specific "
            "password, not your normal login password.")
        self.password_box = password_edit("")
        self.show_password = secondary_button("Show", self._toggle_password, 80)
        password_row.add(row(self.password_box, self.show_password, stretch=0))
        smtp.add(password_row)

        self.test_button = primary_button("Test connection", self._test_smtp, 160)
        smtp.add(row(self.test_button, secondary_button("Save", self.save, 110), None))
        self.smtp_result = muted("")
        smtp.add(self.smtp_result)
        area.add(smtp)

        # --- imap -----------------------------------------------------------
        imap = Section(
            "Incoming mail (IMAP) — optional but strongly recommended",
            "Lets the app read your inbox to detect bounces, unsubscribe replies and genuine "
            "replies. Bounced addresses are removed automatically, which is the single most "
            "effective way to protect your sending reputation.")

        imap_holder = QWidget()
        imap_holder.setProperty("role", "plain")
        imap_grid = QGridLayout(imap_holder)
        imap_grid.setContentsMargins(0, 0, 0, 0)
        imap_grid.setSpacing(10)
        imap_grid.setColumnStretch(0, 3)
        imap_grid.setColumnStretch(1, 1)
        imap_grid.setColumnStretch(2, 2)

        imap_host_row = FormRow("IMAP server")
        self.imap_host_box = line_edit("imap.yourprovider.com")
        imap_host_row.add(self.imap_host_box)
        imap_grid.addWidget(imap_host_row, 0, 0)

        imap_port_row = FormRow("Port")
        self.imap_port_box = line_edit("993")
        imap_port_row.add(self.imap_port_box)
        imap_grid.addWidget(imap_port_row, 0, 1)

        folder_row = FormRow("Folder")
        self.imap_folder_box = line_edit("INBOX")
        folder_row.add(self.imap_folder_box)
        imap_grid.addWidget(folder_row, 0, 2)
        imap.add(imap_holder)

        imap_password_row = FormRow(
            "IMAP password", "Usually the same as above. Leave blank to reuse the SMTP password.")
        self.imap_password_box = password_edit("")
        imap_password_row.add(self.imap_password_box)
        imap.add(imap_password_row)

        self.imap_test_button = primary_button("Test IMAP", self._test_imap, 160)
        imap.add(row(self.imap_test_button, None))
        self.imap_result = muted("")
        imap.add(self.imap_result)
        area.add(imap)

        # --- provider limit -------------------------------------------------
        limits = Section("Provider sending limit",
                         "Every provider caps how many recipients you may contact per day. The "
                         "app never exceeds this, whatever the warm-up schedule says.")
        limit_row = FormRow("Your plan")
        self.limit_picker = combo(list(PROVIDER_LIMITS.keys()), on_change=self._change_limit)
        limit_row.add(self.limit_picker)
        limits.add(limit_row)
        self.limit_note = muted("")
        limits.add(self.limit_note)
        area.add(limits)
        area.add_stretch()

    def _field(self, section: Section, label: str, note: str, placeholder: str):
        form = FormRow(label, note)
        box = line_edit(placeholder)
        form.add(box)
        section.add(form)
        return box

    # --- helpers ------------------------------------------------------------
    def _toggle_password(self) -> None:
        from PyQt6.QtWidgets import QLineEdit

        hidden = self.password_box.echoMode() == QLineEdit.EchoMode.Password
        self.password_box.setEchoMode(
            QLineEdit.EchoMode.Normal if hidden else QLineEdit.EchoMode.Password)
        self.show_password.setText("Hide" if hidden else "Show")

    def _apply_preset(self, name: str) -> None:
        preset = PRESETS.get(name, {})
        if not preset:
            self.preset_note.setText("")
            return
        self.smtp_host_box.setText(preset["smtp_host"])
        self.smtp_port_box.setText(str(preset["smtp_port"]))
        self.imap_host_box.setText(preset["imap_host"])
        self.imap_port_box.setText(str(preset["imap_port"]))
        security = preset.get("security", "starttls")
        self.security_picker.setCurrentText(SECURITY_LABELS.get(security, "Automatic"))
        self.preset_note.setText(preset.get("note", ""))

    def _change_limit(self, name: str) -> None:
        limit = PROVIDER_LIMITS.get(name, 500)
        db.set_setting("provider_limit_name", name)
        db.set_setting("provider_limit", limit)
        self.limit_note.setText(f"Daily ceiling: {limit:,} recipients per day.")

    def _security_value(self) -> str:
        return SECURITY_VALUES.get(self.security_picker.currentText(), "auto")

    def _smtp_settings(self) -> sender.SmtpSettings:
        try:
            port = int(self.smtp_port_box.text().strip() or 587)
        except ValueError:
            port = 587
        return sender.SmtpSettings(
            host=self.smtp_host_box.text().strip(),
            port=port,
            # Same fallback the send worker uses, so a passing test guarantees a
            # working send — otherwise a blank username would test one way and send another.
            username=self.username_box.text().strip() or self.email_box.text().strip(),
            password=self.password_box.text(),
            security=self._security_value(),
        )

    def _imap_settings(self) -> imap_sync.ImapSettings:
        try:
            port = int(self.imap_port_box.text().strip() or 993)
        except ValueError:
            port = 993
        return imap_sync.ImapSettings(
            host=self.imap_host_box.text().strip(),
            port=port,
            username=self.username_box.text().strip() or self.email_box.text().strip(),
            password=self.imap_password_box.text() or self.password_box.text(),
            use_ssl=port == 993,
            folder=self.imap_folder_box.text().strip() or "INBOX",
        )

    # --- actions ------------------------------------------------------------
    def _test_smtp(self) -> None:
        settings = self._smtp_settings()
        if not settings.host:
            self.smtp_result.setText("Enter the SMTP server first.")
            set_tone(self.smtp_result, "error")
            return

        self.test_button.setEnabled(False)
        self.test_button.setText("Testing…")
        self.smtp_result.setText("Connecting…")
        set_tone(self.smtp_result, "muted")

        Task(jobs.test_smtp, settings).start(
            on_result=lambda outcome: self._show_smtp_result(*outcome),
            on_error=lambda message: self._show_smtp_result(False, message))

    def _show_smtp_result(self, ok: bool, message: str) -> None:
        self.test_button.setEnabled(True)
        self.test_button.setText("Test connection")
        self.smtp_result.setText(("✓ " if ok else "✕ ") + message)
        set_tone(self.smtp_result, "success" if ok else "error")
        if ok:
            self.save(silent=True)
            self.notify("Connection successful — settings saved", "success")

    def _test_imap(self) -> None:
        settings = self._imap_settings()
        if not settings.host:
            self.imap_result.setText("Enter the IMAP server first.")
            set_tone(self.imap_result, "error")
            return

        self.imap_test_button.setEnabled(False)
        self.imap_test_button.setText("Testing…")
        self.imap_result.setText("Connecting…")
        set_tone(self.imap_result, "muted")

        Task(jobs.test_imap, settings).start(
            on_result=lambda outcome: self._show_imap_result(*outcome),
            on_error=lambda message: self._show_imap_result(False, message))

    def _show_imap_result(self, ok: bool, message: str) -> None:
        self.imap_test_button.setEnabled(True)
        self.imap_test_button.setText("Test IMAP")
        self.imap_result.setText(("✓ " if ok else "✕ ") + message)
        set_tone(self.imap_result, "success" if ok else "error")
        if ok:
            self.save(silent=True)

    # --- persistence --------------------------------------------------------
    def save(self, silent: bool = False) -> None:
        db.set_setting("sender_name", self.name_box.text().strip())
        db.set_setting("sender_email", self.email_box.text().strip())
        db.set_setting("reply_to", self.reply_box.text().strip())
        db.set_setting("smtp_host", self.smtp_host_box.text().strip())
        db.set_setting("smtp_port", self.smtp_port_box.text().strip())
        db.set_setting("smtp_security", self._security_value())
        db.set_setting("smtp_username", self.username_box.text().strip())
        db.set_setting("imap_host", self.imap_host_box.text().strip())
        db.set_setting("imap_port", self.imap_port_box.text().strip())
        db.set_setting("imap_folder", self.imap_folder_box.text().strip() or "INBOX")
        db.set_setting("smtp_preset", self.preset_picker.currentText())

        if self.password_box.text():
            credentials.save_secret(credentials.SMTP_PASSWORD, self.password_box.text())
        if self.imap_password_box.text():
            credentials.save_secret(credentials.IMAP_PASSWORD, self.imap_password_box.text())

        self.window_.refresh_status()
        if not silent:
            self.notify("Account settings saved", "success")

    def load(self) -> None:
        self.name_box.setText(str(db.get_setting("sender_name", "") or ""))
        self.email_box.setText(str(db.get_setting("sender_email", "") or ""))
        self.reply_box.setText(str(db.get_setting("reply_to", "") or ""))
        self.smtp_host_box.setText(str(db.get_setting("smtp_host", "") or ""))
        self.smtp_port_box.setText(str(db.get_setting("smtp_port", "587") or "587"))
        self.username_box.setText(str(db.get_setting("smtp_username", "") or ""))
        self.imap_host_box.setText(str(db.get_setting("imap_host", "") or ""))
        self.imap_port_box.setText(str(db.get_setting("imap_port", "993") or "993"))
        self.imap_folder_box.setText(str(db.get_setting("imap_folder", "INBOX") or "INBOX"))

        preset = db.get_setting("smtp_preset", "Custom / other")
        if preset in PRESETS:
            blocked = self.preset_picker.blockSignals(True)
            self.preset_picker.setCurrentText(preset)
            self.preset_picker.blockSignals(blocked)
            self.preset_note.setText(PRESETS[preset].get("note", ""))

        security = db.get_setting("smtp_security", "auto")
        self.security_picker.setCurrentText(SECURITY_LABELS.get(security, "Automatic"))

        password = credentials.load_secret(credentials.SMTP_PASSWORD)
        if password:
            self.password_box.setText(password)
        imap_password = credentials.load_secret(credentials.IMAP_PASSWORD)
        if imap_password:
            self.imap_password_box.setText(imap_password)

        limit_name = db.get_setting("provider_limit_name", "Other / shared hosting")
        if limit_name in PROVIDER_LIMITS:
            self.limit_picker.setCurrentText(limit_name)
        self._change_limit(self.limit_picker.currentText())

    def on_show(self) -> None:
        self.load()
