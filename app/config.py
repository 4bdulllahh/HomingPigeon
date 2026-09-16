"""Application paths and constants."""
import os
import sys
from pathlib import Path

APP_NAME = "HomingPigeon"
APP_TITLE = "HomingPigeon"
APP_VERSION = "v0.4.2 beta"
APP_TAGLINE = "Safe, simple email for your business"
REPO_URL = "https://github.com/4bdulllahh/HomingPigeon"


def _app_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / APP_NAME


DATA_DIR = _app_data_dir()
DB_PATH = DATA_DIR / "mailer.db"
SECRETS_PATH = DATA_DIR / "secrets.dat"
KEYS_DIR = DATA_DIR / "keys"
EXPORTS_DIR = DATA_DIR / "exports"
LOGS_DIR = DATA_DIR / "logs"


def ensure_dirs() -> None:
    for d in (DATA_DIR, KEYS_DIR, EXPORTS_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def resource_path(relative: str) -> Path:
    """Resolve a bundled resource, working both from source and from a PyInstaller build."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / relative
    return Path(__file__).resolve().parent.parent / relative


# --- Limits -----------------------------------------------------------------
MAX_ATTACHMENT_BYTES = 2 * 1024 * 1024  # 2 MB hard cap on brochures

# Delay slider bounds, in seconds
DELAY_MIN_SECONDS = 15
DELAY_MAX_SECONDS = 60 * 60

# Reconnect the SMTP session every N messages to avoid long-lived-session throttling
SMTP_RECONNECT_EVERY = 25

# Circuit breaker: stop the run before a bad list damages the sending domain
MAX_CONSECUTIVE_FAILURES = 5
MAX_HARD_BOUNCE_RATE = 0.05
MIN_SAMPLE_FOR_BOUNCE_RATE = 20

# Re-run the spam score automatically when the stored one is older than this
SCORE_STALE_HOURS = 36

DEFAULT_WINDOW_START = "09:00"
DEFAULT_WINDOW_END = "18:00"
