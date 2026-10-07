"""Pre-send spam scoring, done on the finished email.

The score reads the email exactly as one person will receive it: the chosen
subject and message with the merge tags filled in for a real contact, the
brochure link, the signature, the unsubscribe line and the headers that go with
it. Checking the parts one by one missed what only shows up once they are put
together, such as the total length, every link in the email, a tag that stays
empty for this contact, or the bulk-mail signals that send mail to Gmail's
Promotions tab.

Two kinds of check run:
  * on the finished email: what filters and Gmail's tabs react to;
  * across every version: tags and brace mistakes in any subject or message,
    how much variety there is, and the sender's domain and DNS.

Alongside the score it gives an estimate of where the email will land: the
main inbox, the Promotions tab or spam. Gmail does not publish its rules, so
this is guidance based on the signals it is known to weigh.

A local rule engine, not a SpamAssassin clone. Every finding comes with a fix.
Messages are written as templates and translated with ``t()``.
"""
from __future__ import annotations

import json
import random
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from app import config
from app.core import composer, db, merge
from app.i18n import t

# Wording filters weight heavily in a first email. Every language is checked,
# whatever language the app is in, because the email may be written in another.
TRIGGER_WORDS = [
    # English
    "100% free", "act now", "amazing", "apply now", "as seen on", "bargain", "best price",
    "big bucks", "billion", "bonus", "cash bonus", "cheap", "click below", "click here",
    "congratulations", "credit card", "discount", "double your", "earn money",
    "exclusive deal", "expire", "fantastic", "free access", "free gift", "free offer",
    "free trial", "guarantee", "guaranteed", "hurry", "incredible", "instant", "limited time",
    "lowest price", "make money", "miracle", "money back", "no cost", "no credit check",
    "no obligation", "no risk", "offer expires", "once in a lifetime", "only today",
    "order now", "please read", "risk free", "satisfaction guaranteed",
    "save big", "special promotion", "urgent", "wealth", "why pay more", "winner",
    "cash", "billion dollars", "unlimited", "buy direct", "call now", "subscribe now",
    # German
    "kostenlos", "gratis", "jetzt kaufen", "nur heute", "garantiert", "sonderangebot",
    "rabatt", "dringend", "gewinner", "sofort", "schnell zugreifen", "einmalig",
    # Spanish
    "gratis", "oferta especial", "compre ahora", "solo hoy", "garantizado", "descuento",
    "urgente", "ganador", "dinero fácil", "sin riesgo", "promoción", "haga clic aquí",
    # French
    "gratuit", "offre spéciale", "achetez maintenant", "seulement aujourd'hui", "garanti",
    "remise", "urgent", "gagnant", "argent facile", "sans risque", "cliquez ici",
    # Arabic
    "مجاني", "عرض خاص", "اشتر الآن", "لفترة محدودة", "خصم", "عاجل", "فائز", "مضمون",
    "اضغط هنا", "ربح سريع", "بدون مخاطرة",
]

SUBJECT_TRIGGERS = [
    "free", "urgent", "act now", "limited time", "!!!", "$$$", "buy now", "cheap",
    "discount", "guarantee", "winner", "congratulations", "click here", "offer expires",
    "kostenlos", "gratis", "rabatt", "dringend", "descuento", "urgente", "gratuit", "remise",
    "مجاني", "خصم", "عاجل", "عرض",
]

# Words that read as a sale rather than a conversation. Not spam on their own,
# but they are a large part of what Gmail files under Promotions.
PROMOTION_WORDS = [
    "offer", "sale", "deal", "discount", "% off", "promo", "promotion", "special price",
    "limited", "exclusive", "newsletter", "buy", "shop now", "order", "save ", "free",
    "angebot", "rabatt", "aktion", "kaufen", "bestellen", "newsletter",
    "oferta", "descuento", "promoción", "comprar", "pedido", "boletín",
    "offre", "promotion", "remise", "acheter", "commander", "soldes",
    "عرض", "خصم", "تخفيض", "اشتر", "اطلب", "نشرة",
]

SHORTENER_DOMAINS = {
    "bit.ly", "tinyurl.com", "goo.gl", "t.co", "ow.ly", "is.gd", "buff.ly",
    "rebrand.ly", "cutt.ly", "shorturl.at", "rb.gy", "tiny.cc",
}

