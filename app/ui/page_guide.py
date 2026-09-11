"""Setup guide: a live checklist that explains why each step matters.

Written for someone who has never heard of SPF. Every step ticks itself from the
real state of the app, so it doubles as a progress tracker.
"""
from __future__ import annotations

import customtkinter as ctk

from app import theme
from app.core import credentials, db, importer, scorer, shortcut, warmup
from app.ui.widgets.common import toast

INTRO = (
    "Welcome. This page walks you through everything, in order — work down the list from the top "
    "and each step ticks itself off when it is done.\n\n"
    "Email providers judge every message by who sent it, not just what it says. A brand-new "
    "sender pushing out hundreds of identical emails looks exactly like a spammer, and once your "
    "domain gets that reputation it takes months to recover.\n\n"
    "Take your time. Nothing is sent until you press \"Start Emailing\" on the Send page, and the "
    "app checks everything before it lets you."
)


class GuideStep(ctk.CTkFrame):
    def __init__(self, master, number: int, title: str, why: str, how: str,
                 done: bool, action=None, action_label: str = "Open"):
        super().__init__(master, fg_color=theme.BG_PANEL, corner_radius=theme.RADIUS_CARD,
                         border_width=1, border_color=theme.SUCCESS if done else theme.BORDER)

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(14, 0))

        badge = ctk.CTkLabel(head, text="✓" if done else str(number),
                             font=theme.font(13, "bold"),
                             text_color=theme.FG_ON_ACCENT if done else theme.FG,
                             fg_color=theme.SUCCESS if done else theme.BG_INPUT,
                             corner_radius=11, width=22, height=22)
        badge.pack(side="left", padx=(0, 10))

        ctk.CTkLabel(head, text=title, font=theme.font(14, "bold"),
                     text_color=theme.FG_BRIGHT, anchor="w").pack(side="left")

        if action:
            theme.secondary_button(head, action_label, action, width=110, height=28).pack(
                side="right")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="x", padx=(48, 16), pady=(6, 16))

        ctk.CTkLabel(body, text="Why it matters", font=theme.font(11, "bold"),
                     text_color=theme.FG_MUTED, anchor="w").pack(anchor="w")
        why_label = ctk.CTkLabel(body, text=why, font=theme.font(12), text_color=theme.FG,
                                 anchor="w", justify="left", wraplength=740)
        why_label.pack(anchor="w", pady=(0, 8))
        theme.auto_wrap(why_label, self, padding=80)

        ctk.CTkLabel(body, text="What to do", font=theme.font(11, "bold"),
                     text_color=theme.FG_MUTED, anchor="w").pack(anchor="w")
        how_label = ctk.CTkLabel(body, text=how, font=theme.font(12), text_color=theme.FG,
                                 anchor="w", justify="left", wraplength=740)
        how_label.pack(anchor="w")
        theme.auto_wrap(how_label, self, padding=80)


