"""Themes: the ready-made ones, the ones a user makes, and sharing them as a file.

A theme is a handful of colours a person can reason about (background, sidebar,
cards, text, main colour, second button colour), an optional gradient and a
font. ``app.ui.theme.derive`` works out every other colour from these, so a
user never has to pick twenty shades that must agree with each other.

The Appearance setting holds "Dark", "Light", "System", a preset key such as
"ocean", or "custom:" plus the name of a theme the user made.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.core import db

# Fonts that ship with Windows and keep the layout intact at every text size.
# "" is the app's standard font.
# Georgia, Candara and Constantia are left out: their numbers bob up and down.
FONTS = ["", "Segoe UI", "Arial", "Calibri", "Verdana", "Tahoma", "Trebuchet MS", "Cambria",
         "Consolas"]
COLOURS = ("background", "sidebar", "cards", "text", "accent", "secondary")
DIRECTIONS = ("across", "down", "diagonal")
PLACES = ("sidebar", "buttons", "page")
CUSTOM_PREFIX = "custom:"
SETTING = "custom_themes"
FILE_SUFFIX = ".hptheme"
MAX_NAME = 40
MAX_FILE_BYTES = 64 * 1024

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _preset(name, background, sidebar, cards, text, accent, secondary, gradient=(),
            direction="down", where=(), font="") -> dict:
    return {"name": name, "background": background, "sidebar": sidebar, "cards": cards,
            "text": text, "accent": accent, "secondary": secondary, "gradient": list(gradient),
            "direction": direction, "where": list(where), "font": font}


PRESETS = {
    "midnight": _preset("Midnight", "#121726", "#161c2e", "#1b2236", "#d5dbea", "#6c8cff",
                        "#252e48", ("#1d2a5c", "#3b1f5e"), "diagonal", ("sidebar",)),
    "ocean": _preset("Ocean", "#0f1d24", "#11232c", "#152a34", "#cfe3ea", "#1f9fb5",
                     "#1d3843", ("#0e5a73", "#0c2f4a"), "down", ("sidebar",)),
    "forest": _preset("Forest", "#141c17", "#17211b", "#1b2720", "#d3e2d6", "#3f9f6f",
                      "#22352a", ("#1f4d33", "#16261d"), "down", ("sidebar",)),
    "sunset": _preset("Sunset", "#1e1718", "#241a1c", "#2a1f21", "#ecdcd8", "#d9583c",
                      "#3a2a2b", ("#d9583c", "#b83b6e"), "across", ("buttons",)),
    "graphite": _preset("Graphite", "#18191b", "#1d1e21", "#222326", "#d9d9db", "#7d8a9c",
                        "#2c2d31"),
    "rose": _preset("Rose", "#fbf5f7", "#ffffff", "#ffffff", "#4a3a42", "#c2477a", "#f6e6ec",
                    ("#fbe0ea", "#fff7fa"), "down", ("sidebar",)),
    "paper": _preset("Paper", "#f6f3ec", "#fbf9f4", "#fffdf8", "#3d3a33", "#3f6fb5", "#ece6d8",
                     font="Cambria"),
    "sand": _preset("Sand", "#f5efe4", "#efe5d3", "#fbf7ef", "#4a3f2f", "#a86a14", "#eadfca",
                    ("#b7791f", "#a3521f"), "across", ("buttons",)),
}


# --- colour maths ----------------------------------------------------------------
def _rgb(colour: str) -> tuple[int, int, int]:
    colour = colour.lstrip("#")
    return int(colour[0:2], 16), int(colour[2:4], 16), int(colour[4:6], 16)


def mix(a: str, b: str, amount: float) -> str:
    """``amount`` of the way from colour ``a`` to colour ``b``."""
    first, second = _rgb(a), _rgb(b)
    return "#" + "".join(f"{round(x + (y - x) * amount):02x}" for x, y in zip(first, second))


def luminance(colour: str) -> float:
    def channel(value: int) -> float:
        value /= 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(v) for v in _rgb(colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    """The WCAG contrast ratio, from 1 (none) to 21 (black on white)."""
    light, dark = sorted((luminance(a), luminance(b)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def on_colour(background: str) -> str:
    """White or black text for a button of this colour. White wins unless it is hard to read."""
    return "#ffffff" if contrast("#ffffff", background) >= 3 else "#111111"


def is_dark(spec: dict) -> bool:
    return luminance(spec["background"]) < 0.4


# --- checking a theme -------------------------------------------------------------
def validate(raw) -> dict:
    """A clean copy of a theme, or ValueError in plain English. Files from others land here."""
    if not isinstance(raw, dict):
        raise ValueError("This is not a HomingPigeon theme.")
    name = str(raw.get("name", "")).strip()
    if not name:
        raise ValueError("The theme needs a name.")
    if len(name) > MAX_NAME:
        raise ValueError("The theme name is too long.")
    spec = {"name": name}
    for key in COLOURS:
        value = str(raw.get(key, "")).strip()
        if not _HEX.match(value):
            raise ValueError("The theme has a colour that is not valid.")
        spec[key] = value.lower()
    gradient = raw.get("gradient") or []
    if not isinstance(gradient, list) or len(gradient) not in (0, 2) \
            or not all(isinstance(c, str) and _HEX.match(c) for c in gradient):
        raise ValueError("The theme has a colour that is not valid.")
    spec["gradient"] = [c.lower() for c in gradient]
    direction = raw.get("direction", "down")
    spec["direction"] = direction if direction in DIRECTIONS else "down"
    where = raw.get("where") or []
    spec["where"] = [place for place in PLACES if isinstance(where, list) and place in where]
    font = raw.get("font", "")
    spec["font"] = font if font in FONTS else ""
    return spec


def readability_problems(spec: dict) -> list[str]:
    """English warnings for colours that would be hard to read. Shown, never enforced."""
    problems = []
    if min(contrast(spec["text"], spec[key]) for key in ("background", "sidebar", "cards")) < 4.5:
        problems.append("The text colour is hard to read on the background, sidebar or cards.")
    if contrast(on_colour(spec["accent"]), spec["accent"]) < 3:
        problems.append("Writing on the main colour buttons is hard to read.")
    gradient = spec.get("gradient") or []
    if gradient and "sidebar" in spec.get("where", []) \
            and min(contrast(spec["text"], c) for c in gradient) < 4.5:
        problems.append("The text colour is hard to read on the sidebar gradient.")
    if gradient and "buttons" in spec.get("where", []) \
            and min(contrast(on_colour(spec["accent"]), c) for c in gradient) < 3:
        problems.append("Writing on the gradient buttons is hard to read.")
    return problems


# --- saved themes -----------------------------------------------------------------
def custom_themes() -> list[dict]:
    """The user's own themes. A damaged entry is skipped, never allowed to stop the app."""
    out = []
    for raw in db.get_setting(SETTING, []) or []:
        try:
            out.append(validate(raw))
        except ValueError:
            continue
    return out


