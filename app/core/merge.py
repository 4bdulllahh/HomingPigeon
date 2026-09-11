"""Merge tags, spintax expansion and name cleanup.

Two independent mechanisms keep messages from looking machine-stamped:
  * variant rotation (several subjects / bodies, picked per recipient)
  * spintax  {Hi|Hello|Hey}  expanded at send time, nesting supported
"""
from __future__ import annotations

import json
import random
import re
from html import escape
from typing import Any, Mapping

# Honorifics stripped before taking a first name (H.E. Khalaf -> Khalaf)
_TITLES = re.compile(
    r"^(h\.?e\.?|dr\.?|prof\.?|sheikh|shk\.?|eng\.?|mr\.?|mrs\.?|ms\.?|miss|sir|madam|capt\.?)\s+",
    re.IGNORECASE,
)
_SUFFIXES = re.compile(r"[,;]\s*(ceo|cfo|coo|md|gm|manager|director|llc|l\.l\.c).*$", re.IGNORECASE)

TAG_PATTERN = re.compile(r"\{\{\s*([A-Za-z0-9 _\-]+?)\s*\}\}")
_SPIN_INNERMOST = re.compile(r"\{([^{}]*)\}")

BUILTIN_TAGS = ["FirstName", "FullName", "Company", "Email", "Domain"]


def clean_first_name(full_name: Any, fallback: str = "there") -> str:
    """First name with honorifics and trailing job titles removed."""
    if full_name is None:
        return fallback
    text = str(full_name).strip()
    if not text or text.lower() in {"nan", "none", "n/a", "-"}:
        return fallback

    text = _SUFFIXES.sub("", text).strip()
    # Titles can stack: "H.E. Dr. Ahmed"
    previous = None
    while previous != text:
        previous = text
        text = _TITLES.sub("", text).strip()

    parts = [p for p in re.split(r"\s+", text) if p]
    if not parts:
        return fallback

    first = parts[0].strip(".,")
    if not first or len(first) == 1:  # an initial like "A." is useless as a greeting
        return fallback
    # Preserve intentional casing like "McBride"; only fix ALL CAPS / all lower
    if first.isupper() or first.islower():
        first = first.capitalize()
    return first


def clean_company(company: Any, fallback: str = "your company") -> str:
    if company is None:
        return fallback
    text = str(company).strip()
    if not text or text.lower() in {"nan", "none", "n/a", "-"}:
        return fallback
    return text


_TAG_SENTINEL = "\x00T{}\x00"


def _protect_tags(text: str) -> tuple[str, list[str]]:
    """Hide {{Tag}} from the spintax parser, which would otherwise strip the inner braces."""
    saved: list[str] = []

    def stash(match: re.Match) -> str:
        saved.append(match.group(0))
        return _TAG_SENTINEL.format(len(saved) - 1)

    return TAG_PATTERN.sub(stash, text), saved


def _restore_tags(text: str, saved: list[str]) -> str:
    for index, original in enumerate(saved):
        text = text.replace(_TAG_SENTINEL.format(index), original)
    return text


def expand_spintax(text: str, rng: random.Random | None = None) -> str:
    """Expand {a|b|c}, innermost first so nested groups work.

    Merge tags are shielded first: {{Company}} must survive untouched, otherwise
    the inner {Company} looks like a single-option spin group and loses its braces.
    """
    rng = rng or random
    text, saved = _protect_tags(text)
    guard = 0
    while True:
        match = _SPIN_INNERMOST.search(text)
        if not match:
            return _restore_tags(text, saved)
        guard += 1
        if guard > 500:  # malformed template; stop rather than spin forever
            return _restore_tags(text, saved)
        body = match.group(1)
        if "|" in body:
            choice = rng.choice(body.split("|"))
        else:
            choice = body  # {single} is treated as a literal, braces removed
        text = text[: match.start()] + choice + text[match.end():]


def as_mapping(contact: Any) -> dict[str, Any]:
    """Normalise a sqlite3.Row or dict-like into a plain dict.

    sqlite3.Row supports indexing and keys() but has no .get(), so it cannot be
    treated as a Mapping directly.
    """
    if isinstance(contact, dict):
        return contact
    keys = getattr(contact, "keys", None)
    if callable(keys):
        return {key: contact[key] for key in keys()}
    return dict(contact)


def build_context(contact: Mapping[str, Any] | Any) -> dict[str, str]:
    """Merge-tag values for one contact row (a DB row or plain dict)."""
    contact = as_mapping(contact)
    email = str(contact.get("email") or "").strip()
    context: dict[str, str] = {
        "FirstName": clean_first_name(contact.get("person")),
        "FullName": str(contact.get("person") or "").strip() or "there",
        "Company": clean_company(contact.get("company")),
        "Email": email,
        "Domain": email.split("@", 1)[1] if "@" in email else "",
    }

    extra = contact.get("extra_json")
    if extra:
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except json.JSONDecodeError:
                extra = {}
        if isinstance(extra, dict):
            for key, value in extra.items():
                if value is None:
                    continue
                text = str(value).strip()
                if text and text.lower() != "nan":
                    context.setdefault(str(key), text)
    return context


def _lookup(context: Mapping[str, str], name: str) -> str | None:
    if name in context:
        return context[name]
    lowered = {k.lower().replace(" ", ""): v for k, v in context.items()}
    return lowered.get(name.lower().replace(" ", ""))


def apply_tags(text: str, context: Mapping[str, str], html: bool = False) -> str:
    """Substitute {{Tag}}. Unknown tags are left intact so the scorer can flag them."""
    def replace(match: re.Match) -> str:
        value = _lookup(context, match.group(1))
        if value is None:
            return match.group(0)
        return escape(value) if html else value

    return TAG_PATTERN.sub(replace, text)


def render(text: str, context: Mapping[str, str], html: bool = False,
           rng: random.Random | None = None) -> str:
    """Full render: spintax first, then merge tags."""
    return apply_tags(expand_spintax(text, rng), context, html=html)


def unresolved_tags(text: str, known: list[str] | None = None) -> list[str]:
    """Tags that would ship literally to a recipient."""
    known_set = {k.lower().replace(" ", "") for k in (known or BUILTIN_TAGS)}
    found = []
    for match in TAG_PATTERN.finditer(text):
        name = match.group(1)
        if name.lower().replace(" ", "") not in known_set:
            found.append(name)
    return sorted(set(found))


def spintax_variants(text: str) -> int:
    """How many distinct messages the spintax can produce (capped for display)."""
    text, _ = _protect_tags(text)
    total = 1
    for body in re.findall(r"\{([^{}]*)\}", text):
        if "|" in body:
            total *= len(body.split("|"))
        if total > 1_000_000:
            return 1_000_000
    return total


def validate_spintax(text: str) -> str | None:
    """Return an error message if the braces are unbalanced."""
    depth = 0
    for index, char in enumerate(text):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                return f"Unmatched closing brace at position {index}"
    if depth > 0:
        return f"{depth} unclosed brace(s) — every {{ needs a matching }}"
    return None


class VariantCycler:
    """Picks variants without repeating the previous choice back-to-back."""

    def __init__(self, items: list[Any], seed: int | None = None):
        self.items = list(items)
        self.rng = random.Random(seed)
        self._last: Any = None

    def next(self) -> Any:
        if not self.items:
            return None
        if len(self.items) == 1:
            return self.items[0]
        choice = self.rng.choice(self.items)
        attempts = 0
        while choice is self._last and attempts < 8:
            choice = self.rng.choice(self.items)
            attempts += 1
        self._last = choice
        return choice
