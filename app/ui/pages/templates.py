"""My message: several subjects and bodies, a signature, a live preview and the spam score."""
from __future__ import annotations

import random

import tempfile
import webbrowser
from pathlib import Path

from PyQt6 import sip
from PyQt6.QtCore import QEvent, Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QFileDialog, QInputDialog, QSplitter, QVBoxLayout, QWidget

from app.core import composer, db, examples, importer, merge, scorer
from app.i18n import t
from app.ui import theme
from app.ui.pages.base import Page
from app.ui.widgets.common import (Card, ScrollPage, TabBar, body, clear_layout, danger_button,
                                   heading, hint, muted, primary_button, row, secondary_button,
                                   separator, set_tone, small_button, subheading)
from app.ui.widgets.dialogs import ChoiceDialog, InfoDialog
from app.ui.widgets.inputs import Debouncer, checkbox, get_text, read_only_box, set_text, text_box
from app.workers import jobs
from app.workers.base import Task

# Examples are never filled in automatically. The app starts blank and these are
# only inserted when the user presses "Show me an example". They live in
# app/core/examples.py, one set per language, written to reach the main inbox.
# These names are the English set, kept for the tests and anything else that
# wants a fixed example.
EXAMPLE_SUBJECTS = examples.EXAMPLES["en"]["subjects"]
EXAMPLE_BODIES = examples.EXAMPLES["en"]["bodies"]
EXAMPLE_BODY = EXAMPLE_BODIES[0]
EXAMPLE_SIGNATURE = examples.EXAMPLES["en"]["signature"]

SEVERITY_NAMES = {"critical": "Critical", "high": "High", "medium": "Medium", "low": "Low"}

EMPTY_HINT = ("Nothing here yet.\n\n"
              "Press \"Show me an example\" to start from a ready-made one you can change, "
              "or the Add button to write your own from scratch.")

# What each "personal touch" button puts in, in words a first-time user follows
TAG_HELP = {
    "FirstName": "Their first name",
    "FullName": "Their full name",
    "Company": "Their company's name",
    "Email": "Their email address",
    "Domain": "Their company's web address, taken from their email",
}

# What the "?" at the top of the page opens. Written for someone who has never
# heard of HTML or merge tags: what to do, in the order they will do it.
PAGE_HELP_INTRO = (
    "You do not need to know any code. Type your email the way you would in Gmail or "
    "Outlook and the app takes care of the rest. Nothing is sent from this page: you send "
    "from 'Send emails' when you are ready.")

