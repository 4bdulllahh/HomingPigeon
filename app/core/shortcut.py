"""Create a Desktop shortcut so the app can be reopened without a terminal.

Most people will never type a command again after the first install, so the app
offers to put an icon on the Desktop for them.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from app import config


def is_frozen() -> bool:
    """True when running from a PyInstaller-built .exe rather than source."""
    return bool(getattr(sys, "frozen", False))


def app_location() -> Path:
    """The folder a user should think of as 'where the app lives'."""
    if is_frozen():
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent.parent


def launch_target() -> tuple[str, str]:
    """(program, arguments) that will start the app again."""
    if is_frozen():
        return sys.executable, ""

    project = app_location()
    run_script = project / "run.py"
    # pythonw.exe runs without leaving a black console window open behind the app
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    program = str(pythonw if pythonw.exists() else sys.executable)
    return program, f'"{run_script}"'


def how_to_launch() -> str:
    """Plain-English instructions for reopening the app."""
    if is_frozen():
        return (
            f"You are running the ready-made app.\n\n"
            f"It lives here:\n{sys.executable}\n\n"
            f"To open it again, double-click {Path(sys.executable).name} in that folder — "
            f"or press the button below to put an icon on your Desktop."
        )
    project = app_location()
    return (
        f"You are running HomingPigeon from its source folder.\n\n"
        f"The folder is:\n{project}\n\n"
        f"To open it again: open that folder, double-click the address bar at the top, "
        f"type  cmd  and press Enter. Then type  python run.py  and press Enter.\n\n"
        f"Easier: press the button below to put an icon on your Desktop, then just "
        f"double-click that icon from now on."
    )


def desktop_dir() -> Path:
    onedrive = os.environ.get("OneDrive")
    if onedrive and (Path(onedrive) / "Desktop").exists():
        return Path(onedrive) / "Desktop"
    return Path.home() / "Desktop"


def create_desktop_shortcut() -> tuple[bool, str]:
    """Create (or refresh) a Desktop shortcut. Returns (ok, message)."""
    if sys.platform != "win32":
        return False, "Desktop shortcuts are only supported on Windows."

    desktop = desktop_dir()
    if not desktop.exists():
        return False, f"Could not find your Desktop folder at {desktop}."

    link = desktop / f"{config.APP_TITLE}.lnk"
    program, arguments = launch_target()
    working_dir = str(app_location())

    # Escape single quotes for the PowerShell string literals below
    def ps_quote(value: str) -> str:
        return value.replace("'", "''")

    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut("
        f"'{ps_quote(str(link))}'); "
        f"$s.TargetPath = '{ps_quote(program)}'; "
        f"$s.Arguments = '{ps_quote(arguments)}'; "
        f"$s.WorkingDirectory = '{ps_quote(working_dir)}'; "
        f"$s.Description = '{ps_quote(config.APP_TITLE)}'; "
        f"$s.IconLocation = '{ps_quote(program)},0'; "
        "$s.Save()"
    )

    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, f"Could not create the shortcut: {error}"

    if result.returncode != 0 or not link.exists():
        detail = (result.stderr or result.stdout or "").strip()[:200]
        return False, f"Could not create the shortcut. {detail}".strip()

    return True, f"Done — look for the '{config.APP_TITLE}' icon on your Desktop."


def open_folder(path: Path | str) -> None:
    """Open a folder in Windows Explorer."""
    path = Path(path)
    try:
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606 - opening a local folder for the user
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except OSError:
        pass