# Opt-out wording in each language, so a user's own line is recognised
OPT_OUT_WORDS = ["unsubscribe", "opt out", "abmelden", "darse de baja", "baja",
                 "désabonner", "desinscrire", "désinscrire", "إلغاء الاشتراك"]

SEVERITY_WEIGHT = {"critical": 25, "high": 12, "medium": 6, "low": 3}

PRIMARY, PROMOTIONS, SPAM = "primary", "promotions", "spam"

# Shown under the score, translated when shown
LANDING_TEXT = {
    PRIMARY: "Likely to land in the main inbox (Primary).",
    PROMOTIONS: "Likely to land in Gmail's Promotions tab. See the Promotions tab items below "
                "to move it to the main inbox.",
    SPAM: "At risk of going to spam. Fix the critical and high items first.",
}


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
    landing: str = ""                 # primary | promotions | spam, "" when unknown
    version: str = ""                 # which subject and message were scored

    @property
    def verdict(self) -> str:
        if self.score >= 85:
            return "Good. This should reach the inbox."
        if self.score >= 70:
            return "Acceptable, but worth improving before a large send."
        if self.score >= 50:
            return "Risky. Likely to land in spam for some recipients."
        return "Poor. Fix the critical items before sending."

    @property
    def landing_text(self) -> str:
        return t(LANDING_TEXT.get(self.landing, ""))

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


def _found(text: str, words: list[str]) -> list[str]:
    """Which of ``words`` appear in ``text``, matched on word boundaries."""
    lowered = text.lower()
    hits = []
    for word in words:
        pattern = r"(?<!\w)" + re.escape(word.strip()) + r"(?!\w)"
        if re.search(pattern, lowered):
            hits.append(word.strip())
    return sorted(set(hits))


# --- The finished email -----------------------------------------------------
@dataclass
class _Email:
    subject: str
    subject_template: str
    body_template: str
    html: str          # the whole email as sent
    text: str          # its plain-text version
    body_text: str     # the message alone: no signature, link or footer
    context: dict      # the contact's merge-tag values


def _render(content: composer.Content, context: dict, sender: composer.SenderIdentity,
            subject_index: int, body_index: int, seed: int) -> _Email:
    """The same render the Preview tab shows, so the score matches what is on screen."""
    subject, html, text = composer.preview_message(
        sender, context, content, subject_index=subject_index, body_index=body_index, seed=seed)
    body_template = content.body_variants[body_index % len(content.body_variants)]
    body_html = merge.render(body_template, context, html=True, rng=random.Random(seed))
    return _Email(
        subject=subject,
        subject_template=content.subject_variants[subject_index % len(content.subject_variants)],
        body_template=body_template,
        html=html, text=text,
        body_text=composer.html_to_text(composer.text_to_html(body_html)),
        context=dict(context),
    )


def _check_subject(email: _Email, findings: list[Finding]) -> None:
    subject = email.subject.strip()
    if not subject:
        findings.append(Finding("critical", "Subject", t("The subject line is empty."),
                                t("Write a subject line.")))
        return

    if len(subject) > 70:
        findings.append(Finding(
            "low", "Subject",
            t("The subject is {count} characters, so phones will cut it off.", count=len(subject)),
            t("Keep subjects under about 60 characters.")))
    if len(subject) < 15:
        findings.append(Finding(
            "low", "Subject", t("The subject \"{subject}\" is very short.", subject=subject),
            t("Short, vague subjects read as bulk mail. Say what the email is about.")))

    letters = [c for c in subject if c.isalpha()]
    if letters and sum(1 for c in letters if c.isupper()) / len(letters) > 0.5 \
            and len(letters) > 6:
        findings.append(Finding("high", "Subject", t("The subject is mostly capital letters."),
                                t("Use normal sentence case. Shouting is a classic spam signal.")))

    if subject.count("!") > 1:
        findings.append(Finding("medium", "Subject",
                                t("The subject has several exclamation marks."),
                                t("Use at most one, ideally none.")))

    hits = _found(subject, SUBJECT_TRIGGERS)
    if hits or "!!!" in subject or "$$$" in subject:
        findings.append(Finding(
            "high", "Subject",
            t("The subject contains spam wording: {words}.",
              words=", ".join(hits[:4] or ["!!!"])),
            t("Rewrite it the way you would write to a colleague, without sales words.")))

    if "{{" not in email.subject_template and "{" not in email.subject_template:
        findings.append(Finding(
            "low", "Personal touch", t("The subject is the same for everyone."),
            t("Add {{Company}} or {{FirstName}} so each person gets their own subject.")))

    if re.search(r"^\s*(re|fwd?|aw|wg|rv|tr)\s*:", subject.lower()):
        findings.append(Finding(
            "high", "Subject", t("The subject pretends to be a reply or a forward."),
            t("Never start a first email with Re: or Fwd:. Filters treat it as deception.")))