PAGE_HELP_SECTIONS = [
    ("The quick way", [
        "Step 1. Open the Subjects tab and write 3 or more subject lines. Press "
        "\"Show me an example\" if you would like a head start.",
        "Step 2. Open the Message tab and write 2 or 3 versions of your email.",
        "Step 3. Open the Signature tab and add your name, company, phone number and address.",
        "Step 4. Open Preview & score to see exactly what one person will receive. Aim for a "
        "score of 85 or more.",
        "Step 5. Press Save at the bottom of the page.",
        "Started from an example? Replace everything in [square brackets] with your own words.",
    ]),
    ("Reaching the main inbox, not spam or Promotions", [
        "Gmail sorts email by how much it looks like a person writing. Marketing goes to the "
        "Promotions tab, and anything that looks like a trick goes to spam. Write the way you "
        "would write to one colleague.",
        "Greet each person by name: \"Hi {{FirstName}},\".",
        "Keep it short: 50 to 150 words in three or four short paragraphs.",
        "No links in the first email. Put your website in the signature as plain text, and "
        "offer the brochure instead of linking to it: \"Shall I send over our brochure?\".",
        "No pictures, logos, bold text, colours or bullet points.",
        "No sales words such as free, offer, discount, deal, limited time or order now, and no "
        "exclamation marks.",
        "End with one simple question they can answer in a line. Replies tell Gmail people "
        "want your emails, which is the strongest signal there is.",
        "Switch the unsubscribe line off on the Signature tab for personal outreach. It marks "
        "an email as a mass mailing. Replies asking to be removed are still handled.",
        "Send slowly, from your own company address, with the Domain check page all green.",
        "Preview & score tells you where the email is likely to land and what to change.",
    ]),
    ("Why several subjects and messages?", [
        "The subject is the line people see in their inbox before they open your email. The "
        "message is the email itself.",
        "Spam filters notice hundreds of identical emails. The app picks a different subject "
        "and message for each person, so no two emails look the same.",
        "Untick the box next to a version to keep it without using it.",
        "When you have written a lot, scroll the page to see every version. A long subject or "
        "message also scrolls inside its own box.",
    ]),
    ("Typing your message", [
        "Press Enter (or Ctrl+Enter) to start a new line.",
        "Leave an empty line between paragraphs.",
        "Start a line with a dash and a space, like \"- Fast delivery\", to make a bullet point.",
        "To make words bold or turn them into a link, select them and press Bold or Link above "
        "the message.",
        "A subject is always sent as one line. If you press Enter in a subject, the lines are "
        "joined with a space.",
    ]),
    ("Personal touches like {{FirstName}}", [
        "Words in double curly brackets are filled in for each person from your contact list.",
        "\"Hi {{FirstName}}\" reaches Sarah as \"Hi Sarah\" and Omar as \"Hi Omar\". "
        "{{Company}} becomes their company's name.",
        "Click into a box, then press a button in the \"Personal touch\" row to drop one in "
        "where your cursor is. Extra columns from your contact spreadsheet appear there too.",
        "Type them exactly as shown, with two brackets on each side.",
    ]),
    ("Mixing words like {Hi|Hello}", [
        "Put a few choices inside single curly brackets, separated by a straight line, and each "
        "person gets one of them at random.",
        "\"{Hi|Hello|Good morning} {{FirstName}}\" sends \"Hi Sarah\" to one person and "
        "\"Good morning Omar\" to the next.",
        "The straight line | is Shift and the backslash key, usually just above Enter.",
        "Every { needs a matching }. A warning appears next to the version's name if one "
        "is missing.",
    ]),
    ("Set it all up from a spreadsheet", [
        "Press \"Import from a spreadsheet\" at the top of the page to bring in subjects and "
        "messages in one go.",
        "Put subject lines in a column headed Subject and messages in a column headed Message, "
        "one per row. A column headed Signature is optional.",
        "In Excel, press Alt+Enter inside a cell to start a new line in a message.",
        "Not sure of the layout? \"Get a blank sheet\" saves one ready to fill in.",
    ]),
    ("The unsubscribe line", [
        "The Signature tab has a switch for the small unsubscribe line at the bottom of every "
        "email.",
        "Gmail tends to put emails with that line in the Promotions tab. Switch it off and "
        "your email reads like an ordinary one-to-one message.",
        "Either way, anyone who replies with \"unsubscribe\" is taken off your list "
        "automatically when the inbox is checked.",
    ]),
    ("Already know HTML?", [
        "You can still use it. Once a message contains <p> or <br>, the app sends it exactly as "
        "written and stops adding line breaks for you.",
    ]),
    ("Handy keys", [
        "Ctrl+S saves.",
        "Tab moves to the next box.",
    ]),
]

PAGE_HELP_FOOTER = (
    "Not sure how it will look? Preview & score shows the finished email, and "
    "\"Open in browser\" shows it the way most email programs will.")


# What the "?" next to the score opens. The wording is deliberately about what
# to do differently, not about the rule engine: the point is that the reader
# should write a better email afterwards.
SCORE_HELP_INTRO = (
    "The score reads the finished email exactly as the person on the left will receive it: "
    "subject, message, brochure link, signature and unsubscribe line together, with their "
    "details filled in. It starts at 100 and each problem found takes points off. It also "
    "checks every subject and message you have written, and your domain settings. Press "
    "Next contact to score another person's version. Nothing is sent anywhere: the whole "
    "check runs on your computer.")

