"""Theme tokens and styled widget factories.

A softened take on the VS Code palette: same calm, low-contrast greys, but with
rounder corners, warmer neutrals and more breathing room, so the app feels
approachable rather than technical.

Every colour is a (light, dark) tuple so CustomTkinter swaps it automatically
when the appearance mode changes.
"""
import sys
import tkinter.font as tkfont

import customtkinter as ctk

# --- Colour tokens: (light, dark) -------------------------------------------
BG = ("#f7f8fa", "#1f2125")            # window background
BG_SIDEBAR = ("#ffffff", "#25272c")    # side bar
BG_PANEL = ("#ffffff", "#282b31")      # cards / panels
BG_INPUT = ("#ffffff", "#32353c")      # text inputs
BG_HOVER = ("#eef1f6", "#2f323a")      # list hover
BG_SELECTED = ("#e6effb", "#343842")   # list selection
BG_CONSOLE = ("#f4f6f9", "#1b1d21")    # activity panel

BORDER = ("#e3e7ee", "#34373f")
BORDER_STRONG = ("#ccd3de", "#474b55")

FG = ("#3f4650", "#d0d4da")            # primary text
FG_BRIGHT = ("#1f2530", "#f2f4f7")     # headings
FG_MUTED = ("#79818e", "#8d939d")      # secondary text
FG_ON_ACCENT = ("#ffffff", "#ffffff")

ACCENT = ("#2f7fd8", "#3b86dd")        # primary button
ACCENT_HOVER = ("#2670c2", "#4e94e6")
ACCENT_SOFT = ("#e8f1fc", "#2c3a4b")   # tinted background
FOCUS = ("#2f7fd8", "#5aa0e8")
STATUS_BAR = ("#2f7fd8", "#2b5f96")

# Reassuring green, reserved for the go-ahead actions
CONFIRM = ("#2e9e63", "#39ad70")
CONFIRM_HOVER = ("#268a56", "#48bc7e")

SUCCESS = ("#2e9e63", "#6fcf97")
WARNING = ("#b5811f", "#e0b252")
ERROR = ("#cc4b42", "#ef8a7f")
INFO = ("#2f7fd8", "#6fb3ef")

# Used for DNS records and console output
CODE_STRING = ("#9a5b2e", "#e0a878")
CODE_TYPE = ("#2a7d78", "#6fc7bf")
CODE_KEYWORD = ("#2f5fd0", "#7aa6ec")

# --- Metrics ----------------------------------------------------------------
RADIUS = 8
RADIUS_CARD = 14
RADIUS_PILL = 18
PAD = 14
PAD_LARGE = 24
SIDEBAR_WIDTH = 232
INPUT_HEIGHT = 38
BUTTON_HEIGHT = 38
BUTTON_HEIGHT_LARGE = 48


def _pick_family(candidates: list[str], fallback: str) -> str:
    try:
        available = set(tkfont.families())
    except Exception:
        return fallback
    for name in candidates:
        if name in available:
            return name
    return fallback


_UI_FAMILY: str | None = None
_MONO_FAMILY: str | None = None


def ui_family() -> str:
    """Resolve the UI font family once a Tk root exists."""
    global _UI_FAMILY
    if _UI_FAMILY is None:
        default = "Segoe UI" if sys.platform == "win32" else "Helvetica"
        _UI_FAMILY = _pick_family(["Segoe UI Variable Text", "Segoe UI", "Inter", "Helvetica Neue"], default)
    return _UI_FAMILY


def mono_family() -> str:
    global _MONO_FAMILY
    if _MONO_FAMILY is None:
        default = "Consolas" if sys.platform == "win32" else "Courier"
        _MONO_FAMILY = _pick_family(["Cascadia Mono", "Cascadia Code", "Consolas", "JetBrains Mono"], default)
    return _MONO_FAMILY


# Fonts are shared, one object per (family, size, weight), so the "Bold text" setting can
# restyle every label in the app at once. Size scaling is handled by CustomTkinter.
_FONTS: dict[tuple[str, int, str], ctk.CTkFont] = {}
_BOLD_TEXT = False


def _shared_font(kind: str, size: int, weight: str) -> ctk.CTkFont:
    key = (kind, size, weight)
    cached = _FONTS.get(key)
    if cached is None:
        family = ui_family() if kind == "ui" else mono_family()
        effective = "bold" if (_BOLD_TEXT or weight == "bold") else "normal"
        cached = _FONTS[key] = ctk.CTkFont(family=family, size=size, weight=effective)
    return cached


def font(size: int = 13, weight: str = "normal") -> ctk.CTkFont:
    return _shared_font("ui", size, weight)


