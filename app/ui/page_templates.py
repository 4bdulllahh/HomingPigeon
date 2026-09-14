"""Templates: multiple subjects and bodies, signature, live preview, spam score."""
from __future__ import annotations

import random
import tempfile
import webbrowser
from pathlib import Path

import customtkinter as ctk

from app import theme
from app.core import composer, db, importer, merge, scorer
from app.ui.widgets.common import (Section, TabView, copy_to_clipboard, get_text, set_text,
                                   toast)

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


class VariantEditor(ctk.CTkFrame):
    """One subject or body variant with an enable toggle and delete button."""

    def __init__(self, master, text: str = "", enabled: bool = True, multiline: bool = False,
                 on_change=None, on_delete=None, index: int = 1):
        super().__init__(master, fg_color=theme.BG_PANEL, corner_radius=theme.RADIUS,
                         border_width=1, border_color=theme.BORDER)
        self.on_change = on_change
        self.multiline = multiline

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=10, pady=(8, 0))

        self.enabled_var = ctk.BooleanVar(value=enabled)
        theme.checkbox(head, f"Variant {index}", variable=self.enabled_var,
                       command=self._changed).pack(side="left")

        self.info = theme.label(head, "", muted=True, size=11)
        self.info.pack(side="left", padx=(12, 0))

        theme.danger_button(head, "Remove", lambda: on_delete and on_delete(self),
                            width=80, height=26).pack(side="right")

        if multiline:
            self.text_widget = theme.textbox(self, height=240, monospace=True)
        else:
            self.text_widget = theme.entry(self, "")
        self.text_widget.pack(fill="both", expand=True, padx=10, pady=(8, 10))

        if text:
            if multiline:
                self.text_widget.insert("1.0", text)
            else:
                self.text_widget.insert(0, text)

        self.text_widget.bind("<KeyRelease>", lambda e: self._changed())
        self._changed()

    def get_text(self) -> str:
        return get_text(self.text_widget) if self.multiline else self.text_widget.get()

    @property
    def enabled(self) -> bool:
        return self.enabled_var.get()

    def _changed(self) -> None:
        text = self.get_text()
        variants = merge.spintax_variants(text)
        error = merge.validate_spintax(text)
        if error:
            self.info.configure(text=f"⚠ {error}", text_color=theme.ERROR)
        elif variants > 1:
            self.info.configure(text=f"{variants:,} spintax variations", text_color=theme.SUCCESS)
        else:
            self.info.configure(text=f"{len(text)} characters", text_color=theme.FG_MUTED)
        if self.on_change:
            self.on_change()


class TemplatesPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.subject_editors: list[VariantEditor] = []
        self.body_editors: list[VariantEditor] = []
        self._set_id: int | None = None
        self._preview_index = 0
        self._build()
        self.load()

    def _build(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=theme.PAD_LARGE, pady=(theme.PAD, 0))
        theme.heading(header, "Templates").pack(anchor="w")
        theme.label(header,
                    "Write several subjects and bodies. The app picks a different combination for "
                    "each recipient, so hundreds of identical messages never go out — that is what "
                    "spam filters fingerprint.", muted=True, wrap=True).pack(anchor="w", pady=(2, 10))

        self.tabs = TabView(self)
        self.tabs.pack(fill="both", expand=True, padx=theme.PAD_LARGE, pady=(0, theme.PAD))
        for name in ("Subjects", "Body", "Signature", 'Preview & score'):
            self.tabs.add(name)

        self._build_subjects(self.tabs.tab("Subjects"))
        self._build_bodies(self.tabs.tab("Body"))
        self._build_signature(self.tabs.tab("Signature"))
        self._build_preview(self.tabs.tab('Preview & score'))

        self._subjects_hint = None
        self._bodies_hint = None
        self._refresh_empty_hints()

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=theme.PAD_LARGE, pady=(0, theme.PAD))
        theme.primary_button(bar, "Save templates", self.save, width=160).pack(side="left")
        self.save_status = theme.label(bar, "", muted=True)
        self.save_status.pack(side="left", padx=12)

    # --- merge tag helper ---------------------------------------------------
    def _tag_bar(self, parent, target_getter) -> None:
        wrapper = ctk.CTkFrame(parent, fg_color="transparent")
        wrapper.pack(fill="x", pady=(0, 8))
        theme.label(wrapper, "Insert:", muted=True, size=11).pack(side="left", padx=(0, 6))

        for tag in importer.merge_tag_names()[:8]:
            theme.secondary_button(
                wrapper, "{{" + tag + "}}",
                lambda t=tag: self._insert_tag(target_getter(), "{{" + t + "}}"),
                width=len(tag) * 8 + 30, height=24).pack(side="left", padx=2)

        theme.secondary_button(
            wrapper, "{spin|tax}",
            lambda: self._insert_tag(target_getter(), "{option one|option two}"),
            width=90, height=24).pack(side="left", padx=(10, 2))

    def _insert_tag(self, editor: VariantEditor | None, text: str) -> None:
        if editor is None:
            toast(self, "Add a variant first", "warn")
            return
        widget = editor.text_widget
        try:
            widget.insert("insert" if editor.multiline else widget.index("insert"), text)
        except Exception:
            widget.insert("end", text)
        editor._changed()

    # --- subjects -----------------------------------------------------------
    def _build_subjects(self, parent) -> None:
        theme.label(parent,
                    "Use {{Company}} so each subject is different, and spintax like "
                    "{Custom|Bespoke} for extra variation.", muted=True).pack(anchor="w", pady=(10, 6))
        self._tag_bar(parent, lambda: self.subject_editors[-1] if self.subject_editors else None)

        self.subjects_frame = theme.scroll_frame(parent)
        self.subjects_frame.pack(fill="both", expand=True)

        buttons = ctk.CTkFrame(parent, fg_color="transparent")
        buttons.pack(fill="x", pady=8)
        theme.primary_button(buttons, "+ Add a subject line",
                             lambda: self._add_subject(""), width=180).pack(side="left")
        theme.secondary_button(buttons, "Show me an example", self._example_subjects,
                               width=180).pack(side="left", padx=8)

    def _add_subject(self, text: str, enabled: bool = True) -> None:
        editor = VariantEditor(self.subjects_frame, text, enabled, multiline=False,
                               on_change=self._mark_dirty, on_delete=self._remove_subject,
                               index=len(self.subject_editors) + 1)
        editor.pack(fill="x", pady=4)
        self.subject_editors.append(editor)
        self._refresh_empty_hints()

    def _refresh_empty_hints(self) -> None:
        """Show friendly placeholder text while a tab has nothing in it yet."""
        for frame, editors, attr in (
            (self.subjects_frame, self.subject_editors, "_subjects_hint"),
            (self.bodies_frame, self.body_editors, "_bodies_hint"),
        ):
            hint = getattr(self, attr, None)
            if editors:
                if hint is not None:
                    hint.destroy()
                    setattr(self, attr, None)
            elif hint is None:
                hint = theme.label(frame, EMPTY_HINT, muted=True, wrap=True)
                hint.pack(anchor="w", pady=20, padx=4)
                setattr(self, attr, hint)

    def _remove_subject(self, editor: VariantEditor) -> None:
        self.subject_editors.remove(editor)
        editor.destroy()
        self._refresh_empty_hints()
        self._mark_dirty()

    # --- bodies -------------------------------------------------------------
    def _build_bodies(self, parent) -> None:
        theme.label(parent,
                    "Write in simple HTML. The plain-text version sent alongside is generated "
                    "automatically, and your signature plus the unsubscribe footer are added at "
                    "the bottom of every message.", muted=True).pack(anchor="w", pady=(10, 6))
        self._tag_bar(parent, lambda: self.body_editors[-1] if self.body_editors else None)

        self.bodies_frame = theme.scroll_frame(parent)
        self.bodies_frame.pack(fill="both", expand=True)

        buttons = ctk.CTkFrame(parent, fg_color="transparent")
        buttons.pack(fill="x", pady=8)
        theme.primary_button(buttons, "+ Add a message",
                             lambda: self._add_body(""), width=180).pack(side="left")
        theme.secondary_button(buttons, "Show me an example", self._example_body,
                               width=180).pack(side="left", padx=8)

    def _add_body(self, text: str, enabled: bool = True) -> None:
        editor = VariantEditor(self.bodies_frame, text, enabled, multiline=True,
                               on_change=self._mark_dirty, on_delete=self._remove_body,
                               index=len(self.body_editors) + 1)
        editor.pack(fill="x", pady=4)
        self.body_editors.append(editor)
        self._refresh_empty_hints()

    def _remove_body(self, editor: VariantEditor) -> None:
        self.body_editors.remove(editor)
        editor.destroy()
        self._refresh_empty_hints()
        self._mark_dirty()

    # --- signature ----------------------------------------------------------
    def _build_signature(self, parent) -> None:
        theme.label(parent,
                    "Added to the bottom of every message. A signature with a real name, phone "
                    "number and address is a legitimacy signal that spam filters look for.",
                    muted=True).pack(anchor="w", pady=(10, 8))

        self.signature_box = theme.textbox(parent, monospace=True)
        self.signature_box.pack(fill="both", expand=True, pady=(0, 8))
        self.signature_box.bind("<KeyRelease>", lambda e: self._mark_dirty())

        theme.secondary_button(parent, "Show me an example",
                               self._insert_example_signature, width=200).pack(anchor="w", pady=(0, 10))

    def _insert_example_signature(self) -> None:
        set_text(self.signature_box, EXAMPLE_SIGNATURE)
        self._mark_dirty()
        toast(self, "Replace everything in [square brackets] with your own details", "info", 6000)

    def _example_subjects(self) -> None:
        for text in EXAMPLE_SUBJECTS:
            self._add_subject(text)
        self._mark_dirty()
        toast(self, "Example subject lines added — edit them to suit your business", "info", 6000)

    def _example_body(self) -> None:
        self._add_body(EXAMPLE_BODY)
        self._mark_dirty()
        toast(self, "Example message added — replace the [square brackets] with your own words",
              "info", 6000)

    # --- preview ------------------------------------------------------------
    def _build_preview(self, parent) -> None:
        top = ctk.CTkFrame(parent, fg_color="transparent")
        top.pack(fill="x", pady=(10, 8))

        theme.primary_button(top, "Refresh preview", self.refresh_preview, width=150).pack(side="left")
        theme.secondary_button(top, "Next contact", self._next_contact, width=130).pack(
            side="left", padx=8)
        theme.secondary_button(top, "Open in browser", self._open_in_browser, width=150).pack(
            side="left")

        self.preview_contact = theme.label(parent, "", muted=True)
        self.preview_contact.pack(anchor="w", pady=(0, 6))

        split = ctk.CTkFrame(parent, fg_color="transparent")
        split.pack(fill="both", expand=True)
        split.grid_columnconfigure(0, weight=3)
        split.grid_columnconfigure(1, weight=2)
        split.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(split, fg_color=theme.BG_PANEL, corner_radius=theme.RADIUS,
                            border_width=1, border_color=theme.BORDER)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        self.preview_subject = ctk.CTkLabel(left, text="", font=theme.font(14, "bold"),
                                            text_color=theme.FG_BRIGHT, anchor="w",
                                            wraplength=520, justify="left")
        self.preview_subject.pack(anchor="w", padx=14, pady=(12, 4))
        theme.separator(left).pack(fill="x", padx=14)

        self.preview_body = ctk.CTkTextbox(left, font=theme.font(12), fg_color="transparent",
                                           text_color=theme.FG, wrap="word", border_width=0)
        self.preview_body.pack(fill="both", expand=True, padx=10, pady=10)

        right = ctk.CTkFrame(split, fg_color=theme.BG_PANEL, corner_radius=theme.RADIUS,
                             border_width=1, border_color=theme.BORDER)
        right.grid(row=0, column=1, sticky="nsew")

        ctk.CTkLabel(right, text="Spam score", font=theme.font(14, "bold"),
                     text_color=theme.FG_BRIGHT, anchor="w").pack(anchor="w", padx=14, pady=(12, 0))

        self.score_label = ctk.CTkLabel(right, text="—", font=theme.font(38, "bold"),
                                        text_color=theme.FG_MUTED)
        self.score_label.pack(anchor="w", padx=14, pady=(4, 0))
        self.score_verdict = ctk.CTkLabel(right, text="Refresh to check", font=theme.font(12),
                                          text_color=theme.FG_MUTED, anchor="w",
                                          wraplength=320, justify="left")
        self.score_verdict.pack(anchor="w", padx=14, pady=(0, 8))
        theme.separator(right).pack(fill="x", padx=14)

        self.findings_frame = theme.scroll_frame(right)
        self.findings_frame.pack(fill="both", expand=True, padx=6, pady=8)

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
            signature_html=get_text(self.signature_box),
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
        content = self.current_content()
        if not content.subject_variants or not content.body_variants:
            self.preview_subject.configure(text="Add at least one subject and one body")
            set_text(self.preview_body, "", readonly=False)
            return

        contact = self._sample_contact()
        context = merge.build_context(contact)
        identity = self._identity()

        subject, html, text = composer.preview_message(
            identity, context, content,
            subject_index=self._preview_index, body_index=self._preview_index,
            seed=self._preview_index)

        self._preview_html = html
        self.preview_contact.configure(
            text=f"Previewing as: {contact.get('person') or '—'} · {contact.get('company') or '—'} "
                 f"· {contact.get('email')}")
        self.preview_subject.configure(text=subject)
        set_text(self.preview_body, text)

        self._run_score(content, identity)

    def _run_score(self, content: composer.Content, identity: composer.SenderIdentity) -> None:
        dns_results = None
        page = self.app.pages.get("deliverability")
        if page is not None:
            dns_results = page.cached_results() or None

        report = scorer.score(content, sender_email=identity.email, reply_to=identity.reply_to,
                              known_tags=importer.merge_tag_names(), dns_results=dns_results)
        if self._set_id:
            scorer.save_report(self._set_id, report)

        color = theme.status_color(report.status)
        self.score_label.configure(text=f"{report.score}", text_color=color)
        self.score_verdict.configure(text=f"Grade {report.grade} — {report.verdict}",
                                     text_color=color)

        for widget in self.findings_frame.winfo_children():
            widget.destroy()

        if not report.findings:
            theme.label(self.findings_frame, "No issues found.", muted=True).pack(anchor="w", pady=6)
            return

        severity_color = {"critical": theme.ERROR, "high": theme.ERROR,
                          "medium": theme.WARNING, "low": theme.FG_MUTED}
        for finding in report.by_severity():
            card = ctk.CTkFrame(self.findings_frame, fg_color="transparent")
            card.pack(fill="x", pady=(0, 8))
            ctk.CTkLabel(card, text=f"{finding.severity.upper()} · {finding.category}",
                         font=theme.font(10, "bold"),
                         text_color=severity_color.get(finding.severity, theme.FG_MUTED),
                         anchor="w").pack(anchor="w")
            ctk.CTkLabel(card, text=finding.message, font=theme.font(12), text_color=theme.FG,
                         anchor="w", justify="left", wraplength=310).pack(anchor="w")
            if finding.fix:
                ctk.CTkLabel(card, text=finding.fix, font=theme.font(11),
                             text_color=theme.FG_MUTED, anchor="w", justify="left",
                             wraplength=310).pack(anchor="w", pady=(2, 0))

    def _open_in_browser(self) -> None:
        html = getattr(self, "_preview_html", "")
        if not html:
            self.refresh_preview()
            html = getattr(self, "_preview_html", "")
        if not html:
            return
        path = Path(tempfile.gettempdir()) / "homingpigeon_preview.html"
        path.write_text(html, encoding="utf-8")
        webbrowser.open(path.as_uri())

    # --- persistence --------------------------------------------------------
    def _mark_dirty(self) -> None:
        self.save_status.configure(text="Unsaved changes", text_color=theme.WARNING)

    def save(self) -> None:
        subjects = [(e.get_text(), e.enabled) for e in self.subject_editors if e.get_text().strip()]
        bodies = [(e.get_text(), e.enabled) for e in self.body_editors if e.get_text().strip()]

        if not subjects or not bodies:
            toast(self, "Add at least one subject and one body before saving", "warn")
            return

        signature = get_text(self.signature_box)
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
        self.save_status.configure(text="Saved", text_color=theme.SUCCESS)
        toast(self, "Templates saved", "success")
        self.app._refresh_status()
        self.refresh_preview()

    def load(self) -> None:
        row = db.query_one("SELECT * FROM template_sets ORDER BY id LIMIT 1")

        if row is None:
            # First launch: everything stays empty until the user writes or
            # loads an example. Nothing is pre-filled on their behalf.
            return

        self._set_id = row["id"]
        set_text(self.signature_box, row["signature_html"] or "")

        for editor in self.subject_editors + self.body_editors:
            editor.destroy()
        self.subject_editors.clear()
        self.body_editors.clear()

        for subject in db.query("SELECT * FROM subjects WHERE set_id = ? ORDER BY position",
                                (self._set_id,)):
            self._add_subject(subject["text"], bool(subject["enabled"]))
        for body in db.query("SELECT * FROM bodies WHERE set_id = ? ORDER BY position",
                             (self._set_id,)):
            self._add_body(body["html"], bool(body["enabled"]))

        self.save_status.configure(text="")

    def on_show(self) -> None:
        if self.tabs.get() == 'Preview & score':
            self.refresh_preview()