def _check_body(email: _Email, content: composer.Content, findings: list[Finding]) -> None:
    words = email.body_text.split()
    if not words:
        findings.append(Finding("critical", "Message", t("The message is empty."),
                                t("Write the message.")))
        return

    if len(words) < 25:
        findings.append(Finding(
            "medium", "Message", t("The message is only {count} words.", count=len(words)),
            t("Very short emails with a link look like phishing. Aim for 50 to 150 words.")))
    elif len(words) > 250:
        findings.append(Finding(
            "medium", "Message", t("The message is {count} words long.", count=len(words)),
            t("Long first emails read like newsletters and get skimmed. Cut it to under 150 "
              "words: who you are, why you are writing to them, one question.")))

    hits = _found(email.text, TRIGGER_WORDS)
    if len(hits) >= 5:
        findings.append(Finding(
            "high", "Spam words",
            t("{count} spam phrases: {words}.", count=len(hits), words=", ".join(hits[:6])),
            t("Rewrite in plain business language.")))
    elif hits:
        findings.append(Finding(
            "low", "Spam words", t("Spam phrases found: {words}.", words=", ".join(hits)),
            t("Reword these.")))

    letters = [c for c in email.body_text if c.isalpha()]
    if letters and sum(1 for c in letters if c.isupper()) / len(letters) > 0.3:
        findings.append(Finding("high", "Message", t("A lot of the message is in capitals."),
                                t("Use sentence case throughout.")))

    if email.body_text.count("!") > 3:
        findings.append(Finding(
            "medium", "Message",
            t("{count} exclamation marks in the message.", count=email.body_text.count("!")),
            t("Keep it to one or none.")))

    leftover = merge.TAG_PATTERN.findall(email.html) + merge.TAG_PATTERN.findall(email.subject)
    if leftover:
        findings.append(Finding(
            "critical", "Merge tags",
            t("This person would receive {tags} as it is, with the brackets.",
              tags=", ".join("{{" + tag + "}}" for tag in sorted(set(leftover)))),
            t("Check the spelling of the tag, or fill in that column for every contact in "
              "your spreadsheet.")))

    used = merge.TAG_PATTERN.findall(email.subject_template + " " + email.body_template)
    blank = sorted({tag for tag in used if merge._lookup(email.context, tag) == ""})
    if blank:
        findings.append(Finding(
            "low", "Merge tags",
            t("This person has nothing in {tags}, so it is left blank.",
              tags=", ".join("{{" + tag + "}}" for tag in blank)),
            t("Read the preview to check the sentence still makes sense, or fill in that "
              "column in your spreadsheet.")))

    links = re.findall(r'href=["\']([^"\']+)["\']', email.html, re.IGNORECASE)
    web_links = [link for link in links if link.lower().startswith(("http://", "https://"))]
    if len(web_links) > 4:
        findings.append(Finding(
            "medium", "Links", t("{count} links in the email.", count=len(web_links)),
            t("Keep to one link at most in a first email.")))
    for link in web_links:
        host = re.sub(r"^https?://", "", link).split("/")[0].lower()
        if host in SHORTENER_DOMAINS:
            findings.append(Finding(
                "high", "Links", t("A link uses a link shortener ({host}).", host=host),
                t("Link to your own website. Shorteners hide where a link goes and are "
                  "penalised heavily.")))
            break
        if re.match(r"^\d+\.\d+\.\d+\.\d+", host):
            findings.append(Finding("critical", "Links",
                                    t("A link points at a bare IP address ({host}).", host=host),
                                    t("Use your website's name instead.")))
            break
    if any(link.lower().startswith("http://") for link in web_links):
        findings.append(Finding("medium", "Links",
                                t("At least one link starts with http:// instead of https://."),
                                t("Link to the https:// version of your website.")))

    images = re.findall(r"<img\s", email.html, re.IGNORECASE)
    if images and len(words) < 60:
        findings.append(Finding(
            "high", "Images", t("{count} image(s) with very little text.", count=len(images)),
            t("Emails that are mostly pictures are a strong spam signal. Lead with text.")))
    for match in re.finditer(r"<img\s[^>]*>", email.html, re.IGNORECASE):
        if "alt=" not in match.group(0).lower():
            findings.append(Finding("low", "Images", t("An image has no description (alt text)."),
                                    t("Add alt text. Most email programs block images at "
                                      "first.")))
            break

    if not content.unsubscribe_note and not _found(email.text, OPT_OUT_WORDS):
        findings.append(Finding(
            "low", "Opt-out", t("No unsubscribe wording anywhere in the email."),
            t("Fine for a small number of personal emails. For larger sends, offer a polite "
              "way to opt out in your own words, such as \"If this is not relevant, just let "
              "me know.\" Some countries require one.")))