# --- Icons ------------------------------------------------------------------
# Windows ships a crisp icon font; elsewhere simple Unicode symbols stand in.
ICONS = {
    "home": ("\ue80f", "\u2302"),      # Home
    "guide": ("\ue7c1", "\u2691"),     # Flag
    "account": ("\ue715", "\u2709"),   # Mail
    "shield": ("\uea18", "\u25c8"),    # Shield
    "contacts": ("\ue716", "\u2630"),  # People
    "message": ("\ue70f", "\u270e"),   # Edit
    "options": ("\ue9e9", "\u2261"),   # Equalizer
    "send": ("\ue724", "\u27a4"),      # Send
    "inbox": ("\ue8ca", "\u21a9"),     # Mail reply
    "settings": ("\ue713", "\u2699"),  # Gear
}
_ICON_FAMILY: str | None | bool = False


def icon_family() -> str | None:
    global _ICON_FAMILY
    if _ICON_FAMILY is False:
        found = _pick_family(["Segoe Fluent Icons", "Segoe MDL2 Assets"], "")
        _ICON_FAMILY = found or None
    return _ICON_FAMILY


def icon(name: str) -> str:
    glyph, fallback = ICONS.get(name, ("", "•"))
    return glyph if icon_family() else fallback


def icon_font(size: int = 16) -> ctk.CTkFont:
    family = icon_family()
    if family:
        key = ("icon", size, "normal")
        if key not in _FONTS:
            _FONTS[key] = ctk.CTkFont(family=family, size=size)
        return _FONTS[key]
    return font(size)


def mono(size: int = 12, weight: str = "normal") -> ctk.CTkFont:
    return _shared_font("mono", size, weight)


def set_bold_text(enabled: bool) -> None:
    global _BOLD_TEXT
    _BOLD_TEXT = enabled
    for (kind, _size, weight), shared in _FONTS.items():
        if kind != "icon":
            shared.configure(weight="bold" if (enabled or weight == "bold") else "normal")


def set_text_scale(scale: float) -> None:
    """Make everything bigger or smaller: text, buttons, inputs and spacing."""
    ctk.set_widget_scaling(scale)


def apply_appearance(mode: str) -> None:
    """mode is 'Dark', 'Light' or 'System'."""
    ctk.set_appearance_mode(mode)


# --- High contrast ----------------------------------------------------------
# Stronger text, borders and accents for people who find the soft palette hard to read.
# Colour tokens are read when widgets are built, so the shell rebuilds after a change.
_HIGH_CONTRAST = {
    "BG": ("#ffffff", "#0f1012"),
    "BG_SIDEBAR": ("#eef0f4", "#17181b"),
    "BG_PANEL": ("#ffffff", "#1a1c20"),
    "BG_INPUT": ("#ffffff", "#0b0c0e"),
    "BG_HOVER": ("#dfe5ee", "#2c3038"),
    "BG_SELECTED": ("#cfe0f7", "#26344a"),
    "BG_CONSOLE": ("#f4f6f9", "#0b0c0e"),
    "BORDER": ("#9aa4b2", "#5b606b"),
    "BORDER_STRONG": ("#5f6977", "#8a909c"),
    "FG": ("#12161c", "#f4f6f9"),
    "FG_BRIGHT": ("#000000", "#ffffff"),
    "FG_MUTED": ("#39414c", "#c9ced6"),
    "ACCENT": ("#1459b8", "#4c9bf0"),
    "ACCENT_HOVER": ("#0f4a9c", "#6aaef5"),
    "ACCENT_SOFT": ("#d6e6fa", "#1f3550"),
    "FOCUS": ("#1459b8", "#8cc2fa"),
    "CONFIRM": ("#1d7a48", "#3fbf7a"),
    "CONFIRM_HOVER": ("#166239", "#5ccf90"),
    "SUCCESS": ("#1d7a48", "#7fe0a8"),
    "WARNING": ("#8a5d00", "#ffc861"),
    "ERROR": ("#b3261e", "#ff9d92"),
    "INFO": ("#1459b8", "#8cc2fa"),
}
_NORMAL = {name: globals()[name] for name in _HIGH_CONTRAST}
_HIGH_CONTRAST_ON = False


def set_high_contrast(enabled: bool) -> None:
    global _HIGH_CONTRAST_ON
    _HIGH_CONTRAST_ON = enabled
    globals().update(_HIGH_CONTRAST if enabled else _NORMAL)
    STATUS_COLORS.update({
        "pass": SUCCESS, "ok": SUCCESS, "sent": SUCCESS, "warn": WARNING, "pending": FG_MUTED,
        "skipped": FG_MUTED, "fail": ERROR, "failed": ERROR, "bounced": ERROR, "info": INFO,
    })


def high_contrast() -> bool:
    return _HIGH_CONTRAST_ON


