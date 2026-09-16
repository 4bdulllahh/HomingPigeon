"""Setup guide: a live checklist that explains why each step matters.

Written for someone who has never heard of SPF. Every step ticks itself from the
real state of the app, so it doubles as a progress tracker.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from app.core import credentials, db, importer, scorer, shortcut
from app.ui import theme
from app.ui.pages.base import Page
from app.ui.widgets.common import (Card, clear_layout, confirm_button, hint, muted,
                                   secondary_button, set_tone, subheading)

INTRO = (
    "Welcome. This page walks you through everything, in order — work down the list from the "
    "top and each step ticks itself off when it is done.\n\n"
    "Email providers judge every message by who sent it, not just what it says. A brand-new "
    "sender pushing out hundreds of identical emails looks exactly like a spammer, and once your "
    "domain gets that reputation it takes months to recover.\n\n"
    "Take your time. Nothing is sent until you press \"Start Emailing\" on the Send page, and the "
    "app checks everything before it lets you."
)


class GuideStep(Card):
    def __init__(self, number: int, title: str, why: str, how: str, done: bool, action=None):
        super().__init__(kind="card", padding=16)
        if done:
            self.setStyleSheet(f"QFrame[role=\"card\"] {{ border-color: {theme.color('success')}; }}")

        header = QHBoxLayout()
        header.setSpacing(10)
        badge = QLabel("✓" if done else str(number))
        size = round(22 * theme.text_scale())
        badge.setFixedSize(size, size)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"background-color: {theme.color('success') if done else theme.color('bg_input')};"
            f"color: {'#ffffff' if done else theme.color('fg')};"
            f"border-radius: {size // 2}px; font-weight: 700;")
        header.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        header.addWidget(subheading(title), 1)
        if action:
            header.addWidget(secondary_button("Open", action, 110), 0, Qt.AlignmentFlag.AlignTop)
        self.add_layout(header)

        body = QVBoxLayout()
        body.setContentsMargins(round(32 * theme.text_scale()), 0, 0, 0)
        body.setSpacing(2)
        body.addWidget(hint("Why it matters"))
        body.addWidget(muted(why))
        body.addSpacing(6)
        body.addWidget(hint("What to do"))
        body.addWidget(muted(how))
        self.add_layout(body)


class GuidePage(Page):
    def __init__(self, window):
        super().__init__(window)
        self.add_header("Setup guide")
        area = self.scroll_body()
        area.add(muted(INTRO))

        self.progress_label = muted("")
        area.add(self.progress_label)
        self.progress = QProgressBar()
        self.progress.setProperty("tone", "success")
        self.progress.setTextVisible(False)
        area.add(self.progress)

        area.add(self._launch_card())

        self.steps_holder = QWidget()
        self.steps_holder.setProperty("role", "plain")
        self.steps_layout = QVBoxLayout(self.steps_holder)
        self.steps_layout.setContentsMargins(0, 0, 0, 0)
        self.steps_layout.setSpacing(10)
        area.add(self.steps_holder)
        area.add_stretch()

    def _launch_card(self) -> QWidget:
        """How to find and reopen the app — the first thing a new user needs."""
        card = Card(kind="tint-card", padding=18)
        card.add(subheading("Opening HomingPigeon next time"))
        card.add(muted(shortcut.how_to_launch()))

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addWidget(confirm_button("Put an icon on my Desktop", self._make_shortcut, 260))
        buttons.addWidget(secondary_button(
            "Open the app's folder",
            lambda: shortcut.open_folder(shortcut.app_location()), 190))
        buttons.addStretch(1)
        card.add_layout(buttons)

        self.shortcut_status = muted("")
        card.add(self.shortcut_status)
        return card

    def _make_shortcut(self) -> None:
        ok, message = shortcut.create_desktop_shortcut()
        self.shortcut_status.setText(message)
        set_tone(self.shortcut_status, "success" if ok else "error")
        self.notify(message, "success" if ok else "error", 6000)

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
                "action": lambda: self.go("account"),
            },
            {
                "title": "Publish an SPF record",
                "why": "SPF lists which servers are allowed to send email for your domain. "
                       "Without it, a receiving server has no way to tell your mail from a "
                       "forgery, and treats it with suspicion.",
                "how": f"Open 'Domain check', run the checks on {domain}, then use the SPF "
                       f"generator and add the result as a TXT record at your DNS host.",
                "done": dns_status.get("SPF") == "pass",
                "action": lambda: self.go("deliverability"),
            },
            {
                "title": "Enable DKIM signing",
                "why": "DKIM adds a cryptographic signature to every message, proving it really "
                       "came from your domain and was not altered on the way. Gmail and Outlook "
                       "both weight it heavily.",
                "how": "Open 'Domain check' → DKIM setup, pick your provider, and follow the "
                       "exact steps for their admin console. Only your provider can generate the key.",
                "done": dns_status.get("DKIM") == "pass",
                "action": lambda: self.go("deliverability"),
            },
            {
                "title": "Publish a DMARC record",
                "why": "DMARC ties SPF and DKIM together and tells receivers what to do when a "
                       "message fails. Gmail and Yahoo now require one from anyone sending in "
                       "volume — without it, bulk mail is routinely rejected.",
                "how": "Open 'Domain check' → DMARC generator. Start with p=none, and move to "
                       "quarantine and then reject once your reports look clean.",
                "done": dns_status.get("DMARC") in ("pass", "warn"),
                "action": lambda: self.go("deliverability"),
            },
            {
                "title": "Import and clean your list",
                "why": "Bounces are the fastest route to a blacklist. A list full of dead "
                       "addresses tells providers you are mailing people who never opted in. "
                       "Above roughly 5% bounces, filtering gets severe.",
                "how": "Import your spreadsheet on the 'My contacts' page with the domain check "
                       "enabled. Remove addresses you have no business reason to contact.",
                "done": importer.contact_count() > 0,
                "action": lambda: self.go("contacts"),
            },
            {
                "title": "Write several subject lines and bodies",
                "why": "Hundreds of byte-identical messages are trivial for filters to "
                       "fingerprint. Varying the wording per recipient is the single most "
                       "effective content-side defence.",
                "how": "On the 'My message' page write at least 3 subjects and 2-3 bodies, add "
                       "{{Company}} and {{FirstName}} merge tags, and use spintax like "
                       "{Hi|Hello} for extra variation.",
                "done": (db.query_one("SELECT COUNT(*) AS n FROM subjects WHERE enabled = 1")
                         or {"n": 0})["n"] >= 2,
                "action": lambda: self.go("templates"),
            },
            {
                "title": "Check your spam score",
                "why": "Trigger words, shouting capitals, image-heavy layouts, link shorteners "
                       "and attachments on first contact all push a message toward the spam "
                       "folder — often without you realising.",
                "how": "'My message' → Preview & score. Aim for 85 or above, and fix anything "
                       "marked critical or high before sending.",
                "done": bool(report and report.score >= 70),
                "action": lambda: self.go("templates"),
            },
            {
                "title": "Link the brochure instead of attaching it",
                "why": "An attachment from an unknown sender is one of the strongest spam signals "
                       "there is, and large files slow every send. A link costs you nothing in "
                       "credibility and a great deal less in deliverability.",
                "how": "Put the PDF on your website or Drive and paste the link on the Campaign "
                       "page. Save the attachment for people who have replied.",
                "done": (db.get_setting("attach_mode", "link") == "link"
                         and bool(db.get_setting("link_url", ""))),
                "action": lambda: self.go("campaign"),
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
                "action": lambda: self.go("campaign"),
            },
            {
                "title": "Turn on bounce and reply detection",
                "why": "Continuing to mail addresses that already bounced is the clearest "
                       "possible signal that you are not managing your list. Removing them "
                       "immediately protects the reputation you are building.",
                "how": "Add your IMAP details on the 'My email account' page, then check the "
                       "inbox regularly from the 'Replies & bounces' page.",
                "done": bool(db.get_setting("imap_host", "")),
                "action": lambda: self.go("account"),
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
                "action": lambda: self.go("campaign"),
            },
        ]

    def on_show(self) -> None:
        clear_layout(self.steps_layout)

        steps = self._steps()
        done = sum(1 for step in steps if step["done"])
        self.progress.setRange(0, len(steps))
        self.progress.setValue(done)
        self.progress_label.setText(f"{done} of {len(steps)} steps complete")
        set_tone(self.progress_label, "success" if done == len(steps) else "muted")

        for number, step in enumerate(steps, start=1):
            self.steps_layout.addWidget(
                GuideStep(number, step["title"], step["why"], step["how"], step["done"],
                          step["action"]))
