"""User preferences from the Settings page, and date/time formatting that follows them.

Everything that shows a date or time to the user goes through format_datetime(),
format_date() or format_time(), so the Settings choice applies everywhere.
"""
from __future__ import annotations

from datetime import datetime

from app.core import db

# --- Appearance ---------------------------------------------------------------
THEMES = [("Dark", "Dark"), ("Light", "Light"), ("System", "Match my computer")]

# (key, label, scale). Scale multiplies every widget and font in the app.
TEXT_SIZES = [
    ("small", "Small", 0.9),
    ("medium", "Medium", 1.0),
    ("large", "Large", 1.15),
    ("xlarge", "Extra large", 1.3),
    ("huge", "Huge", 1.5),
]
DEFAULT_TEXT_SIZE = "large"

START_PAGES = [("dashboard", "Home"), ("guide", "Start here"), ("last", "The page I used last")]

# --- Date and time --------------------------------------------------------------
DATE_FORMATS = {
    "dmy": ("DD/MM/YYYY", "%d/%m/%Y"),
    "mdy": ("MM/DD/YYYY", "%m/%d/%Y"),
    "ymd": ("YYYY-MM-DD", "%Y-%m-%d"),
    "long": ("DD Mon YYYY", "%d %b %Y"),
}
DEFAULT_DATE_FORMAT = "dmy"
TIME_FORMATS = {"12": "12-hour", "24": "24-hour"}
DEFAULT_TIME_FORMAT = "12"

DEFAULTS = {
    "appearance": "Dark",
    "text_size": DEFAULT_TEXT_SIZE,
    "high_contrast": False,
    "bold_text": False,
    "date_format": DEFAULT_DATE_FORMAT,
    "time_format": DEFAULT_TIME_FORMAT,
    "start_page": "dashboard",
}


def get(key: str):
    return db.get_setting(key, DEFAULTS[key])


def text_scale() -> float:
    wanted = get("text_size")
    for key, _label, scale in TEXT_SIZES:
        if key == wanted:
            return scale
    return 1.15


def _parse(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _date_pattern(key: str | None = None) -> str:
    return DATE_FORMATS.get(key or get("date_format"), DATE_FORMATS[DEFAULT_DATE_FORMAT])[1]


def format_date(value, key: str | None = None) -> str:
    moment = _parse(value)
    if moment is None:
        return str(value or "")
    return moment.strftime(_date_pattern(key))


def format_time(value, seconds: bool = False, key: str | None = None) -> str:
    moment = _parse(value)
    if moment is None:
        return str(value or "")
    if (key or get("time_format")) == "24":
        return moment.strftime("%H:%M:%S" if seconds else "%H:%M")
    hour = moment.hour % 12 or 12
    rest = moment.strftime(":%M:%S" if seconds else ":%M")
    return f"{hour}{rest} {'AM' if moment.hour < 12 else 'PM'}"


def format_datetime(value, seconds: bool = False) -> str:
    moment = _parse(value)
    if moment is None:
        return str(value or "")
    return f"{format_date(moment)}  {format_time(moment, seconds)}"


def format_clock(hhmm: str) -> str:
    """'17:00' -> '5:00 PM' (or unchanged in 24-hour mode). Used for the send-window menus."""
    try:
        moment = datetime.strptime(hhmm, "%H:%M")
    except ValueError:
        return hhmm
    return format_time(moment)


def parse_clock(text: str) -> str:
    """The reverse of format_clock: any displayed time back to '17:00'."""
    for pattern in ("%H:%M", "%I:%M %p"):
        try:
            return datetime.strptime(text.strip(), pattern).strftime("%H:%M")
        except ValueError:
            continue
    return text
