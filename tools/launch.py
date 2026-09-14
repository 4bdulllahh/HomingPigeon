"""Get HomingPigeon ready, then start it.

The "Start HomingPigeon" files next to README.md run this with whatever Python
the computer has. It:

  1. checks that Python is new enough and has its window toolkit (tkinter),
  2. keeps the app's add-ons in a private folder, so it never disturbs any other
     Python program on the computer,
  3. installs those add-ons the first time (and again whenever requirements.txt
     changes, or if something has gone missing),
  4. starts the app without leaving a command window behind.

Standard library only: nothing else is installed yet when this runs.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

APP_NAME = "HomingPigeon"
MIN_PYTHON = (3, 10)
ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "requirements.txt"
RUN_SCRIPT = ROOT / "run.py"

# Top-level modules the app imports; if any is missing, setup runs again.
REQUIRED_MODULES = ["customtkinter", "pandas", "openpyxl", "dns", "cryptography", "PIL", "certifi"]


def say(text: str = "") -> None:
    print(f"  {text}" if text else "", flush=True)


def fail(*lines: str) -> int:
    say()
    for line in lines:
        say(line)
    say()
    return 1


# --- Checks -----------------------------------------------------------------
def python_problem() -> list[str] | None:
    if sys.version_info < MIN_PYTHON:
        return [
            f"This computer's Python is version {sys.version_info.major}.{sys.version_info.minor}, "
            f"but HomingPigeon needs {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer.",
            "Install the latest Python from https://www.python.org/downloads/",
            "then double-click the Start file again.",
        ]
    try:
        import tkinter  # noqa: F401
    except ImportError:
        if sys.platform == "darwin":
            return [
                "This Python cannot draw windows (it is missing 'tkinter').",
                "Install Python from https://www.python.org/downloads/macos/",
                "then double-click the Start file again.",
                "(If you use Homebrew, 'brew install python-tk' also fixes it.)",
            ]
        if sys.platform.startswith("linux"):
            return [
                "This Python cannot draw windows (it is missing 'tkinter').",
                "Install it, then run the Start file again:",
                "  Ubuntu / Debian / Mint:  sudo apt install python3-tk python3-venv",
                "  Fedora:                  sudo dnf install python3-tkinter",
                "  Arch:                    sudo pacman -S tk",
            ]
        return [
            "This Python cannot draw windows (it is missing 'tkinter').",
            "Reinstall Python from https://www.python.org/downloads/ and leave",
            "'tcl/tk and IDLE' ticked, then double-click the Start file again.",
        ]
    return None


# --- Private environment ----------------------------------------------------
def runtime_dir() -> Path:
    """Where the add-ons live. Outside the app folder, so cloud-synced folders
    (OneDrive, iCloud Desktop) never have to sync thousands of library files."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    version = f"py{sys.version_info.major}.{sys.version_info.minor}"
    return base / APP_NAME / "runtime" / version


def env_python(env: Path, windowless: bool = False) -> Path:
    if sys.platform == "win32":
        return env / "Scripts" / ("pythonw.exe" if windowless else "python.exe")
    return env / "bin" / "python"


def requirements_fingerprint() -> str:
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def env_is_ready(env: Path) -> bool:
    python = env_python(env)
    stamp = env / "homingpigeon-ready.txt"
    if not python.exists() or not stamp.exists():
        return False
    if stamp.read_text(encoding="utf-8").strip() != requirements_fingerprint():
        return False
    # Cheap check (no heavy imports) that every add-on is still present
    probe = (
        "import importlib.util, sys; "
        f"sys.exit(any(importlib.util.find_spec(m) is None for m in {REQUIRED_MODULES!r}))"
    )
    try:
        result = subprocess.run([str(python), "-c", probe], capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def env_works(env: Path) -> bool:
    """The private folder exists and its Python still runs (Python may have been
    reinstalled or moved since it was made)."""
    try:
        return subprocess.run([str(env_python(env)), "-c", "pass"],
                              capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def create_env(env: Path) -> bool:
    if env_works(env):
        return True  # reuse it; only the add-ons need refreshing
    if env.exists():
        import shutil

        shutil.rmtree(env, ignore_errors=True)
    env.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([sys.executable, "-m", "venv", str(env)],
                            capture_output=True, text=True)
    if result.returncode != 0 or not env_python(env).exists():
        details = (result.stderr or result.stdout or "").strip()
        if details:
            say(details.splitlines()[-1])
        return False
    return True


def pip(env: Path, *args: str) -> bool:
    command = [str(env_python(env)), "-m", "pip", "--disable-pip-version-check", *args]
    return subprocess.run(command).returncode == 0


def set_up(env: Path) -> int:
    say(f"Getting {APP_NAME} ready. This only happens the first time")
    say("(or after an update) and takes about 2-5 minutes.")
    say("Please keep this window open and stay connected to the internet.")
    say()

    say("[1/3] Preparing a private folder for the app...")
    if not create_env(env):
        if sys.platform.startswith("linux"):
            return fail("Could not prepare the app folder. Install the missing piece, then try again:",
                        "  Ubuntu / Debian / Mint:  sudo apt install python3-venv python3-tk",
                        "  Fedora:                  sudo dnf install python3-tkinter")
        return fail("Could not prepare the app folder.",
                    "Reinstalling Python from https://www.python.org/downloads/ usually fixes this.")

    say("[2/3] Updating the installer...")
    pip(env, "install", "--quiet", "--upgrade", "pip")  # an old pip is not fatal

    say("[3/3] Downloading the parts the app needs...")
    say()
    if not pip(env, "install", "--prefer-binary", "-r", str(REQUIREMENTS)):
        return fail("The download did not finish.",
                    "Check your internet connection, then double-click the Start file again.",
                    "It will pick up where it left off.")

    (env / "homingpigeon-ready.txt").write_text(requirements_fingerprint(), encoding="utf-8")
    say()
    say("All set. Opening the app...")
    return 0


# --- Start the app ----------------------------------------------------------
def start_app(env: Path) -> int:
    if sys.platform == "win32":
        pythonw = env_python(env, windowless=True)
        program = pythonw if pythonw.exists() else env_python(env)
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen([str(program), str(RUN_SCRIPT)], cwd=ROOT, creationflags=flags,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True)
    else:
        subprocess.Popen([str(env_python(env)), str(RUN_SCRIPT)], cwd=ROOT,
                         start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return 0


def main() -> int:
    problem = python_problem()
    if problem:
        return fail(*problem)

    env = runtime_dir()
    if not env_is_ready(env):
        code = set_up(env)
        if code != 0:
            return code
    return start_app(env)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(1)
    except Exception as error:  # noqa: BLE001 - the user must see what went wrong
        sys.exit(fail("Something unexpected went wrong:", f"{type(error).__name__}: {error}"))