def save_custom(spec: dict, replacing: str | None = None) -> dict:
    """Add a theme, or replace the one called ``replacing``. Same name, same theme."""
    spec = validate(spec)
    drop = {spec["name"].casefold(), (replacing or "").casefold()}
    kept = [theme for theme in custom_themes() if theme["name"].casefold() not in drop]
    db.set_setting(SETTING, kept + [spec])
    return spec


def delete_custom(name: str) -> None:
    db.set_setting(SETTING, [theme for theme in custom_themes()
                             if theme["name"].casefold() != name.casefold()])


def custom_key(name: str) -> str:
    return CUSTOM_PREFIX + name


def find(mode: str) -> dict | None:
    """The theme an Appearance value names, or None for Dark, Light and System."""
    if mode in PRESETS:
        return PRESETS[mode]
    if isinstance(mode, str) and mode.startswith(CUSTOM_PREFIX):
        name = mode[len(CUSTOM_PREFIX):].casefold()
        return next((theme for theme in custom_themes() if theme["name"].casefold() == name),
                    None)
    return None


# --- sharing as a file ------------------------------------------------------------
def write_file(path: str | Path, spec: dict) -> Path:
    path = Path(path)
    if path.suffix.lower() != FILE_SUFFIX:
        path = path.with_suffix(FILE_SUFFIX)
    payload = {"homingpigeon_theme": 1, **validate(spec)}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def read_file(path: str | Path) -> dict:
    path = Path(path)
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("This is not a HomingPigeon theme.")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("This is not a HomingPigeon theme.") from None
    if not isinstance(raw, dict) or "homingpigeon_theme" not in raw:
        raise ValueError("This is not a HomingPigeon theme.")
    return validate(raw)
