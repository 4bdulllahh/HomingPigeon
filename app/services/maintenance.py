"""App-management jobs that belong to neither the UI nor the business logic.

Backing up the database, restarting the process, launching the uninstaller and
comparing version numbers are all things the Settings page asks for but has no
business implementing. They live here so the page stays presentation only, and
so they can run on a worker thread without dragging Qt in.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from app import config
from app.core import db, shortcut


# --- backups ----------------------------------------------------------------
def write_backup(target: str | Path) -> Path:
    """Copy the live database to ``target`` using SQLite's own backup API.

    Passwords are not included: they live in the encrypted credential store,
    which is tied to this computer and would not be readable elsewhere anyway.
    """
    destination = sqlite3.connect(str(target))
    try:
        with destination:
            db.connect().backup(destination)
    finally:
        destination.close()
    return Path(target)


def is_backup(source: str | Path) -> bool:
    try:
        connection = sqlite3.connect(f"file:{Path(source).as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return False
    try:
        connection.execute("SELECT key FROM settings LIMIT 1")
        return True
    except sqlite3.Error:
        return False
    finally:
        connection.close()


def restore_backup(source: str | Path) -> Path:
    """Replace the live database with a backup, keeping a copy of what was there."""
    safety = config.DATA_DIR / f"before-restore {datetime.now():%Y-%m-%d %H%M}.hpbackup"
    write_backup(safety)

    backup = sqlite3.connect(f"file:{Path(source).as_posix()}?mode=ro", uri=True)
    try:
        with db.connect() as live:
            backup.backup(live)
    finally:
        backup.close()
    return safety


def default_backup_name() -> str:
    return f"HomingPigeon backup {datetime.now():%Y-%m-%d}.hpbackup"


# --- process management -----------------------------------------------------
def restart() -> None:
    """Start a fresh copy of the app. The caller closes this one."""
    flags = [flag for flag, on in (("-E", sys.flags.ignore_environment),
                                   ("-s", sys.flags.no_user_site)) if on]
    subprocess.Popen([sys.executable, *flags, str(shortcut.app_location() / "run.py")],
                     cwd=shortcut.app_location(), close_fds=True)


def start_uninstaller(delete_data: bool) -> None:
    """Hand over to the installer's uninstall mode, which waits for this app to close."""
    home = shortcut.app_location()
    command = [str(home / "python" / "pythonw.exe"), "-E", "-s",
               str(home / "installer" / "setup_app.py"), "--uninstall", "--confirmed",
               "--target", str(home)]
    if delete_data:
        command.append("--delete-data")
    subprocess.Popen(command, cwd=tempfile.gettempdir(), close_fds=True,
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))


def delete_all_data() -> None:
    """Remove the data folder and exit immediately, before anything can rewrite it."""
    shutil.rmtree(config.DATA_DIR, ignore_errors=True)
    os._exit(0)


# --- versions ---------------------------------------------------------------
def version_tuple(text: str) -> tuple[int, ...]:
    """'v0.2.1 beta' -> (0, 2, 1)."""
    digits = "".join(ch if ch.isdigit() or ch == "." else " " for ch in str(text)).split()
    if not digits:
        return (0,)
    return tuple(int(part) for part in digits[0].split(".") if part)


def is_newer(candidate: str, current: str) -> bool:
    return version_tuple(candidate) > version_tuple(current)