def apply_preferences() -> None:
    """Apply the saved Settings. Call once before the main window is built."""
    from app.core import prefs

    apply_appearance(prefs.get("appearance"))
    set_text_scale(prefs.text_scale())
    set_high_contrast(bool(prefs.get("high_contrast")))
    set_bold_text(bool(prefs.get("bold_text")))


# --- Widget factories -------------------------------------------------------
def heading(master, text: str, size: int = 20, **kwargs) -> ctk.CTkLabel:
    return ctk.CTkLabel(
        master, text=text, font=font(size, "bold"), text_color=FG_BRIGHT, anchor="w", **kwargs
    )


def subheading(master, text: str, **kwargs) -> ctk.CTkLabel:
    return ctk.CTkLabel(
        master, text=text, font=font(14, "bold"), text_color=FG_BRIGHT, anchor="w", **kwargs
    )


def label(master, text: str, muted: bool = False, size: int = 13, wrap: bool = False,
          **kwargs) -> ctk.CTkLabel:
    widget = ctk.CTkLabel(
        master,
        text=text,
        font=font(size),
        text_color=FG_MUTED if muted else FG,
        anchor="w",
        justify="left",
        **kwargs,
    )
    if wrap:
        auto_wrap(widget, master)
    return widget


def auto_wrap(widget, container, padding: int = 40) -> None:
    """Keep a label's wraplength in step with its container, so text never clips.

    The binding outlives the label when the label is destroyed (an empty-state
    hint being replaced, a page rebuilding), so every access is guarded.
    """
    import tkinter as tk

    def resize(event) -> None:
        try:
            if not widget.winfo_exists():
                return
            # event.width is in screen pixels, but CustomTkinter multiplies wraplength by the
            # text-size scaling, so convert back or large text runs off the edge
            scaling = ctk.ScalingTracker.get_widget_scaling(widget)
            width = max(200, int((event.width - padding) / scaling))
            if abs(widget.cget("wraplength") - width) > 8:
                widget.configure(wraplength=width)
        except (tk.TclError, AttributeError):
            return  # the widget has gone away; nothing to resize

    container.bind("<Configure>", resize, add="+")


def card(master, **kwargs) -> ctk.CTkFrame:
    kwargs.setdefault("fg_color", BG_PANEL)
    kwargs.setdefault("border_color", BORDER)
    kwargs.setdefault("border_width", 1)
    kwargs.setdefault("corner_radius", RADIUS_CARD)
    return ctk.CTkFrame(master, **kwargs)


def primary_button(master, text: str, command=None, **kwargs) -> ctk.CTkButton:
    kwargs.setdefault("fg_color", ACCENT)
    kwargs.setdefault("hover_color", ACCENT_HOVER)
    kwargs.setdefault("text_color", FG_ON_ACCENT)
    kwargs.setdefault("corner_radius", RADIUS)
    kwargs.setdefault("height", BUTTON_HEIGHT)
    kwargs.setdefault("font", font(13, "bold"))
    return ctk.CTkButton(master, text=text, command=command, **kwargs)


def confirm_button(master, text: str, command=None, **kwargs) -> ctk.CTkButton:
    """The big, green, go-ahead button. Reserved for the main action on a page."""
    kwargs.setdefault("fg_color", CONFIRM)
    kwargs.setdefault("hover_color", CONFIRM_HOVER)
    kwargs.setdefault("text_color", FG_ON_ACCENT)
    kwargs.setdefault("corner_radius", RADIUS_PILL)
    kwargs.setdefault("height", BUTTON_HEIGHT_LARGE)
    kwargs.setdefault("font", font(15, "bold"))
    return ctk.CTkButton(master, text=text, command=command, **kwargs)


def secondary_button(master, text: str, command=None, **kwargs) -> ctk.CTkButton:
    kwargs.setdefault("fg_color", "transparent")
    kwargs.setdefault("hover_color", BG_HOVER)
    kwargs.setdefault("text_color", FG)
    kwargs.setdefault("border_color", BORDER_STRONG)
    kwargs.setdefault("border_width", 1)
    kwargs.setdefault("corner_radius", RADIUS)
    kwargs.setdefault("height", BUTTON_HEIGHT)
    kwargs.setdefault("font", font(13))
    return ctk.CTkButton(master, text=text, command=command, **kwargs)


def danger_button(master, text: str, command=None, **kwargs) -> ctk.CTkButton:
    kwargs.setdefault("fg_color", "transparent")
    kwargs.setdefault("hover_color", ("#f5d5d5", "#4d2626"))
    kwargs.setdefault("text_color", ERROR)
    kwargs.setdefault("border_color", ERROR)
    kwargs.setdefault("border_width", 1)
    kwargs.setdefault("corner_radius", RADIUS)
    kwargs.setdefault("height", BUTTON_HEIGHT)
    kwargs.setdefault("font", font(13))
    return ctk.CTkButton(master, text=text, command=command, **kwargs)


