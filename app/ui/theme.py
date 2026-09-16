"""Design tokens and the application-wide stylesheet.

Everything visual comes from one place: a token dictionary is chosen for the
current appearance/contrast setting, and :func:`stylesheet` turns it into a
single QSS string applied with ``QApplication.setStyleSheet``.

That is the whole point of this module. Switching theme, contrast, bold text or
text size never destroys or rebuilds a widget. It re-renders one string and
hands it to Qt, which repaints in a single frame. The old CustomTkinter build
had to tear down and rebuild every page, which is what made Settings feel slow.
"""
from __future__ import annotations

import sys
from functools import lru_cache

from PyQt6.QtGui import QColor, QFontDatabase

# --- Metrics ----------------------------------------------------------------
RADIUS = 8
RADIUS_CARD = 12
RADIUS_PILL = 18
PAD = 14
PAD_LARGE = 22
SIDEBAR_WIDTH = 248
INPUT_HEIGHT = 34
BUTTON_HEIGHT = 34
BUTTON_HEIGHT_LARGE = 44

# Above this text scale the sidebar subtitles are hidden so the menu still fits
SUBTITLE_MAX_SCALE = 1.15
# Sidebar entry heights, with and without the second line of text. Generous on
# purpose: two lines of text need clear space above and below, or the highlight
# looks like it is squeezing them. 54 leaves about ten pixels either side and
# still lets all ten entries fit the window at the default text size.
NAV_HEIGHT = 54
NAV_HEIGHT_COMPACT = 42


def nav_height() -> int:
    """The height of one sidebar entry at the current text scale.

    Read by both the stylesheet and :class:`~app.ui.main_window.NavButton`, so
    the QSS ``min-height`` and the widget's size hint can never disagree. They
    have to agree: re-polishing a widget replaces size constraints set in code
    with whatever the stylesheet asks for.
    """
    scale = text_scale()
    return round((NAV_HEIGHT if scale <= SUBTITLE_MAX_SCALE else NAV_HEIGHT_COMPACT) * scale)


# --- Colour tokens ----------------------------------------------------------
# A softened take on the VS Code palette: calm, low-contrast greys with rounder
# corners and warmer neutrals, so the app feels approachable rather than technical.
LIGHT = {
    "bg": "#f7f8fa",
    "bg_sidebar": "#ffffff",
    "bg_panel": "#ffffff",
    "bg_input": "#ffffff",
    "bg_hover": "#eef1f6",
    "bg_selected": "#e6effb",
    "bg_console": "#f4f6f9",
    "bg_header": "#f0f2f6",
    "border": "#e3e7ee",
    "border_strong": "#ccd3de",
    "fg": "#3f4650",
    "fg_bright": "#1f2530",
    "fg_muted": "#79818e",
    "fg_on_accent": "#ffffff",
    "accent": "#2f7fd8",
    "accent_hover": "#2670c2",
    "accent_soft": "#e8f1fc",
    "focus": "#2f7fd8",
    "status_bar": "#2f7fd8",
    "confirm": "#2e9e63",
    "confirm_hover": "#268a56",
    "success": "#2e9e63",
    "warning": "#b5811f",
    "error": "#cc4b42",
    "error_soft": "#f7e3e1",
    "info": "#2f7fd8",
    "code": "#9a5b2e",
    "row_alt": "#f7f9fc",
    # Table selection is its own token: the general "selected" grey is far too
    # close to the panel colour to tell a picked row from an unpicked one.
    "row_selected": "#bcd9f8",
    "row_selected_edge": "#2f7fd8",
}

