"""HomingPigeon Setup: the Windows installer.

Built into "HomingPigeon Setup.exe" by tools/build_installer.py. The app's own
files travel inside the .exe; everything else is downloaded while the user
watches:

  * a private copy of Python from python.org (checked against a pinned SHA-256),
  * the add-ons in requirements.txt from pypi.org.

Everything goes into one folder, %LOCALAPPDATA%\\Programs\\HomingPigeon, so no
administrator rights are needed and nothing else on the computer changes. The
user's data lives elsewhere (%APPDATA%\\HomingPigeon) and survives updates and
uninstalls.

Standard library only, so the .exe stays small.

The same script also runs without the .exe: on PCs where Windows Smart App
Control blocks the unsigned Setup.exe, "Install HomingPigeon (if Setup is
blocked).bat" fetches the (signed) python.org Python with Windows' own tools and
runs this script with it. Uninstalling always uses that signed Python too.

    HomingPigeon Setup.exe                 install, update or repair
    setup_app.py --uninstall               remove (used by Settings > Apps)
    ... --uninstall --confirmed [--delete-data]   remove straight away (the app's Settings page)
    ... --target DIR                       install somewhere else (testing)
"""
from __future__ import annotations

import ctypes
import hashlib
import math
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import urllib.request
import zipfile
from pathlib import Path
from tkinter import messagebox

APP_NAME = "HomingPigeon"
PUBLISHER = "HomingPigeon"
REGISTRY_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\HomingPigeon"

# Private Python. Hashes are pinned so a tampered download is refused.
PYTHON_VERSION = "3.13.15"
PYTHON_BUILDS = {
    "amd64": ("6479223746cdfb79d25865110d6f524ac98de081324e119af1dc3ae36bddc7a5", 34_324_622),
    "arm64": ("b17017eb390de122e7acfcea0b2f28e3b0f39ba0dc6e46c6fd5fa004fd545875", 33_457_747),
}
PYTHON_URL = "https://www.python.org/ftp/python/{v}/python-{v}-{arch}.zip"

# Download tuning. One connection is usually round-trip-limited rather than
# bandwidth-limited, so the Python zip is fetched as parallel byte ranges.
DOWNLOAD_CONNECTIONS = 6
DOWNLOAD_CHUNK = 1024 * 1024
DOWNLOAD_HEADERS = {"User-Agent": f"{APP_NAME}-Setup", "Accept-Encoding": "identity"}

# Roughly what requirements.txt weighs as wheels, used only to scale the progress
# bar for the add-ons step. Being a little out just makes the bar move unevenly.
EXPECTED_ADDON_MB = 135.0

REQUIRED_IMPORTS = ("import PyQt6.QtWidgets, PyQt6.QtGui, PyQt6.QtCore, pandas, openpyxl, "
                    "dns.resolver, cryptography, PIL, certifi")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# How long to watch a freshly opened app before calling the launch a success.
# Long enough for Qt to create its window, short enough not to feel like a hang.
LAUNCH_CONFIRM_SECONDS = 4.0

# --- Look (matches the app's dark theme) -------------------------------------
BG = "#1f2125"
PANEL = "#282b31"
CONSOLE = "#17191c"
BORDER = "#34373f"
FG = "#d0d4da"
FG_BRIGHT = "#f2f4f7"
FG_MUTED = "#8d939d"
ACCENT = "#3b86dd"
ACCENT_HOVER = "#4e94e6"
CONFIRM = "#39ad70"
CONFIRM_HOVER = "#48bc7e"
SECONDARY = "#34373f"
SECONDARY_HOVER = "#40444d"
ERROR = "#ef8a7f"


