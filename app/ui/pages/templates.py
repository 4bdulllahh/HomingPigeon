"""Templates: several subjects and bodies, a signature, a live preview and the spam score."""
from __future__ import annotations

import tempfile
import webbrowser
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QSplitter, QVBoxLayout, QWidget

from app.core import composer, db, importer, merge, scorer
from app.ui import theme
from app.ui.pages.base import Page
from app.ui.widgets.common import (Card, ScrollPage, TabBar, clear_layout, danger_button, hint,
                                   muted, primary_button, row, secondary_button, separator,
                                   set_tone, small_button, subheading)
from app.ui.widgets.dialogs import InfoDialog
from app.ui.widgets.inputs import (Debouncer, checkbox, get_text, line_edit, read_only_box,
                                   set_text, text_box)
from app.workers import jobs
from app.workers.base import Task

# Examples are never filled in automatically — the app starts blank and these are
# only inserted when the user presses "Show me an example".
EXAMPLE_SUBJECTS = [
    "{A quick question|Quick question} about {{Company}}",
    "{Introducing|A short introduction to} our services for {{Company}}",
    "Would this be useful for {{Company}}?",
]

EXAMPLE_BODY = """<p>{Hi|Hello} {{FirstName}},</p>

<p>{I hope your week is going well.|Hope you are having a productive week.|I hope this finds you well.}</p>

<p>I am reaching out from <strong>[Your Company]</strong>. We help businesses like {{Company}} with
[describe what you do in one sentence].</p>

<p>We handle the whole process:</p>

<ul>
  <li>[First thing you offer]</li>
  <li>[Second thing you offer]</li>
  <li>[Third thing you offer]</li>
</ul>

<p>Would you be open to a short call this week?</p>"""

EXAMPLE_SIGNATURE = """<p style="margin-top:20px;">
  <strong>[Your Name]</strong><br>
  <span style="color:#555555;">[Your Company] &mdash; [what you do]</span><br>
  <strong>Phone:</strong> [your phone number]<br>
  <strong>Email:</strong> [your email address]<br>
  <strong>Web:</strong> <a href="https://www.example.com">[your website]</a><br>
  <em>[Your city and country]</em>
</p>"""

EMPTY_HINT = ("Nothing here yet.\n\n"
              "Press \"Show me an example\" to start from a ready-made template you can edit, "
              "or \"Add\" to write your own from scratch.")


# What the "?" next to the score opens. The wording is deliberately about what
# to do differently, not about the rule engine: the point is that the reader
# should write a better email afterwards.
SCORE_HELP_INTRO = (
    "Every message starts at 100. The checks below run over your subjects, your message, "
    "your signature and your domain settings, and each problem found takes points off. "
    "Nothing is sent anywhere — the whole check runs on your computer.")