DARK = {
    "bg": "#1f2125",
    "bg_sidebar": "#25272c",
    "bg_panel": "#282b31",
    "bg_input": "#32353c",
    "bg_hover": "#2f323a",
    "bg_selected": "#343842",
    "bg_console": "#1b1d21",
    "bg_header": "#2c2f36",
    "border": "#34373f",
    "border_strong": "#474b55",
    "fg": "#d0d4da",
    "fg_bright": "#f2f4f7",
    "fg_muted": "#8d939d",
    "fg_on_accent": "#ffffff",
    "accent": "#3b86dd",
    "accent_hover": "#4e94e6",
    "accent_soft": "#2c3a4b",
    "focus": "#5aa0e8",
    "status_bar": "#2b5f96",
    "confirm": "#39ad70",
    "confirm_hover": "#48bc7e",
    "success": "#6fcf97",
    "warning": "#e0b252",
    "error": "#ef8a7f",
    "error_soft": "#4d2626",
    "info": "#6fb3ef",
    "code": "#e0a878",
    "row_alt": "#2b2e34",
    "row_selected": "#3c5f8c",
    "row_selected_edge": "#6fb3ef",
}

# Stronger text, borders and accents for people who find the soft palette hard to read.
LIGHT_HC = dict(LIGHT, **{
    "bg": "#ffffff", "bg_sidebar": "#eef0f4", "bg_panel": "#ffffff", "bg_input": "#ffffff",
    "bg_hover": "#dfe5ee", "bg_selected": "#cfe0f7", "bg_console": "#f4f6f9",
    "bg_header": "#e4e8ef", "border": "#9aa4b2", "border_strong": "#5f6977",
    "fg": "#12161c", "fg_bright": "#000000", "fg_muted": "#39414c",
    "accent": "#1459b8", "accent_hover": "#0f4a9c", "accent_soft": "#d6e6fa",
    "focus": "#1459b8", "confirm": "#1d7a48", "confirm_hover": "#166239",
    "success": "#1d7a48", "warning": "#8a5d00", "error": "#b3261e", "info": "#1459b8",
    "row_alt": "#f0f3f8", "row_selected": "#9cc8f5", "row_selected_edge": "#0f4a9c",
})

DARK_HC = dict(DARK, **{
    "bg": "#0f1012", "bg_sidebar": "#17181b", "bg_panel": "#1a1c20", "bg_input": "#0b0c0e",
    "bg_hover": "#2c3038", "bg_selected": "#26344a", "bg_console": "#0b0c0e",
    "bg_header": "#202329", "border": "#5b606b", "border_strong": "#8a909c",
    "fg": "#f4f6f9", "fg_bright": "#ffffff", "fg_muted": "#c9ced6",
    "accent": "#4c9bf0", "accent_hover": "#6aaef5", "accent_soft": "#1f3550",
    "focus": "#8cc2fa", "confirm": "#3fbf7a", "confirm_hover": "#5ccf90",
    "success": "#7fe0a8", "warning": "#ffc861", "error": "#ff9d92", "info": "#8cc2fa",
    "row_alt": "#191b1f", "row_selected": "#2f6299", "row_selected_edge": "#8cc2fa",
})


# --- Current state ----------------------------------------------------------
# Read by widgets that paint themselves (the range slider, status icons) and by
# anything that needs a colour as a value rather than as a stylesheet rule.
_state = {
    "appearance": "Dark",   # 'Dark', 'Light' or 'System'
    "dark": True,
    "high_contrast": False,
    "bold_text": False,
    "scale": 1.15,
}


def system_prefers_dark() -> bool:
    """Windows' own app-theme setting; anything unreadable falls back to dark."""
    if sys.platform == "win32":
        try:
            import winreg

            key = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
                return not winreg.QueryValueEx(handle, "AppsUseLightTheme")[0]
        except OSError:
            return True
    try:
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            window = app.palette().color(app.palette().ColorRole.Window)
            return window.lightness() < 128
    except Exception:  # noqa: BLE001 - never let theme detection stop startup
        pass
    return True


def set_appearance(mode: str) -> None:
    _state["appearance"] = mode
    _state["dark"] = system_prefers_dark() if mode == "System" else (mode == "Dark")


def set_high_contrast(enabled: bool) -> None:
    _state["high_contrast"] = bool(enabled)


def set_bold_text(enabled: bool) -> None:
    _state["bold_text"] = bool(enabled)


def set_text_scale(scale: float) -> None:
    _state["scale"] = float(scale)


