"""VS Code-inspired theme tokens and styled widget factories.

Every colour is a (light, dark) tuple so CustomTkinter swaps it automatically
when the appearance mode changes. Palettes follow VS Code's Light+ / Dark+.
"""
import sys
import tkinter.font as tkfont

import customtkinter as ctk

# --- Colour tokens: (Light+, Dark+) -----------------------------------------
BG = ("#ffffff", "#1e1e1e")            # editor background
BG_SIDEBAR = ("#f3f3f3", "#252526")    # side bar
BG_PANEL = ("#f8f8f8", "#252526")      # cards / panels
BG_INPUT = ("#ffffff", "#3c3c3c")      # text inputs
BG_HOVER = ("#e8e8e8", "#2a2d2e")      # list hover
BG_SELECTED = ("#e4e6f1", "#37373d")   # list selection
BG_CONSOLE = ("#f3f3f3", "#181818")    # terminal panel

BORDER = ("#e5e5e5", "#3c3c3c")
BORDER_STRONG = ("#cecece", "#545454")

FG = ("#3b3b3b", "#cccccc")            # primary text
FG_BRIGHT = ("#1f1f1f", "#ffffff")     # headings
FG_MUTED = ("#6f6f6f", "#858585")      # secondary text
FG_ON_ACCENT = ("#ffffff", "#ffffff")

ACCENT = ("#005fb8", "#0e639c")        # primary button
ACCENT_HOVER = ("#0258a8", "#1177bb")
FOCUS = ("#005fb8", "#007fd4")         # focus ring
STATUS_BAR = ("#0066b8", "#007acc")

SUCCESS = ("#1a7f37", "#89d185")
WARNING = ("#bf8803", "#cca700")
ERROR = ("#cd3131", "#f48771")
INFO = ("#0066b8", "#4fc1ff")

# Syntax-ish accents, used for DNS records and console output
CODE_STRING = ("#a31515", "#ce9178")
CODE_TYPE = ("#267f99", "#4ec9b0")
CODE_KEYWORD = ("#0000ff", "#569cd6")

# --- Metrics ----------------------------------------------------------------
RADIUS = 4
RADIUS_CARD = 6
PAD = 12
PAD_LARGE = 20
SIDEBAR_WIDTH = 220
INPUT_HEIGHT = 32
BUTTON_HEIGHT = 32


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
    """Keep a label's wraplength in step with its container, so text never clips."""
    def resize(event) -> None:
        width = max(200, event.width - padding)
        if abs(widget.cget("wraplength") - width) > 8:
            widget.configure(wraplength=width)

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
    kwargs.setdefault("font", font(13))
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
