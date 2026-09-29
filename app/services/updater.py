"""Finding, downloading and installing a newer release.

The app asks GitHub for the latest release when it opens. If there is a newer
one, the user is offered "Update now" or "Update later". Updating now:

  1. downloads that release's HomingPigeon-vX.Y.Z.zip (the same file people
     download by hand) and checks it against the SHA-256 GitHub publishes,
  2. unpacks just its ``files/`` folder, which holds the new app and the new
     installer script,
  3. copies the app's private Python (minus its add-ons) to a temporary folder
     and runs the new installer on that copy in ``--update`` mode, then
  4. closes the app. The installer waits for it to go, updates everything in
     place, and opens the app again.

Running the installer on a copy of Python matters: an update may bring a newer
Python, and the installer cannot replace the program it is running on. The
copy is python.org's own signed files, so Smart App Control lets it run, which
it would not do for the unsigned Setup.exe.

Nothing here touches Qt, so it can run on a worker thread and be tested alone.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app import config
from app.core import shortcut, tls
from app.services.maintenance import is_newer

API_URL = config.REPO_URL.replace("https://github.com/", "https://api.github.com/repos/")
ASSET_PATTERN = re.compile(r"^HomingPigeon-v[\d.]+\.zip$")
WORK_DIR = Path(tempfile.gettempdir()) / f"{config.APP_NAME}-update"
CHUNK = 256 * 1024
SKIP_IN_PYTHON = {f"{config.APP_NAME}.exe", "Doc", "include", "libs", "Scripts"}
STAMP = "started.txt"   # when the last update handed over to the installer


@dataclass
class Release:
    tag: str             # "v0.6.0"
    page_url: str        # the release page on GitHub
    zip_url: str = ""    # the downloadable zip, empty while GitHub is still building it
    zip_size: int = 0
    sha256: str = ""     # published by GitHub for each asset; empty on older releases
    notes: str = ""


class UpdateCancelled(Exception):
    pass


# --- checking ---------------------------------------------------------------
def parse_release(data: dict) -> Release:
    release = Release(tag=str(data.get("tag_name") or ""),
                      page_url=str(data.get("html_url") or f"{config.REPO_URL}/releases"),
                      notes=str(data.get("body") or ""))
    for asset in data.get("assets") or []:
        if ASSET_PATTERN.match(str(asset.get("name") or "")):
            release.zip_url = str(asset.get("browser_download_url") or "")
            release.zip_size = int(asset.get("size") or 0)
            digest = str(asset.get("digest") or "")
            if digest.startswith("sha256:"):
                release.sha256 = digest.split(":", 1)[1].lower()
            break
    return release


def latest_release() -> Release | None:
    """The newest published release, or None when GitHub can't be reached."""
    try:
        request = urllib.request.Request(
            f"{API_URL}/releases/latest",
            headers={"User-Agent": config.APP_NAME, "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(request, timeout=15, context=tls.secure_context()) as reply:
            data = json.loads(reply.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - offline, rate limited, no releases yet
        return None
    release = parse_release(data)
    return release if release.tag else None


def available_update() -> Release | None:
    """The latest release if it is newer than this copy, otherwise None."""
    cleanup()
    release = latest_release()
    if release and is_newer(release.tag, config.APP_VERSION):
        return release
    return None


def can_update_itself(release: Release | None = None) -> bool:
    """True when this copy can install an update without the user's help.

    That needs a Windows install made by Setup (with its private Python) and a
    release whose zip GitHub has finished attaching. Anything else, such as a
    Mac, Linux or a developer running from source, gets the download page.
    """
    if sys.platform != "win32" or not shortcut.is_installed():
        return False
    if not (shortcut.app_location() / "python" / "pythonw.exe").exists():
        return False
    return release is None or bool(release.zip_url)


# --- downloading ------------------------------------------------------------
def download(release: Release, progress: Callable[[int, int], None] | None = None,
             cancelled: Callable[[], bool] | None = None) -> Path:
    """Fetch the release zip, check it, and unpack the app files. Returns their folder."""
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    archive = WORK_DIR / f"HomingPigeon-{release.tag}.zip"
    partial = archive.with_suffix(".part")
    digest = hashlib.sha256()
    received = 0

    request = urllib.request.Request(release.zip_url, headers={"User-Agent": config.APP_NAME})
    try:
        with urllib.request.urlopen(request, timeout=60, context=tls.secure_context()) as reply, \
                open(partial, "wb") as out:
            total = int(reply.headers.get("Content-Length") or release.zip_size or 0)
            while True:
                if cancelled and cancelled():
                    raise UpdateCancelled()
                chunk = reply.read(CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                received += len(chunk)
                if progress:
                    progress(received, total)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise

    if release.sha256 and digest.hexdigest() != release.sha256:
        partial.unlink(missing_ok=True)
        raise OSError("the download was damaged on the way. Please try again")
    partial.replace(archive)

    staged = WORK_DIR / "files"
    shutil.rmtree(staged, ignore_errors=True)
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            if member.filename.startswith("files/") and not member.is_dir():
                target = WORK_DIR / member.filename
                if WORK_DIR.resolve() not in target.resolve().parents:
                    continue  # never write outside the work folder
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as source, open(target, "wb") as out:
                    shutil.copyfileobj(source, out)
    archive.unlink(missing_ok=True)

    if not (staged / "installer" / "setup_app.py").exists() or not (staged / "run.py").exists():
        raise OSError("the download didn't contain the app's files")
    return staged


# --- installing -------------------------------------------------------------
def _installer_python() -> Path:
    """A throwaway copy of the private Python that the installer can run on.

    The add-ons in site-packages are left out, since the installer uses only
    Python's own library, and so are the offline manual and the files for
    building extensions. That takes the copy from about 500 MB to about 45.
    """
    source = shortcut.app_location() / "python"
    target = WORK_DIR / "python"
    shutil.rmtree(target, ignore_errors=True)

    def ignore(folder: str, names: list[str]) -> list[str]:
        here = Path(folder)
        return [name for name in names
                if name == "__pycache__"
                or (here == source and name in SKIP_IN_PYTHON)
                or (here == source / "Lib" and name == "site-packages")]

    shutil.copytree(source, target, ignore=ignore)
    return target / "pythonw.exe"


def start_install(staged: Path) -> None:
    """Hand over to the new installer. The caller then closes the app."""
    python = _installer_python()
    (WORK_DIR / STAMP).write_text(str(time.time()), encoding="utf-8")
    command = [str(python), "-E", "-s", str(staged / "installer" / "setup_app.py"),
               "--update", "--target", str(shortcut.app_location())]
    base = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    last: OSError | None = None
    # Leave any job object the app is in, or closing the app could close the installer too
    for flags in (base | 0x01000000, base):  # 0x01000000 is CREATE_BREAKAWAY_FROM_JOB
        try:
            subprocess.Popen(command, cwd=str(WORK_DIR), close_fds=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, creationflags=flags)
            return
        except OSError as error:
            last = error
    raise last or OSError("the installer could not be started")


def cleanup() -> None:
    """Remove what an earlier update left in the temp folder.

    The installer is still running on that folder's Python for a few seconds
    after it reopens the app, so a fresh one is left for the next launch.
    """
    try:
        started = float((WORK_DIR / STAMP).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        started = 0.0
    if time.time() - started > 10 * 60:
        shutil.rmtree(WORK_DIR, ignore_errors=True)