def _check_promotions(email: _Email, content: composer.Content,
                      findings: list[Finding]) -> int:
    """What sends an email to Gmail's Promotions tab. Returns how strongly it points there.

    Gmail sorts on how much an email looks like marketing: bulk-mail headers, an
    unsubscribe footer, links, pictures, heavy formatting and sales wording. A
    short plain message that greets the person by name and asks a question
    looks like a person writing, and that is what lands in the main inbox.
    """
    points = 0
    category = "Promotions tab"

    if content.unsubscribe_note:
        points += 2
        findings.append(Finding(
            "low", category,
            t("The unsubscribe line and the bulk-mail header mark this as a mass mailing."),
            t("For personal one-to-one outreach, switch the unsubscribe line off on the "
              "Signature tab. Anyone who replies asking to be removed is still taken off your "
              "list.")))

    links = [link for link in re.findall(r'href=["\']([^"\']+)["\']', email.html, re.IGNORECASE)
             if link.lower().startswith(("http://", "https://"))]
    if links:
        points += min(2, len(links))
        brochure = bool(content.attach_mode == "link" and content.link_url.strip())
        findings.append(Finding(
            "low" if len(links) == 1 else "medium", category,
            t("The email has {count} link(s).", count=len(links)),
            t("Leave the brochure link out of the first email and offer to send it instead, "
              "for example \"Shall I send over our brochure?\". A reply is worth more than a "
              "click.") if brochure else
            t("A first email with no links at all looks the most personal. Put your website "
              "in the signature as plain text instead.")))

    if content.attach_mode == "attach" and content.attachment_path:
        points += 2

    if re.search(r"<img\s", email.html, re.IGNORECASE):
        points += 2
        findings.append(Finding("medium", category, t("The email contains pictures."),
                                t("Personal emails are plain text. Remove pictures and logos "
                                  "from the first email.")))

    template = email.body_template
    styled = len(re.findall(r"<(strong|b|em|ul|ol|li|h[1-6]|table|font)\b|style=", template,
                            re.IGNORECASE)) + \
        len(re.findall(r"^\s*[-*•]\s+", template, re.MULTILINE))
    if styled >= 3:
        points += 1
        findings.append(Finding("low", category, t("The message uses a lot of formatting."),
                                t("Bold text, bullet points and styling read like a newsletter. "
                                  "Write short plain paragraphs, as you would to a colleague.")))

    sales = _found(email.body_text + " " + email.subject, PROMOTION_WORDS)
    if sales:
        points += 1 if len(sales) < 3 else 2
        findings.append(Finding(
            "low" if len(sales) < 3 else "medium", category,
            t("Sales wording: {words}.", words=", ".join(sales[:6])),
            t("Talk about their business and ask a question rather than offering a deal.")))

    if len(email.body_text.split()) > 180:
        points += 1

    if "?" not in email.body_text and "؟" not in email.body_text:
        findings.append(Finding("low", "Personal touch",
                                t("The message does not ask a question."),
                                t("End with one simple question they can answer in a line, such "
                                  "as \"Would a short call next week be useful?\". Replies are "
                                  "the strongest sign to Gmail that your emails are wanted.")))

    if not re.search(r"\{\{\s*(first\s*name|full\s*name)\s*\}\}", template, re.IGNORECASE):
        findings.append(Finding("low", "Personal touch",
                                t("The message does not greet the person by name."),
                                t("Start with \"Hi {{FirstName}},\". A greeting by name is how a "
                                  "personal email begins.")))
    return points