SCORE_HELP_SECTIONS = [
    ("How much each problem costs", [
        "Critical −25: something that will get the mail rejected or is outright deceptive.",
        "High −12: a strong spam signal that filters weight heavily.",
        "Medium −6: a habit that hurts across a large send.",
        "Low −3: a small improvement worth making.",
        "85 and above reaches the inbox reliably; below 70 is risky; below 50 will be filtered.",
    ]),
    ("Main inbox, Promotions or spam", [
        "Under the score is where the email is likely to land in Gmail.",
        "Main inbox: it reads like a person writing. This is what you want.",
        "Promotions tab: it looks like marketing. The items marked Promotions tab say what "
        "to change: usually the unsubscribe line, links, pictures, formatting or sales words.",
        "Spam: there is a serious problem. Fix the critical and high items first.",
        "This is an estimate. Gmail does not publish its rules, so it is based on what Gmail "
        "is known to look at.",
    ]),
    ("Your subject lines", [
        "Keep them under about 60 characters, or phones cut them off.",
        "Sentence case only. Mostly-capitals reads as shouting and is penalised heavily.",
        "At most one exclamation mark, ideally none.",
        "Avoid promotional wording: free, urgent, act now, limited time, discount, "
        "guarantee, winner, click here.",
        "Never fake a thread with 'Re:' or 'Fwd:' on a first contact. That is treated as "
        "deception and costs the most of any single check.",
        "Put {{Company}} in the subject so no two recipients get an identical one.",
    ]),
    ("Your message", [
        "Aim for 50 to 150 words. Very short mail with a link looks like phishing; long first "
        "emails read like newsletters.",
        "Write in plain business language. Five or more sales-pitch phrases is a heavy penalty.",
        "No links is best in a first email; one at most, to your own website, over https. Link "
        "shorteners and bare IP addresses are penalised hard because they hide where a link "
        "goes.",
        "Lead with text, not images. An image-heavy email with little text is a classic "
        "spam pattern, and most email programs block images by default anyway.",
        "End with one simple question, and greet the person by name.",
    ]),
    ("Variety, the one most people miss", [
        "Hundreds of identical messages are what filters fingerprint, and it is the most "
        "common reason a perfectly polite campaign gets blocked.",
        "Write 3 or more subject lines and 2 or 3 versions of the message.",
        "Use spintax like {Hi|Hello|Good morning} to multiply the combinations further.",
        "The check wants at least 10 genuinely different versions of the email.",
    ]),
    ("Who you are", [
        "Send from your own company domain. A free Gmail or Outlook address cannot pass "
        "DMARC for your brand and is filtered much harder for bulk sending.",
        "Keep Reply-To on the same domain as From. A mismatch is a phishing pattern.",
        "Fix SPF, DKIM and DMARC on the Domain check page. Failures there are the single "
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
    "Re-run the check after any change. The score updates as you type.")


class VariantEditor(Card):
    """One subject or body variant, with an enable toggle and a delete button.

    Both kinds are multi-line boxes of a fixed height that scroll on their own,
    so a long message never pushes the rest of the list off the page, and the
    page itself scrolls to show every variant.
    """

    def __init__(self, text: str = "", enabled: bool = True, multiline: bool = False,
                 on_change=None, on_delete=None, index: int = 1, on_focus=None):
        super().__init__(kind="card", padding=10)
        self.multiline = multiline
        self.noun = "Message" if multiline else "Subject"
        self._on_change = on_change
        self._on_focus = on_focus

        self.enabled_box = checkbox(self._numbered(index), enabled,
                                    on_change=lambda _c: self._changed())
        self.enabled_box.setToolTip(t("Untick to keep this one without sending it"))
        self.info = hint("", wrap=False)
        remove = danger_button("Remove", lambda: on_delete and on_delete(self), 90)
        self.add(row(self.enabled_box, self.info, None, remove))

        if multiline:
            self.editor = text_box(
                "Type your message here, just like a normal email.\n\n"
                "Press Enter for a new line and leave an empty line between paragraphs.",
                lines=12)
        else:
            self.editor = text_box(
                "Type a subject line, for example: A quick question for {{Company}}", lines=2)
        self.add(self.editor)
        self.editor.installEventFilter(self)

        if text:
            set_text(self.editor, text)

        # Counting spintax variants parses the text, so it is debounced like the score
        self._debounce = Debouncer(250, self)
        self._debounce.connect(self._changed)
        self.editor.textChanged.connect(lambda *_: self._debounce.poke())
        self._changed()

    def eventFilter(self, obj, event):  # noqa: N802 - Qt naming
        if obj is self.editor and event.type() == QEvent.Type.FocusIn and self._on_focus:
            self._on_focus(self)
        return False

    def get_text(self) -> str:
        return get_text(self.editor)

    @property
    def enabled(self) -> bool:
        return self.enabled_box.isChecked()

    def set_index(self, index: int) -> None:
        self.enabled_box.setText(self._numbered(index))

    def _numbered(self, index: int) -> str:
        return t("Message {number}", number=index) if self.multiline \
            else t("Subject {number}", number=index)

    def _changed(self) -> None:
        text = self.get_text()
        error = merge.validate_spintax(text)
        variants = merge.spintax_variants(text)
        if error:
            self.info.setText(t(f"⚠ {error}"))
            set_tone(self.info, "error")
        elif variants > 1:
            self.info.setText(t("{variants:,} mixed versions", variants=variants))
            set_tone(self.info, "success")
        else:
            self.info.setText(t("{count} characters", count=len(text)))
            set_tone(self.info, "muted")
        if self._on_change:
            self._on_change()

    def insert(self, snippet: str) -> None:
        self.editor.insertPlainText(snippet)
        self.editor.setFocus()
        self._changed()

    def wrap_selection(self, before: str, after: str, placeholder: str) -> None:
        """Put ``before`` and ``after`` round the selected words, or round a placeholder."""
        cursor = self.editor.textCursor()
        # QTextCursor marks line breaks in a selection with U+2029
        chosen = cursor.selectedText().replace(" ", "\n")
        cursor.insertText(before + (chosen or placeholder) + after)
        if not chosen:
            # Leave the placeholder selected so typing replaces it
            end = cursor.position() - len(after)
            cursor.setPosition(end - len(placeholder))
            cursor.setPosition(end, cursor.MoveMode.KeepAnchor)
            self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    def insert_list(self) -> None:
        """Bullet points: the selected lines become the points, or two to type over."""
        cursor = self.editor.textCursor()
        chosen = cursor.selectedText().replace(" ", "\n").strip("\n")
        points = [line.strip() for line in chosen.splitlines() if line.strip()] \
            or ["First point", "Second point"]
        # A message laid out in HTML would ignore "- ", so it gets a real list
        if composer.uses_html(self.get_text()):
            block = "<ul>\n" + "\n".join(f"  <li>{p}</li>" for p in points) + "\n</ul>"
        else:
            block = "\n".join(f"- {p}" for p in points)
        before = "" if cursor.atBlockStart() or cursor.hasSelection() else "\n"
        cursor.insertText(before + block + "\n")
        self.editor.setFocus()


class TemplatesPage(Page):
    def __init__(self, window):
        super().__init__(window)
        self.subject_editors: list[VariantEditor] = []
        self.body_editors: list[VariantEditor] = []
        self._focused: dict[bool, VariantEditor] = {}   # multiline -> last box typed in
        self._set_id: int | None = None
        self._preview_index = 0
        self._subject_pick = 0
        self._body_pick = 0
        self._preview_html = ""
        self._tag_layouts: dict[bool, object] = {}
        self._tag_names: list[str] = []

        # Everything above the Save button scrolls as one page. It used to be a
        # fixed frame with a small scrolling list squeezed inside it, and once a
        # few subjects or messages were added there was no room left to see them.
        scale = theme.text_scale()
        self.scroll = ScrollPage(margins=(0, 0, round(8 * scale), 0), spacing=round(10 * scale))
        self.root.addWidget(self.scroll, 1)

        help_button = secondary_button("?  How to write your email", self._explain_page)
        help_button.setToolTip(t("A short guide to this page, in plain English"))
        import_button = secondary_button("Import from a spreadsheet...", self._import_sheet)
        import_button.setToolTip(t("Bring in subject lines and messages from an Excel or CSV file"))
        sample_button = secondary_button("Get a blank sheet...", self._save_sample_sheet)
        sample_button.setToolTip(t("Save a spreadsheet laid out ready for you to fill in"))
        self.scroll.add(row(heading("My message"), None, import_button, sample_button,
                            help_button))
        self.scroll.add(muted(
            "Write what you want to say. Give the app a few versions of your subject and "
            "message and it mixes them, so every person gets a slightly different email. "
            "That keeps you out of spam folders. Press the ? button above for a quick guide."))

        self.tabs = TabBar()
        self.tabs.add("Subjects", self._build_subjects)
        self.tabs.add("Message", self._build_bodies)
        self.tabs.add("Signature", self._build_signature)
        self.tabs.add("Preview & score", self._build_preview)
        self.tabs.changed.connect(self._tab_changed)
        self.scroll.add(self.tabs, 1)
        # The four tabs share the same content, so they are all built up front:
        # loading saved subjects has to be able to reach the Subjects tab even
        # while the Signature tab is the one on screen.
        self.tabs.build_all()

        self.save_status = muted("", wrap=False)
        save = primary_button("Save", self.save, 170)
        save.setToolTip(t("Save your subjects, messages and signature (Ctrl+S)"))
        self.root.addWidget(row(save, self.save_status, None))

        shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Save), self)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(self.save)

        # Scoring runs after typing stops rather than on every keystroke
        self._score_debounce = Debouncer(450, self)
        self._score_debounce.connect(self.refresh_preview)

        self.tabs.set("Subjects")
        self.load()

    def _explain_page(self) -> None:
        InfoDialog.show_for(self, "How to write your email", PAGE_HELP_INTRO,
                            PAGE_HELP_SECTIONS, PAGE_HELP_FOOTER)

    # --- merge tags ---------------------------------------------------------
    def _target(self, multiline: bool) -> VariantEditor | None:
        """The box the toolbar buttons act on: the last one typed in, else the last one."""
        editors = self.body_editors if multiline else self.subject_editors
        focused = self._focused.get(multiline)
        if focused in editors:
            return focused
        return editors[-1] if editors else None

    def _remember_focus(self, editor: VariantEditor) -> None:
        self._focused[editor.multiline] = editor

    def _tag_bar(self, multiline: bool) -> QWidget:
        from app.ui.widgets.common import flow_row

        container, layout = flow_row(4)
        self._tag_layouts[multiline] = layout
        self._fill_tag_bar(multiline, importer.merge_tag_names())
        return container

    def _fill_tag_bar(self, multiline: bool, names: list[str]) -> None:
        """One button per tag: the built-in ones, then every column of the spreadsheet."""
        layout = self._tag_layouts[multiline]
        clear_layout(layout)
        self._tag_names = list(names)
        label = hint("Personal touch:", wrap=False)
        label.setToolTip(t("Filled in for each person from your contact list"))
        layout.addWidget(label)
        for tag in names:
            snippet = "{{" + tag + "}}"
            button = small_button(snippet, lambda s=snippet: self._insert(multiline, s))
            button.setToolTip(t(TAG_HELP.get(tag, t("The {tag} column from your contact list",
                                                    tag=tag))))
            layout.addWidget(button)
        mix = small_button("{Hi|Hello}", lambda: self._insert(multiline, "{Hi|Hello}"))
        mix.setToolTip(t("Mix words: each person gets one of the choices at random. "
                       "Change them to your own, separated by |"))
        layout.addWidget(mix)

    def _refresh_tag_bars(self) -> None:
        """A new import adds columns; show them without needing a restart."""
        names = importer.merge_tag_names()
        if names == self._tag_names:
            return
        for multiline in list(self._tag_layouts):
            self._fill_tag_bar(multiline, names)

    def _format_bar(self) -> QWidget:
        """Bold, link and bullet points for people who have never written HTML."""
        from app.ui.widgets.common import flow_row

        container, layout = flow_row(4)
        layout.addWidget(hint("Style:", wrap=False))
        bold = small_button("Bold", lambda: self._format("bold"))
        bold.setToolTip(t("Select some words, then press this to make them bold"))
        link = small_button("Link", lambda: self._format("link"))
        link.setToolTip(t("Select some words, then press this to turn them into a link"))
        bullets = small_button("Bullet points", lambda: self._format("list"))
        bullets.setToolTip(t("Turn the selected lines into bullet points, or start a new list"))
        for button in (bold, link, bullets):
            layout.addWidget(button)
        return container

    def _insert(self, multiline: bool, snippet: str) -> None:
        editor = self._target(multiline)
        if editor is None:
            self.notify("Add a subject or message first", "warn")
            return
        editor.insert(snippet)

    def _format(self, kind: str) -> None:
        editor = self._target(True)
        if editor is None:
            self.notify("Add a message first", "warn")
            return
        if kind == "bold":
            editor.wrap_selection("<strong>", "</strong>", "bold words")
        elif kind == "list":
            editor.insert_list()
        else:
            address, ok = QInputDialog.getText(
                self, t("Add a link"), t("Web address the link opens, for example www.yourcompany.com"))
            address = address.strip()
            if not ok or not address:
                return
            if "://" not in address and not address.startswith("mailto:"):
                address = "https://" + address
            editor.wrap_selection(f'<a href="{address}">', "</a>", "link text")

    def _list_holder(self) -> tuple[QWidget, QVBoxLayout]:
        holder = QWidget()
        holder.setProperty("role", "plain")
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        return holder, layout

    def _reveal(self, editor: VariantEditor) -> None:
        """Scroll a newly added box into view and put the cursor in it."""
        def show() -> None:
            if sip.isdeleted(self) or sip.isdeleted(editor):
                return
            self.scroll.ensureWidgetVisible(editor, 0, round(40 * theme.text_scale()))
            editor.editor.setFocus()

        # Once the layout has made room for it
        QTimer.singleShot(30, show)

    # --- subjects -----------------------------------------------------------
    def _build_subjects(self) -> QWidget:
        holder = QWidget()
        holder.setProperty("role", "plain")
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(muted(
            "The subject is the line people see in their inbox before they open your email. "
            "Write 3 or more and each person gets one of them."))
        layout.addWidget(self._tag_bar(False))

        self.subjects_list, self.subjects_layout = self._list_holder()
        layout.addWidget(self.subjects_list)
        self._subjects_hint = muted(EMPTY_HINT)
        self.subjects_layout.addWidget(self._subjects_hint)

        layout.addWidget(row(
            primary_button("+ Add a subject line", self._new_subject, 190),
            secondary_button("Show me an example", self._example_subjects, 190), None))
        layout.addStretch(1)
        self._refresh_empty_hints()
        return holder

    def _new_subject(self) -> None:
        self._reveal(self._add_subject(""))

    def _add_subject(self, text: str, enabled: bool = True) -> VariantEditor:
        editor = VariantEditor(text, enabled, multiline=False, on_change=self._content_changed,
                               on_delete=self._remove_subject,
                               index=len(self.subject_editors) + 1,
                               on_focus=self._remember_focus)
        self.subjects_layout.addWidget(editor)
        self.subject_editors.append(editor)
        self._refresh_empty_hints()
        return editor

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
            "Type your message just like a normal email: press Enter for a new line and leave "
            "an empty line between paragraphs. Write 2 or 3 versions. Your signature (and the "
            "unsubscribe line, if it is switched on in the Signature tab) is added at the bottom "
            "for you."))
        layout.addWidget(self._tag_bar(True))
        layout.addWidget(self._format_bar())

        self.bodies_list, self.bodies_layout = self._list_holder()
        layout.addWidget(self.bodies_list)
        self._bodies_hint = muted(EMPTY_HINT)
        self.bodies_layout.addWidget(self._bodies_hint)

        layout.addWidget(row(
            primary_button("+ Add a message", self._new_body, 190),
            secondary_button("Show me an example", self._example_body, 190), None))
        layout.addStretch(1)
        self._refresh_empty_hints()
        return holder

    def _new_body(self) -> None:
        self._reveal(self._add_body(""))

    def _add_body(self, text: str, enabled: bool = True) -> VariantEditor:
        editor = VariantEditor(text, enabled, multiline=True, on_change=self._content_changed,
                               on_delete=self._remove_body, index=len(self.body_editors) + 1,
                               on_focus=self._remember_focus)
        self.bodies_layout.addWidget(editor)
        self.body_editors.append(editor)
        self._refresh_empty_hints()
        return editor

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
            "Added to the bottom of every message. Type it the way you want it to look, with "
            "your name, job title, company, phone number and address each on its own line. A "
            "real signature helps your email reach the inbox."))

        self.signature_box = text_box(
            "For example:\nSarah Jones\nSales manager, Jones Supplies\nPhone: ...")
        self.signature_box.setMinimumHeight(self.signature_box.fontMetrics().lineSpacing() * 12)
        self.signature_box.textChanged.connect(self._content_changed)
        layout.addWidget(self.signature_box, 1)
        layout.addWidget(row(secondary_button("Show me an example",
                                              self._insert_example_signature, 210), None))

        layout.addWidget(separator())
        self.unsubscribe_box = checkbox(
            "Add an unsubscribe line at the bottom of every email",
            bool(db.get_setting("unsubscribe_note", True)), on_change=self._unsubscribe_changed)
        layout.addWidget(self.unsubscribe_box)
        layout.addWidget(hint(
            "The line reads: \"You received this message because we believe it is relevant to "
            "your business. If it is not, reply with Unsubscribe and we will remove you "
            "immediately.\" It also adds the Unsubscribe button Gmail and Outlook show at the "
            "top of an email.\n\n"
            "Gmail often files emails like that under Promotions. Switch it off and your email "
            "looks like an ordinary one-to-one message. Anyone who replies asking to be removed "
            "is still taken off your list automatically, whichever you choose. The setting is "
            "saved as soon as you change it."))
        return holder

    def _unsubscribe_changed(self, on: bool) -> None:
        db.set_setting("unsubscribe_note", bool(on))
        self.notify("Unsubscribe line switched on" if on else
                    "Unsubscribe line switched off. Replies asking to unsubscribe are still "
                    "handled automatically", "success", 5000)
        if self.tabs.current() == "Preview & score":
            self._score_debounce.poke()

    def _signature_text(self) -> str:
        box = getattr(self, "signature_box", None)
        if box is not None:
            return get_text(box)
        record = db.query_one("SELECT signature_html FROM template_sets ORDER BY id LIMIT 1")
        return (record["signature_html"] or "") if record else ""

    def _insert_example_signature(self) -> None:
        set_text(self.signature_box, examples.for_language()["signature"])
        self._content_changed()
        self.notify("Replace everything in [square brackets] with your own details", "info", 6000)

    def _example_subjects(self) -> None:
        subjects = examples.for_language()["subjects"]
        for text in subjects:
            self._add_subject(text)
        self._content_changed()
        self.notify(t("{count} example subject lines added. Edit them to suit your business",
                      count=len(subjects)), "info", 6000)

    def _example_body(self) -> None:
        """Add all three examples, not one.

        One body is a finding in its own right: identical bodies sent in volume
        are the easiest thing in the world to fingerprint, and the score says so.
        """
        bodies = examples.for_language()["bodies"]
        for text in bodies:
            self._add_body(text)
        self._content_changed()
        self.notify(t("{count} example messages added. Replace the [square brackets] with your own "
                      "words", count=len(bodies)), "info", 6000)

    # --- import from a spreadsheet ------------------------------------------
    def _import_sheet(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, t("Choose a spreadsheet of subjects and messages"), "",
            t("Spreadsheets (*.xlsx *.xls *.csv);;All files (*.*)"))
        if not path:
            return
        self.notify("Reading the spreadsheet...", "info", 2000)
        Task(importer.read_templates, Path(path)).start(
            on_result=self.guard(self._sheet_ready),
            on_error=self.guard(
                lambda message: self.notify(t("Could not read that file: {message}",
                                              message=message), "error", 8000)))

    def _sheet_ready(self, sheet: importer.TemplateSheet) -> None:
        if not sheet.subjects and not sheet.bodies:
            InfoDialog.show_for(
                self, "Nothing found to import",
                "No subject lines or messages were found in that file.",
                [("How to lay out the sheet", [
                    "Put subject lines in a column headed Subject, one per row.",
                    "Put messages in a column headed Message, one per row.",
                    "A column headed Signature is optional.",
                    "Press \"Get a blank sheet\" for a file that is ready to fill in.",
                ])])
            return

        found = []
        if sheet.subjects:
            found.append(t("{count} subject line(s)", count=len(sheet.subjects)))
        if sheet.bodies:
            found.append(t("{count} message(s)", count=len(sheet.bodies)))
        if sheet.signature:
            found.append(t("a signature"))
        summary = t("Found {things}.", things=", ".join(found))

        mode = "add"
        if any(e.get_text().strip() for e in self.subject_editors + self.body_editors):
            mode = ChoiceDialog.ask(
                self, "Import subjects and messages",
                summary + "\n\n" + t("You already have some written. What should happen to "
                                     "them?"),
                [("add", "Keep mine and add these", "primary"),
                 ("replace", "Replace mine with these", "danger"),
                 (None, "Cancel", "secondary")])
            if mode is None:
                return

        if mode == "replace":
            if sheet.subjects:
                for editor in list(self.subject_editors):
                    self._remove_subject(editor)
            if sheet.bodies:
                for editor in list(self.body_editors):
                    self._remove_body(editor)

        for text in sheet.subjects:
            self._add_subject(text)
        for text in sheet.bodies:
            self._add_body(text)
        if sheet.signature and (mode == "replace" or not self._signature_text().strip()):
            set_text(self.signature_box, sheet.signature)
        self._content_changed()

        unknown = sorted({tag for text in sheet.subjects + sheet.bodies
                          for tag in merge.unresolved_tags(text, importer.merge_tag_names())})
        message = summary + " " + t("Check them over, then press Save.")
        if unknown:
            message += " " + t("Some tags do not match a column in your contacts: {tags}",
                               tags=", ".join("{{" + tag + "}}" for tag in unknown))
        self.notify(message, "warn" if unknown else "success", 9000)
        self.tabs.set("Subjects" if sheet.subjects else "Message")

    def _save_sample_sheet(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self, t("Save a blank sheet for your subjects and messages"), "my message.xlsx",
            t("Excel (*.xlsx)"))
        if not path:
            return
        sample = examples.for_language()
        Task(importer.write_template_sample, path, sample["subjects"], sample["bodies"],
             sample["signature"]).start(
            on_result=self.guard(lambda saved: self.notify(
                t("Saved {name}. It has examples in it: change them, save the file and import "
                  "it here", name=Path(saved).name), "success", 8000)),
            on_error=self.guard(lambda message: self.notify(
                t("Could not save the sheet: {message}", message=message), "error", 8000)))

    # --- preview ------------------------------------------------------------
    def _build_preview(self) -> QWidget:
        holder = QWidget()
        holder.setProperty("role", "plain")
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        next_button = secondary_button("Next contact", self._next_contact, 140)
        next_button.setToolTip(t("Another recipient, with a different subject and message "
                               "drawn from your lists"))
        layout.addWidget(row(
            primary_button("Refresh preview", self.refresh_preview, 160),
            next_button,
            secondary_button("Open in browser", self._open_in_browser, 160), None))

        self.preview_contact = muted("", wrap=False)
        layout.addWidget(self.preview_contact)
        self.preview_variant = hint("", wrap=False)
        layout.addWidget(self.preview_variant)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)

        left = Card(kind="card", padding=14)
        self.preview_subject = subheading("")
        self.preview_subject.setWordWrap(True)
        left.add(self.preview_subject)
        left.add(separator())
        self.preview_body = read_only_box("", role="", lines=12)
        self.preview_body.setMaximumHeight(16777215)   # at least 12 lines, then fill the card
        left.add(self.preview_body, 1)
        splitter.addWidget(left)

        right = Card(kind="card", padding=14)
        help_button = small_button("?  How this works", self._explain_score)
        help_button.setToolTip(t("What the score measures, and how to write a better email"))
        right.add(row(subheading("Spam score"), None, help_button))
        self.score_label = muted("-", wrap=False)
        self.score_label.setProperty("role", "score")
        right.add(self.score_label)
        self.score_verdict = muted("Refresh to check")
        right.add(self.score_verdict)
        self.score_landing = body("")
        self.score_landing.setVisible(False)
        right.add(self.score_landing)
        right.add(separator())
        self.findings_area = ScrollPage(spacing=8)
        right.add(self.findings_area, 1)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        # The page scrolls, so the preview needs a height of its own to fill
        splitter.setMinimumHeight(round(460 * theme.text_scale()))
        layout.addWidget(splitter, 1)
        return holder

    def _explain_score(self) -> None:
        InfoDialog.show_for(self, "How the spam score works", SCORE_HELP_INTRO,
                            SCORE_HELP_SECTIONS, SCORE_HELP_FOOTER)

    def _sample_contact(self) -> dict:
        rows = db.query("SELECT * FROM contacts WHERE valid = 1 ORDER BY id LIMIT 50")
        if not rows:
            return dict(scorer.SAMPLE_CONTACT)
        return merge.as_mapping(rows[self._preview_index % len(rows)])

    @staticmethod
    def _another(current: int, count: int) -> int:
        """A different index from ``current``, at random, for a list of ``count``.

        Random alone repeats itself often enough that pressing the button twice
        can show the same variant, which looks broken. Stepping on when the draw
        collides keeps every press visibly different, and that is also how
        VariantCycler behaves during a real send.
        """
        if count <= 1:
            return 0
        choice = random.randrange(count)
        return (current + 1) % count if choice == current % count else choice

    def _next_contact(self) -> None:
        """Show the next recipient, with a freshly drawn subject and body."""
        self._preview_index += 1
        content = self.current_content()
        self._subject_pick = self._another(self._subject_pick, len(content.subject_variants))
        self._body_pick = self._another(self._body_pick, len(content.body_variants))
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
            self.preview_subject.setText(t("Add at least one subject and one body"))
            self.preview_body.setPlainText("")
            self.preview_variant.setText("")
            return

        contact = self._sample_contact()
        context = merge.build_context(contact, importer.extra_columns())
        identity = self._identity()

        self.preview_contact.setText(
            t("Previewing as: {value} · {value2} · {get}",
              value=contact.get('person') or '-', value2=contact.get('company') or '-',
              get=contact.get('email')))

        # The pick is held on the page rather than drawn here, so editing the
        # text refreshes the same combination instead of shuffling under the
        # cursor on every keystroke. Only "Next contact" draws again.
        subject_index = self._subject_pick % len(content.subject_variants)
        body_index = self._body_pick % len(content.body_variants)
        self.preview_variant.setText(
            t("Subject {number} of {count}  ·  Message {number2} of {count2}",
              number=subject_index + 1, count=len(content.subject_variants),
              number2=body_index + 1, count2=len(content.body_variants)))

        # Rendering and scoring both parse the whole message; neither belongs on
        # the UI thread while the user is still typing.
        Task(jobs.build_preview, identity, context, content, subject_index, body_index,
             self._preview_index).start(on_result=self._show_preview)

        dns_results = None
        page = self.window_.page("deliverability")
        if page is not None:
            dns_results = page.cached_results() or None

        Task(jobs.score_content, content, identity, importer.merge_tag_names(), dns_results,
             context, subject_index, body_index, self._preview_index).start(
            on_result=self._show_score)

    def _show_preview(self, result) -> None:
        subject, html, text = result
        self._preview_html = html
        self.preview_subject.setText(t(subject))
        self.preview_body.setPlainText(text)

    def _show_score(self, report: scorer.ScoreReport) -> None:
        if self._set_id:
            scorer.save_report(self._set_id, report)

        colour = theme.status_color(report.status)
        self.score_label.setText(t(str(report.score)))
        self.score_label.setStyleSheet(
            f"color: {colour}; font-size: {theme.px(36)}px; font-weight: 700;")
        self.score_verdict.setText(t("Grade {grade}: {verdict}",
                                     grade=report.grade, verdict=report.verdict))
        self.score_verdict.setStyleSheet(f"color: {colour};")
        landing_tones = {"primary": "success", "promotions": "warning", "spam": "error"}
        self.score_landing.setText(t(report.landing_text))
        set_tone(self.score_landing, landing_tones.get(report.landing, "muted"))
        self.score_landing.setVisible(bool(report.landing))

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
            label = hint(t(SEVERITY_NAMES.get(finding.severity, finding.severity)) + " · "
                         + t(finding.category))
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
            self.notify("Building the preview. Press again in a moment", "info", 3000)
            return
        path = Path(tempfile.gettempdir()) / "homingpigeon_preview.html"
        path.write_text(self._preview_html, encoding="utf-8")
        webbrowser.open(path.as_uri())

    # --- persistence --------------------------------------------------------
    def _content_changed(self) -> None:
        self.save_status.setText(t("Unsaved changes"))
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
        self.save_status.setText(t("Saved"))
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
        self._refresh_tag_bars()
        box = getattr(self, "unsubscribe_box", None)
        if box is not None:
            box.blockSignals(True)
            box.setChecked(bool(db.get_setting("unsubscribe_note", True)))
            box.blockSignals(False)
        if self.tabs.current() == "Preview & score":
            self.refresh_preview()