# =============================================================================
# Paths and facts about this computer
# =============================================================================
def payload_dir() -> Path:
    """The app files packed inside Setup.exe (or the repo, when run from source)."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "payload"
    return Path(__file__).resolve().parent.parent


def default_install_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "Programs" / APP_NAME


def data_dir() -> Path:
    roaming = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(roaming) / APP_NAME


def read_version(root: Path) -> str | None:
    try:
        text = (root / "app" / "config.py").read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r'APP_VERSION\s*=\s*"v?([^"\s]+)', text)
    return match.group(1) if match else None


def python_arch() -> str:
    arch = (os.environ.get("PROCESSOR_ARCHITEW6432") or os.environ.get("PROCESSOR_ARCHITECTURE") or "")
    return "arm64" if arch.upper() == "ARM64" else "amd64"


def clean_env() -> dict[str, str]:
    """Environment for the private Python: ignore any other Python setup on the PC."""
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(("PYTHON", "_PYI", "_MEI", "PIP_", "VIRTUAL_ENV", "CONDA"))}
    env.update(PYTHONNOUSERSITE="1", PYTHONIOENCODING="utf-8", PIP_NO_INPUT="1",
               PIP_DISABLE_PIP_VERSION_CHECK="1")
    return env


def human_mb(n: float) -> str:
    return f"{n / 1_048_576:.1f} MB"


def _as_mb(amount: str | None, unit: str | None) -> float:
    """'12.6', 'MB' -> 12.6. Anything unparsable counts as nothing."""
    try:
        value = float(amount or 0)
    except ValueError:
        return 0.0
    return value * {"kB": 1 / 1024, "MB": 1.0, "GB": 1024.0}.get(unit or "MB", 1.0)


def running_app_pids(install_dir: Path) -> list[int]:
    """Process ids of HomingPigeon windows started from this install folder."""
    # HomingPigeon.exe is the renamed copy the shortcuts use; the two Python
    # names still matter for installs made before it existed, and for the
    # machines where it could not be created.
    script = (
        f"Get-Process {APP_NAME},python,pythonw -ErrorAction SilentlyContinue | "
        f"Where-Object {{ $_.Path -like '{str(install_dir).replace(chr(39), chr(39) * 2)}\\*' }} | "
        "ForEach-Object { $_.Id }"
    )
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                             capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [int(line) for line in out.stdout.split() if line.strip().isdigit() and int(line) != os.getpid()]


def make_shortcut(link: Path, install_dir: Path) -> None:
    def q(value: object) -> str:
        return str(value).replace("'", "''")

    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut("
        f"'{q(link)}'); "
        f"$s.TargetPath = '{q(app_exe(install_dir))}'; "
        f"$s.Arguments = '-E -s \"{q(install_dir / 'run.py')}\"'; "
        f"$s.WorkingDirectory = '{q(install_dir)}'; "
        f"$s.IconLocation = '{q(install_dir / 'assets' / 'icon.ico')},0'; "
        "$s.Description = 'Safe, simple email for your business'; "
        "$s.Save()"
    )
    link.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, text=True, timeout=60, creationflags=NO_WINDOW)
    if result.returncode != 0 or not link.exists():
        raise OSError((result.stderr or "the shortcut could not be saved").strip()[:300])


def special_folder(name: str) -> Path:
    """'Desktop' or 'Programs' (the Start menu), following OneDrive redirection."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             f"(New-Object -ComObject WScript.Shell).SpecialFolders('{name}')"],
            capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
        if out.stdout.strip():
            return Path(out.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        pass
    if name == "Desktop":
        return Path.home() / "Desktop"
    return Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


# Takes the new process out of any job object it would otherwise inherit.
CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def build_named_exe(install_dir: Path, log=None) -> Path:
    """Make python/HomingPigeon.exe, the program the shortcuts point at.

    Task Manager names a running program after its executable, so launching the
    app through pythonw.exe listed it as "python", which is alarming if you are
    checking what is running on your computer. A plain copy under the app's own
    name fixes that everywhere and keeps python.org's signature intact.

    Nothing is written into the copy. An earlier version rewrote its version
    resource to fix the description column too, which invalidated that
    signature; an executable whose signature no longer checks out looks worse
    to Windows and to antivirus than one that was never signed.
    """
    source = install_dir / "python" / "pythonw.exe"
    target = install_dir / "python" / f"{APP_NAME}.exe"
    if not source.exists():
        raise OSError(f"{source} is missing")

    if target.exists():
        target.unlink()
    shutil.copy2(source, target)  # a plain copy keeps python.org's signature valid

    # Never hand the user a program that will not start: prove it runs first.
    try:
        finished = subprocess.run([str(target), "-c", "pass"], capture_output=True, timeout=60,
                                  env=clean_env(), creationflags=NO_WINDOW)
        if finished.returncode != 0:
            raise OSError((finished.stderr or b"").decode("utf-8", "replace").strip()[:200]
                          or "it did not start")
    except (OSError, subprocess.TimeoutExpired) as error:
        if log:
            log(f"  {APP_NAME}.exe will not run here ({error}); using pythonw.exe instead.")
        target.unlink(missing_ok=True)
        return source
    return target


def app_exe(install_dir: Path, windowed: bool = True) -> Path:
    """The program that starts the app: the app's own name when it is available."""
    if windowed:
        named = install_dir / "python" / f"{APP_NAME}.exe"
        if named.exists():
            return named
    return install_dir / "python" / ("pythonw.exe" if windowed else "python.exe")


def app_command(install_dir: Path, windowed: bool = True) -> list[str]:
    return [str(app_exe(install_dir, windowed)), "-E", "-s", str(install_dir / "run.py")]


def start_app(install_dir: Path) -> subprocess.Popen:
    """Open the app. Returns the process so the caller can check it stayed up.

    Two things used to make "Open HomingPigeon now" quietly do nothing.

    Setup is usually launched from a browser's download manager or from an
    Explorer window, and those put the processes they start into a job object
    marked kill-on-close. A child inherits that job, so the app was killed the
    instant Setup's window closed. CREATE_BREAKAWAY_FROM_JOB leaves the job.

    A DETACHED_PROCESS child also inherits Setup's standard handles, which stop
    being valid once Setup exits; pythonw.exe can fail during start-up on that.
    Giving it its own null handles removes the race.
    """
    command = app_command(install_dir)
    base = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    last: OSError | None = None
    for flags in (base | CREATE_BREAKAWAY_FROM_JOB, base):
        try:
            return subprocess.Popen(
                command, cwd=install_dir, env=clean_env(), close_fds=True,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=flags)
        except OSError as error:
            last = error  # breakaway is not allowed in this job; try without it
    raise last or OSError("the app could not be started")


def why_app_failed(install_dir: Path) -> str:
    """Re-run the app on the console Python to turn a silent exit into a message."""
    try:
        finished = subprocess.run(
            app_command(install_dir, windowed=False), cwd=install_dir, env=clean_env(),
            capture_output=True, text=True, errors="replace", timeout=25,
            creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return ""  # it stayed up this time, so there is nothing to report
    output = (finished.stderr or finished.stdout or "").strip()
    return output.splitlines()[-1][:300] if output else ""


# =============================================================================
# The work, run on a background thread
# =============================================================================
class Cancelled(Exception):
    pass


class StepFailed(Exception):
    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.hint = hint


INSTALL_STEPS = [
    ("internet", "Check the internet connection", 2),
    ("download", f"Download Python {PYTHON_VERSION[:4]} from python.org", 22),
    ("verify", "Check the download is genuine", 3),
    ("unpack", "Unpack Python", 10),
    ("copy", "Copy HomingPigeon's files", 3),
    ("addons", "Download and install the add-ons", 52),
    ("check", "Make sure everything works", 5),
    ("finish", "Finish up", 3),
]

UNINSTALL_STEPS = [
    ("close", "Check HomingPigeon is closed", 10),
    ("shortcuts", "Remove shortcuts", 10),
    ("files", "Delete the program files", 70),
    ("register", "Remove it from Settings > Apps", 10),
]


class Job:
    """Base for install/uninstall: reports to the window through a queue."""

    steps: list[tuple[str, str, int]] = []

    def __init__(self, events: queue.Queue, install_dir: Path):
        self.events = events
        self.install_dir = install_dir
        self.cancel_event = threading.Event()
        self.process: subprocess.Popen | None = None
        self.log_path = Path(tempfile.gettempdir()) / f"{APP_NAME}-setup-log.txt"
        self._log_file = open(self.log_path, "w", encoding="utf-8")
        self._total_weight = sum(w for _, _, w in self.steps)
        self._done_weight = 0
        self._current_weight = 0

    # -- reporting -------------------------------------------------------------
    def log(self, text: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        for line in text.rstrip().splitlines() or [""]:
            self._log_file.write(f"{stamp}  {line}\n")
            self.events.put(("log", line))
        self._log_file.flush()

    def progress(self, fraction: float, detail: str = "") -> None:
        fraction = max(0.0, min(1.0, fraction))
        overall = (self._done_weight + self._current_weight * fraction) / self._total_weight
        self.events.put(("progress", overall, detail))

    def check_cancel(self) -> None:
        if self.cancel_event.is_set():
            raise Cancelled()

    def cancel(self) -> None:
        self.cancel_event.set()
        if self.process and self.process.poll() is None:
            try:
                self.process.kill()
            except OSError:
                pass

    # -- running ---------------------------------------------------------------
    def run(self) -> None:
        try:
            for index, (key, title, weight) in enumerate(self.steps):
                self.check_cancel()
                self._current_weight = weight
                self.events.put(("step", index, "running", ""))
                self.log("")
                self.log(f"== {title} ==")
                self.progress(0)
                summary = getattr(self, f"step_{key}")() or "Done"
                self._done_weight += weight
                self.progress(0)
                self.events.put(("step", index, "done", summary))
            self.events.put(("finished",))
        except Cancelled:
            self.log("Stopped because Cancel was pressed.")
            self.events.put(("cancelled",))
        except StepFailed as error:
            self.log(f"PROBLEM: {error}")
            self.events.put(("failed", str(error), error.hint))
        except Exception as error:  # noqa: BLE001 - always tell the user
            import traceback

            self.log(traceback.format_exc())
            self.events.put(("failed", f"Something unexpected went wrong: {error}",
                             "Click Try again. If it keeps happening, send the log file to support."))
        finally:
            self._log_file.close()

    def run_logged(self, command: list[str], line_handler=None, cwd: Path | None = None) -> int:
        """Run a command, streaming each output line into the log."""
        self.log("> " + " ".join(f'"{c}"' if " " in c else c for c in command))
        self.process = subprocess.Popen(
            command, cwd=cwd or self.install_dir, env=clean_env(), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
            errors="replace", creationflags=NO_WINDOW)
        assert self.process.stdout is not None
        for line in self.process.stdout:
            line = line.rstrip()
            if line:
                self.log(line)
                if line_handler:
                    line_handler(line)
        code = self.process.wait()
        self.check_cancel()
        return code


class InstallJob(Job):
    steps = INSTALL_STEPS

    def __init__(self, events: queue.Queue, install_dir: Path, register: bool):
        super().__init__(events, install_dir)
        self.register = register
        self.arch = python_arch()
        self.sha256, self.size = PYTHON_BUILDS[self.arch]
        self.url = PYTHON_URL.format(v=PYTHON_VERSION, arch=self.arch)
        self.download_path = Path(tempfile.gettempdir()) / f"{APP_NAME}-python-{PYTHON_VERSION}-{self.arch}.zip"
        self.python_dir = install_dir / "python"
        self.python_marker = self.python_dir / "homingpigeon-python.txt"
        self.python_ready = False

    @property
    def python(self) -> Path:
        return self.python_dir / "python.exe"

    # -- 1 ---------------------------------------------------------------------
    def step_internet(self) -> str:
        self.log(f"Installing to: {self.install_dir}")
        try:
            free = shutil.disk_usage(self.install_dir.anchor or "C:\\").free
            self.log(f"Free disk space: {human_mb(free)}")
            if free < 600 * 1_048_576:
                raise StepFailed("There isn't enough free disk space.",
                                 "HomingPigeon needs about 400 MB. Free up some space, then click Try again.")
        except OSError:
            pass

        for index, url in enumerate(("https://www.python.org/", "https://pypi.org/simple/")):
            self.check_cancel()
            self.log(f"Contacting {url}")
            try:
                request = urllib.request.Request(url, method="HEAD",
                                                 headers={"User-Agent": f"{APP_NAME}-Setup"})
                with urllib.request.urlopen(request, timeout=20) as response:
                    self.log(f"  reply: {response.status} OK")
            except Exception as error:  # noqa: BLE001
                self.log(f"  failed: {error}")
                host = url.split("/")[2]
                raise StepFailed(f"Couldn't reach {host}.",
                                 "Check that this computer is connected to the internet, then click "
                                 "Try again. On a work network, ask your IT team whether python.org "
                                 "and pypi.org are blocked.") from None
            self.progress((index + 1) / 2)
        return "Connected"

    # -- 2 ---------------------------------------------------------------------
    def step_download(self) -> str:
        if self.python_marker.exists() and self.python_marker.read_text().strip() == PYTHON_VERSION \
                and self.python.exists():
            self.python_ready = True
            self.log(f"Python {PYTHON_VERSION} is already installed in {self.python_dir}; not downloading again.")
            return "Already installed"

        if self.download_path.exists() and self.download_path.stat().st_size == self.size:
            self.log(f"Using the copy downloaded earlier: {self.download_path}")
            return "Already downloaded"

        self.log(f"Downloading {self.url}")
        self.log(f"Saving to {self.download_path}")
        partial = self.download_path.with_suffix(".part")
        try:
            received = self._fetch(self.url, partial)
            self.log(f"Downloaded {human_mb(received)}")
        except Cancelled:
            partial.unlink(missing_ok=True)
            raise
        except Exception as error:  # noqa: BLE001
            partial.unlink(missing_ok=True)
            self.log(f"Download error: {error}")
            raise StepFailed("The Python download was interrupted.",
                             "Check your internet connection, then click Try again.") from None
        partial.replace(self.download_path)
        return human_mb(self.size)

    # -- downloading -----------------------------------------------------------
    def _fetch(self, url: str, target: Path) -> int:
        """Download to `target`, using several connections when the server allows it.

        One HTTP connection rarely fills a fast line: a single TCP stream to a
        distant CDN node is limited by round-trip time long before it is limited
        by bandwidth. Asking for byte ranges in parallel fixes that, and on a
        slow line it costs nothing because the link is the bottleneck either way.

        Servers that do not advertise ranges, and any failure part-way through,
        fall back to the plain single-stream download.
        """
        total, ranges_ok = self._probe(url)
        if ranges_ok and total > 0 and DOWNLOAD_CONNECTIONS > 1:
            try:
                return self._fetch_ranged(url, target, total)
            except Cancelled:
                raise
            except Exception as error:  # noqa: BLE001
                self.log(f"  parallel download failed ({error}); using a single connection")
        return self._fetch_serial(url, target, total)

    def _probe(self, url: str) -> tuple[int, bool]:
        """Size and range support, from one HEAD request."""
        try:
            request = urllib.request.Request(url, method="HEAD", headers=DOWNLOAD_HEADERS)
            with urllib.request.urlopen(request, timeout=20) as response:
                total = int(response.headers.get("Content-Length") or 0)
                ranges_ok = "bytes" in (response.headers.get("Accept-Ranges") or "").lower()
        except Exception:  # noqa: BLE001 - fall back to a plain download
            return self.size, False
        return total or self.size, ranges_ok

    def _report_speed(self, received: int, total: int, started: float) -> None:
        speed = received / max(time.monotonic() - started, 0.001)
        self.progress(received / total if total else 0,
                      f"{human_mb(received)} of {human_mb(total)}  ·  {human_mb(speed)}/s")

    def _fetch_serial(self, url: str, target: Path, total: int) -> int:
        request = urllib.request.Request(url, headers=DOWNLOAD_HEADERS)
        received = 0
        started = time.monotonic()
        last_report = 0.0
        with urllib.request.urlopen(request, timeout=60) as response, open(target, "wb") as out:
            total = int(response.headers.get("Content-Length") or total or self.size)
            while True:
                self.check_cancel()
                chunk = response.read(DOWNLOAD_CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                received += len(chunk)
                now = time.monotonic()
                if now - last_report > 0.15:
                    self._report_speed(received, total, started)
                    last_report = now
        return received

    def _fetch_ranged(self, url: str, target: Path, total: int) -> int:
        """Fetch byte ranges on several threads, straight into one pre-sized file."""
        count = DOWNLOAD_CONNECTIONS
        span = total // count
        done = [0] * count
        failure: list[BaseException] = []
        lock = threading.Lock()
        stop = threading.Event()

        # Pre-size the file so every worker can seek to its own slice and write
        # in place; there are no part files to stitch together afterwards.
        with open(target, "wb") as out:
            out.truncate(total)

        def grab(index: int) -> None:
            start = index * span
            end = (start + span - 1) if index < count - 1 else total - 1
            headers = dict(DOWNLOAD_HEADERS, Range=f"bytes={start}-{end}")
            request = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    with open(target, "r+b") as out:
                        out.seek(start)
                        while not stop.is_set():
                            chunk = response.read(DOWNLOAD_CHUNK)
                            if not chunk:
                                break
                            out.write(chunk)
                            with lock:
                                done[index] += len(chunk)
            except BaseException as error:  # noqa: BLE001 - re-raised on the main thread
                with lock:
                    failure.append(error)
                stop.set()

        started = time.monotonic()
        workers = [threading.Thread(target=grab, args=(i,), daemon=True) for i in range(count)]
        self.log(f"  using {count} connections")
        for worker in workers:
            worker.start()

        while any(worker.is_alive() for worker in workers):
            if self.cancel_event.is_set():
                stop.set()
                break
            with lock:
                received = sum(done)
            self._report_speed(received, total, started)
            time.sleep(0.15)

        # Always wait for the workers before touching the file: on Windows it
        # cannot be deleted or renamed while a thread still has it open.
        for worker in workers:
            worker.join(timeout=15)

        self.check_cancel()
        if failure:
            raise failure[0]
        received = sum(done)
        if received != total:
            raise OSError(f"got {received} bytes of {total}")
        return received

    # -- 3 ---------------------------------------------------------------------
    def step_verify(self) -> str:
        if self.python_ready:
            return "Already installed"
        self.log("Comparing the file's SHA-256 fingerprint with the one built into this installer.")
        digest = hashlib.sha256()
        done = 0
        with open(self.download_path, "rb") as source:
            while chunk := source.read(1024 * 1024):
                self.check_cancel()
                digest.update(chunk)
                done += len(chunk)
                self.progress(done / self.size)
        actual = digest.hexdigest()
        self.log(f"  expected: {self.sha256}")
        self.log(f"  received: {actual}")
        if actual != self.sha256:
            self.download_path.unlink(missing_ok=True)
            raise StepFailed("The downloaded file didn't match the official Python release, so it was deleted.",
                             "This is usually a download that got corrupted. Click Try again.")
        self.log("  They match: this is the genuine file from python.org.")
        return "Verified"

    # -- 4 ---------------------------------------------------------------------
    def step_unpack(self) -> str:
        if self.python_ready:
            return "Already installed"
        staging = self.install_dir / "python.new"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        with zipfile.ZipFile(self.download_path) as archive:
            members = archive.infolist()
            self.log(f"Unpacking {len(members)} files into {self.python_dir}")
            for index, member in enumerate(members):
                if index % 40 == 0:
                    self.check_cancel()
                    self.progress(index / len(members), f"{index} of {len(members)} files")
                archive.extract(member, staging)
        if self.python_dir.exists():
            self.log("Replacing the previous Python copy.")
            shutil.rmtree(self.python_dir)
        staging.rename(self.python_dir)
        self.python_marker.write_text(PYTHON_VERSION)
        self.download_path.unlink(missing_ok=True)
        self.log("Removed the downloaded zip (no longer needed).")
        return f"{len(members)} files"

    # -- 5 ---------------------------------------------------------------------
    def step_copy(self) -> str:
        source = payload_dir()
        ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
        items = ["app", "assets", "installer", "run.py", "requirements.txt"]
        for index, name in enumerate(items):
            self.check_cancel()
            src, dst = source / name, self.install_dir / name
            self.log(f"Copying {name}")
            if src.is_dir():
                shutil.rmtree(dst, ignore_errors=True)  # drop files an older version had
                shutil.copytree(src, dst, ignore=ignore)
            else:
                shutil.copy2(src, dst)
            self.progress((index + 1) / len(items))
        return "Copied"

    # -- 6 ---------------------------------------------------------------------
    def step_addons(self) -> str:
        """Install everything in requirements.txt, in a single pip run.

        This used to run pip twice: once with --dry-run --report to learn how
        many packages were coming, and then again to actually install them. The
        dry run repeats the whole dependency resolution, which means another
        round of metadata requests to pypi.org before a single byte of any wheel
        is fetched. Progress now comes from the sizes pip prints as it downloads,
        so that first pass is gone and the step starts fetching immediately.
        """
        requirements = self.install_dir / "requirements.txt"
        pip = [str(self.python), "-E", "-s", "-m", "pip"]

        self.progress(0.02, "Contacting pypi.org...")
        downloaded = 0.0          # MB, summed from pip's own "(12.3 MB)" notes
        packages: list[str] = []

        def on_line(line: str) -> None:
            nonlocal downloaded
            match = re.match(r"(?:Downloading|Using cached) (\S+)(?:\s+\(([\d.]+)\s*([kKMG]B)\))?",
                             line)
            if match:
                name = match.group(1).rsplit("/", 1)[-1].split("-")[0]
                packages.append(name)
                downloaded += _as_mb(match.group(2), match.group(3))
                share = min(downloaded / EXPECTED_ADDON_MB, 1.0)
                self.progress(0.03 + 0.80 * share,
                              f"{downloaded:.0f} MB of about {EXPECTED_ADDON_MB:.0f} MB  "
                              f"·  {name}")
            elif line.startswith("Installing collected packages"):
                self.progress(0.88, "Installing...")
            elif line.startswith("Successfully installed"):
                self.progress(1.0, "Installed")

        code = self.run_logged(
            pip + ["install", "--prefer-binary", "--progress-bar", "off",
                   "--no-warn-script-location", "--disable-pip-version-check",
                   "--retries", "2", "--timeout", "30", "-r", str(requirements)],
            on_line)
        if code != 0:
            raise StepFailed("Installing the add-ons didn't finish.",
                             "Check your internet connection and that HomingPigeon is closed, "
                             "then click Try again.")
        if not packages:
            self.log("Every add-on was already installed and up to date.")
            return "Up to date"
        return f"{len(packages)} installed"

    # -- 7 ---------------------------------------------------------------------
    def step_check(self) -> str:
        self.progress(0.3, "Loading the app's parts...")
        code = self.run_logged([str(self.python), "-E", "-s", "-c",
                                f"{REQUIRED_IMPORTS}; import app.config; print('Everything loads correctly.')"])
        if code != 0:
            raise StepFailed("The app's parts didn't load correctly.",
                             "Click Try again. If it keeps happening, send the log file to support.")
        return "All good"

    # -- 8 ---------------------------------------------------------------------
    def step_finish(self) -> str:
        self.progress(0.1, "Naming the program...")
        self.log(f"Creating {APP_NAME}.exe, so the app runs under its own name "
                 f"rather than Python's.")
        try:
            started = build_named_exe(self.install_dir, log=self.log)
            self.log(f"  the app will start from {started.name}")
        except OSError as error:
            # Cosmetic only. The shortcuts fall back to pythonw.exe
            self.log(f"  could not create it ({error}); using pythonw.exe.")

        self.progress(0.3)
        self.desktop = special_folder("Desktop")
        self.start_menu = special_folder("Programs")
        self.progress(0.5)

        if self.register:
            version = read_version(self.install_dir) or ""
            size_kb = sum(f.stat().st_size for f in self.install_dir.rglob("*") if f.is_file()) // 1024
            self.log("Adding HomingPigeon to Settings > Apps, so it can be removed like any other app.")
            import winreg

            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY) as key:
                values = {
                    "DisplayName": APP_NAME,
                    "DisplayVersion": version,
                    "Publisher": PUBLISHER,
                    "DisplayIcon": str(self.install_dir / "assets" / "icon.ico"),
                    "InstallLocation": str(self.install_dir),
                    # Runs on the private python.org Python, which is signed, so Windows
                    # Smart App Control never blocks removing the app.
                    "UninstallString": (f'"{self.install_dir / "python" / "pythonw.exe"}" -E -s '
                                        f'"{self.install_dir / "installer" / "setup_app.py"}" --uninstall'),
                }
                for name, value in values.items():
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
                winreg.SetValueEx(key, "EstimatedSize", 0, winreg.REG_DWORD, size_kb)
                winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
                winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
        self.progress(1.0)
        self._log_file.flush()
        try:
            shutil.copy2(self.log_path, self.install_dir / "setup-log.txt")
        except OSError:
            pass
        return "Done"


class UninstallJob(Job):
    steps = UNINSTALL_STEPS

    def __init__(self, events: queue.Queue, install_dir: Path, delete_data: bool, register: bool):
        super().__init__(events, install_dir)
        self.delete_data = delete_data
        self.register = register  # False for test installs elsewhere: leave real shortcuts alone

    def step_close(self) -> str:
        # When started from the app's Settings page, the app is closing as this starts: give it
        # a little while before asking the user to close it.
        for attempt in range(20):
            if not running_app_pids(self.install_dir):
                return "Closed"
            if attempt == 0:
                self.log("Waiting for HomingPigeon to close...")
            self.check_cancel()
            time.sleep(1)
        raise StepFailed("HomingPigeon is still open.", "Close HomingPigeon, then click Try again.")

    def step_shortcuts(self) -> str:
        if not self.register:
            return "Skipped (test install)"
        removed = 0
        for folder in (special_folder("Desktop"), special_folder("Programs")):
            link = folder / f"{APP_NAME}.lnk"
            if link.exists():
                self.log(f"Deleting {link}")
                link.unlink()
                removed += 1
        return f"{removed} removed"

    def step_files(self) -> str:
        targets = [self.install_dir]
        if self.delete_data:
            targets.append(data_dir())
        # This uninstaller may itself be running on the private Python; those files are
        # locked until it closes, so they are removed right after the window closes.
        own_python = Path(sys.executable).resolve().parent
        for target in (t.resolve() for t in targets):
            if not target.exists():
                continue
            files = [p for p in target.rglob("*") if p.is_file() and own_python not in p.parents]
            self.log(f"Deleting {target} ({len(files)} files)")
            for index, path in enumerate(files):
                if index % 50 == 0:
                    self.check_cancel()
                    self.progress(index / max(len(files), 1), f"{index} of {len(files)} files")
                try:
                    path.unlink()
                except OSError as error:
                    self.log(f"  could not delete {path}: {error}")
            if own_python.is_relative_to(target):
                self.log("The last few files are removed as soon as this window closes.")
            else:
                shutil.rmtree(target, ignore_errors=True)
        if not self.delete_data:
            self.log(f"Your contacts, templates and settings were kept in {data_dir()}")
        return "Deleted"

    def step_register(self) -> str:
        if not self.register:
            return "Skipped (test install)"
        import winreg

        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY)
            self.log("Removed from Settings > Apps.")
        except OSError:
            pass
        return "Done"


# =============================================================================
# The window
# =============================================================================
class Button(tk.Label):
    """A flat, rounded-feeling button that matches the app (tk.Button can't be styled on Windows)."""

    def __init__(self, master, text: str, command, kind: str = "secondary", **kwargs):
        colours = {"primary": (ACCENT, ACCENT_HOVER), "confirm": (CONFIRM, CONFIRM_HOVER),
                   "secondary": (SECONDARY, SECONDARY_HOVER)}[kind]
        self._normal, self._hover = colours
        self._command = command
        self._enabled = True
        super().__init__(master, text=text, bg=self._normal, fg=FG_BRIGHT, cursor="hand2",
                         padx=22, pady=9, **kwargs)
        self.bind("<Enter>", lambda _e: self._enabled and self.configure(bg=self._hover))
        self.bind("<Leave>", lambda _e: self.configure(bg=self._normal if self._enabled else SECONDARY))
        self.bind("<Button-1>", lambda _e: self.invoke())

    def invoke(self) -> None:
        if self._enabled:
            self._command()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.configure(bg=self._normal if enabled else SECONDARY, fg=FG_BRIGHT if enabled else FG_MUTED,
                       cursor="hand2" if enabled else "arrow")


class StepRow(tk.Frame):
    def __init__(self, master, title: str, fonts, scale: float):
        super().__init__(master, bg=PANEL)
        size = int(18 * scale)
        self.size = size
        self.icon = tk.Canvas(self, width=size, height=size, bg=PANEL, highlightthickness=0)
        self.icon.pack(side="left", padx=(0, int(10 * scale)))
        self.title = tk.Label(self, text=title, bg=PANEL, fg=FG_MUTED, font=fonts["body"], anchor="w")
        self.title.pack(side="left")
        self.detail = tk.Label(self, text="", bg=PANEL, fg=FG_MUTED, font=fonts["small"], anchor="e")
        self.detail.pack(side="right")
        self.state = "pending"
        self.angle = 0
        self.draw()

    def set(self, state: str, detail: str = "") -> None:
        self.state = state
        self.title.configure(fg={"pending": FG_MUTED, "running": FG_BRIGHT}.get(state, FG))
        self.detail.configure(text=detail, fg=ERROR if state == "failed" else FG_MUTED)
        self.draw()

    def draw(self) -> None:
        c, s = self.icon, self.size
        c.delete("all")
        pad = 2
        width = max(2, s // 9)
        if self.state == "pending":
            c.create_oval(pad, pad, s - pad, s - pad, outline=BORDER, width=width)
        elif self.state == "running":
            c.create_oval(pad, pad, s - pad, s - pad, outline=BORDER, width=width)
            c.create_arc(pad, pad, s - pad, s - pad, start=self.angle, extent=110, style="arc",
                         outline=ACCENT, width=width)
        elif self.state == "done":
            c.create_oval(pad, pad, s - pad, s - pad, fill=CONFIRM, outline=CONFIRM)
            c.create_line(s * 0.28, s * 0.52, s * 0.44, s * 0.68, s * 0.73, s * 0.34,
                          fill="white", width=width, capstyle="round", joinstyle="round")
        elif self.state == "failed":
            c.create_oval(pad, pad, s - pad, s - pad, fill="#c0493f", outline="#c0493f")
            c.create_line(s * 0.34, s * 0.34, s * 0.66, s * 0.66, fill="white", width=width, capstyle="round")
            c.create_line(s * 0.66, s * 0.34, s * 0.34, s * 0.66, fill="white", width=width, capstyle="round")

    def spin(self) -> None:
        if self.state == "running":
            self.angle = (self.angle - 18) % 360
            self.draw()


class SetupWindow:
    def __init__(self, uninstall: bool, install_dir: Path, register: bool,
                 confirmed: bool = False, delete_data: bool = False):
        self.uninstall = uninstall
        self.install_dir = install_dir
        self.register = register
        self.confirmed = confirmed  # already confirmed in the app's Settings page
        self.preset_delete_data = delete_data
        self.events: queue.Queue = queue.Queue()
        self.job: Job | None = None
        self.busy = False
        self.uninstalled = False
        self.new_version = read_version(payload_dir()) or ""
        self.old_version = read_version(install_dir) if (install_dir / "run.py").exists() else None

        self.root = tk.Tk()
        self.scale = self.root.winfo_fpixels("1i") / 96
        self.root.title(f"{APP_NAME} Setup" if not uninstall else f"Remove {APP_NAME}")
        self.root.configure(bg=BG)
        # Tall enough that the activity log shows a dozen lines without
        # scrolling, and clamped so it still fits a 768-pixel laptop screen.
        width = int(760 * self.scale)
        height = min(int(780 * self.scale), self.root.winfo_screenheight() - int(80 * self.scale))
        x = (self.root.winfo_screenwidth() - width) // 2
        y = (self.root.winfo_screenheight() - height) // 3
        self.root.geometry(f"{width}x{height}+{x}+{max(y, 0)}")
        self.root.minsize(int(620 * self.scale), int(560 * self.scale))
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.bind("<Return>", lambda _e: self.primary and self.primary.invoke())

        assets = payload_dir() / "assets"
        try:
            self.root.iconbitmap(str(assets / "icon.ico"))
        except tk.TclError:
            pass

        family = "Segoe UI"
        self.fonts = {
            "title": tkfont.Font(family="Segoe UI Semibold", size=17),
            "heading": tkfont.Font(family="Segoe UI Semibold", size=12),
            "body": tkfont.Font(family=family, size=10),
            "bold": tkfont.Font(family="Segoe UI Semibold", size=10),
            "small": tkfont.Font(family=family, size=9),
            "mono": tkfont.Font(family="Consolas", size=9),
        }
        self.root.option_add("*Font", self.fonts["body"])

        self._build_frame(assets)
        self.primary: Button | None = None
        self.bob_phase = 0.0
        self.bob_speed = 0.09
        self._animate()
        self._poll()

        if uninstall and confirmed:
            self.root.after(300, self.start_uninstall)
        elif uninstall:
            self.page_confirm_uninstall()
        else:
            self.page_welcome()

    # -- frame -----------------------------------------------------------------
    def _build_frame(self, assets: Path) -> None:
        s = self.scale
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=int(28 * s), pady=(int(20 * s), int(8 * s)))

        sizes = [96, 128, 160, 192, 256]
        wanted = 112 * s
        best = min(sizes, key=lambda n: abs(n - wanted))
        try:
            self.logo = tk.PhotoImage(file=str(assets / f"logo-{best}.png"))
        except tk.TclError:
            self.logo = None
        box = best if self.logo else int(96 * s)
        self.bob_room = int(8 * s)
        self.logo_canvas = tk.Canvas(header, width=box, height=box + self.bob_room * 2, bg=BG,
                                     highlightthickness=0)
        self.logo_canvas.pack(side="left")
        if self.logo:
            self.logo_item = self.logo_canvas.create_image(box // 2, box // 2 + self.bob_room,
                                                           image=self.logo)
        self.shadow_item = self.logo_canvas.create_oval(0, 0, 0, 0, fill="#2a2c32", outline="")
        self.logo_canvas.tag_lower(self.shadow_item)
        self.logo_box = box

        titles = tk.Frame(header, bg=BG)
        titles.pack(side="left", padx=(int(18 * s), 0), fill="x", expand=True)
        self.title_label = tk.Label(titles, text="", bg=BG, fg=FG_BRIGHT, font=self.fonts["title"],
                                    anchor="w", justify="left")
        self.title_label.pack(anchor="w")
        self.subtitle_label = tk.Label(titles, text="", bg=BG, fg=FG_MUTED, font=self.fonts["body"],
                                       anchor="w", justify="left")
        self.subtitle_label.pack(anchor="w", pady=(int(2 * s), 0))
        titles.bind("<Configure>", lambda e: self.subtitle_label.configure(wraplength=e.width))

        # Footer is packed first (at the bottom) so its buttons can never be pushed out of view
        self.footer = tk.Frame(self.root, bg=BG)
        self.footer.pack(side="bottom", fill="x", padx=int(28 * s), pady=int(18 * s))

        self.body = tk.Frame(self.root, bg=BG)
        self.body.pack(fill="both", expand=True, padx=int(28 * s))

    def _clear(self) -> None:
        for widget in list(self.body.winfo_children()) + list(self.footer.winfo_children()):
            widget.destroy()
        # Everything below belonged to the page just torn down. The worker
        # thread keeps posting log and progress events for a moment after Setup
        # has moved on, and writing to a destroyed widget killed the event pump.
        self.primary = None
        self.detail = None
        self.log_text = None
        self.percent = None
        self.bar = None
        self.rows = []

    def _heading(self, title: str, subtitle: str) -> None:
        self.title_label.configure(text=title)
        self.subtitle_label.configure(text=subtitle)

    def _card(self, parent=None) -> tuple[tk.Frame, tk.Frame]:
        s = self.scale
        outer = tk.Frame(parent or self.body, bg=BORDER)
        inner = tk.Frame(outer, bg=PANEL, padx=int(18 * s), pady=int(14 * s))
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        return outer, inner

    def _status(self, text: str) -> None:
        """Show a line of progress, if the current page has somewhere to put it.

        Every page rebuild destroys the body, so the label from a previous page
        is a dead Tcl command. Writing to one used to raise inside the Finish
        handler, which left the app launched but Setup still on screen.
        """
        label = getattr(self, "detail", None)
        try:
            if label is not None:
                label.configure(text=text)
                self.root.update_idletasks()
        except tk.TclError:
            self.detail = None

    def _footer_note(self, text: str) -> None:
        tk.Label(self.footer, text=text, bg=BG, fg=FG_MUTED, font=self.fonts["small"]).pack(side="left")

    def _button(self, text: str, command, kind: str = "secondary", primary: bool = False) -> Button:
        button = Button(self.footer, text, command, kind, font=self.fonts["bold"])
        button.pack(side="right", padx=(int(10 * self.scale), 0))
        if primary:
            self.primary = button
        return button

    def _animate(self) -> None:
        """The pigeon bobs gently, and flies a bit faster while work is happening."""
        self.bob_phase += self.bob_speed
        if self.logo:
            offset = math.sin(self.bob_phase) * self.bob_room * 0.8
            centre = self.logo_box // 2
            self.logo_canvas.coords(self.logo_item, centre, centre + self.bob_room + offset)
            spread = self.logo_box * (0.30 - 0.03 * math.sin(self.bob_phase))
            bottom = self.logo_box + self.bob_room * 2 - 2
            self.logo_canvas.coords(self.shadow_item, centre - spread, bottom - self.bob_room * 0.7,
                                    centre + spread, bottom)
        for row in getattr(self, "rows", []):
            try:
                row.spin()
            except tk.TclError:
                pass
        self.root.after(33, self._animate)

    # -- pages: install ----------------------------------------------------------
    def page_welcome(self) -> None:
        self._clear()
        s = self.scale
        if self.old_version:
            same = self.old_version == self.new_version
            title = f"Repair {APP_NAME} v{self.new_version}" if same else f"Update {APP_NAME} to v{self.new_version}"
            subtitle = ("HomingPigeon is already installed. This will check everything and fix anything "
                        "that's missing." if same else
                        f"You have v{self.old_version}. Your contacts, templates and settings are kept.")
            action = "Repair" if same else "Update"
        else:
            title = f"Install {APP_NAME} v{self.new_version}"
            subtitle = "Safe, simple email for your business. Setup takes about 2 to 5 minutes."
            action = "Install"
        self._heading(title, subtitle)

        outer, card = self._card()
        outer.pack(fill="x", pady=(int(8 * s), 0))
        tk.Label(card, text="What Setup will do", bg=PANEL, fg=FG_BRIGHT, font=self.fonts["heading"],
                 anchor="w").pack(anchor="w", pady=(0, int(8 * s)))
        points = [
            ("Download Python from python.org",
             f"The free program HomingPigeon is built with (about 34 MB). Setup keeps a private "
             f"copy just for HomingPigeon and checks the file is genuine before using it."),
            ("Download the add-ons it needs from pypi.org",
             "Python's official library of add-ons (about 45 MB)."),
            ("Put everything in one folder",
             str(self.install_dir)),
        ]
        for heading, text in points:
            row = tk.Frame(card, bg=PANEL)
            row.pack(fill="x", pady=int(5 * s))
            tk.Label(row, text="•", bg=PANEL, fg=ACCENT, font=self.fonts["heading"]).pack(side="left", anchor="n")
            col = tk.Frame(row, bg=PANEL)
            col.pack(side="left", fill="x", expand=True, padx=(int(8 * s), 0))
            tk.Label(col, text=heading, bg=PANEL, fg=FG, font=self.fonts["bold"], anchor="w").pack(anchor="w")
            detail = tk.Label(col, text=text, bg=PANEL, fg=FG_MUTED, font=self.fonts["small"], anchor="w",
                              justify="left")
            detail.pack(anchor="w", fill="x")
            col.bind("<Configure>", lambda e, d=detail: d.configure(wraplength=e.width))

        tk.Label(self.body, text="No administrator password needed. Needs an internet connection "
                                 "and about 400 MB of free space.",
                 bg=BG, fg=FG_MUTED, font=self.fonts["small"], anchor="w").pack(anchor="w", pady=(int(14 * s), 0))

        self._footer_note(f"v{self.new_version}  ·  Free beta")
        self._button(action, self.start_install, "confirm", primary=True)
        self._button("Cancel", self.root.destroy)

    def start_install(self) -> None:
        if self.old_version and running_app_pids(self.install_dir):
            if not messagebox.askokcancel(f"{APP_NAME} is open",
                                          "HomingPigeon is open right now.\n\nClose it (your work is saved "
                                          "automatically), then click OK to continue.", parent=self.root):
                return
            if running_app_pids(self.install_dir):
                messagebox.showinfo(APP_NAME, "HomingPigeon still seems to be open. Close it and try again.",
                                    parent=self.root)
                return
        self.install_dir.mkdir(parents=True, exist_ok=True)
        self.page_progress(InstallJob(self.events, self.install_dir, self.register),
                           f"Installing {APP_NAME}", "Sit back, this takes a few minutes. "
                           "You can watch every step below.")

    def page_progress(self, job: Job, title: str, subtitle: str) -> None:
        self._clear()
        s = self.scale
        self._heading(title, subtitle)
        self.job = job
        self.busy = True
        self.bob_speed = 0.22

        outer, card = self._card()
        outer.pack(fill="x", pady=(int(4 * s), 0))
        self.rows = []
        for _key, step_title, _w in job.steps:
            row = StepRow(card, step_title, self.fonts, s)
            row.pack(fill="x", pady=int(3 * s))
            self.rows.append(row)

        bar_row = tk.Frame(self.body, bg=BG)
        bar_row.pack(fill="x", pady=(int(14 * s), int(2 * s)))
        self.bar_height = int(10 * s)
        self.bar = tk.Canvas(bar_row, height=self.bar_height + 2, bg=BG, highlightthickness=0)
        self.bar.pack(side="left", fill="x", expand=True)
        self.percent = tk.Label(bar_row, text="0%", bg=BG, fg=FG_BRIGHT, font=self.fonts["bold"],
                                width=5, anchor="e")
        self.percent.pack(side="right")
        self.bar_fraction = 0.0
        self.bar.bind("<Configure>", lambda _e: self._draw_bar())
        self.detail = tk.Label(self.body, text="", bg=BG, fg=FG_MUTED, font=self.fonts["small"], anchor="w")
        self.detail.pack(fill="x")

        tk.Label(self.body, text="Activity log", bg=BG, fg=FG, font=self.fonts["bold"],
                 anchor="w").pack(anchor="w", pady=(int(10 * s), int(4 * s)))
        log_frame = tk.Frame(self.body, bg=BORDER)
        log_frame.pack(fill="both", expand=True)
        self.log_text = tk.Text(log_frame, bg=CONSOLE, fg="#aab1bb", font=self.fonts["mono"], relief="flat",
                                wrap="word", padx=int(10 * s), pady=int(8 * s), height=13,
                                insertbackground=CONSOLE, highlightthickness=0, borderwidth=0)

        self.log_text.configure(state="disabled")  # scrolls with the mouse wheel
        self.log_text.pack(fill="both", expand=True, padx=1, pady=1)
        self.log_text.tag_configure("heading", foreground=FG_BRIGHT)
        self.log_text.tag_configure("problem", foreground=ERROR)

        # The log follows the newest line until the user scrolls up to read
        # something, and starts following again when they scroll back down.
        self.log_follow = True
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>", "<Prior>", "<Next>",
                         "<Up>", "<Down>", "<Home>", "<End>", "<B1-Motion>"):
            self.log_text.bind(sequence, self._log_scrolled, add="+")

        self._button("Cancel", self.on_close)
        threading.Thread(target=job.run, daemon=True).start()

    def _draw_bar(self) -> None:
        if getattr(self, "bar", None) is None:
            return
        width = self.bar.winfo_width()
        h = self.bar_height
        y = h // 2 + 1
        self.bar.delete("all")
        self.bar.create_line(h // 2, y, width - h // 2, y, fill=PANEL, width=h, capstyle="round")
        if self.bar_fraction > 0:
            end = h // 2 + (width - h) * self.bar_fraction
            self.bar.create_line(h // 2, y, max(end, h // 2 + 1), y, fill=ACCENT, width=h, capstyle="round")

    def _log_scrolled(self, _event=None) -> None:
        """Note whether the user has scrolled away from the newest line.

        Checked just after the scroll has been applied, so it reads the position
        the user ended up at rather than the one they started from.
        """
        def check() -> None:
            try:
                if self.log_text is not None:
                    self.log_follow = self.log_text.yview()[1] > 0.999
            except tk.TclError:
                pass

        self.root.after_idle(check)

    def _append_log(self, line: str) -> None:
        if getattr(self, "log_text", None) is None:
            return
        self.log_text.configure(state="normal")
        tag = "heading" if line.startswith("== ") else "problem" if line.startswith("PROBLEM") else ""
        self.log_text.insert("end", line + "\n", tag)
        self.log_text.configure(state="disabled")
        if self.log_follow:
            # yview_moveto goes to the very bottom every time; see("end") only
            # scrolls far enough to reveal the last line, which on a wrapped
            # line can stop a fraction short, and once it did, the old
            # "are we at the bottom?" test said no and the log never moved again.
            self.log_text.yview_moveto(1.0)

    def _poll(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "log":
                    self._append_log(event[1])
                elif kind == "progress":
                    self.bar_fraction = event[1]
                    if self.percent is not None:
                        self._draw_bar()
                        self.percent.configure(text=f"{int(event[1] * 100)}%")
                    self._status(event[2])
                elif kind == "step":
                    _, index, state, detail = event
                    if index < len(self.rows):
                        self.rows[index].set(state, detail)
                elif kind == "finished":
                    self.busy = False
                    self.bob_speed = 0.09
                    self.page_uninstalled() if self.uninstall else self.page_done()
                elif kind == "failed":
                    self.busy = False
                    self.bob_speed = 0.09
                    self.show_failure(event[1], event[2])
                elif kind == "cancelled":
                    self.busy = False
                    self.bob_speed = 0.09
                    self.show_cancelled()
        except queue.Empty:
            pass
        self.root.after(50, self._poll)

    def show_failure(self, message: str, hint: str) -> None:
        for row in self.rows:
            if row.state == "running":
                row.set("failed", "Didn't finish")
        self._heading("Removal didn't finish" if self.uninstall else "Setup didn't finish", f"{message} {hint}".strip())
        self.subtitle_label.configure(fg=ERROR)
        self._status("Nothing is broken. Anything already done is kept, so trying again is quicker.")
        for widget in self.footer.winfo_children():
            widget.destroy()
        self._button("Try again", self.retry, "primary", primary=True)
        self._button("Open log file", lambda: os.startfile(self.job.log_path))  # noqa: S606
        self._button("Close", self.root.destroy)

    def show_cancelled(self) -> None:
        for row in self.rows:
            if row.state == "running":
                row.set("failed", "Cancelled")
        self._heading("Cancelled", "Nothing is broken. Run Setup again whenever you like; "
                                             "it picks up where it left off.")
        for widget in self.footer.winfo_children():
            widget.destroy()
        self._button("Close", self.root.destroy, "primary", primary=True)

    def retry(self) -> None:
        self.subtitle_label.configure(fg=FG_MUTED)
        if self.uninstall:
            self.start_uninstall()
        else:
            self.start_install()

    def page_done(self) -> None:
        self._clear()
        s = self.scale
        self.rows = []
        verb = "updated" if self.old_version and self.old_version != self.new_version else "installed"
        self._heading(f"{APP_NAME} is {verb}!", "Everything downloaded, checked and ready to go.")

        outer, card = self._card()
        outer.pack(fill="x", pady=(int(8 * s), 0))
        tk.Label(card, text="Before you finish", bg=PANEL, fg=FG_BRIGHT, font=self.fonts["heading"],
                 anchor="w").pack(anchor="w", pady=(0, int(8 * s)))

        self.want_start = tk.BooleanVar(value=True)
        self.want_desktop = tk.BooleanVar(value=True)
        self.want_launch = tk.BooleanVar(value=True)
        options = [
            (self.want_start, "Add HomingPigeon to the Start menu", "Find it by pressing the Windows key and typing HomingPigeon."),
            (self.want_desktop, "Put a shortcut on the Desktop", "Double-click the pigeon to open the app."),
            (self.want_launch, "Open HomingPigeon now", "Its Setup guide walks you through the rest."),
        ]
        for variable, label, hint in options:
            row = tk.Frame(card, bg=PANEL)
            row.pack(fill="x", pady=int(5 * s))
            tk.Checkbutton(row, text=label, variable=variable, bg=PANEL, fg=FG_BRIGHT, activebackground=PANEL,
                           activeforeground=FG_BRIGHT, selectcolor=CONSOLE, font=self.fonts["bold"],
                           anchor="w", cursor="hand2", highlightthickness=0, bd=0).pack(anchor="w")
            tk.Label(row, text=hint, bg=PANEL, fg=FG_MUTED, font=self.fonts["small"], anchor="w").pack(
                anchor="w", padx=(int(26 * s), 0))
        self._shortcut_places = (self.job.start_menu, self.job.desktop)

        where = tk.Label(self.body, text=f"Installed in {self.install_dir}\n"
                                         f"Your contacts, templates and settings are stored in {data_dir()}",
                         bg=BG, fg=FG_MUTED, font=self.fonts["small"], justify="left", anchor="w")
        where.pack(anchor="w", fill="x", pady=(int(14 * s), 0))
        where.bind("<Configure>", lambda e: where.configure(wraplength=e.width))

        self.detail = tk.Label(self.body, text="", bg=BG, fg=FG_MUTED, font=self.fonts["small"],
                               anchor="w")
        self.detail.pack(fill="x", pady=(int(8 * s), 0))

        self._footer_note(f"v{self.new_version}  ·  Thanks for trying the beta!")
        self._button("Finish", self.finish, "confirm", primary=True)

    def finish(self) -> None:
        """Make the shortcuts, open the app, and close Setup no matter what.

        Closing is in a ``finally`` on purpose. Anything that goes wrong here is
        worth a warning, but none of it is a reason to leave Setup sitting on
        screen with a Finish button that looks like it did nothing.
        """
        problems: list[str] = []
        try:
            if self.primary is not None:
                self.primary.set_enabled(False)   # no second click while we work
            start_menu, desktop = self._shortcut_places
            for wanted, folder in ((self.want_start.get(), start_menu),
                                   (self.want_desktop.get(), desktop)):
                if not wanted:
                    continue
                try:
                    make_shortcut(folder / f"{APP_NAME}.lnk", self.install_dir)
                except (OSError, subprocess.TimeoutExpired) as error:
                    problems.append(f"{folder}: {error}")
            if self.want_launch.get():
                problems.extend(self._launch_app())
            if problems:
                self._reveal()
                messagebox.showwarning(APP_NAME, "Almost done, but:\n\n" + "\n".join(problems),
                                       parent=self.root)
        except Exception as error:  # noqa: BLE001 - Setup still has to close
            print(f"Problem finishing up: {type(error).__name__}: {error}")
        finally:
            self.root.destroy()

    def _reveal(self) -> None:
        """Bring Setup back after it hid itself, so a warning has a parent window."""
        try:
            self.root.deiconify()
            self.root.lift()
        except tk.TclError:
            pass

    def _launch_app(self) -> list[str]:
        """Open the app, and wait long enough to know it really stayed open.

        Setup used to close the moment it had called Popen, so an app that never
        drew a window, or one killed along with Setup's job object, looked
        exactly like success and the user was left staring at the desktop.
        """
        self._status(f"Opening {APP_NAME}...")
        try:
            process = start_app(self.install_dir)
        except OSError as error:
            return [f"Couldn't open the app: {error}"]

        # Setup disappears now rather than in four seconds' time, so Finish
        # feels like it closed Setup and opened the app. It is hidden, not
        # gone: the watch below still needs a live event loop, and a launch
        # that fails brings the window back to say so.
        try:
            self.root.withdraw()
        except tk.TclError:
            pass

        deadline = time.monotonic() + LAUNCH_CONFIRM_SECONDS
        while time.monotonic() < deadline:
            if process.poll() is None:
                self.root.update()      # keep the event loop turning while waiting
                time.sleep(0.1)
                continue
            reason = why_app_failed(self.install_dir)
            detail = f"\n\n{reason}" if reason else ""
            return [f"{APP_NAME} closed again right after opening.{detail}\n\n"
                    f"Try opening it from the Start menu. If it still won't start, send "
                    f"{self.job.log_path} to support."]
        return []

    # -- pages: uninstall --------------------------------------------------------
    def page_confirm_uninstall(self) -> None:
        self._clear()
        s = self.scale
        self._heading(f"Remove {APP_NAME}?", "This removes the app, its private copy of Python and its shortcuts.")
        outer, card = self._card()
        outer.pack(fill="x", pady=(int(8 * s), 0))
        tk.Label(card, text="Your information", bg=PANEL, fg=FG_BRIGHT, font=self.fonts["heading"],
                 anchor="w").pack(anchor="w", pady=(0, int(6 * s)))
        info = tk.Label(card, bg=PANEL, fg=FG_MUTED, font=self.fonts["small"], justify="left", anchor="w",
                        text=f"Your contacts, templates and settings are kept unless you tick the box below, "
                             f"so reinstalling later brings everything back.\n{data_dir()}")
        info.pack(anchor="w", fill="x")
        card.bind("<Configure>", lambda e: info.configure(wraplength=e.width - int(40 * s)))
        self.want_delete_data = tk.BooleanVar(value=False)
        tk.Checkbutton(card, text="Also delete my contacts, templates and settings", variable=self.want_delete_data,
                       bg=PANEL, fg=FG_BRIGHT, activebackground=PANEL, activeforeground=FG_BRIGHT,
                       selectcolor=CONSOLE, font=self.fonts["bold"], anchor="w", highlightthickness=0,
                       bd=0, cursor="hand2").pack(anchor="w", pady=(int(10 * s), 0))
        self._button("Remove", self.start_uninstall, "primary", primary=True)
        self._button("Cancel", self.root.destroy)

    def start_uninstall(self) -> None:
        if self.confirmed:
            delete_data = self.preset_delete_data
        else:
            delete_data = self.want_delete_data.get() if hasattr(self, "want_delete_data") else False
        if delete_data and not self.confirmed and not messagebox.askyesno(
                APP_NAME, "Permanently delete your contacts, templates and settings too?\n\n"
                          "This can't be undone.", icon="warning", parent=self.root):
            return
        self.page_progress(UninstallJob(self.events, self.install_dir, delete_data, self.register),
                           f"Removing {APP_NAME}", "This only takes a moment.")

    def page_uninstalled(self) -> None:
        self.uninstalled = True
        self._clear()
        self.rows = []
        self._heading(f"{APP_NAME} has been removed", "Thanks for trying it. You can reinstall any time "
                                                     "from the GitHub Releases page.")
        if not self.job.delete_data and data_dir().exists():
            outer, card = self._card()
            outer.pack(fill="x", pady=(int(8 * self.scale), 0))
            tk.Label(card, text="Your information was kept", bg=PANEL, fg=FG_BRIGHT, font=self.fonts["heading"],
                     anchor="w").pack(anchor="w")
            tk.Label(card, text=f"Reinstall later and your contacts, templates and settings will be there.\n"
                                f"They're stored in {data_dir()}",
                     bg=PANEL, fg=FG_MUTED, font=self.fonts["small"], justify="left", anchor="w").pack(
                anchor="w", pady=(int(4 * self.scale), 0))
        self._button("Close", self.root.destroy, "primary", primary=True)

    # -- closing -------------------------------------------------------------------
    def on_close(self) -> None:
        if self.busy and self.job:
            if messagebox.askyesno("Cancel?", "Stop now? Nothing will be broken, and you can run Setup "
                                              "again later to finish.", parent=self.root):
                self._status("Stopping...")
                self.job.cancel()
            return
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


# =============================================================================
# Entry point
# =============================================================================
def remove_folder_after_exit(folder: Path) -> None:
    """Delete what's left of the install folder once this process (which uses it) has closed."""
    subprocess.Popen(f'cmd /c ping 127.0.0.1 -n 4 >nul & rmdir /s /q "{folder}"',
                     creationflags=NO_WINDOW | subprocess.DETACHED_PROCESS, close_fds=True,
                     cwd=tempfile.gettempdir())


def main() -> int:
    args = sys.argv[1:]
    uninstall = "--uninstall" in args
    install_dir = default_install_dir()
    if "--target" in args:
        install_dir = Path(args[args.index("--target") + 1]).resolve()
    register = install_dir == default_install_dir()

    if sys.platform != "win32":
        print("HomingPigeon Setup is for Windows. On a Mac or Linux, use the Start file in the source download.")
        return 1

    frozen = getattr(sys, "frozen", False)
    if frozen:
        # PyInstaller points DLL lookups at its temp folder; child processes (the private
        # Python) must not inherit that, or they can load the wrong DLLs.
        ctypes.windll.kernel32.SetDllDirectoryW(None)

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # crisp text on high-DPI screens
    except (AttributeError, OSError):
        pass

    window = SetupWindow(uninstall, install_dir, register, confirmed="--confirmed" in args,
                         delete_data="--delete-data" in args)
    window.run()

    if uninstall and window.uninstalled and install_dir.exists():
        os.chdir(tempfile.gettempdir())
        remove_folder_after_exit(install_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
