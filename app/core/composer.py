"""Builds the outgoing message.

Every message is multipart/alternative (HTML + a generated plain-text part),
carries proper List-Unsubscribe headers, and deliberately omits any X-Mailer
header. Bulk tools that advertise themselves in the headers get filtered.
"""
from __future__ import annotations

import mimetypes
import random
import re
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from html import unescape
from pathlib import Path
from typing import Mapping

from app import config
from app.core import merge


@dataclass
class SenderIdentity:
    name: str
    email: str
    reply_to: str = ""

    @property
    def domain(self) -> str:
        return self.email.split("@", 1)[1] if "@" in self.email else ""


@dataclass
class Content:
    """Everything that shapes the body of one campaign."""
    subject_variants: list[str]
    body_variants: list[str]
    signature_html: str = ""
    attach_mode: str = "link"          # 'link' | 'attach' | 'none'
    attachment_path: str = ""
    link_url: str = ""
    link_text: str = "View our brochure"
    unsubscribe_note: bool = True


class AttachmentTooLarge(ValueError):
    pass


# --- HTML -> text -----------------------------------------------------------
_BLOCK_END = re.compile(r"</(p|div|tr|h[1-6]|li|table|ul|ol|blockquote)\s*>", re.IGNORECASE)
_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_LI = re.compile(r"<li[^>]*>", re.IGNORECASE)
_STYLE_SCRIPT = re.compile(r"<(style|script)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_ANCHOR = re.compile(r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_HR = re.compile(r"<hr\s*/?>", re.IGNORECASE)


def html_to_text(html: str) -> str:
    """Readable plain-text alternative. Links become 'text (url)'."""
    text = _STYLE_SCRIPT.sub("", html)
    text = _HR.sub("\n" + "-" * 40 + "\n", text)
    text = _BR.sub("\n", text)
    text = _LI.sub("\n  * ", text)
    text = _BLOCK_END.sub("\n", text)

    def link(match: re.Match) -> str:
        url = match.group(1).strip()
        label = _TAG.sub("", match.group(2)).strip()
        if not label:
            return url
        if url.startswith("mailto:") and url[7:] == label:
            return label
        if label == url:
            return url
        return f"{label} ({url})"

    text = _ANCHOR.sub(link, text)
    text = _TAG.sub("", text)
    text = unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# --- Assembly ---------------------------------------------------------------
def brochure_block(content: Content) -> str:
    if content.attach_mode != "link" or not content.link_url.strip():
        return ""
    url = content.link_url.strip()
    label = content.link_text.strip() or "View our brochure"
    return (
        f'<p style="margin:18px 0;">'
        f'<a href="{url}" style="color:#005fb8;text-decoration:underline;">{label}</a>'
        f'</p>'
    )


def unsubscribe_footer(sender: SenderIdentity) -> str:
    return (
        '<hr style="border:none;border-top:1px solid #cccccc;margin-top:24px;">'
        '<p style="font-size:11px;color:#777777;line-height:1.5;">'
        f'You received this message because we believe it is relevant to your business. '
        f'If it is not, reply with <strong>Unsubscribe</strong> and we will remove you immediately.'
        '</p>'
    )


def assemble_html(body_html: str, content: Content, sender: SenderIdentity) -> str:
    """Body + brochure link + signature + unsubscribe footer, wrapped for email clients."""
    parts = [body_html.strip()]

    block = brochure_block(content)
    if block:
        parts.append(block)

    if content.signature_html.strip():
        parts.append(content.signature_html.strip())

    if content.unsubscribe_note:
        parts.append(unsubscribe_footer(sender))

    inner = "\n".join(parts)
    if re.search(r"<html[\s>]", inner, re.IGNORECASE):
        return inner  # the template already provides a full document

    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"></head>'
        '<body style="margin:0;padding:0;background:#ffffff;">'
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#333333;'
        'line-height:1.6;max-width:640px;">'
        f'{inner}'
        '</div></body></html>'
    )


def check_attachment(path: str | Path) -> int:
    """Validate an attachment and return its size. Raises if missing or over the cap."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Attachment not found: {file_path}")
    size = file_path.stat().st_size
    if size > config.MAX_ATTACHMENT_BYTES:
        raise AttachmentTooLarge(
            f"{file_path.name} is {size / 1_048_576:.1f} MB. The limit is "
            f"{config.MAX_ATTACHMENT_BYTES / 1_048_576:.0f} MB"
        )
    return size


def build_message(
    sender: SenderIdentity,
    recipient: str,
    context: Mapping[str, str],
    content: Content,
    rng: random.Random | None = None,
) -> tuple[EmailMessage, str, str]:
    """Render one message. Returns (message, subject_used, body_variant_preview)."""
    rng = rng or random

    if not content.subject_variants:
        raise ValueError("No subject variants are enabled")
    if not content.body_variants:
        raise ValueError("No body variants are enabled")

    subject_template = rng.choice(content.subject_variants)
    body_template = rng.choice(content.body_variants)

    subject = merge.render(subject_template, context, html=False, rng=rng).strip()
    body_html = merge.render(body_template, context, html=True, rng=rng)
    full_html = assemble_html(body_html, content, sender)
    text_body = html_to_text(full_html)

    message = EmailMessage()
    message["From"] = formataddr((sender.name, sender.email)) if sender.name else sender.email
    message["To"] = recipient
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain=sender.domain or None)

    if sender.reply_to.strip():
        message["Reply-To"] = sender.reply_to.strip()

    # Native unsubscribe button in Gmail / Outlook, no website required
    message["List-Unsubscribe"] = f"<mailto:{sender.reply_to.strip() or sender.email}?subject=Unsubscribe>"
    message["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

    message.set_content(text_body)
    message.add_alternative(full_html, subtype="html")

    if content.attach_mode == "attach" and content.attachment_path:
        file_path = Path(content.attachment_path)
        check_attachment(file_path)
        guessed, _ = mimetypes.guess_type(file_path.name)
        maintype, subtype = (guessed or "application/octet-stream").split("/", 1)
        message.add_attachment(
            file_path.read_bytes(), maintype=maintype, subtype=subtype, filename=file_path.name
        )

    preview = body_template[:60].replace("\n", " ")
    return message, subject, preview


def preview_message(
    sender: SenderIdentity,
    context: Mapping[str, str],
    content: Content,
    subject_index: int = 0,
    body_index: int = 0,
    seed: int | None = 7,
) -> tuple[str, str, str]:
    """Deterministic render for the preview pane: (subject, html, text)."""
    rng = random.Random(seed)
    subject_template = content.subject_variants[subject_index % len(content.subject_variants)] \
        if content.subject_variants else "(no subject variants)"
    body_template = content.body_variants[body_index % len(content.body_variants)] \
        if content.body_variants else "<p>(no body variants)</p>"

    subject = merge.render(subject_template, context, html=False, rng=rng).strip()
    body_html = merge.render(body_template, context, html=True, rng=random.Random(seed))
    full_html = assemble_html(body_html, content, sender)
    return subject, full_html, html_to_text(full_html)
