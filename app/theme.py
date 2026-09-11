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


def font(size: int = 13, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=ui_family(), size=size, weight=weight)


def mono(size: int = 12, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=mono_family(), size=size, weight=weight)


def apply_appearance(mode: str) -> None:
    """mode is 'Dark', 'Light' or 'System'."""
    ctk.set_appearance_mode(mode)


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
            width = max(200, event.width - padding)
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