def entry(master, placeholder: str = "", **kwargs) -> ctk.CTkEntry:
    kwargs.setdefault("fg_color", BG_INPUT)
    kwargs.setdefault("border_color", BORDER_STRONG)
    kwargs.setdefault("border_width", 1)
    kwargs.setdefault("corner_radius", RADIUS)
    kwargs.setdefault("height", INPUT_HEIGHT)
    kwargs.setdefault("text_color", FG)
    kwargs.setdefault("font", font(13))
    return ctk.CTkEntry(master, placeholder_text=placeholder, **kwargs)


def textbox(master, monospace: bool = False, **kwargs) -> ctk.CTkTextbox:
    kwargs.setdefault("fg_color", BG_INPUT)
    kwargs.setdefault("border_color", BORDER_STRONG)
    kwargs.setdefault("border_width", 1)
    kwargs.setdefault("corner_radius", RADIUS)
    kwargs.setdefault("text_color", FG)
    kwargs.setdefault("font", mono(12) if monospace else font(13))
    kwargs.setdefault("wrap", "word")
    return ctk.CTkTextbox(master, **kwargs)


def option_menu(master, values: list[str], **kwargs) -> ctk.CTkOptionMenu:
    kwargs.setdefault("fg_color", BG_INPUT)
    kwargs.setdefault("button_color", BORDER_STRONG)
    kwargs.setdefault("button_hover_color", ACCENT)
    kwargs.setdefault("text_color", FG)
    kwargs.setdefault("dropdown_fg_color", BG_PANEL)
    kwargs.setdefault("dropdown_hover_color", BG_HOVER)
    kwargs.setdefault("dropdown_text_color", FG)
    kwargs.setdefault("corner_radius", RADIUS)
    kwargs.setdefault("height", INPUT_HEIGHT)
    kwargs.setdefault("font", font(13))
    kwargs.setdefault("dropdown_font", font(13))
    return ctk.CTkOptionMenu(master, values=values, **kwargs)


def checkbox(master, text: str, **kwargs) -> ctk.CTkCheckBox:
    kwargs.setdefault("fg_color", ACCENT)
    kwargs.setdefault("hover_color", ACCENT_HOVER)
    kwargs.setdefault("border_color", BORDER_STRONG)
    kwargs.setdefault("text_color", FG)
    kwargs.setdefault("corner_radius", 3)
    kwargs.setdefault("border_width", 1)
    kwargs.setdefault("checkbox_width", 18)
    kwargs.setdefault("checkbox_height", 18)
    kwargs.setdefault("font", font(13))
    return ctk.CTkCheckBox(master, text=text, **kwargs)


def switch(master, text: str, **kwargs) -> ctk.CTkSwitch:
    kwargs.setdefault("progress_color", ACCENT)
    kwargs.setdefault("button_color", ("#ffffff", "#d4d4d4"))
    kwargs.setdefault("fg_color", BORDER_STRONG)
    kwargs.setdefault("text_color", FG)
    kwargs.setdefault("font", font(13))
    return ctk.CTkSwitch(master, text=text, **kwargs)


def separator(master, **kwargs) -> ctk.CTkFrame:
    kwargs.setdefault("fg_color", BORDER)
    kwargs.setdefault("height", 1)
    kwargs.setdefault("corner_radius", 0)
    return ctk.CTkFrame(master, **kwargs)


def scroll_frame(master, **kwargs) -> ctk.CTkScrollableFrame:
    kwargs.setdefault("fg_color", "transparent")
    kwargs.setdefault("corner_radius", 0)
    kwargs.setdefault("scrollbar_button_color", BORDER_STRONG)
    kwargs.setdefault("scrollbar_button_hover_color", FG_MUTED)
    return ctk.CTkScrollableFrame(master, **kwargs)


# --- Status helpers ---------------------------------------------------------
STATUS_COLORS = {
    "pass": SUCCESS,
    "ok": SUCCESS,
    "sent": SUCCESS,
    "warn": WARNING,
    "pending": FG_MUTED,
    "skipped": FG_MUTED,
    "fail": ERROR,
    "failed": ERROR,
    "bounced": ERROR,
    "info": INFO,
}

STATUS_ICONS = {
    "pass": "✓",   # check
    "ok": "✓",
    "warn": "⚠",   # warning sign
    "fail": "✕",   # cross
    "info": "ℹ",
    "pending": "○",
}


def status_color(status: str):
    return STATUS_COLORS.get(str(status).lower(), FG_MUTED)