# --- Across every version ---------------------------------------------------
def _check_versions(content: composer.Content, known_tags: list[str],
                    findings: list[Finding]) -> None:
    pieces = [(t("Subject {number}", number=index), text)
              for index, text in enumerate(content.subject_variants, start=1)]
    pieces += [(t("Message {number}", number=index), text)
               for index, text in enumerate(content.body_variants, start=1)]
    for where, text in pieces:
        unknown = merge.unresolved_tags(text, known_tags)
        if unknown:
            findings.append(Finding(
                "critical", "Merge tags",
                t("{where} uses tags that do not match any column: {tags}", where=where,
                  tags=", ".join("{{" + tag + "}}" for tag in unknown)),
                t("These would be sent with the brackets. Fix the spelling or import a column "
                  "with that name.")))
        error = merge.validate_spintax(text)
        if error:
            findings.append(Finding("high", "Spintax", t("{where}: {error}", where=where,
                                                         error=error),
                                    t("Every { needs a matching }.")))


def _check_variety(content: composer.Content, findings: list[Finding]) -> None:
    subjects = len(content.subject_variants)
    bodies = len(content.body_variants)
    if subjects < 2:
        findings.append(Finding("medium", "Variety", t("Only one subject is switched on."),
                                t("Write 3 or more subjects so hundreds of people do not get "
                                  "the same one.")))
    if bodies < 2:
        findings.append(Finding("medium", "Variety", t("Only one message is switched on."),
                                t("Write 2 or 3 versions. Identical emails sent in volume are "
                                  "easy to fingerprint.")))
    spin = max((merge.spintax_variants(b) for b in content.body_variants), default=1)
    if subjects * bodies * spin < 10:
        findings.append(Finding(
            "low", "Variety",
            t("Only about {count} different versions of the email are possible.",
              count=subjects * bodies * spin),
            t("Add choices such as {Hi|Hello|Good morning} to multiply the versions.")))


def _check_identity(sender_email: str, reply_to: str, findings: list[Finding],
                    dns_results: list | None) -> None:
    if not sender_email or "@" not in sender_email:
        findings.append(Finding("critical", "Identity", t("No sender address is set up."),
                                t("Add your email address on the My email account page.")))
        return

    domain = sender_email.split("@", 1)[1].lower()
    free_providers = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
                      "icloud.com"}
    if domain in free_providers:
        findings.append(Finding(
            "high", "Identity",
            t("Sending business email from a free {domain} address.", domain=domain),
            t("Send from your own company domain. Free addresses cannot prove they speak for "
              "your business and are filtered harder.")))

    if reply_to and "@" in reply_to:
        reply_domain = reply_to.split("@", 1)[1].lower()
        if reply_domain != domain:
            findings.append(Finding(
                "medium", "Identity",
                t("Replies go to {reply_domain}, but the email comes from {domain}.",
                  reply_domain=reply_domain, domain=domain),
                t("Use the same domain for both. A mismatch is a phishing pattern.")))

    for result in dns_results or []:
        if result.name == "SPF" and result.status == "fail":
            findings.append(Finding("critical", "Authentication", f"SPF: {t(result.summary)}",
                                    t(result.fix) or t("Fix SPF on the Domain check page.")))
        elif result.name == "DKIM" and result.status in ("fail", "warn"):
            findings.append(Finding("high", "Authentication", f"DKIM: {t(result.summary)}",
                                    t(result.fix) or t("Turn on DKIM on the Domain check "
                                                       "page.")))
        elif result.name == "DMARC" and result.status == "fail":
            findings.append(Finding("critical", "Authentication", f"DMARC: {t(result.summary)}",
                                    t(result.fix) or t("Publish a DMARC record.")))
        elif result.name == "Blacklists" and result.status == "fail":
            findings.append(Finding("critical", "Reputation", t(result.summary),
                                    t(result.fix) or t("Ask to be removed before sending.")))


