"""Deliverability toolkit: the authentication checker plus SPF/DMARC/DKIM generators."""
from __future__ import annotations

from PyQt6.QtWidgets import QGridLayout, QVBoxLayout, QWidget

from app.core import db, dns_tools
from app.ui import theme
from app.ui.pages.base import Page
from app.ui.widgets.common import (Card, FormRow, ScrollPage, Section, StatusRow, TabBar,
                                   copy_to_clipboard, muted, primary_button, row, set_tone,
                                   small_button, subheading)
from app.ui.widgets.inputs import Debouncer, checkbox, combo, line_edit, read_only_box
from app.workers import jobs
from app.workers.base import Task

DMARC_POLICIES = [
    "none — monitor only (start here)",
    "quarantine — send failures to spam",
    "reject — refuse failures outright",
]


class DeliverabilityPage(Page):
    def __init__(self, window):
        super().__init__(window)
        self._results: list[dns_tools.CheckResult] = []

        self.add_header(
            "Deliverability",
            "SPF, DKIM and DMARC are DNS records that prove your mail is really from you. Without "
            "them, bulk email is filtered as spam no matter how good the content is.")

        self.tabs = TabBar()
        self.tabs.add("Check my domain", self._build_checker)
        self.tabs.add("SPF generator", self._build_spf)
        self.tabs.add("DMARC generator", self._build_dmarc)
        self.tabs.add("DKIM setup", self._build_dkim)
        self.root.addWidget(self.tabs, 1)
        self.tabs.set("Check my domain")

    # =======================================================================
    # Checker
    # =======================================================================
    def _build_checker(self) -> QWidget:
        holder = QWidget()
        holder.setProperty("role", "plain")
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        domain_row = FormRow("Domain to check")
        self.domain_box = line_edit("yourcompany.com")
        self.domain_box.returnPressed.connect(self._run_checks)
        self.check_button = primary_button("Run checks", self._run_checks, 140)
        domain_row.add(row(self.domain_box, self.check_button, stretch=0))
        layout.addWidget(domain_row)

        selector_row = FormRow("Extra DKIM selectors (optional, comma separated)")
        self.selector_box = line_edit("e.g. mailer, key2")
        selector_row.add(self.selector_box)
        layout.addWidget(selector_row)

        self.verdict = muted("")
        layout.addWidget(self.verdict)

        self.results_area = ScrollPage(spacing=4)
        self.results_area.add(muted(
            "Enter your domain above and run the checks.\n\n"
            "The app reads your public DNS records directly — nothing is sent to any "
            "third-party service."))
        self.results_area.add_stretch()
        layout.addWidget(self.results_area, 1)
        return holder

    def _run_checks(self) -> None:
        domain = dns_tools.normalise_domain(self.domain_box.text())
        if not domain:
            self.notify("Enter a domain first", "warn")
            return

        db.set_setting("check_domain", domain)
        self.check_button.setEnabled(False)
        self.check_button.setText("Checking…")
        self.verdict.setText("Querying DNS…")
        set_tone(self.verdict, "muted")
        self.results_area.clear()

        extra = [s.strip() for s in self.selector_box.text().split(",") if s.strip()]
        selectors = dns_tools.COMMON_SELECTORS + extra
        smtp_host = db.get_setting("smtp_host", "")

        Task(jobs.dns_report, domain, smtp_host, selectors).start(
            on_result=self._show_results, on_error=self._checks_failed)

    def _checks_failed(self, message: str) -> None:
        self.check_button.setEnabled(True)
        self.check_button.setText("Run checks")
        self.verdict.setText(f"Could not complete the checks: {message}")
        set_tone(self.verdict, "error")

    def _show_results(self, results: list[dns_tools.CheckResult]) -> None:
        self._results = results
        self.check_button.setEnabled(True)
        self.check_button.setText("Run checks")

        status, message = dns_tools.overall_grade(results)
        self.verdict.setText(f"{theme.STATUS_ICONS.get(status, '')}  {message}")
        self.verdict.setStyleSheet(f"color: {theme.status_color(status)};")

        self.results_area.clear()
        for result in results:
            self.results_area.add(StatusRow(result.name, result.status, result.summary,
                                            result.detail, result.record, result.fix,
                                            result.extras))
        self.results_area.add_stretch()

        db.set_setting("dns_last_status", {r.name: r.status for r in results})
        db.set_setting("dns_checked_at", db.now())

    def cached_results(self) -> list[dns_tools.CheckResult]:
        return self._results

    # =======================================================================
    # SPF
    # =======================================================================
    def _build_spf(self) -> QWidget:
        area = ScrollPage(spacing=12)
        section = Section("Build an SPF record",
                          "Tick every service that sends email using your domain. Missing one "
                          "means its mail starts failing authentication.")

        self.spf_boxes: dict[str, object] = {}
        grid_holder = QWidget()
        grid_holder.setProperty("role", "plain")
        grid = QGridLayout(grid_holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        for index, name in enumerate(dns_tools.SPF_PRESETS):
            box = checkbox(name, False, on_change=lambda _c: self._update_spf())
            grid.addWidget(box, index // 2, index % 2)
            self.spf_boxes[name] = box
        section.add(grid_holder)

        ip_row = FormRow(
            "Additional IPv4 addresses or ranges (comma separated)",
            "Only needed if you send from your own server, e.g. 203.0.113.4 or 203.0.113.0/24")
        self.spf_ip_box = line_edit("")
        self._spf_debounce = Debouncer(350, self)
        self._spf_debounce.connect(self._update_spf)
        self.spf_ip_box.textChanged.connect(lambda _t: self._spf_debounce.poke())
        ip_row.add(self.spf_ip_box)
        section.add(ip_row)

        self.spf_strict = checkbox("Use -all (strict — reject anything not listed)", False,
                                   on_change=lambda _c: self._update_spf())
        section.add(self.spf_strict)
        section.add(muted(
            "Start with the default ~all. Move to -all only once you are certain every sending "
            "service is in the list, or legitimate mail will be rejected."))
        area.add(section)

        self.spf_output = self._output_card(
            area, "Your SPF record", "Add this as a TXT record on your root domain (@).")
        self.spf_warnings = muted("")
        area.add(self.spf_warnings)
        area.add_stretch()
        self._update_spf()
        return area

    def _update_spf(self) -> None:
        providers = [name for name, box in self.spf_boxes.items() if box.isChecked()]
        ips = [v.strip() for v in self.spf_ip_box.text().split(",") if v.strip()]
        record, warnings = dns_tools.generate_spf(providers, ipv4=ips,
                                                  strict=self.spf_strict.isChecked())
        self.spf_output.setPlainText(record)
        self._show_warnings(self.spf_warnings, warnings)

    # =======================================================================
    # DMARC
    # =======================================================================
    def _build_dmarc(self) -> QWidget:
        area = ScrollPage(spacing=12)
        section = Section(
            "Build a DMARC record",
            "DMARC tells receiving servers what to do when a message fails SPF and DKIM. Gmail "
            "and Yahoo now require one from anyone sending in volume.")

        policy_row = FormRow("Policy",
                             "Start at 'none' for a few weeks, then quarantine, then reject.")
        self.dmarc_policy = combo(DMARC_POLICIES, on_change=lambda _t: self._update_dmarc())
        policy_row.add(self.dmarc_policy)
        section.add(policy_row)

        rua_row = FormRow("Report address (rua)",
                          "Where DMARC summary reports are sent. Use a real mailbox you check.")
        self.dmarc_rua = line_edit("dmarc@yourcompany.com")
        self._dmarc_debounce = Debouncer(350, self)
        self._dmarc_debounce.connect(self._update_dmarc)
        self.dmarc_rua.textChanged.connect(lambda _t: self._dmarc_debounce.poke())
        rua_row.add(self.dmarc_rua)
        section.add(rua_row)

        self.dmarc_strict = checkbox("Strict alignment (adkim=s, aspf=s)", False,
                                     on_change=lambda _c: self._update_dmarc())
        section.add(self.dmarc_strict)
        section.add(muted(
            "Strict alignment requires an exact domain match rather than allowing subdomains. "
            "Leave this off unless you know you need it."))
        area.add(section)

        self.dmarc_output = self._output_card(
            area, "Your DMARC record",
            "Add this as a TXT record at the host name  _dmarc  on your domain.")
        self.dmarc_warnings = muted("")
        area.add(self.dmarc_warnings)
        area.add_stretch()
        self._update_dmarc()
        return area

    def _update_dmarc(self) -> None:
        policy = self.dmarc_policy.currentText().split(" ")[0]
        record, warnings = dns_tools.generate_dmarc(
            policy=policy, rua=self.dmarc_rua.text().strip(),
            strict_alignment=self.dmarc_strict.isChecked())
        self.dmarc_output.setPlainText(record)
        self._show_warnings(self.dmarc_warnings, warnings)

    # =======================================================================
    # DKIM
    # =======================================================================
    def _build_dkim(self) -> QWidget:
        area = ScrollPage(spacing=12)
        section = Section(
            "How to enable DKIM",
            "DKIM signs every outgoing message with a private key held by whoever runs your mail "
            "server. If you use a hosted provider, only they can generate that key — the app "
            "cannot do it for you, so here are the exact steps for each provider.")

        provider_row = FormRow("Your email provider")
        self.dkim_provider = combo(list(dns_tools.DKIM_PROVIDER_STEPS.keys()),
                                   on_change=self._show_dkim_steps)
        provider_row.add(self.dkim_provider)
        section.add(provider_row)

        self.dkim_steps = read_only_box("", role="", lines=7)
        section.add(self.dkim_steps)
        area.add(section)
        self._show_dkim_steps(self.dkim_provider.currentText())

        generator = Section(
            "Generate a key pair (self-hosted mail servers only)",
            "Use this only if you run your own mail server such as Postfix with OpenDKIM. On "
            "Google Workspace, Microsoft 365, Zoho or shared hosting, a key generated here cannot "
            "be used, because your provider signs the mail with their own key.")

        fields_holder = QWidget()
        fields_holder.setProperty("role", "plain")
        fields = QGridLayout(fields_holder)
        fields.setContentsMargins(0, 0, 0, 0)
        fields.setSpacing(10)
        fields.setColumnStretch(0, 1)
        fields.setColumnStretch(1, 2)

        selector_row = FormRow("Selector", "A short label, e.g. 'mail' or 's1'")
        self.dkim_selector = line_edit("mail")
        selector_row.add(self.dkim_selector)
        fields.addWidget(selector_row, 0, 0)

        domain_row = FormRow("Domain")
        self.dkim_domain = line_edit("yourcompany.com")
        domain_row.add(self.dkim_domain)
        fields.addWidget(domain_row, 0, 1)
        generator.add(fields_holder)

        self.dkim_button = primary_button("Generate 2048-bit key pair", self._generate_dkim, 230)
        generator.add(row(self.dkim_button, None))
        area.add(generator)

        self.dkim_host_output = self._output_card(area, "DNS host name", "", lines=1)
        self.dkim_record_output = self._output_card(
            area, "DNS TXT value (the public key)",
            "Add this as a TXT record at the host name above.", lines=5)
        self.dkim_key_note = muted("")
        area.add(self.dkim_key_note)
        area.add_stretch()
        return area

    def _show_dkim_steps(self, provider: str) -> None:
        self.dkim_steps.setPlainText(dns_tools.DKIM_PROVIDER_STEPS.get(provider, ""))

    def _generate_dkim(self) -> None:
        selector = self.dkim_selector.text().strip() or "mail"
        domain = dns_tools.normalise_domain(self.dkim_domain.text())
        if not domain:
            self.notify("Enter your domain first", "warn")
            return

        self.dkim_button.setEnabled(False)
        self.dkim_button.setText("Generating…")

        def reset() -> None:
            self.dkim_button.setEnabled(True)
            self.dkim_button.setText("Generate 2048-bit key pair")

        Task(jobs.generate_dkim, selector, domain).start(
            on_result=self._show_dkim_result,
            on_error=lambda message: self.notify(f"Key generation failed: {message}", "error"),
            on_done=reset)

    def _show_dkim_result(self, result: dict) -> None:
        self.dkim_host_output.setPlainText(result["host"])
        self.dkim_record_output.setPlainText(result["record"])
        self.dkim_key_note.setText(
            f"Private key saved to:\n{result['private_key_path']}\n\n"
            f"Keep this file secret — anyone holding it can sign mail as your domain. "
            f"Point your mail server's DKIM module at it.")
        set_tone(self.dkim_key_note, "warning")
        self.notify("Key pair generated", "success")

    # =======================================================================
    # Shared
    # =======================================================================
    def _output_card(self, area: ScrollPage, title: str, note: str, lines: int = 3):
        card = Card(kind="card", padding=16)
        header = subheading(title)
        box = read_only_box("", role="code", lines=lines)
        card.add(row(header, None, small_button("Copy", lambda: self._copy(box))))
        if note:
            card.add(muted(note))
        card.add(box)
        area.add(card)
        return box

    def _copy(self, box) -> None:
        text = box.toPlainText().strip()
        if not text:
            return
        copy_to_clipboard(text)
        self.notify("Copied to clipboard", "success", 2000)

    @staticmethod
    def _show_warnings(label, warnings: list[str]) -> None:
        label.setText("\n".join(f"⚠  {w}" for w in warnings))
        set_tone(label, "warning" if warnings else "muted")

    # =======================================================================
    def on_show(self) -> None:
        if not self.domain_box.text():
            domain = db.get_setting("check_domain", "")
            if not domain:
                email = db.get_setting("sender_email", "")
                domain = email.split("@", 1)[1] if "@" in email else ""
            if domain:
                self.domain_box.setText(domain)
                if self.tabs.page("DKIM setup") is not None:
                    self.dkim_domain.setText(domain)
                if self.tabs.page("DMARC generator") is not None and not self.dmarc_rua.text():
                    self.dmarc_rua.setText(f"dmarc@{domain}")