SCORE_HELP_SECTIONS = [
    ("How much each problem costs", [
        "Critical −25: something that will get the mail rejected or is outright deceptive.",
        "High −12: a strong spam signal that filters weight heavily.",
        "Medium −6: a habit that hurts across a large send.",
        "Low −3: a small improvement worth making.",
        "85 and above reaches the inbox reliably; below 70 is risky; below 50 will be filtered.",
    ]),
    ("Your subject lines", [
        "Keep them under about 60 characters, or phones cut them off.",
        "Sentence case only. Mostly-capitals reads as shouting and is penalised heavily.",
        "At most one exclamation mark — ideally none.",
        "Avoid promotional wording: free, urgent, act now, limited time, discount, "
        "guarantee, winner, click here.",
        "Never fake a thread with 'Re:' or 'Fwd:' on a first contact. That is treated as "
        "deception and costs the most of any single check.",
        "Put {{Company}} in the subject so no two recipients get an identical one.",
    ]),
    ("Your message", [
        "Aim for 80–200 words. Very short mail with a link looks like phishing; very long "
        "first emails get ignored.",
        "Write in plain business language. Five or more sales-pitch phrases is a heavy penalty.",
        "One or two links at most, to your own domain, over https. Link shorteners and raw "
        "IP addresses are penalised hard because they hide the destination.",
        "Lead with text, not images. An image-heavy email with little text is a classic "
        "spam pattern, and most email programs block images by default anyway.",
        "Keep a clear opt-out line. The app adds one for you unless you switch it off.",
    ]),
    ("Variety — the one most people miss", [
        "Hundreds of identical messages are what filters fingerprint, and it is the most "
        "common reason a perfectly polite campaign gets blocked.",
        "Write 3 or more subject lines and 2–3 versions of the message.",
        "Use spintax like {Hi|Hello|Good morning} to multiply the combinations further.",
        "The check wants at least 10 genuinely different versions of the email.",
    ]),
    ("Who you are", [
        "Send from your own company domain. A free Gmail or Outlook address cannot pass "
        "DMARC for your brand and is filtered much harder for bulk sending.",
        "Keep Reply-To on the same domain as From. A mismatch is a phishing pattern.",
        "Fix SPF, DKIM and DMARC on the Domain check page — failures there are the single "
        "biggest cause of mail landing in spam, and they cost critical points here.",
        "Give a real signature: name, company, phone number and address.",
    ]),
    ("Your brochure", [
        "Linking to the brochure scores better than attaching it. An attachment from an "
        "unknown sender on first contact raises spam scores noticeably.",
        "If you do attach, use a PDF and keep it small.",
    ]),
]

SCORE_HELP_FOOTER = (
    "This is a guide based on what mail filters are known to react to, not a guarantee. "
    "Re-run the check after any change — the score updates as you type.")


class VariantEditor(Card):
    """One subject or body variant, with an enable toggle and a delete button."""

    def __init__(self, text: str = "", enabled: bool = True, multiline: bool = False,
                 on_change=None, on_delete=None, index: int = 1):
        super().__init__(kind="card", padding=10)
        self.multiline = multiline
        self._on_change = on_change

        self.enabled_box = checkbox(f"Variant {index}", enabled,
                                    on_change=lambda _c: self._changed())
        self.info = hint("", wrap=False)
        remove = danger_button("Remove", lambda: on_delete and on_delete(self), 90)
        self.add(row(self.enabled_box, self.info, None, remove))

        if multiline:
            self.editor = text_box("", monospace=True, lines=12)
        else:
            self.editor = line_edit("")
        self.add(self.editor)

        if text:
            if multiline:
                set_text(self.editor, text)
            else:
                self.editor.setText(text)

        # Counting spintax variants parses the text, so it is debounced like the score
        self._debounce = Debouncer(250, self)
        self._debounce.connect(self._changed)
        self.editor.textChanged.connect(lambda *_: self._debounce.poke())
        self._changed()

    def get_text(self) -> str:
        return get_text(self.editor) if self.multiline else self.editor.text()

    @property
    def enabled(self) -> bool:
        return self.enabled_box.isChecked()

    def set_index(self, index: int) -> None:
        self.enabled_box.setText(f"Variant {index}")

    def _changed(self) -> None:
        text = self.get_text()
        error = merge.validate_spintax(text)
        variants = merge.spintax_variants(text)
        if error:
            self.info.setText(f"⚠ {error}")
            set_tone(self.info, "error")
        elif variants > 1:
            self.info.setText(f"{variants:,} spintax variations")
            set_tone(self.info, "success")
        else:
            self.info.setText(f"{len(text)} characters")
            set_tone(self.info, "muted")
        if self._on_change:
            self._on_change()

    def insert(self, snippet: str) -> None:
        if self.multiline:
            self.editor.insertPlainText(snippet)
        else:
            self.editor.insert(snippet)
        self.editor.setFocus()
        self._changed()