def _check_attachment(content: composer.Content, findings: list[Finding]) -> None:
    if content.attach_mode != "attach" or not content.attachment_path:
        return
    from pathlib import Path

    path = Path(content.attachment_path)
    if not path.exists():
        findings.append(Finding("critical", "Attachment",
                                t("The attachment cannot be found: {name}", name=path.name),
                                t("Choose the file again on the Sending options page.")))
        return

    size = path.stat().st_size
    findings.append(Finding(
        "medium", "Attachment",
        t("Every email carries {name} ({size} MB).", name=path.name,
          size=f"{size / 1_048_576:.1f}"),
        t("An attachment from someone they do not know raises the spam score and sends mail "
          "to Promotions. Offer to send it instead.")))
    if size > config.MAX_ATTACHMENT_BYTES:
        findings.append(Finding(
            "critical", "Attachment",
            t("{name} is over the {limit} MB limit.", name=path.name,
              limit=config.MAX_ATTACHMENT_BYTES // 1_048_576),
            t("Make the PDF smaller or switch to a link.")))
    if path.suffix.lower() not in {".pdf", ".png", ".jpg", ".jpeg", ".docx", ".xlsx"}:
        findings.append(Finding("high", "Attachment",
                                t("Unusual attachment type: {kind}", kind=path.suffix),
                                t("Use a PDF. Programs and zip files are blocked.")))


def _check_signature(content: composer.Content, findings: list[Finding]) -> None:
    if not content.signature_html.strip():
        findings.append(Finding("medium", "Signature", t("There is no signature."),
                                t("Add your name, company, phone number and address on the "
                                  "Signature tab. Real businesses sign their emails.")))
        return
    signature = composer.html_to_text(composer.text_to_html(content.signature_html))
    if not re.search(r"\+?\d[\d\s\-()]{7,}", signature):
        findings.append(Finding("low", "Signature", t("The signature has no phone number."),
                                t("Add a phone number. It shows there is a real business behind "
                                  "the email.")))


# --- Entry point ------------------------------------------------------------
SAMPLE_CONTACT = {"email": "sample@example.com", "company": "Example Trading LLC",
                  "person": "Ahmed Khan", "extra_json": None}


def score(
    content: composer.Content,
    sender_email: str = "",
    reply_to: str = "",
    known_tags: list[str] | None = None,
    dns_results: list | None = None,
    context: dict | None = None,
    subject_index: int = 0,
    body_index: int = 0,
    seed: int = 7,
    sender_name: str = "",
) -> ScoreReport:
    """Score the finished email for one contact, plus the checks across every version.

    ``context`` is the contact's merge-tag values (``merge.build_context``) and
    the indexes and seed pick the same subject, message and spintax choices the
    Preview tab shows.
    """
    findings: list[Finding] = []
    known_tags = known_tags or merge.BUILTIN_TAGS
    landing_points = 0
    version = ""

    if content.subject_variants and content.body_variants:
        subject_index %= len(content.subject_variants)
        body_index %= len(content.body_variants)
        sender = composer.SenderIdentity(sender_name, sender_email or "you@example.com",
                                         reply_to)
        email = _render(content, context or merge.build_context(SAMPLE_CONTACT), sender,
                        subject_index, body_index, seed)
        version = t("Subject {subject} and message {message}", subject=subject_index + 1,
                    message=body_index + 1)
        _check_subject(email, findings)
        _check_body(email, content, findings)
        landing_points = _check_promotions(email, content, findings)
    else:
        findings.append(Finding("critical", "Message",
                                t("There is no subject or no message switched on."),
                                t("Write at least one subject and one message.")))

    _check_versions(content, known_tags, findings)

    if content.attach_mode == "link" and not content.link_url.strip():
        findings.append(Finding("low", "Brochure",
                                t("Brochure link is selected but no web address is set."),
                                t("Add the address on the Sending options page, or choose no "
                                  "brochure.")))
    _check_attachment(content, findings)
    _check_variety(content, findings)
    _check_identity(sender_email, reply_to, findings, dns_results)
    _check_signature(content, findings)

    # The same problem raised twice (by two versions, say) only counts once
    unique: dict[tuple[str, str], Finding] = {}
    for finding in findings:
        unique.setdefault((finding.category, finding.message), finding)
    findings = list(unique.values())

    penalty = sum(SEVERITY_WEIGHT.get(f.severity, 3) for f in findings)
    value = max(0, min(100, 100 - penalty))

    if value < 60 or any(f.severity == "critical" for f in findings):
        landing = SPAM
    elif landing_points >= 3:
        landing = PROMOTIONS
    else:
        landing = PRIMARY

    return ScoreReport(score=value, grade=_grade(value), findings=findings,
                       checked_at=datetime.now().isoformat(timespec="seconds"),
                       landing=landing, version=version)


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
        row = db.query_one("SELECT * FROM scores WHERE set_id = ? ORDER BY id DESC LIMIT 1",
                           (set_id,))
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
