"""Email account setup: SMTP for sending, IMAP for bounce and reply detection.

Sending and the inbox can be two different accounts: someone who sends through
Brevo usually reads replies in Gmail. Either can sign in with Google or
Microsoft instead of a password (``app.core.oauth``), and a sending service's
API key turns on delivery reports (``app.core.delivery``).
"""
from __future__ import annotations

from PyQt6.QtWidgets import QGridLayout, QVBoxLayout, QWidget

from app.core import credentials, db, delivery, imap_sync, oauth, sender
from app.core.warmup import PROVIDER_LIMITS
from app.i18n import t
from app.ui.pages.base import Page
from app.ui.widgets.common import (FormRow, Section, muted, primary_button, row, secondary_button,
                                   set_tone, wrap_row)
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
    "Outlook.com / Hotmail": {
        "smtp_host": "smtp-mail.outlook.com", "smtp_port": 587, "security": "starttls",
        "imap_host": "outlook.office365.com", "imap_port": 993,
        "note": "Microsoft no longer accepts passwords from email apps for Outlook.com and "
                "Hotmail. Use the Sign in with Microsoft button.",
    },
    "Yahoo Mail": {
        "smtp_host": "smtp.mail.yahoo.com", "smtp_port": 465, "security": "ssl",
        "imap_host": "imap.mail.yahoo.com", "imap_port": 993,
        "note": "Yahoo needs an app password: Yahoo Account Security → Generate app password. "
                "Your normal password will not work.",
    },
    "iCloud Mail": {
        "smtp_host": "smtp.mail.me.com", "smtp_port": 587, "security": "starttls",
        "imap_host": "imap.mail.me.com", "imap_port": 993,
        "note": "iCloud needs an app-specific password: appleid.apple.com → Sign-In and "
                "Security → App-Specific Passwords.",
    },
    "Brevo": {
        "smtp_host": "smtp-relay.brevo.com", "smtp_port": 587, "security": "starttls",
        "stats": "brevo",
        "note": "Username: the SMTP login in Brevo → SMTP & API (it ends in @smtp-brevo.com). "
                "Password: an SMTP key from the same page. Brevo only sends, so put the inbox "
                "your replies arrive in (for example Gmail) under Incoming mail.",
    },
    "SendGrid": {
        "smtp_host": "smtp.sendgrid.net", "smtp_port": 587, "security": "starttls",
        "stats": "sendgrid",
        "note": "Username: the word apikey. Password: a SendGrid API key. SendGrid only sends, "
                "so put the inbox your replies arrive in under Incoming mail.",
    },
    "Mailgun": {
        "smtp_host": "smtp.mailgun.org", "smtp_port": 587, "security": "starttls",
        "stats": "mailgun",
        "note": "Username and password: your Mailgun SMTP login (postmaster@your-domain), from "
                "Mailgun → Sending → Domain settings. EU accounts use smtp.eu.mailgun.org. "
                "Mailgun only sends, so put the inbox your replies arrive in under Incoming mail.",
    },
    "Postmark": {
        "smtp_host": "smtp.postmarkapp.com", "smtp_port": 587, "security": "starttls",
        "stats": "postmark",
        "note": "Username and password: both are your Postmark Server API token. Postmark only "
                "sends, so put the inbox your replies arrive in under Incoming mail.",
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

NOT_CONNECTED = "Not connected"
SERVICE_NOTES = {
    "": "Pick the service your emails go out through.",
    "brevo": "In Brevo: your name (top right) → SMTP & API → API keys → Generate a new API "
             "key. This is a different key from the SMTP key.",
    "sendgrid": "In SendGrid: Settings → API Keys → Create API Key. Read access is enough.",
    "mailgun": "In Mailgun: your name (top right) → API Security → Add new key. Your Mailgun "
               "SMTP login must be the username above.",
    "postmark": "In Postmark: open your server → API Tokens → Server API token. Switch on open "
                "tracking in Postmark to see opens.",
}


class SignInRow(QWidget):
    """Sign in with Google or Microsoft for one slot, or who is signed in.

    Hidden entirely when this copy of the app has no sign-in set up and nobody
    is signed in, so the page looks exactly as it did before.
    """

    def __init__(self, page: "AccountPage", slot: str):
        super().__init__()
        self.setProperty("role", "plain")
        self.slot = slot
        self.cancelled = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.status = muted("")
        layout.addWidget(self.status)
        self.buttons = [
            secondary_button(t("Sign in with {label}", label=provider.label),
                             lambda _checked=False, key=provider.key: page.sign_in(slot, key), 230)
            for provider in oauth.available()]
        self.cancel = secondary_button("Cancel", self._cancel, 110)
        self.use_password = secondary_button("Use a password instead",
                                             lambda: page.sign_out(slot), 220)
        # No refresh() here: showing a widget before it has a parent opens it as its own
        # window. The page's load() refreshes it once it is in place.
        layout.addWidget(wrap_row(*self.buttons, self.cancel, self.use_password))

    def _cancel(self) -> None:
        self.cancelled = True

    def waiting(self) -> None:
        self.cancelled = False
        for button in self.buttons:
            button.setEnabled(False)
        self.cancel.setVisible(True)
        self.status.setText(t("Finish signing in in your browser. The app waits for up to "
                              "5 minutes."))
        set_tone(self.status, "muted")

    def refresh(self, error: str = "") -> None:
        account = oauth.account(self.slot)
        self.setVisible(bool(account or self.buttons))
        self.cancel.setVisible(False)
        self.use_password.setVisible(account is not None)
        for button in self.buttons:
            button.setEnabled(True)
            button.setVisible(account is None)
        if error:
            self.status.setText("✕ " + t(error))
            set_tone(self.status, "error")
        elif account:
            label = oauth.PROVIDERS[account["provider"]].label
            self.status.setText("✓ " + t("Signed in with {label} as {email}. No password needed.",
                                         label=label, email=account["email"]))
            set_tone(self.status, "success")
        else:
            self.status.setText(t("Gmail, Outlook or Microsoft 365? Sign in instead of typing "
                                  "a password."))
            set_tone(self.status, "muted")


class AccountPage(Page):
    def __init__(self, window):
        super().__init__(window)
        self._build()
        self.load()

    def _build(self) -> None:
        self.add_header(
            "My email account",
            t("Your password is encrypted on this computer using {backend_name} and never "
              "leaves it.", backend_name=credentials.backend_name()))
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
        self.smtp_sign_in = SignInRow(self, "smtp")
        smtp.add(self.smtp_sign_in)

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

        self.username_box, self.username_row = self._field(
            smtp, "Username", "Usually your full email address.", "you@yourcompany.com",
            with_row=True)

        password_row = FormRow(
            "Password",
            "If your provider uses two-factor authentication, this must be an app-specific "
            "password, not your normal login password.")
        self.password_box = password_edit("")
        self.show_password = secondary_button("Show", self._toggle_password, 80)
        password_row.add(row(self.password_box, self.show_password, stretch=0))
        smtp.add(password_row)
        self.password_row = password_row

        self.test_button = primary_button("Test connection", self._test_smtp, 160)
        smtp.add(row(self.test_button, secondary_button("Save", self.save, 110), None))
        self.smtp_result = muted("")
        smtp.add(self.smtp_result)
        area.add(smtp)

        # --- imap -----------------------------------------------------------
        imap = Section(
            "Incoming mail (IMAP): optional, but strongly recommended",
            "Lets the app read your inbox to detect bounces, unsubscribe replies and genuine "
            "replies. Bounced addresses are removed automatically, which is the single most "
            "effective way to protect your sending reputation.")
        self.imap_sign_in = SignInRow(self, "imap")
        imap.add(self.imap_sign_in)

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

        self.imap_user_box, self.imap_user_row = self._field(
            imap, "Inbox email address",
            "The mailbox your replies arrive in, if it is not the account that sends. For "
            "example your Gmail address when you send through Brevo. Leave blank to use the "
            "sending username.", "", with_row=True)

        imap_password_row = FormRow(
            "IMAP password",
            "The password for the inbox above. For Gmail, an app password. Leave blank if it "
            "is the same as the sending password.")
        self.imap_password_box = password_edit("")
        imap_password_row.add(self.imap_password_box)
        imap.add(imap_password_row)
        self.imap_password_row = imap_password_row

        self.imap_test_button = primary_button("Test IMAP", self._test_imap, 160)
        imap.add(row(self.imap_test_button, None))
        self.imap_result = muted("")
        imap.add(self.imap_result)
        area.add(imap)

        # --- delivery reports -----------------------------------------------
        reports = Section(
            "Delivery reports: optional",
            "If your emails go out through Brevo, SendGrid, Mailgun or Postmark, the app can ask "
            "it which emails were delivered, opened, clicked or bounced, and show it under Sent "
            "emails. Bounces, spam complaints and unsubscribes are then taken off your list "
            "automatically.")
        service_row = FormRow("Sending service")
        self.service_picker = combo([NOT_CONNECTED, *delivery.SERVICES.values()],
                                    on_change=lambda _name: self._service_changed())
        service_row.add(self.service_picker)
        reports.add(service_row)
        key_row = FormRow("API key")
        self.api_key_box = password_edit("")
        key_row.add(self.api_key_box)
        self.service_note = muted("")
        key_row.add(self.service_note)
        reports.add(key_row)
        self.reports_button = primary_button("Test and fetch reports", self._test_reports, 210)
        reports.add(row(self.reports_button, None))
        self.reports_result = muted("")
        reports.add(self.reports_result)
        area.add(reports)

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

    def _field(self, section: Section, label: str, note: str, placeholder: str,
               with_row: bool = False):
        form = FormRow(label, note)
        box = line_edit(placeholder)
        form.add(box)
        section.add(form)
        return (box, form) if with_row else box

    # --- helpers ------------------------------------------------------------
    def _toggle_password(self) -> None:
        from PyQt6.QtWidgets import QLineEdit

        hidden = self.password_box.echoMode() == QLineEdit.EchoMode.Password
        self.password_box.setEchoMode(
            QLineEdit.EchoMode.Normal if hidden else QLineEdit.EchoMode.Password)
        self.show_password.setText(t("Hide" if hidden else "Show"))

    def _apply_preset(self, name: str) -> None:
        preset = PRESETS.get(name, {})
        if not preset:
            self.preset_note.setText("")
            return
        self.smtp_host_box.setText(preset["smtp_host"])
        self.smtp_port_box.setText(str(preset["smtp_port"]))
        # A sending service has no inbox, so whatever inbox is set up stays
        if preset.get("imap_host"):
            self.imap_host_box.setText(preset["imap_host"])
            self.imap_port_box.setText(str(preset["imap_port"]))
        if preset.get("stats") and not self._service_key():
            self.service_picker.setCurrentText(delivery.SERVICES[preset["stats"]])
        security = preset.get("security", "starttls")
        self.security_picker.setCurrentText(SECURITY_LABELS.get(security, "Automatic"))
        self.preset_note.setText(t(preset.get("note", "")))

    def _change_limit(self, name: str) -> None:
        limit = PROVIDER_LIMITS.get(name, 500)
        db.set_setting("provider_limit_name", name)
        db.set_setting("provider_limit", limit)
        self.limit_note.setText(t("Daily ceiling: {limit:,} recipients per day.", limit=limit))

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
            # working send. Otherwise a blank username would test one way and send another.
            username=self.username_box.text().strip() or self.email_box.text().strip(),
            password=self.password_box.text(),
            security=self._security_value(),
            oauth="smtp" if oauth.account("smtp") else "",
        )

    def _imap_settings(self) -> imap_sync.ImapSettings:
        try:
            port = int(self.imap_port_box.text().strip() or 993)
        except ValueError:
            port = 993
        return imap_sync.ImapSettings(
            host=self.imap_host_box.text().strip(),
            port=port,
            username=(self.imap_user_box.text().strip() or self.username_box.text().strip()
                      or self.email_box.text().strip()),
            password=self.imap_password_box.text() or self.password_box.text(),
            use_ssl=port == 993,
            folder=self.imap_folder_box.text().strip() or "INBOX",
            oauth="imap" if oauth.account("imap") else "",
        )

    def _service_key(self) -> str:
        names = {label: key for key, label in delivery.SERVICES.items()}
        return names.get(self.service_picker.currentText(), "")

    def _service_changed(self) -> None:
        self.service_note.setText(t(SERVICE_NOTES[self._service_key()]))
        self.reports_result.setText("")

    def _show_auth(self) -> None:
        """Signed in: no username or password boxes to fill, for that half of the page."""
        for slot, rows in (("smtp", (self.username_row, self.password_row)),
                           ("imap", (self.imap_user_row, self.imap_password_row))):
            signed_in = oauth.account(slot) is not None
            for widget in rows:
                widget.setVisible(not signed_in)
        self.smtp_sign_in.refresh()
        self.imap_sign_in.refresh()

    # --- signing in with Google / Microsoft --------------------------------
    def sign_in(self, slot: str, provider_key: str) -> None:
        box = self.smtp_sign_in if slot == "smtp" else self.imap_sign_in
        box.waiting()
        Task(oauth.sign_in, provider_key, lambda: box.cancelled).start(
            on_result=self.guard(lambda account: self._signed_in(slot, account)),
            on_error=self.guard(lambda message: box.refresh(error=message)))

    def _signed_in(self, slot: str, account: dict) -> None:
        provider = oauth.PROVIDERS[account["provider"]]
        oauth.save(slot, account)
        slots = [slot]
        if slot == "smtp":
            self.smtp_host_box.setText(provider.smtp_host)
            self.smtp_port_box.setText("587")
            self.security_picker.setCurrentText(SECURITY_LABELS["starttls"])
            self.username_box.setText(account["email"])
            if not self.email_box.text().strip():
                self.email_box.setText(account["email"])
            # The same account reads the inbox too, unless another inbox is already set up
            if not self.imap_host_box.text().strip() and oauth.account("imap") is None:
                oauth.save("imap", account)
                slots.append("imap")
        if "imap" in slots:
            self.imap_host_box.setText(provider.imap_host)
            self.imap_port_box.setText("993")
            self.imap_user_box.setText(account["email"])
        self.save(silent=True)
        self._show_auth()
        self.notify(t("Signed in as {email}", email=account["email"]), "success")

    def sign_out(self, slot: str) -> None:
        oauth.forget(slot)
        self._show_auth()
        self.notify("Signed out. Type a password below instead.", "info")

    # --- delivery reports -------------------------------------------------
    def _test_reports(self) -> None:
        service, key = self._service_key(), self.api_key_box.text().strip()
        if not service or not key:
            self.reports_result.setText(t("Pick your sending service and paste its API key "
                                          "first."))
            set_tone(self.reports_result, "error")
            return
        self.reports_button.setEnabled(False)
        self.reports_button.setText(t("Checking..."))
        self.reports_result.setText(t("Connecting..."))
        set_tone(self.reports_result, "muted")
        Task(delivery.check, service, key).start(
            on_result=self.guard(self._show_reports_result),
            on_error=self.guard(
                lambda message: self._show_reports_result(delivery.DeliveryResult(
                    errors=[message]))))

    def _show_reports_result(self, result: delivery.DeliveryResult) -> None:
        self.reports_button.setEnabled(True)
        self.reports_button.setText(t("Test and fetch reports"))
        ok = not result.errors
        text = ("✓ " + t("Connected. {summary}", summary=t(result.summary())) if ok
                else "✕ " + t(result.summary()))
        for note in result.notes:
            text += "\n" + t(note)
        self.reports_result.setText(text)
        set_tone(self.reports_result, "success" if ok else "error")
        if ok:
            self.save(silent=True)

    # --- actions ------------------------------------------------------------
    def _test_smtp(self) -> None:
        settings = self._smtp_settings()
        if not settings.host:
            self.smtp_result.setText(t("Enter the SMTP server first."))
            set_tone(self.smtp_result, "error")
            return

        self.test_button.setEnabled(False)
        self.test_button.setText(t("Testing..."))
        self.smtp_result.setText(t("Connecting..."))
        set_tone(self.smtp_result, "muted")

        Task(jobs.test_smtp, settings).start(
            on_result=self.guard(lambda outcome: self._show_smtp_result(*outcome)),
            on_error=self.guard(lambda message: self._show_smtp_result(False, message)))

    def _show_smtp_result(self, ok: bool, message: str) -> None:
        self.test_button.setEnabled(True)
        self.test_button.setText(t("Test connection"))
        self.smtp_result.setText(("✓ " if ok else "✕ ") + t(message))
        set_tone(self.smtp_result, "success" if ok else "error")
        if ok:
            self.save(silent=True)
            self.notify("Connection successful, settings saved", "success")

    def _test_imap(self) -> None:
        settings = self._imap_settings()
        if not settings.host:
            self.imap_result.setText(t("Enter the IMAP server first."))
            set_tone(self.imap_result, "error")
            return

        self.imap_test_button.setEnabled(False)
        self.imap_test_button.setText(t("Testing..."))
        self.imap_result.setText(t("Connecting..."))
        set_tone(self.imap_result, "muted")

        Task(jobs.test_imap, settings).start(
            on_result=self.guard(lambda outcome: self._show_imap_result(*outcome)),
            on_error=self.guard(lambda message: self._show_imap_result(False, message)))

    def _show_imap_result(self, ok: bool, message: str) -> None:
        self.imap_test_button.setEnabled(True)
        self.imap_test_button.setText(t("Test IMAP"))
        self.imap_result.setText(("✓ " if ok else "✕ ") + t(message))
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
        db.set_setting("imap_username", self.imap_user_box.text().strip())
        db.set_setting("smtp_preset", self.preset_picker.currentText())
        db.set_setting("stats_service", self._service_key())
        if not self._service_key():
            credentials.delete_secret(delivery.API_KEY)
        elif self.api_key_box.text().strip():
            credentials.save_secret(delivery.API_KEY, self.api_key_box.text().strip())

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
        self.imap_user_box.setText(str(db.get_setting("imap_username", "") or ""))

        preset = db.get_setting("smtp_preset", "Custom / other")
        if preset in PRESETS:
            blocked = self.preset_picker.blockSignals(True)
            self.preset_picker.setCurrentText(preset)
            self.preset_picker.blockSignals(blocked)
            self.preset_note.setText(t(PRESETS[preset].get("note", "")))

        security = db.get_setting("smtp_security", "auto")
        self.security_picker.setCurrentText(SECURITY_LABELS.get(security, "Automatic"))

        password = credentials.load_secret(credentials.SMTP_PASSWORD)
        if password:
            self.password_box.setText(password)
        imap_password = credentials.load_secret(credentials.IMAP_PASSWORD)
        if imap_password:
            self.imap_password_box.setText(imap_password)

        service = db.get_setting("stats_service", "")
        blocked = self.service_picker.blockSignals(True)
        self.service_picker.setCurrentText(delivery.SERVICES.get(service, NOT_CONNECTED))
        self.service_picker.blockSignals(blocked)
        self.service_note.setText(t(SERVICE_NOTES[self._service_key()]))
        self.api_key_box.setText(credentials.load_secret(delivery.API_KEY))
        self._show_auth()

        limit_name = db.get_setting("provider_limit_name", "Other / shared hosting")
        if limit_name in PROVIDER_LIMITS:
            self.limit_picker.setCurrentText(limit_name)
        self._change_limit(self.limit_picker.currentText())

    def on_show(self) -> None:
        self.load()