def is_dark() -> bool:
    return bool(_state["dark"])


def text_scale() -> float:
    return float(_state["scale"])


def bold_text() -> bool:
    return bool(_state["bold_text"])


def tokens() -> dict[str, str]:
    if _state["high_contrast"]:
        return DARK_HC if _state["dark"] else LIGHT_HC
    return DARK if _state["dark"] else LIGHT


def color(name: str) -> str:
    """One token as a hex string, for widgets that paint themselves."""
    return tokens().get(name, "#888888")


def qcolor(name: str) -> QColor:
    return QColor(color(name))


def apply_preferences() -> None:
    """Load the saved Settings. Call once before the main window is built."""
    from app.core import prefs

    set_appearance(prefs.get("appearance"))
    set_high_contrast(bool(prefs.get("high_contrast")))
    set_bold_text(bool(prefs.get("bold_text")))
    set_text_scale(prefs.text_scale())


# --- Fonts ------------------------------------------------------------------
@lru_cache(maxsize=1)
def ui_family() -> str:
    families = set(QFontDatabase.families())
    for name in ("Segoe UI Variable Text", "Segoe UI", "Inter", "Helvetica Neue", "Noto Sans"):
        if name in families:
            return name
    return "Segoe UI" if sys.platform == "win32" else "Sans Serif"


@lru_cache(maxsize=1)
def mono_family() -> str:
    families = set(QFontDatabase.families())
    for name in ("Cascadia Mono", "Cascadia Code", "Consolas", "JetBrains Mono", "DejaVu Sans Mono"):
        if name in families:
            return name
    return "Consolas" if sys.platform == "win32" else "Monospace"


@lru_cache(maxsize=1)
def icon_family() -> str | None:
    """Windows ships a crisp icon font; elsewhere Unicode symbols stand in."""
    families = set(QFontDatabase.families())
    for name in ("Segoe Fluent Icons", "Segoe MDL2 Assets"):
        if name in families:
            return name
    return None


# QSS can only point at an image by file path, and it has no way to draw a
# triangle, so the two glyphs the controls need are written out as small SVGs.
@lru_cache(maxsize=16)
def _asset(name: str, content: str) -> str:
    from app import config

    config.ensure_dirs()
    path = config.DATA_DIR / name
    if not path.exists():
        path.write_text(content, encoding="utf-8")
    return path.as_posix()


def check_mark() -> str:
    """The tick inside a ticked checkbox.

    White on transparent, which reads correctly on the accent fill in every
    palette, so one file serves all four themes.
    """
    return _asset(
        "check.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
        '<path d="M3.5 8.5 L6.5 11.5 L12.5 4.5" fill="none" stroke="#ffffff" '
        'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>')


