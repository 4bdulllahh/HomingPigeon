"""Deliverability toolkit: authentication checker plus SPF/DMARC/DKIM generators."""
from __future__ import annotations

import threading

import customtkinter as ctk

from app import theme
from app.core import db, dns_tools
from app.ui.widgets.common import (FormRow, Section, StatusRow, copy_to_clipboard, get_text,
                                   open_url, set_text, toast)


class DeliverabilityPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self._results: list[dns_tools.CheckResult] = []
        self._build()

    def _build(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=theme.PAD_LARGE, pady=(theme.PAD, 0))
        theme.heading(header, "Deliverability").pack(anchor="w")
        theme.label(header,
                    "SPF, DKIM and DMARC are DNS records that prove your mail is really from you. "
                    "Without them, bulk email is filtered as spam no matter how good the content is.",
                    muted=True, wrap=True).pack(anchor="w", pady=(2, 10))

        self.tabs = ctk.CTkTabview(
            self, fg_color=theme.BG_PANEL, segmented_button_fg_color=theme.BG_SIDEBAR,
            segmented_button_selected_color=theme.ACCENT,
            segmented_button_selected_hover_color=theme.ACCENT_HOVER,
            segmented_button_unselected_color=theme.BG_SIDEBAR,
            text_color=theme.FG, border_width=1, border_color=theme.BORDER,
            corner_radius=theme.RADIUS_CARD)
        self.tabs.pack(fill="both", expand=True, padx=theme.PAD_LARGE, pady=(0, theme.PAD))

        for name in ("Check my domain", "SPF generator", "DMARC generator", "DKIM setup"):
            self.tabs.add(name)

        self._build_checker(self.tabs.tab("Check my domain"))
        self._build_spf(self.tabs.tab("SPF generator"))
        self._build_dmarc(self.tabs.tab("DMARC generator"))
        self._build_dkim(self.tabs.tab("DKIM setup"))

    # --- checker ------------------------------------------------------------
    def _build_checker(self, parent) -> None:
        top = ctk.CTkFrame(parent, fg_color="transparent")
        top.pack(fill="x", pady=(10, 10))

        theme.label(top, "Domain to check", size=12).pack(anchor="w")
        row = ctk.CTkFrame(top, fg_color="transparent")
        row.pack(fill="x", pady=(4, 0))

        self.domain_entry = theme.entry(row, "yourcompany.com")
        self.domain_entry.pack(side="left", fill="x", expand=True)
        self.check_button = theme.primary_button(row, "Run checks", self._run_checks, width=140)
        self.check_button.pack(side="left", padx=(8, 0))

        options = ctk.CTkFrame(top, fg_color="transparent")
        options.pack(fill="x", pady=(8, 0))
        theme.label(options, "Extra DKIM selectors (optional, comma separated)", size=11,
                    muted=True).pack(anchor="w")
        self.selector_entry = theme.entry(options, "e.g. mailer, key2")
        self.selector_entry.pack(fill="x", pady=(3, 0))

        self.verdict = theme.label(parent, "", size=13)
        self.verdict.pack(anchor="w", pady=(6, 6))

        self.results_frame = theme.scroll_frame(parent)
        self.results_frame.pack(fill="both", expand=True)
        theme.label(self.results_frame,
                    "Enter your domain above and run the checks.\n\n"
                    "The app reads your public DNS records directly — nothing is sent to any "
                    "third-party service.", muted=True).pack(anchor="w", pady=20)

    def _run_checks(self) -> None:
        domain = dns_tools.normalise_domain(self.domain_entry.get())
        if not domain:
            toast(self, "Enter a domain first", "warn")
            return

        db.set_setting("check_domain", domain)
        self.check_button.configure(state="disabled", text="Checking…")
        self.verdict.configure(text="Querying DNS…", text_color=theme.FG_MUTED)
        for widget in self.results_frame.winfo_children():
            widget.destroy()

        selectors = [s.strip() for s in self.selector_entry.get().split(",") if s.strip()]
        all_selectors = dns_tools.COMMON_SELECTORS + selectors
        smtp_host = db.get_setting("smtp_host", "")

        def work() -> None:
            try:
                results = dns_tools.full_report(domain, smtp_host, all_selectors)
            except Exception as error:  # noqa: BLE001
                self.after(0, lambda: self._checks_failed(str(error)))
                return
            self.after(0, lambda: self._show_results(results))

        threading.Thread(target=work, daemon=True).start()

    def _checks_failed(self, message: str) -> None:
        self.check_button.configure(state="normal", text="Run checks")
        self.verdict.configure(text=f"Could not complete the checks: {message}",
                               text_color=theme.ERROR)

    def _show_results(self, results: list[dns_tools.CheckResult]) -> None:
        self._results = results
        self.check_button.configure(state="normal", text="Run checks")

        status, message = dns_tools.overall_grade(results)
        self.verdict.configure(text=f"{theme.STATUS_ICONS.get(status, '')}  {message}",
                               text_color=theme.status_color(status))

        for widget in self.results_frame.winfo_children():
            widget.destroy()
        for result in results:
            StatusRow(self.results_frame, result.name, result.status, result.summary,
                      result.detail, result.record, result.fix, result.extras).pack(fill="x")

        db.set_setting("dns_last_status", {r.name: r.status for r in results})
        db.set_setting("dns_checked_at", db.now())

    def cached_results(self) -> list[dns_tools.CheckResult]:
        return self._results

    # --- SPF ----------------------------------------------------------------
    def _build_spf(self, parent) -> None:
        scroll = theme.scroll_frame(parent)
        scroll.pack(fill="both", expand=True)

        section = Section(scroll, "Build an SPF record",
                          "Tick every service that sends email using your domain. Missing one "
                          "means its mail starts failing authentication.")
        section.pack(fill="x", pady=(10, 12))

        self.spf_vars: dict[str, ctk.BooleanVar] = {}
        grid = ctk.CTkFrame(section.body, fg_color="transparent")
        grid.pack(fill="x")
        for index, name in enumerate(dns_tools.SPF_PRESETS):
            var = ctk.BooleanVar(value=False)
            self.spf_vars[name] = var
            theme.checkbox(grid, name, variable=var, command=self._update_spf).grid(
                row=index // 2, column=index % 2, sticky="w", padx=(0, 20), pady=3)

        row = FormRow(section.body, "Additional IPv4 addresses or ranges (comma separated)",
                      "Only needed if you send from your own server, e.g. 203.0.113.4 or 203.0.113.0/24")
        row.pack(fill="x", pady=(14, 0))
        self.spf_ip_entry = theme.entry(row.input_area, "")
        self.spf_ip_entry.pack(fill="x")
        self.spf_ip_entry.bind("<KeyRelease>", lambda e: self._update_spf())

        self.spf_strict = ctk.BooleanVar(value=False)
        theme.checkbox(section.body, "Use -all (strict — reject anything not listed)",
                       variable=self.spf_strict, command=self._update_spf).pack(
            anchor="w", pady=(12, 0))
        theme.label(section.body,
                    "Start with the default ~all. Move to -all only once you are certain every "
                    "sending service is in the list, or legitimate mail will be rejected.",
                    muted=True, size=11).pack(anchor="w", pady=(2, 0))

        self.spf_output = self._output_box(scroll, "Your SPF record",
                                           "Add this as a TXT record on your root domain (@).")
        self.spf_warnings = theme.label(scroll, "", muted=True)
        self.spf_warnings.pack(anchor="w", padx=4, pady=(0, 14))
        self._update_spf()

    def _update_spf(self) -> None:
        providers = [name for name, var in self.spf_vars.items() if var.get()]
        ips = [v.strip() for v in self.spf_ip_entry.get().split(",") if v.strip()]
        record, warnings = dns_tools.generate_spf(providers, ipv4=ips, strict=self.spf_strict.get())
        set_text(self.spf_output, record, readonly=True)
        self.spf_warnings.configure(
            text="\n".join(f"⚠  {w}" for w in warnings),
            text_color=theme.WARNING if warnings else theme.FG_MUTED)

    # --- DMARC --------------------------------------------------------------
    def _build_dmarc(self, parent) -> None:
        scroll = theme.scroll_frame(parent)
        scroll.pack(fill="both", expand=True)

        section = Section(
            scroll, "Build a DMARC record",
            "DMARC tells receiving servers what to do when a message fails SPF and DKIM. "
            "Gmail and Yahoo now require one from anyone sending in volume.")
        section.pack(fill="x", pady=(10, 12))

        row = FormRow(section.body, "Policy",
                      "Start at 'none' for a few weeks, then quarantine, then reject.")
        row.pack(fill="x", pady=(0, 12))
        self.dmarc_policy = theme.option_menu(
            row.input_area,
            ["none — monitor only (start here)",
             "quarantine — send failures to spam",
             "reject — refuse failures outright"],
            command=lambda _: self._update_dmarc())
        self.dmarc_policy.pack(fill="x")

        row = FormRow(section.body, "Report address (rua)",
                      "Where DMARC summary reports are sent. Use a real mailbox you check.")
        row.pack(fill="x", pady=(0, 12))
        self.dmarc_rua = theme.entry(row.input_area, "dmarc@yourcompany.com")
        self.dmarc_rua.pack(fill="x")
        self.dmarc_rua.bind("<KeyRelease>", lambda e: self._update_dmarc())

        self.dmarc_strict = ctk.BooleanVar(value=False)
        theme.checkbox(section.body, "Strict alignment (adkim=s, aspf=s)",
                       variable=self.dmarc_strict, command=self._update_dmarc).pack(anchor="w")
        theme.label(section.body,
                    "Strict alignment requires an exact domain match rather than allowing "
                    "subdomains. Leave this off unless you know you need it.",
                    muted=True, size=11).pack(anchor="w", pady=(2, 0))

        self.dmarc_output = self._output_box(
            scroll, "Your DMARC record",
            "Add this as a TXT record at the host name  _dmarc  on your domain.")
        self.dmarc_warnings = theme.label(scroll, "", muted=True)
        self.dmarc_warnings.pack(anchor="w", padx=4, pady=(0, 14))
        self._update_dmarc()

    def _update_dmarc(self) -> None:
        policy = self.dmarc_policy.get().split(" ")[0]
        record, warnings = dns_tools.generate_dmarc(
            policy=policy, rua=self.dmarc_rua.get().strip(),
            strict_alignment=self.dmarc_strict.get())
        set_text(self.dmarc_output, record, readonly=True)
        self.dmarc_warnings.configure(
            text="\n".join(f"⚠  {w}" for w in warnings),
            text_color=theme.WARNING if warnings else theme.FG_MUTED)

    # --- DKIM ---------------------------------------------------------------
    def _build_dkim(self, parent) -> None:
        scroll = theme.scroll_frame(parent)
        scroll.pack(fill="both", expand=True)

        section = Section(
            scroll, "How to enable DKIM",
            "DKIM signs every outgoing message with a private key held by whoever runs your mail "
            "server. If you use a hosted provider, only they can generate that key — the app "
            "cannot do it for you, so here are the exact steps for each provider.")
        section.pack(fill="x", pady=(10, 12))

        row = FormRow(section.body, "Your email provider")
        row.pack(fill="x", pady=(0, 10))
        self.dkim_provider = theme.option_menu(
            row.input_area, list(dns_tools.DKIM_PROVIDER_STEPS.keys()),
            command=self._show_dkim_steps)
        self.dkim_provider.pack(fill="x")

        self.dkim_steps = ctk.CTkTextbox(
            section.body, height=130, font=theme.font(12), fg_color=theme.BG_INPUT,
            text_color=theme.FG, wrap="word", border_width=1, border_color=theme.BORDER)
        self.dkim_steps.pack(fill="x")
        self._show_dkim_steps(self.dkim_provider.get())

        # Key generator — only meaningful for a self-hosted server
        gen = Section(
            scroll, "Generate a key pair (self-hosted mail servers only)",
            "Use this only if you run your own mail server such as Postfix with OpenDKIM. "
            "On Google Workspace, Microsoft 365, Zoho or shared hosting, a key generated here "
            "cannot be used, because your provider signs the mail with their own key.")
        gen.pack(fill="x", pady=(0, 12))

        fields = ctk.CTkFrame(gen.body, fg_color="transparent")
        fields.pack(fill="x")
        fields.grid_columnconfigure(0, weight=1)
        fields.grid_columnconfigure(1, weight=2)

        selector_row = FormRow(fields, "Selector", "A short label, e.g. 'mail' or 's1'")
        selector_row.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.dkim_selector = theme.entry(selector_row.input_area, "mail")
        self.dkim_selector.pack(fill="x")

        domain_row = FormRow(fields, "Domain")
        domain_row.grid(row=0, column=1, sticky="ew")
        self.dkim_domain = theme.entry(domain_row.input_area, "yourcompany.com")
        self.dkim_domain.pack(fill="x")

        self.dkim_button = theme.primary_button(gen.body, "Generate 2048-bit key pair",
                                                self._generate_dkim, width=220)
        self.dkim_button.pack(anchor="w", pady=(12, 0))

        self.dkim_host_output = self._output_box(scroll, "DNS host name", "", height=40)
        self.dkim_record_output = self._output_box(
            scroll, "DNS TXT value (the public key)",
            "Add this as a TXT record at the host name above.", height=110)
        self.dkim_key_note = theme.label(scroll, "", muted=True)
        self.dkim_key_note.pack(anchor="w", padx=4, pady=(0, 16))

    def _show_dkim_steps(self, provider: str) -> None:
        set_text(self.dkim_steps, dns_tools.DKIM_PROVIDER_STEPS.get(provider, ""), readonly=True)

    def _generate_dkim(self) -> None:
        selector = self.dkim_selector.get().strip() or "mail"
        domain = dns_tools.normalise_domain(self.dkim_domain.get())
        if not domain:
            toast(self, "Enter your domain first", "warn")
            return

        self.dkim_button.configure(state="disabled", text="Generating…")

        def work() -> None:
            try:
                result = dns_tools.generate_dkim_keypair(selector, domain)
            except Exception as error:  # noqa: BLE001
                self.after(0, lambda: toast(self, f"Key generation failed: {error}", "error"))
                self.after(0, lambda: self.dkim_button.configure(
                    state="normal", text="Generate 2048-bit key pair"))
                return
            self.after(0, lambda: self._show_dkim_result(result))

        threading.Thread(target=work, daemon=True).start()

    def _show_dkim_result(self, result: dict) -> None:
        self.dkim_button.configure(state="normal", text="Generate 2048-bit key pair")
        set_text(self.dkim_host_output, result["host"], readonly=True)
        set_text(self.dkim_record_output, result["record"], readonly=True)
        self.dkim_key_note.configure(
            text=f"Private key saved to:\n{result['private_key_path']}\n\n"
                 f"Keep this file secret — anyone holding it can sign mail as your domain. "
                 f"Point your mail server's DKIM module at it.",
            text_color=theme.WARNING)
        toast(self, "Key pair generated", "success")

    # --- shared -------------------------------------------------------------
    def _output_box(self, parent, title: str, hint: str, height: int = 80) -> ctk.CTkTextbox:
        wrapper = ctk.CTkFrame(parent, fg_color=theme.BG_PANEL, corner_radius=theme.RADIUS_CARD,
                               border_width=1, border_color=theme.BORDER)
        wrapper.pack(fill="x", padx=4, pady=(0, 8))

        head = ctk.CTkFrame(wrapper, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(12, 0))
        ctk.CTkLabel(head, text=title, font=theme.font(13, "bold"), text_color=theme.FG_BRIGHT,
                     anchor="w").pack(side="left")

        box = ctk.CTkTextbox(wrapper, height=height, font=theme.mono(11), fg_color=theme.BG_INPUT,
                             text_color=theme.CODE_STRING, wrap="word", border_width=1,
                             border_color=theme.BORDER)

        theme.secondary_button(head, "Copy", lambda: self._copy(box), width=70,
                               height=26).pack(side="right")

        if hint:
            ctk.CTkLabel(wrapper, text=hint, font=theme.font(11), text_color=theme.FG_MUTED,
                         anchor="w", justify="left", wraplength=700).pack(
                anchor="w", padx=16, pady=(4, 0))
        box.pack(fill="x", padx=16, pady=(8, 14))
        return box

    def _copy(self, box: ctk.CTkTextbox) -> None:
        text = box.get("1.0", "end").strip()
        if not text:
            return
        copy_to_clipboard(self, text)
        toast(self, "Copied to clipboard", "success", 2000)

    def on_show(self) -> None:
        if not self.domain_entry.get():
            domain = db.get_setting("check_domain", "")
            if not domain:
                email = db.get_setting("sender_email", "")
                domain = email.split("@", 1)[1] if "@" in email else ""
            if domain:
                self.domain_entry.insert(0, domain)
                self.dkim_domain.delete(0, "end")
                self.dkim_domain.insert(0, domain)
                if not self.dmarc_rua.get():
                    self.dmarc_rua.insert(0, f"dmarc@{domain}")
                    self._update_dmarc()