class GuidePage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self._build()

    def _build(self) -> None:
        self.scroll = theme.scroll_frame(self)
        self.scroll.pack(fill="both", expand=True, padx=theme.PAD_LARGE, pady=theme.PAD)

        theme.heading(self.scroll, "Setup guide").pack(anchor="w")
        theme.label(self.scroll, INTRO, muted=True, wrap=True).pack(anchor="w", pady=(6, 8))

        self.progress_label = theme.label(self.scroll, "", size=13)
        self.progress_label.pack(anchor="w", pady=(0, 4))
        self.progress = ctk.CTkProgressBar(self.scroll, progress_color=theme.SUCCESS,
                                           fg_color=theme.BORDER, height=6)
        self.progress.pack(fill="x", pady=(0, 16))

        self._build_launch_card()

        self.steps_frame = ctk.CTkFrame(self.scroll, fg_color="transparent")
        self.steps_frame.pack(fill="both", expand=True)

    def _build_launch_card(self) -> None:
        """How to find and reopen the app — the first thing a new user needs."""
        card = ctk.CTkFrame(self.scroll, fg_color=theme.ACCENT_SOFT,
                            corner_radius=theme.RADIUS_CARD, border_width=1,
                            border_color=theme.BORDER)
        card.pack(fill="x", pady=(0, 16))

        ctk.CTkLabel(card, text="Opening HomingPigeon next time",
                     font=theme.font(15, "bold"), text_color=theme.FG_BRIGHT,
                     anchor="w").pack(anchor="w", padx=18, pady=(16, 6))

        info = ctk.CTkLabel(card, text=shortcut.how_to_launch(), font=theme.font(12),
                            text_color=theme.FG, anchor="w", justify="left", wraplength=720)
        info.pack(anchor="w", padx=18)
        theme.auto_wrap(info, card, padding=56)

        buttons = ctk.CTkFrame(card, fg_color="transparent")
        buttons.pack(fill="x", padx=18, pady=(14, 12))

        theme.confirm_button(buttons, "Put an icon on my Desktop", self._make_shortcut,
                             width=250, height=42).pack(side="left")
        theme.secondary_button(buttons, "Open the app's folder",
                               lambda: shortcut.open_folder(shortcut.app_location()),
                               width=180, height=42).pack(side="left", padx=10)

        self.shortcut_status = theme.label(card, "", muted=True)
        self.shortcut_status.pack(anchor="w", padx=18, pady=(0, 16))

    def _make_shortcut(self) -> None:
        ok, message = shortcut.create_desktop_shortcut()
        self.shortcut_status.configure(text=message,
                                       text_color=theme.SUCCESS if ok else theme.ERROR)
        toast(self, message, "success" if ok else "error", 6000)

    # --- state ---------------------------------------------------------------
    def _steps(self) -> list[dict]:
        dns_status = db.get_setting("dns_last_status", {}) or {}
        account_ready = bool(db.get_setting("sender_email", "")
                             and db.get_setting("smtp_host", "")
                             and credentials.has_secret(credentials.SMTP_PASSWORD))
        report = scorer.latest_report()
        sender_email = db.get_setting("sender_email", "")
        domain = sender_email.split("@", 1)[1] if "@" in sender_email else "your domain"

        return [
            {
                "title": "Use a company domain address",
                "why": "Sending business outreach from a free Gmail or Hotmail address cannot be "
                       "authenticated for your brand and is filtered far more aggressively. Mail "
                       "from your own domain can be signed and verified.",
                "how": "Set up an address on your company domain with your email provider, then "
                       "enter it on the 'My email account' page along with the SMTP details.",
                "done": account_ready and not any(
                    sender_email.endswith(p) for p in
                    ("@gmail.com", "@yahoo.com", "@hotmail.com", "@outlook.com")),
                "action": lambda: self.app.show("account"),
            },
            {
                "title": "Publish an SPF record",
                "why": "SPF lists which servers are allowed to send email for your domain. Without "
                       "it, a receiving server has no way to tell your mail from a forgery, and "
                       "treats it with suspicion.",
                "how": f"Open 'Domain check', run the checks on {domain}, then use the SPF "
                       f"generator and add the result as a TXT record at your DNS host.",
                "done": dns_status.get("SPF") == "pass",
                "action": lambda: self.app.show("deliverability"),
            },
            {
                "title": "Enable DKIM signing",
                "why": "DKIM adds a cryptographic signature to every message, proving it really "
                       "came from your domain and was not altered on the way. Gmail and Outlook "
                       "both weight it heavily.",
                "how": "Open 'Domain check' → DKIM setup, pick your provider, and follow the exact "
                       "steps for their admin console. Only your provider can generate the key.",
                "done": dns_status.get("DKIM") == "pass",
                "action": lambda: self.app.show("deliverability"),
            },
            {
                "title": "Publish a DMARC record",
                "why": "DMARC ties SPF and DKIM together and tells receivers what to do when a "
                       "message fails. Gmail and Yahoo now require one from anyone sending in "
                       "volume — without it, bulk mail is routinely rejected.",
                "how": "Open 'Domain check' → DMARC generator. Start with p=none, and move to "
                       "quarantine and then reject once your reports look clean.",
                "done": dns_status.get("DMARC") in ("pass", "warn"),
                "action": lambda: self.app.show("deliverability"),
            },
            {
                "title": "Import and clean your list",
                "why": "Bounces are the fastest route to a blacklist. A list full of dead addresses "
                       "tells providers you are mailing people who never opted in. Above roughly 5% "
                       "bounces, filtering gets severe.",
                "how": "Import your spreadsheet on the 'My contacts' page with the domain check enabled. "
                       "Remove addresses you have no business reason to contact.",
                "done": importer.contact_count() > 0,
                "action": lambda: self.app.show("contacts"),
            },
            {
                "title": "Write several subject lines and bodies",
                "why": "Hundreds of byte-identical messages are trivial for filters to fingerprint. "
                       "Varying the wording per recipient is the single most effective content-side "
                       "defence.",
                "how": "On the 'My message' page write at least 3 subjects and 2-3 bodies, add "
                       "{{Company}} and {{FirstName}} merge tags, and use spintax like "
                       "{Hi|Hello} for extra variation.",
                "done": (db.query_one("SELECT COUNT(*) AS n FROM subjects WHERE enabled = 1") or
                         {"n": 0})["n"] >= 2,
                "action": lambda: self.app.show("templates"),
            },
            {
                "title": "Check your spam score",
                "why": "Trigger words, shouting capitals, image-heavy layouts, link shorteners and "
                       "attachments on first contact all push a message toward the spam folder — "
                       "often without you realising.",
                "how": "'My message' → Preview & score. Aim for 85 or above, and fix anything marked "
                       "critical or high before sending.",
                "done": bool(report and report.score >= 70),
                "action": lambda: self.app.show("templates"),
            },
            {
                "title": "Link the brochure instead of attaching it",
                "why": "An attachment from an unknown sender is one of the strongest spam signals "
                       "there is, and large files slow every send. A link costs you nothing in "
                       "credibility and a great deal less in deliverability.",
                "how": "Put the PDF on your website or Drive and paste the link on the Campaign "
                       "page. Save the attachment for people who have replied.",
                "done": db.get_setting("attach_mode", "link") == "link"
                        and bool(db.get_setting("link_url", "")),
                "action": lambda: self.app.show("campaign"),
            },
            {
                "title": "Start slow and let the warm-up run",
                "why": "A domain that has never sent bulk email and suddenly emits 500 messages "
                       "looks compromised. Volume built gradually earns a reputation; volume "
                       "dumped at once destroys one.",
                "how": "Leave the warm-up ramp on. It starts at about 20 a day and rises over "
                       "several weeks. Keep a wide, random delay between emails and stay inside "
                       "office hours.",
                "done": bool(db.get_setting("warmup_enabled", True)),
                "action": lambda: self.app.show("campaign"),
            },
            {
                "title": "Turn on bounce and reply detection",
                "why": "Continuing to mail addresses that already bounced is the clearest possible "
                       "signal that you are not managing your list. Removing them immediately "
                       "protects the reputation you are building.",
                "how": "Add your IMAP details on the 'My email account' page, then check the inbox "
                       "regularly from the 'Replies & bounces' page.",
                "done": bool(db.get_setting("imap_host", "")),
                "action": lambda: self.app.show("account"),
            },
            {
                "title": "Honour every opt-out, immediately",
                "why": "Complaints hurt far more than bounces, and in most jurisdictions ignoring "
                       "an opt-out is illegal. One complaint per thousand messages is enough to "
                       "cause real filtering problems.",
                "how": "The app adds an unsubscribe footer and the standard header that puts an "
                       "Unsubscribe button in Gmail and Outlook, and suppresses anyone who asks. "
                       "Leave those on, and never re-import a suppressed address.",
                "done": bool(db.get_setting("unsubscribe_note", True)),
                "action": lambda: self.app.show("campaign"),
            },
        ]

    def on_show(self) -> None:
        for widget in self.steps_frame.winfo_children():
            widget.destroy()

        steps = self._steps()
        done = sum(1 for step in steps if step["done"])
        self.progress.set(done / len(steps))
        self.progress_label.configure(
            text=f"{done} of {len(steps)} steps complete",
            text_color=theme.SUCCESS if done == len(steps) else theme.FG)

        for number, step in enumerate(steps, start=1):
            GuideStep(self.steps_frame, number, step["title"], step["why"], step["how"],
                      step["done"], step["action"]).pack(fill="x", pady=(0, 10))