def chevron(token: str = "fg_muted") -> str:
    """The drop-down arrow. One file per colour, so it follows the theme."""
    shade = color(token).lstrip("#")
    return _asset(
        f"chevron-{shade}.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 8">'
        f'<path d="M1.5 2 L6 6.5 L10.5 2" fill="none" stroke="#{shade}" '
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>')


def px(size: int) -> int:
    """A design size in points scaled by the Text size setting."""
    return max(8, round(size * _state["scale"]))


ICONS = {
    "home": ("", "⌂"),
    "guide": ("", "⚑"),
    "account": ("", "✉"),
    "shield": ("", "◈"),
    "contacts": ("", "☰"),
    "message": ("", "✎"),
    "options": ("", "≡"),
    "send": ("", "➤"),
    "history": ("", "↺"),
    "inbox": ("", "↩"),
    "settings": ("", "⚙"),
}


def icon(name: str) -> str:
    glyph, fallback = ICONS.get(name, ("", "•"))
    return glyph if icon_family() else fallback


# --- Status helpers ---------------------------------------------------------
STATUS_ICONS = {
    "pass": "✓", "ok": "✓", "sent": "✓",
    "warn": "⚠", "fail": "✕", "failed": "✕", "bounced": "✕",
    "info": "ℹ", "pending": "○", "skipped": "○",
}

_STATUS_TOKEN = {
    "pass": "success", "ok": "success", "sent": "success",
    "warn": "warning", "pending": "fg_muted", "skipped": "fg_muted",
    "fail": "error", "failed": "error", "bounced": "error", "error": "error",
    "info": "info", "success": "success",
}


def status_color(status: str) -> str:
    return color(_STATUS_TOKEN.get(str(status).lower(), "fg_muted"))


# --- Stylesheet -------------------------------------------------------------
def stylesheet() -> str:
    """The entire application's QSS, built from the active tokens and text scale.

    Kept as one string applied at application level: Qt then styles every widget
    that exists now and every widget created later, with no per-widget work.
    """
    t = tokens()
    s = _state["scale"]
    weight = "600" if _state["bold_text"] else "400"
    heavy = "700" if _state["bold_text"] else "600"
    ui, mono = ui_family(), mono_family()

    base = px(13)
    small = px(12)
    tiny = px(11)
    control_h = round(INPUT_HEIGHT * s)
    button_h = round(BUTTON_HEIGHT * s)
    nav_h = nav_height()
    # A radius larger than half the box makes Qt give up and draw a square, so
    # the tick box and radio dot are sized together rather than independently.
    box = px(16)
    box_radius = box // 2
    dot = max(3, box // 4)

    return f"""
/* ---------- base ---------- */
QWidget {{
    background-color: transparent;
    color: {t['fg']};
    font-family: "{ui}";
    font-size: {base}px;
    font-weight: {weight};
}}
QMainWindow, QDialog {{ background-color: {t['bg']}; }}
QToolTip {{
    background-color: {t['bg_panel']};
    color: {t['fg']};
    border: 1px solid {t['border_strong']};
    padding: 6px 8px;
    border-radius: {RADIUS}px;
}}

/* ---------- typography roles ---------- */
QLabel[role="heading"]    {{ color: {t['fg_bright']}; font-size: {px(20)}px; font-weight: {heavy}; }}
QLabel[role="subheading"] {{ color: {t['fg_bright']}; font-size: {px(15)}px; font-weight: {heavy}; }}
QLabel[role="section-title"] {{ color: {t['fg_bright']}; font-size: {px(15)}px; font-weight: {heavy}; }}
QLabel[role="app-title"]  {{ color: {t['fg_bright']}; font-size: {px(17)}px; font-weight: 700; }}
QLabel[role="field"]      {{ color: {t['fg']};        font-size: {small}px;  font-weight: {heavy}; }}
QLabel[role="muted"]      {{ color: {t['fg_muted']};  font-size: {small}px; }}
QLabel[role="hint"]       {{ color: {t['fg_muted']};  font-size: {tiny}px; }}
QLabel[role="value"]      {{ color: {t['fg_bright']}; font-size: {px(24)}px; font-weight: {heavy}; }}
QLabel[role="score"]      {{ font-size: {px(36)}px; font-weight: {heavy}; }}
QLabel[tone="success"] {{ color: {t['success']}; }}
QLabel[tone="warning"] {{ color: {t['warning']}; }}
QLabel[tone="error"]   {{ color: {t['error']}; }}
QLabel[tone="muted"]   {{ color: {t['fg_muted']}; }}
QLabel[tone="accent"]  {{ color: {t['accent']}; }}
QLabel[tone="bright"]  {{ color: {t['fg_bright']}; }}
QLabel:disabled {{ color: {t['fg_muted']}; }}

/* ---------- containers ----------
   QLabel derives from QFrame, so every rule here is written against roles that
   only the container widgets use. A label must never share a role name with a
   card, or it picks up the card's border. */
QFrame[role="card"], QFrame[role="section"] {{
    background-color: {t['bg_panel']};
    border: 1px solid {t['border']};
    border-radius: {RADIUS_CARD}px;
}}
QFrame[role="danger-card"] {{
    background-color: {t['bg_panel']};
    border: 1px solid {t['error']};
    border-radius: {RADIUS_CARD}px;
}}
QFrame[role="tint-card"] {{
    background-color: {t['accent_soft']};
    border: 1px solid {t['border']};
    border-radius: {RADIUS_CARD}px;
}}
QFrame[role="console"] {{
    background-color: {t['bg_console']};
    border: 1px solid {t['border']};
    border-radius: {RADIUS}px;
}}
QFrame[role="separator"] {{ background-color: {t['border']}; border: none; }}
QFrame[role="plain"] {{ background-color: transparent; border: none; }}

/* ---------- inputs ---------- */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QComboBox {{
    background-color: {t['bg_input']};
    color: {t['fg']};
    border: 1px solid {t['border_strong']};
    border-radius: {RADIUS}px;
    padding: 4px 8px;
    selection-background-color: {t['accent']};
    selection-color: {t['fg_on_accent']};
}}
QLineEdit, QComboBox, QSpinBox {{ min-height: {control_h}px; max-height: {control_h}px; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus {{
    border: 1px solid {t['focus']};
}}
QLineEdit:disabled, QPlainTextEdit:disabled, QComboBox:disabled {{
    color: {t['fg_muted']};
    background-color: {t['bg_hover']};
}}
QPlainTextEdit[role="mono"], QTextEdit[role="mono"] {{
    font-family: "{mono}";
    font-size: {px(12)}px;
}}
QPlainTextEdit[role="code"] {{
    font-family: "{mono}";
    font-size: {px(12)}px;
    color: {t['code']};
}}
QPlainTextEdit[role="console"] {{
    font-family: "{mono}";
    font-size: {px(12)}px;
    background-color: transparent;
    border: none;
}}
QComboBox::drop-down {{ border: none; width: {px(22)}px; }}
QComboBox::down-arrow {{
    image: url("{chevron()}");
    width: {px(11)}px;
    height: {px(7)}px;
    margin-right: {px(8)}px;
}}
QComboBox QAbstractItemView {{
    background-color: {t['bg_panel']};
    color: {t['fg']};
    border: 1px solid {t['border_strong']};
    border-radius: {RADIUS}px;
    selection-background-color: {t['bg_selected']};
    selection-color: {t['fg_bright']};
    outline: none;
    padding: 4px;
}}

/* ---------- buttons ---------- */
QPushButton {{
    background-color: transparent;
    color: {t['fg']};
    border: 1px solid {t['border_strong']};
    border-radius: {RADIUS}px;
    padding: 0 {px(14)}px;
    min-height: {button_h}px;
    font-size: {base}px;
    font-weight: {weight};
}}
QPushButton:hover  {{ background-color: {t['bg_hover']}; }}
QPushButton:pressed {{ background-color: {t['bg_selected']}; }}
QPushButton:disabled {{ color: {t['fg_muted']}; border-color: {t['border']}; background: transparent; }}

QPushButton[kind="primary"] {{
    background-color: {t['accent']};
    color: {t['fg_on_accent']};
    border: 1px solid {t['accent']};
    font-weight: {heavy};
}}
QPushButton[kind="primary"]:hover  {{ background-color: {t['accent_hover']}; border-color: {t['accent_hover']}; }}
QPushButton[kind="primary"]:pressed {{ background-color: {t['accent_hover']}; }}
QPushButton[kind="primary"]:disabled {{
    background-color: {t['border']}; border-color: {t['border']}; color: {t['fg_muted']};
}}

QPushButton[kind="confirm"] {{
    background-color: {t['confirm']};
    color: #ffffff;
    border: 1px solid {t['confirm']};
    border-radius: {round(RADIUS_PILL * s)}px;
    min-height: {round(BUTTON_HEIGHT_LARGE * s)}px;
    padding: 0 {px(22)}px;
    font-size: {px(15)}px;
    font-weight: {heavy};
}}
QPushButton[kind="confirm"]:hover {{ background-color: {t['confirm_hover']}; border-color: {t['confirm_hover']}; }}
QPushButton[kind="confirm"]:disabled {{
    background-color: {t['border']}; border-color: {t['border']}; color: {t['fg_muted']};
}}

QPushButton[kind="danger"] {{ color: {t['error']}; border: 1px solid {t['error']}; }}
QPushButton[kind="danger"]:hover {{ background-color: {t['error_soft']}; }}
QPushButton[kind="danger"]:disabled {{
    color: {t['fg_muted']}; border-color: {t['border']}; background: transparent;
}}

QPushButton[kind="ghost"] {{ border: none; color: {t['accent']}; }}
QPushButton[kind="ghost"]:hover {{ background-color: {t['bg_hover']}; }}

QPushButton[kind="small"] {{
    min-height: {round(26 * s)}px;
    padding: 0 {px(10)}px;
    font-size: {small}px;
}}

/* choice buttons and tabs: exactly one selected at a time */
QPushButton[choice="off"] {{
    background-color: {t['bg_panel']};
    color: {t['fg']};
    border: 1px solid {t['border_strong']};
}}
QPushButton[choice="off"]:hover {{ background-color: {t['bg_hover']}; }}
QPushButton[choice="on"] {{
    background-color: {t['accent']};
    color: {t['fg_on_accent']};
    border: 1px solid {t['accent']};
    font-weight: {heavy};
}}
QPushButton[choice="on"]:hover {{ background-color: {t['accent_hover']}; }}

/* ---------- sidebar ---------- */
QFrame#Sidebar {{ background-color: {t['bg_sidebar']}; border-right: 1px solid {t['border']}; }}
QFrame#Sidebar QLabel {{ background: transparent; }}
/* Both states carry the same 3px left edge, transparent when the entry is not
   the current one, so the icons stay on one vertical line as the highlight moves. */
QPushButton[nav="off"] {{
    background-color: transparent;
    border: none;
    border-left: {round(3 * s)}px solid transparent;
    border-radius: {RADIUS}px;
    text-align: left;
    padding: 0;
    min-height: {nav_h}px;
}}
QPushButton[nav="off"]:hover {{ background-color: {t['bg_hover']}; }}
QPushButton[nav="on"] {{
    background-color: {t['accent_soft']};
    border: none;
    border-left: {round(3 * s)}px solid {t['accent']};
    border-radius: {RADIUS}px;
    text-align: left;
    padding: 0;
    min-height: {nav_h}px;
}}
QPushButton[nav="on"]:hover {{ background-color: {t['accent_soft']}; }}

/* ---------- status bar ---------- */
QFrame#StatusBar {{ background-color: {t['status_bar']}; border: none; }}
QFrame#StatusBar QLabel {{ color: #ffffff; font-size: {small}px; background: transparent; }}

/* ---------- checkboxes, radios, switches ---------- */
QCheckBox, QRadioButton {{ spacing: {px(8)}px; color: {t['fg']}; background: transparent; }}
/* QSS width/height is the content box, so the border is added on top of it.
   Each state therefore shrinks the content by its own border width, keeping the
   outer box exactly `box` across; otherwise the radius is too small for the real
   size and a selected radio button draws as a rounded square. */
QCheckBox::indicator, QRadioButton::indicator {{
    width: {box - 2}px; height: {box - 2}px;
    border: 1px solid {t['border_strong']};
    background-color: {t['bg_input']};
}}
QCheckBox::indicator {{ border-radius: 3px; }}
QRadioButton::indicator {{ border-radius: {box_radius}px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {t['accent']}; }}
QCheckBox::indicator:checked {{
    background-color: {t['accent']};
    border-color: {t['accent']};
    image: url("{check_mark()}");
}}
QRadioButton::indicator:checked {{
    width: {box - 2 * dot}px; height: {box - 2 * dot}px;
    background-color: {t['bg_input']};
    border: {dot}px solid {t['accent']};
    border-radius: {box_radius}px;
}}
QCheckBox:disabled, QRadioButton:disabled {{ color: {t['fg_muted']}; }}

/* ---------- progress ---------- */
QProgressBar {{
    background-color: {t['border']};
    border: none;
    border-radius: 3px;
    max-height: {px(6)}px;
    min-height: {px(6)}px;
    text-align: center;
}}
QProgressBar::chunk {{ background-color: {t['accent']}; border-radius: 3px; }}
QProgressBar[tone="success"]::chunk {{ background-color: {t['success']}; }}

/* ---------- scroll areas ---------- */
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QScrollBar:vertical {{
    background: transparent; width: {px(11)}px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {t['border_strong']};
    border-radius: {px(5)}px;
    min-height: {px(28)}px;
}}
QScrollBar::handle:vertical:hover {{ background: {t['fg_muted']}; }}
QScrollBar:horizontal {{
    background: transparent; height: {px(11)}px; margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {t['border_strong']};
    border-radius: {px(5)}px;
    min-width: {px(28)}px;
}}
QScrollBar::handle:horizontal:hover {{ background: {t['fg_muted']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------- tables ---------- */
QTableView {{
    background-color: {t['bg_panel']};
    alternate-background-color: {t['row_alt']};
    color: {t['fg']};
    border: 1px solid {t['border']};
    border-radius: {RADIUS}px;
    gridline-color: {t['border']};
    selection-background-color: {t['row_selected']};
    selection-color: {t['fg_bright']};
    outline: none;
}}
QTableView::item {{ padding: {px(4)}px {px(6)}px; border: none; }}
QTableView::item:hover {{ background-color: {t['bg_hover']}; }}
/* Qt fades the selection to the inactive palette the moment the table loses
   focus, which is the moment the user reaches for the Delete button. Painting
   both states the same is what makes a picked row stay obviously picked. */
QTableView::item:selected {{
    background-color: {t['row_selected']};
    color: {t['fg_bright']};
}}
QTableView::item:selected:!active {{
    background-color: {t['row_selected']};
    color: {t['fg_bright']};
}}
QHeaderView {{ background-color: {t['bg_header']}; border: none; }}
QHeaderView::section {{
    background-color: {t['bg_header']};
    color: {t['fg_muted']};
    border: none;
    border-right: 1px solid {t['border']};
    border-bottom: 1px solid {t['border']};
    padding: {px(6)}px {px(8)}px;
    font-size: {small}px;
    font-weight: {heavy};
}}
QHeaderView::section:hover {{ color: {t['fg_bright']}; }}
QTableCornerButton::section {{ background-color: {t['bg_header']}; border: none; }}

/* ---------- menus ---------- */
QMenu {{
    background-color: {t['bg_panel']};
    color: {t['fg']};
    border: 1px solid {t['border_strong']};
    border-radius: {RADIUS}px;
    padding: {px(5)}px;
}}
QMenu::item {{
    padding: {px(6)}px {px(16)}px;
    border-radius: {px(5)}px;
}}
QMenu::item:selected {{ background-color: {t['bg_selected']}; color: {t['fg_bright']}; }}
QMenu::item:disabled {{ color: {t['fg_muted']}; }}
QMenu::separator {{
    height: 1px;
    background-color: {t['border']};
    margin: {px(4)}px {px(8)}px;
}}

/* ---------- completer popup ---------- */
QListView {{
    background-color: {t['bg_panel']};
    color: {t['fg']};
    border: 1px solid {t['border_strong']};
    border-radius: {RADIUS}px;
    selection-background-color: {t['bg_selected']};
    selection-color: {t['fg_bright']};
    outline: none;
}}
QListView::item {{ padding: {px(5)}px {px(8)}px; }}

/* ---------- toasts ---------- */
QFrame[role="toast"] {{
    background-color: {t['bg_panel']};
    border: 1px solid {t['border_strong']};
    border-radius: {RADIUS}px;
}}
QFrame[role="toast"][level="success"] {{ border-color: {t['success']}; }}
QFrame[role="toast"][level="error"]   {{ border-color: {t['error']}; }}
QFrame[role="toast"][level="warn"]    {{ border-color: {t['warning']}; }}
QFrame[role="toast"][level="info"]    {{ border-color: {t['accent']}; }}
"""
