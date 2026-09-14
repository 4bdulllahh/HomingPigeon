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


def app_location() -> Path:
    """The folder a user should think of as 'where the app lives'."""
    return Path(__file__).resolve().parent.parent.parent


def is_installed() -> bool:
    """True when installed by HomingPigeon Setup, which keeps a private Python in the app folder."""
    return Path(sys.executable).resolve().parent == app_location() / "python"


def start_file() -> Path:
    """The double-click "Start HomingPigeon" file for Mac or Linux (Windows uses Setup)."""
    name = "Start HomingPigeon - Mac.command" if sys.platform == "darwin" else "Start HomingPigeon - Linux.sh"
    return app_location() / name


def launch_target() -> tuple[str, str, str]:
    """(program, arguments, icon) that will start the app again."""
    icon = app_location() / "assets" / "icon.ico"
    run_script = app_location() / "run.py"
    if is_installed():
        pythonw = app_location() / "python" / "pythonw.exe"
        return str(pythonw), f'-E -s "{run_script}"', str(icon)

    # Running from the source folder on Windows (developers): use the current Python.
    # pythonw.exe runs without leaving a black console window open behind the app.
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return str(pythonw if pythonw.exists() else sys.executable), f'"{run_script}"', str(icon)


def how_to_launch() -> str:
    """Plain-English instructions for reopening the app."""
    if is_installed():
        return (
            "Open HomingPigeon from the Start menu (press the Windows key and type HomingPigeon), "
            "or from its Desktop icon.\n\n"
            "No icon on your Desktop? Press the button below to add one."
        )
    if sys.platform == "win32":
        return (
            f"You are running HomingPigeon from its source folder:\n{app_location()}\n\n"
            f"Press the button below to put an icon on your Desktop, then just double-click "
            f"that icon from now on. (Most people install with HomingPigeon Setup from the "
            f"GitHub Releases page instead, which adds a Start menu entry too.)"
        )
    return (
        f"HomingPigeon lives in this folder:\n{app_location()}\n\n"
        f"To open it again, double-click  {start_file().name}  in that folder."
    )


def desktop_dir() -> Path:
    onedrive = os.environ.get("OneDrive")
    if onedrive and (Path(onedrive) / "Desktop").exists():
        return Path(onedrive) / "Desktop"
    return Path.home() / "Desktop"


def create_desktop_shortcut() -> tuple[bool, str]:
    """Create (or refresh) a Desktop shortcut. Returns (ok, message)."""
    if sys.platform != "win32":
        return False, (f"Desktop icons can only be made on Windows. To open the app, "
                       f"double-click '{start_file().name}' in the app's folder.")

    desktop = desktop_dir()
    if not desktop.exists():
        return False, f"Could not find your Desktop folder at {desktop}."

    link = desktop / f"{config.APP_TITLE}.lnk"
    program, arguments, icon = launch_target()
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
        f"$s.IconLocation = '{ps_quote(icon)},0'; "
        "$s.WindowStyle = 1; "
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
    """Open a folder in Explorer, Finder or the Linux file manager."""
    path = Path(path)
    try:
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606 - opening a local folder for the user
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except OSError:
        pass