class TemplatesPage(Page):
    def __init__(self, window):
        super().__init__(window)
        self.subject_editors: list[VariantEditor] = []
        self.body_editors: list[VariantEditor] = []
        self._set_id: int | None = None
        self._preview_index = 0
        self._preview_html = ""

        self.add_header(
            "Templates",
            "Write several subjects and bodies. The app picks a different combination for each "
            "recipient, so hundreds of identical messages never go out — that is what spam "
            "filters fingerprint.")

        self.tabs = TabBar()
        self.tabs.add("Subjects", self._build_subjects)
        self.tabs.add("Body", self._build_bodies)
        self.tabs.add("Signature", self._build_signature)
        self.tabs.add("Preview & score", self._build_preview)
        self.tabs.changed.connect(self._tab_changed)
        self.root.addWidget(self.tabs, 1)
        # The four tabs share the same content, so they are all built up front:
        # loading saved subjects has to be able to reach the Subjects tab even
        # while the Signature tab is the one on screen.
        self.tabs.build_all()

        self.save_status = muted("", wrap=False)
        self.root.addWidget(row(primary_button("Save templates", self.save, 170),
                                self.save_status, None))

        # Scoring runs after typing stops rather than on every keystroke
        self._score_debounce = Debouncer(450, self)
        self._score_debounce.connect(self.refresh_preview)

        self.tabs.set("Subjects")
        self.load()

    # --- merge tags ---------------------------------------------------------
    def _tag_bar(self, target) -> QWidget:
        from app.ui.widgets.common import flow_row

        container, layout = flow_row(4)
        label = hint("Insert:", wrap=False)
        layout.addWidget(label)
        for tag in importer.merge_tag_names()[:8]:
            snippet = "{{" + tag + "}}"
            layout.addWidget(small_button(snippet, lambda s=snippet: self._insert(target(), s)))
        layout.addWidget(small_button(
            "{spin|tax}", lambda: self._insert(target(), "{option one|option two}")))
        return container

    def _insert(self, editor: VariantEditor | None, snippet: str) -> None:
        if editor is None:
            self.notify("Add a variant first", "warn")
            return
        editor.insert(snippet)

    # --- subjects -----------------------------------------------------------
    def _build_subjects(self) -> QWidget:
        holder = QWidget()
        holder.setProperty("role", "plain")
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(muted(
            "Use {{Company}} so each subject is different, and spintax like {Custom|Bespoke} for "
            "extra variation."))
        layout.addWidget(self._tag_bar(
            lambda: self.subject_editors[-1] if self.subject_editors else None))

        self.subjects_area = ScrollPage(spacing=6)
        layout.addWidget(self.subjects_area, 1)

        layout.addWidget(row(
            primary_button("+ Add a subject line", lambda: self._add_subject(""), 190),
            secondary_button("Show me an example", self._example_subjects, 190), None))

        self._subjects_hint = muted(EMPTY_HINT)
        self.subjects_area.add(self._subjects_hint)
        self.subjects_area.add_stretch()
        self._refresh_empty_hints()
        return holder

    def _add_subject(self, text: str, enabled: bool = True) -> None:
        editor = VariantEditor(text, enabled, multiline=False, on_change=self._content_changed,
                               on_delete=self._remove_subject,
                               index=len(self.subject_editors) + 1)
        self.subjects_area.body_layout.insertWidget(
            self.subjects_area.body_layout.count() - 1, editor)
        self.subject_editors.append(editor)
        self._refresh_empty_hints()

    def _remove_subject(self, editor: VariantEditor) -> None:
        self.subject_editors.remove(editor)
        editor.setParent(None)
        editor.deleteLater()
        self._renumber(self.subject_editors)
        self._refresh_empty_hints()
        self._content_changed()

    # --- bodies -------------------------------------------------------------
    def _build_bodies(self) -> QWidget:
        holder = QWidget()
        holder.setProperty("role", "plain")
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(muted(
            "Write in simple HTML. The plain-text version sent alongside is generated "
            "automatically, and your signature plus the unsubscribe footer are added at the "
            "bottom of every message."))
        layout.addWidget(self._tag_bar(
            lambda: self.body_editors[-1] if self.body_editors else None))

        self.bodies_area = ScrollPage(spacing=6)
        layout.addWidget(self.bodies_area, 1)

        layout.addWidget(row(
            primary_button("+ Add a message", lambda: self._add_body(""), 190),
            secondary_button("Show me an example", self._example_body, 190), None))

        self._bodies_hint = muted(EMPTY_HINT)
        self.bodies_area.add(self._bodies_hint)
        self.bodies_area.add_stretch()
        self._refresh_empty_hints()
        return holder

    def _add_body(self, text: str, enabled: bool = True) -> None:
        editor = VariantEditor(text, enabled, multiline=True, on_change=self._content_changed,
                               on_delete=self._remove_body, index=len(self.body_editors) + 1)
        self.bodies_area.body_layout.insertWidget(
            self.bodies_area.body_layout.count() - 1, editor)
        self.body_editors.append(editor)
        self._refresh_empty_hints()

    def _remove_body(self, editor: VariantEditor) -> None:
        self.body_editors.remove(editor)
        editor.setParent(None)
        editor.deleteLater()
        self._renumber(self.body_editors)
        self._refresh_empty_hints()
        self._content_changed()

    @staticmethod
    def _renumber(editors: list[VariantEditor]) -> None:
        for index, editor in enumerate(editors, start=1):
            editor.set_index(index)

    def _refresh_empty_hints(self) -> None:
        """Friendly placeholder text while a tab has nothing in it yet."""
        for attr, editors in (("_subjects_hint", self.subject_editors),
                              ("_bodies_hint", self.body_editors)):
            label = getattr(self, attr, None)
            if label is not None:
                label.setVisible(not editors)

    # --- signature ----------------------------------------------------------
    def _build_signature(self) -> QWidget:
        holder = QWidget()
        holder.setProperty("role", "plain")
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(muted(
            "Added to the bottom of every message. A signature with a real name, phone number and "
            "address is a legitimacy signal that spam filters look for."))

        self.signature_box = text_box("", monospace=True)
        self.signature_box.textChanged.connect(self._content_changed)
        layout.addWidget(self.signature_box, 1)
        layout.addWidget(row(secondary_button("Show me an example",
                                              self._insert_example_signature, 210), None))
        return holder

    def _signature_text(self) -> str:
        box = getattr(self, "signature_box", None)
        if box is not None:
            return get_text(box)
        record = db.query_one("SELECT signature_html FROM template_sets ORDER BY id LIMIT 1")
        return (record["signature_html"] or "") if record else ""

    def _insert_example_signature(self) -> None:
        set_text(self.signature_box, EXAMPLE_SIGNATURE)
        self._content_changed()
        self.notify("Replace everything in [square brackets] with your own details", "info", 6000)

    def _example_subjects(self) -> None:
        for text in EXAMPLE_SUBJECTS:
            self._add_subject(text)
        self._content_changed()
        self.notify("Example subject lines added — edit them to suit your business",
                    "info", 6000)

    def _example_body(self) -> None:
        self._add_body(EXAMPLE_BODY)
        self._content_changed()
        self.notify("Example message added — replace the [square brackets] with your own words",
                    "info", 6000)

    # --- preview ------------------------------------------------------------
    def _build_preview(self) -> QWidget:
        holder = QWidget()
        holder.setProperty("role", "plain")
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(row(
            primary_button("Refresh preview", self.refresh_preview, 160),
            secondary_button("Next contact", self._next_contact, 140),
            secondary_button("Open in browser", self._open_in_browser, 160), None))

        self.preview_contact = muted("", wrap=False)
        layout.addWidget(self.preview_contact)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)

        left = Card(kind="card", padding=14)
        self.preview_subject = subheading("")
        self.preview_subject.setWordWrap(True)
        left.add(self.preview_subject)
        left.add(separator())
        self.preview_body = read_only_box("", role="", lines=18)
        left.add(self.preview_body, 1)
        splitter.addWidget(left)

        right = Card(kind="card", padding=14)
        help_button = small_button("?  How this works", self._explain_score)
        help_button.setToolTip("What the score measures, and how to write a better email")
        right.add(row(subheading("Spam score"), None, help_button))
        self.score_label = muted("—", wrap=False)
        self.score_label.setProperty("role", "score")
        right.add(self.score_label)
        self.score_verdict = muted("Refresh to check")
        right.add(self.score_verdict)
        right.add(separator())
        self.findings_area = ScrollPage(spacing=8)
        right.add(self.findings_area, 1)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)
        return holder

    def _explain_score(self) -> None:
        InfoDialog.show_for(self, "How the spam score works", SCORE_HELP_INTRO,
                            SCORE_HELP_SECTIONS, SCORE_HELP_FOOTER)

    def _sample_contact(self) -> dict:
        rows = db.query("SELECT * FROM contacts WHERE valid = 1 ORDER BY id LIMIT 50")
        if not rows:
            return {"email": "sample@example.com", "company": "Example Trading LLC",
                    "person": "Mr. Ahmed Khan", "extra_json": None}
        return merge.as_mapping(rows[self._preview_index % len(rows)])

    def _next_contact(self) -> None:
        self._preview_index += 1
        self.refresh_preview()

    def current_content(self) -> composer.Content:
        return composer.Content(
            subject_variants=[e.get_text() for e in self.subject_editors
                              if e.enabled and e.get_text().strip()],
            body_variants=[e.get_text() for e in self.body_editors
                           if e.enabled and e.get_text().strip()],
            signature_html=self._signature_text(),
            attach_mode=db.get_setting("attach_mode", "link"),
            attachment_path=db.get_setting("attachment_path", ""),
            link_url=db.get_setting("link_url", ""),
            link_text=db.get_setting("link_text", "View our brochure"),
            unsubscribe_note=bool(db.get_setting("unsubscribe_note", True)),
        )

    def _identity(self) -> composer.SenderIdentity:
        return composer.SenderIdentity(
            name=db.get_setting("sender_name", ""),
            email=db.get_setting("sender_email", "you@example.com"),
            reply_to=db.get_setting("reply_to", ""),
        )

    def refresh_preview(self) -> None:
        if self.tabs.page("Preview & score") is None:
            return
        content = self.current_content()
        if not content.subject_variants or not content.body_variants:
            self.preview_subject.setText("Add at least one subject and one body")
            self.preview_body.setPlainText("")
            return

        contact = self._sample_contact()
        context = merge.build_context(contact)
        identity = self._identity()

        self.preview_contact.setText(
            f"Previewing as: {contact.get('person') or '—'} · "
            f"{contact.get('company') or '—'} · {contact.get('email')}")

        # Rendering and scoring both parse the whole message; neither belongs on
        # the UI thread while the user is still typing.
        Task(jobs.build_preview, identity, context, content, self._preview_index).start(
            on_result=self._show_preview)

        dns_results = None
        page = self.window_.page("deliverability")
        if page is not None:
            dns_results = page.cached_results() or None

        Task(jobs.score_content, content, identity.email, identity.reply_to,
             importer.merge_tag_names(), dns_results).start(on_result=self._show_score)

    def _show_preview(self, result) -> None:
        subject, html, text = result
        self._preview_html = html
        self.preview_subject.setText(subject)
        self.preview_body.setPlainText(text)

    def _show_score(self, report: scorer.ScoreReport) -> None:
        if self._set_id:
            scorer.save_report(self._set_id, report)

        colour = theme.status_color(report.status)
        self.score_label.setText(str(report.score))
        self.score_label.setStyleSheet(
            f"color: {colour}; font-size: {theme.px(36)}px; font-weight: 700;")
        self.score_verdict.setText(f"Grade {report.grade} — {report.verdict}")
        self.score_verdict.setStyleSheet(f"color: {colour};")

        clear_layout(self.findings_area.body_layout)
        if not report.findings:
            self.findings_area.add(muted("No issues found."))
            self.findings_area.add_stretch()
            return

        tones = {"critical": "error", "high": "error", "medium": "warning", "low": "muted"}
        for finding in report.by_severity():
            block = QWidget()
            block.setProperty("role", "plain")
            inner = QVBoxLayout(block)
            inner.setContentsMargins(0, 0, 0, 0)
            inner.setSpacing(1)
            label = hint(f"{finding.severity.upper()} · {finding.category}")
            set_tone(label, tones.get(finding.severity, "muted"))
            inner.addWidget(label)
            inner.addWidget(muted(finding.message))
            if finding.fix:
                inner.addWidget(hint(finding.fix))
            self.findings_area.add(block)
        self.findings_area.add_stretch()

    def _open_in_browser(self) -> None:
        if not self._preview_html:
            self.refresh_preview()
            self.notify("Building the preview — press again in a moment", "info", 3000)
            return
        path = Path(tempfile.gettempdir()) / "homingpigeon_preview.html"
        path.write_text(self._preview_html, encoding="utf-8")
        webbrowser.open(path.as_uri())

    # --- persistence --------------------------------------------------------
    def _content_changed(self) -> None:
        self.save_status.setText("Unsaved changes")
        set_tone(self.save_status, "warning")
        if self.tabs.current() == "Preview & score":
            self._score_debounce.poke()

    def _tab_changed(self, name: str) -> None:
        if name == "Preview & score":
            self.refresh_preview()

    def save(self) -> None:
        subjects = [(e.get_text(), e.enabled) for e in self.subject_editors
                    if e.get_text().strip()]
        bodies = [(e.get_text(), e.enabled) for e in self.body_editors if e.get_text().strip()]

        if not subjects or not bodies:
            self.notify("Add at least one subject and one body before saving", "warn")
            return

        signature = self._signature_text()
        if self._set_id is None:
            self._set_id = db.execute(
                "INSERT INTO template_sets(name, signature_html, created_at) VALUES (?, ?, ?)",
                ("Default", signature, db.now()))
        else:
            db.execute("UPDATE template_sets SET signature_html = ? WHERE id = ?",
                       (signature, self._set_id))

        db.execute("DELETE FROM subjects WHERE set_id = ?", (self._set_id,))
        db.execute("DELETE FROM bodies WHERE set_id = ?", (self._set_id,))
        db.execute_many(
            "INSERT INTO subjects(set_id, text, enabled, position) VALUES (?, ?, ?, ?)",
            [(self._set_id, text, int(enabled), index)
             for index, (text, enabled) in enumerate(subjects)])
        db.execute_many(
            "INSERT INTO bodies(set_id, name, html, enabled, position) VALUES (?, ?, ?, ?, ?)",
            [(self._set_id, f"Variant {index + 1}", text, int(enabled), index)
             for index, (text, enabled) in enumerate(bodies)])

        db.set_setting("template_set_id", self._set_id)
        self.save_status.setText("Saved")
        set_tone(self.save_status, "success")
        self.notify("Templates saved", "success")
        self.window_.refresh_status()
        self.refresh_preview()

    def load(self) -> None:
        record = db.query_one("SELECT * FROM template_sets ORDER BY id LIMIT 1")
        if record is None:
            # First launch: everything stays empty until the user writes or
            # loads an example. Nothing is pre-filled on their behalf.
            return

        self._set_id = record["id"]
        box = getattr(self, "signature_box", None)
        if box is not None:
            set_text(box, record["signature_html"] or "")

        for editor in self.subject_editors + self.body_editors:
            editor.setParent(None)
            editor.deleteLater()
        self.subject_editors.clear()
        self.body_editors.clear()

        for subject in db.query("SELECT * FROM subjects WHERE set_id = ? ORDER BY position",
                                (self._set_id,)):
            self._add_subject(subject["text"], bool(subject["enabled"]))
        for record_body in db.query("SELECT * FROM bodies WHERE set_id = ? ORDER BY position",
                                    (self._set_id,)):
            self._add_body(record_body["html"], bool(record_body["enabled"]))

        self.save_status.setText("")

    def on_show(self) -> None:
        if self.tabs.current() == "Preview & score":
            self.refresh_preview()
