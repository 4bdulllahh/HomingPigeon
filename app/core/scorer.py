"""Pre-send spam scoring.

A local rule engine approximating what content filters react to. It is not a
SpamAssassin clone and does not claim to be — it catches the mistakes that
actually get office outreach filtered, and every finding comes with a fix.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta

from app import config
from app.core import composer, db, merge

# Words filters weight heavily in a cold-outreach context
TRIGGER_WORDS = [
    "100% free", "act now", "amazing", "apply now", "as seen on", "bargain", "best price",
    "big bucks", "billion", "bonus", "cash bonus", "cheap", "click below", "click here",
    "congratulations", "credit card", "deal", "discount", "double your", "earn money",
    "exclusive deal", "expire", "fantastic", "free access", "free gift", "free offer",
    "free trial", "guarantee", "guaranteed", "hurry", "incredible", "instant", "limited time",
    "lowest price", "make money", "miracle", "money back", "no cost", "no credit check",
    "no obligation", "no risk", "offer expires", "once in a lifetime", "only today",
    "opportunity", "order now", "please read", "risk free", "satisfaction guaranteed",
    "save big", "special promotion", "urgent", "wealth", "why pay more", "winner", "win",
    "cash", "billion dollars", "unlimited", "buy direct", "call now", "subscribe now",
]

SUBJECT_TRIGGERS = [
    "free", "urgent", "act now", "limited time", "!!!", "$$$", "buy now", "cheap",
    "discount", "guarantee", "winner", "congratulations", "click here", "offer expires",
]

SHORTENER_DOMAINS = {
    "bit.ly", "tinyurl.com", "goo.gl", "t.co", "ow.ly", "is.gd", "buff.ly",
    "rebrand.ly", "cutt.ly", "shorturl.at", "rb.gy", "tiny.cc",
}

SEVERITY_WEIGHT = {"critical": 25, "high": 12, "medium": 6, "low": 3}


@dataclass
class Finding:
    severity: str         # critical | high | medium | low
    category: str
    message: str
    fix: str = ""


@dataclass
class ScoreReport:
    score: int
    grade: str
    findings: list[Finding] = field(default_factory=list)
    checked_at: str = ""

    @property
    def verdict(self) -> str:
        if self.score >= 85:
            return "Good — this should reach the inbox."
        if self.score >= 70:
            return "Acceptable, but worth improving before a large send."
        if self.score >= 50:
            return "Risky — likely to land in spam for some recipients."
        return "Poor — fix the critical items before sending."

    @property
    def status(self) -> str:
        if self.score >= 85:
            return "pass"
        if self.score >= 70:
            return "warn"
        return "fail"

    def by_severity(self) -> list[Finding]:
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        return sorted(self.findings, key=lambda f: order.get(f.severity, 4))


def _grade(score: int) -> str:
    for threshold, letter in ((95, "A+"), (90, "A"), (85, "A-"), (80, "B+"), (75, "B"),
                              (70, "B-"), (65, "C+"), (60, "C"), (50, "D")):
        if score >= threshold:
            return letter
    return "F"


def _text_of(html: str) -> str:
    return composer.html_to_text(html)


# --- Individual rule groups -------------------------------------------------
def _check_subject(subject: str, findings: list[Finding]) -> None:
    stripped = subject.strip()
    if not stripped:
        findings.append(Finding("critical", "Subject", "A subject line is empty.",
                                "Every subject variant needs text."))
        return

    if len(stripped) > 70:
        findings.append(Finding("low", "Subject",
                                f"Subject is {len(stripped)} characters; it will be cut off on mobile.",
                                "Keep subjects under about 60 characters."))
    if len(stripped) < 15:
        findings.append(Finding("low", "Subject", f"Subject '{stripped}' is very short.",
                                "Short, vague subjects read as bulk mail. Be specific."))

    letters = [c for c in stripped if c.isalpha()]
    if letters and sum(1 for c in letters if c.isupper()) / len(letters) > 0.5 and len(letters) > 6:
        findings.append(Finding("high", "Subject", "Subject is mostly capital letters.",
                                "Use normal sentence case — shouting is a classic spam signal."))

    if stripped.count("!") > 1:
        findings.append(Finding("medium", "Subject", "Subject contains multiple exclamation marks.",
                                "Use at most one, ideally none."))

    lowered = stripped.lower()
    hits = [w for w in SUBJECT_TRIGGERS if w in lowered]
    if hits:
        findings.append(Finding("high", "Subject",
                                f"Subject contains spam-trigger wording: {', '.join(hits[:4])}.",
                                "Rewrite without promotional language."))

    if "{{" not in subject and "{" not in subject:
        findings.append(Finding("low", "Subject", "Subject has no personalisation or spintax.",
                                "Insert {{Company}} so each subject differs between recipients."))

    if re.search(r"(re|fwd):", lowered):
        findings.append(Finding("high", "Subject",
                                "Subject fakes a reply or forward (Re:/Fwd:).",
                                "Never fake a thread on a first contact — it is treated as deception."))


def _check_body(html: str, findings: list[Finding], name: str = "Body",
                footer_added: bool = True) -> None:
    text = _text_of(html)
    words = text.split()

    if not words:
        findings.append(Finding("critical", name, "The body is empty.", "Write the message content."))
        return

    if len(words) < 40:
        findings.append(Finding("medium", name, f"{name} is only {len(words)} words.",
                                "Very short cold emails with a link look like phishing. Aim for 80-200 words."))
    elif len(words) > 400:
        findings.append(Finding("low", name, f"{name} is {len(words)} words — long for a cold email.",
                                "Trim to under 200 words; long first emails get ignored."))

    lowered = text.lower()
    hits = sorted({w for w in TRIGGER_WORDS if w in lowered})
    if len(hits) >= 5:
        findings.append(Finding("high", name,
                                f"{len(hits)} spam-trigger phrases: {', '.join(hits[:6])}.",
                                "Rewrite in plain business language."))
    elif hits:
        findings.append(Finding("low", name, f"Spam-trigger phrases present: {', '.join(hits)}.",
                                "Consider rewording these."))

    letters = [c for c in text if c.isalpha()]
    if letters and sum(1 for c in letters if c.isupper()) / len(letters) > 0.3:
        findings.append(Finding("high", name, "Large amount of capitalised text.",
                                "Use sentence case throughout."))

    if text.count("!") > 3:
        findings.append(Finding("medium", name, f"{text.count('!')} exclamation marks in the body.",
                                "Keep it to one or none."))

    links = re.findall(r'href=["\']([^"\']+)["\']', html, re.IGNORECASE)
    web_links = [l for l in links if l.lower().startswith(("http://", "https://"))]
    if len(web_links) > 4:
        findings.append(Finding("medium", name, f"{len(web_links)} links in the body.",
                                "Keep to one or two links on a first email."))

    for link in web_links:
        host = re.sub(r"^https?://", "", link).split("/")[0].lower()
        if host in SHORTENER_DOMAINS:
            findings.append(Finding("high", name, f"Link uses a URL shortener ({host}).",
                                    "Link to your real domain; shorteners hide the destination and "
                                    "are heavily penalised."))
            break
        if re.match(r"^\d+\.\d+\.\d+\.\d+", host):
            findings.append(Finding("critical", name, f"Link points at a raw IP address ({host}).",
                                    "Use a domain name."))
            break

    if any(l.lower().startswith("http://") for l in web_links):
        findings.append(Finding("medium", name, "At least one link uses http:// rather than https://.",
                                "Serve your site over HTTPS and link to it that way."))

    images = re.findall(r"<img\s", html, re.IGNORECASE)
    if images and len(words) < 60:
        findings.append(Finding("high", name, f"{len(images)} image(s) with very little text.",
                                "Image-heavy mail with little text is a strong spam signal. "
                                "Lead with text."))
    if len(images) > 4:
        findings.append(Finding("medium", name, f"{len(images)} images in the body.",
                                "Reduce the number of images."))
    for match in re.finditer(r"<img\s[^>]*>", html, re.IGNORECASE):
        if "alt=" not in match.group(0).lower():
            findings.append(Finding("low", name, "An image has no alt text.",
                                    "Add alt text — images are blocked by default in most clients."))
            break

    # The unsubscribe footer is appended at send time, so only complain when it is switched off
    if not footer_added and "unsubscribe" not in lowered:
        findings.append(Finding("high", name, "No unsubscribe wording anywhere in the message.",
                                "Re-enable the automatic footer on the Campaign page, or add your "
                                "own opt-out line — mail without one is treated as spam and, for "
                                "many jurisdictions, is not legal to send."))


def _check_tags(text: str, known_tags: list[str], findings: list[Finding], where: str) -> None:
    unknown = merge.unresolved_tags(text, known_tags)
    if unknown:
        findings.append(Finding(
            "critical", "Merge tags",
            f"{where} contains merge tags that will not resolve: "
            + ", ".join("{{" + t + "}}" for t in unknown),
            "These would be sent literally to the recipient. Fix the spelling or import a column "
            "with that name.",
        ))

    error = merge.validate_spintax(text)
    if error:
        findings.append(Finding("high", "Spintax", f"{where}: {error}",
                                "Balance the braces so spintax expands correctly."))


def _check_identity(sender_email: str, reply_to: str, findings: list[Finding],
                    dns_results: list | None) -> None:
    if not sender_email or "@" not in sender_email:
        findings.append(Finding("critical", "Identity", "No valid sender address is configured.",
                                "Set your from-address on the Account page."))
        return

    domain = sender_email.split("@", 1)[1].lower()
    free_providers = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com", "icloud.com"}
    if domain in free_providers:
        findings.append(Finding(
            "high", "Identity", f"Sending business outreach from a free {domain} address.",
            "Send from your own company domain. Free-provider addresses cannot pass DMARC "
            "alignment for your brand and are filtered harder for bulk sending.",
        ))

    if reply_to and "@" in reply_to:
        reply_domain = reply_to.split("@", 1)[1].lower()
        if reply_domain != domain:
            findings.append(Finding(
                "medium", "Identity",
                f"Reply-To domain ({reply_domain}) differs from the From domain ({domain}).",
                "Mismatched reply addresses are a phishing pattern. Use the same domain.",
            ))

    if dns_results:
        for result in dns_results:
            if result.name == "SPF" and result.status == "fail":
                findings.append(Finding("critical", "Authentication", f"SPF: {result.summary}",
                                        result.fix or "Fix SPF on the Deliverability page."))
            elif result.name == "DKIM" and result.status in ("fail", "warn"):
                findings.append(Finding("high", "Authentication", f"DKIM: {result.summary}",
                                        result.fix or "Enable DKIM on the Deliverability page."))
            elif result.name == "DMARC" and result.status == "fail":
                findings.append(Finding("critical", "Authentication", f"DMARC: {result.summary}",
                                        result.fix or "Publish a DMARC record."))
            elif result.name == "Blacklists" and result.status == "fail":
                findings.append(Finding("critical", "Reputation", result.summary,
                                        result.fix or "Request delisting before sending."))


def _check_attachment(content: composer.Content, findings: list[Finding]) -> None:
    if content.attach_mode != "attach" or not content.attachment_path:
        return
    from pathlib import Path

    path = Path(content.attachment_path)
    if not path.exists():
        findings.append(Finding("critical", "Attachment", f"Attachment not found: {path.name}",
                                "Select the file again on the Campaign page."))
        return

    size = path.stat().st_size
    findings.append(Finding(
        "medium", "Attachment",
        f"Every email carries {path.name} ({size / 1_048_576:.1f} MB).",
        "Attachments on first contact from an unknown sender raise spam scores noticeably. "
        "Linking to the brochure instead is measurably safer.",
    ))
    if size > config.MAX_ATTACHMENT_BYTES:
        findings.append(Finding("critical", "Attachment",
                                f"{path.name} exceeds the {config.MAX_ATTACHMENT_BYTES // 1_048_576} MB limit.",
                                "Compress the PDF or switch to a link."))
    if path.suffix.lower() not in {".pdf", ".png", ".jpg", ".jpeg", ".docx", ".xlsx"}:
        findings.append(Finding("high", "Attachment", f"Unusual attachment type: {path.suffix}",
                                "Stick to PDF for brochures; executables and archives are blocked."))


def _check_variety(content: composer.Content, findings: list[Finding]) -> None:
    subjects = len(content.subject_variants)
    bodies = len(content.body_variants)

    if subjects < 2:
        findings.append(Finding("medium", "Variety", "Only one subject variant is enabled.",
                                "Add at least 3 subject variants so identical subjects are not "
                                "repeated across hundreds of recipients."))
    if bodies < 2:
        findings.append(Finding("medium", "Variety", "Only one body variant is enabled.",
                                "Add 2-3 body variants; identical bodies in volume are easy to "
                                "fingerprint."))

    combos = subjects * bodies
    spin = max((merge.spintax_variants(b) for b in content.body_variants), default=1)
    if combos * spin < 10:
        findings.append(Finding("low", "Variety",
                                f"Only about {combos * spin} distinct message versions are possible.",
                                "Add spintax such as {Hi|Hello|Good morning} to multiply the variations."))


# --- Entry point ------------------------------------------------------------
def score(
    content: composer.Content,
    sender_email: str = "",
    reply_to: str = "",
    known_tags: list[str] | None = None,
    dns_results: list | None = None,
) -> ScoreReport:
    findings: list[Finding] = []
    known_tags = known_tags or merge.BUILTIN_TAGS

    for subject in content.subject_variants:
        _check_subject(subject, findings)
        _check_tags(subject, known_tags, findings, "A subject line")

    for index, body in enumerate(content.body_variants, start=1):
        name = f"Body {index}" if len(content.body_variants) > 1 else "Body"
        _check_body(body, findings, name, footer_added=content.unsubscribe_note)
        _check_tags(body, known_tags, findings, name)

    if content.attach_mode == "link" and not content.link_url.strip():
        findings.append(Finding("low", "Brochure", "Link mode is selected but no URL is set.",
                                "Add the brochure URL on the Campaign page, or switch to 'no brochure'."))

    _check_attachment(content, findings)
    _check_variety(content, findings)
    _check_identity(sender_email, reply_to, findings, dns_results)

    if not content.signature_html.strip():
        findings.append(Finding("medium", "Structure", "No signature is configured.",
                                "A signature with your name, company, phone and address is a "
                                "legitimacy signal filters look for."))
    else:
        signature_text = _text_of(content.signature_html).lower()
        if not re.search(r"\+?\d[\d\s\-()]{7,}", signature_text):
            findings.append(Finding("low", "Structure", "The signature has no phone number.",
                                    "Add a contact number — it distinguishes real business mail."))

    # Deduplicate identical findings raised by several variants
    unique: dict[tuple[str, str], Finding] = {}
    for finding in findings:
        unique.setdefault((finding.category, finding.message), finding)
    findings = list(unique.values())

    penalty = sum(SEVERITY_WEIGHT.get(f.severity, 3) for f in findings)
    value = max(0, min(100, 100 - penalty))
    report = ScoreReport(score=value, grade=_grade(value), findings=findings,
                         checked_at=datetime.now().isoformat(timespec="seconds"))
    return report


# --- Persistence ------------------------------------------------------------
def save_report(set_id: int, report: ScoreReport) -> None:
    db.execute(
        "INSERT INTO scores(ts, set_id, score, grade, findings_json) VALUES (?, ?, ?, ?, ?)",
        (report.checked_at, set_id, report.score, report.grade,
         json.dumps([asdict(f) for f in report.findings])),
    )


def latest_report(set_id: int | None = None) -> ScoreReport | None:
    if set_id is None:
        row = db.query_one("SELECT * FROM scores ORDER BY id DESC LIMIT 1")
    else:
        row = db.query_one("SELECT * FROM scores WHERE set_id = ? ORDER BY id DESC LIMIT 1", (set_id,))
    if row is None:
        return None
    try:
        findings = [Finding(**f) for f in json.loads(row["findings_json"] or "[]")]
    except (json.JSONDecodeError, TypeError):
        findings = []
    return ScoreReport(score=row["score"], grade=row["grade"], findings=findings,
                       checked_at=row["ts"] or "")


def is_stale(set_id: int | None = None) -> bool:
    """True when no score exists or the stored one has aged out (DNS drifts)."""
    report = latest_report(set_id)
    if report is None or not report.checked_at:
        return True
    try:
        checked = datetime.fromisoformat(report.checked_at)
    except ValueError:
        return True
    return datetime.now() - checked > timedelta(hours=config.SCORE_STALE_HOURS)
