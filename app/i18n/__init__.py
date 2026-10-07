"""The app's languages: English, Arabic, German, Spanish and French.

Every piece of text is written in English in the code, and the English text is
also the key into the translations in ``locales/<code>.json``. Anything missing
from a translation falls back to English, so a half-translated string can never
crash the app or leave a blank button.

How text reaches the screen translated:
  * the shared widgets (labels, buttons, dialogs, toasts, tables) pass whatever
    they are given through ``t()``, so a plain English string can be handed to
    them as it is;
  * a sentence with something filled in is written as a template,
    ``t("{count} contacts imported", count=n)``, so the template is the key and
    each language can put the number where its grammar wants it.

Nothing is translated at import time. Module-level text stays English and is
translated where it is shown, which is what lets the language change while the
app is open: the window is simply rebuilt.

Pure Python, no Qt, so ``app/core`` can use it too.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# (code, name in its own language, name in English)
LANGUAGES = [
    ("en", "English", "English"),
    ("ar", "العربية", "Arabic"),
    ("de", "Deutsch", "German"),
    ("es", "Español", "Spanish"),
    ("fr", "Français", "French"),
]
CODES = [code for code, _native, _english in LANGUAGES]
RTL_LANGUAGES = {"ar"}
DEFAULT = "en"

LOCALE_DIR = Path(__file__).resolve().parent / "locales"

_language = DEFAULT
_catalogs: dict[str, dict[str, str]] = {}

_FIELD = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)(?:![rsa])?(?::[^{}]*)?\}")


def catalog(code: str) -> dict[str, str]:
    """English text -> translation for one language. Empty for English."""
    if code == DEFAULT:
        return {}
    if code not in _catalogs:
        path = LOCALE_DIR / f"{code}.json"
        try:
            _catalogs[code] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            _catalogs[code] = {}
    return _catalogs[code]


def set_language(code: str | None) -> str:
    global _language
    _language = code if code in CODES else DEFAULT
    return _language


def language() -> str:
    return _language


def is_rtl(code: str | None = None) -> bool:
    return (code or _language) in RTL_LANGUAGES


def native_name(code: str) -> str:
    for key, native, _english in LANGUAGES:
        if key == code:
            return native
    return code


def system_language(locale_name: str | None) -> str:
    """The supported language closest to the computer's own, else English.

    ``locale_name`` is something like "de_DE" or "ar-AE".
    """
    if not locale_name:
        return DEFAULT
    prefix = re.split(r"[_\-.]", locale_name.strip().lower())[0]
    return prefix if prefix in CODES else DEFAULT


def lookup(text: str, code: str | None = None) -> str:
    """The translation of one exact English string, or the string itself."""
    return catalog(code or _language).get(text, text)


def t(text: Any, **values: Any) -> Any:
    """Translate ``text`` into the current language.

    With ``values`` it is a template: ``{name}`` fields are filled in after
    translating, and any value that is itself a known English string (a status,
    a category) is translated too. A translation whose fields do not match the
    English is ignored rather than allowed to raise.

    Anything that is not a string is returned unchanged, so it is safe to wrap
    a value whose type is not known.
    """
    if not isinstance(text, str) or not text:
        return text
    translated = lookup(text)
    if not values:
        return translated
    filled = {key: (lookup(value) if isinstance(value, str) else value)
              for key, value in values.items()}
    try:
        return translated.format(**filled)
    except (KeyError, IndexError, ValueError):
        try:
            return text.format(**filled)
        except (KeyError, IndexError, ValueError):
            return text


def fields(text: str) -> set[str]:
    """The ``{name}`` fields in a template, for checking translations keep them."""
    plain = text.replace("{{", "").replace("}}", "")
    return set(_FIELD.findall(plain))
