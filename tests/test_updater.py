"""The self-updater: reading GitHub's reply, downloading and unpacking a release,
and the installer's side of the hand-over. Nothing here touches the network."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import zipfile
from pathlib import Path

import pytest

from app import config
from app.services import updater

ROOT = Path(__file__).resolve().parent.parent


def github_reply(**asset) -> dict:
    return {
        "tag_name": "v9.9.9",
        "html_url": "https://github.com/4bdulllahh/HomingPigeon/releases/tag/v9.9.9",
        "body": "## What's new\n* Things",
        "assets": [
            {"name": "notes.txt", "browser_download_url": "https://example.invalid/notes.txt"},
            {"name": "HomingPigeon-v9.9.9.zip",
             "browser_download_url": "https://example.invalid/HomingPigeon-v9.9.9.zip",
             "size": 1234, **asset},
        ],
    }


def release_zip() -> bytes:
    """A miniature release zip: Setup at the top, the app files under files/."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("HomingPigeon Setup.exe", b"MZ")
        bundle.writestr("files/run.py", "print('hi')")
        bundle.writestr("files/installer/setup_app.py", "# installer")
        bundle.writestr("files/app/config.py", 'APP_VERSION = "v9.9.9 beta"')
    return buffer.getvalue()


class FakeReply(io.BytesIO):
    def __init__(self, data: bytes):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


@pytest.fixture
def work_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "WORK_DIR", tmp_path / "update")
    return tmp_path / "update"


def test_release_finds_the_zip_and_its_checksum():
    release = updater.parse_release(github_reply(digest="sha256:ABC123"))
    assert release.tag == "v9.9.9"
    assert release.zip_url.endswith("HomingPigeon-v9.9.9.zip")
    assert release.zip_size == 1234
    assert release.sha256 == "abc123"
    assert "What's new" in release.notes


def test_release_without_its_zip_yet_falls_back_to_the_page():
    data = github_reply()
    data["assets"] = []
    release = updater.parse_release(data)
    assert release.zip_url == ""
    assert not updater.can_update_itself(release)


def test_source_checkouts_are_sent_to_the_download_page():
    # The tests run from the repo, not from an install made by Setup
    assert not updater.can_update_itself()


def test_only_newer_releases_are_offered(monkeypatch, work_dir):
    newer = updater.parse_release(github_reply())
    monkeypatch.setattr(updater, "latest_release", lambda: newer)
    assert updater.available_update() is newer

    same = updater.Release(tag=config.APP_VERSION.split()[0], page_url="")
    monkeypatch.setattr(updater, "latest_release", lambda: same)
    assert updater.available_update() is None

    monkeypatch.setattr(updater, "latest_release", lambda: None)
    assert updater.available_update() is None


def test_download_checks_and_unpacks_only_the_app_files(monkeypatch, work_dir):
    data = release_zip()
    release = updater.parse_release(github_reply(digest="sha256:" + hashlib.sha256(data).hexdigest()))
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *_a, **_k: FakeReply(data))

    seen: list[tuple[int, int]] = []
    staged = updater.download(release, lambda done, total: seen.append((done, total)))

    assert staged == work_dir / "files"
    assert (staged / "installer" / "setup_app.py").exists()
    assert (staged / "run.py").exists()
    assert not (work_dir / "HomingPigeon Setup.exe").exists()
    assert not list(work_dir.glob("*.zip")), "the zip is deleted once unpacked"
    assert seen and seen[-1] == (len(data), len(data))


def test_a_damaged_download_is_refused(monkeypatch, work_dir):
    data = release_zip()
    release = updater.parse_release(github_reply(digest="sha256:" + "0" * 64))
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *_a, **_k: FakeReply(data))
    with pytest.raises(OSError, match="damaged"):
        updater.download(release)
    assert not (work_dir / "files").exists()


def test_cancelling_leaves_nothing_behind(monkeypatch, work_dir):
    data = release_zip()
    release = updater.parse_release(github_reply())
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *_a, **_k: FakeReply(data))
    with pytest.raises(updater.UpdateCancelled):
        updater.download(release, cancelled=lambda: True)
    assert not list(work_dir.iterdir())


def test_a_recent_update_folder_is_left_for_the_running_installer(work_dir):
    work_dir.mkdir()
    (work_dir / updater.STAMP).write_text(str(updater.time.time()), encoding="utf-8")
    updater.cleanup()
    assert work_dir.exists()

    (work_dir / updater.STAMP).write_text("0", encoding="utf-8")
    updater.cleanup()
    assert not work_dir.exists()


# --- the installer's side ---------------------------------------------------
def load_setup():
    path = ROOT / "installer" / "setup_app.py"
    spec = importlib.util.spec_from_file_location("setup_app_updater_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_installer_can_update_without_questions():
    setup = load_setup()
    assert "auto_update" in setup.SetupWindow.__init__.__code__.co_varnames
    assert hasattr(setup.SetupWindow, "start_auto_update")
    assert hasattr(setup.SetupWindow, "finish_auto_update")
    assert "wait_for_app" in setup.InstallJob.__init__.__code__.co_varnames


def test_uninstall_cleanup_never_opens_a_console(monkeypatch):
    """The leftover-folder helper used to run ping in a visible command window."""
    setup = load_setup()
    started: list[tuple[list[str], int]] = []

    def fake_popen(command, creationflags=0, **_kwargs):
        started.append((command, creationflags))

    monkeypatch.setattr(setup.subprocess, "Popen", fake_popen)
    setup.remove_folder_after_exit(Path("C:/Somewhere/HomingPigeon"))

    command, flags = started[0]
    assert "ping" not in " ".join(command).lower()
    assert command[0] == "powershell"
    assert flags & setup.NO_WINDOW == setup.NO_WINDOW
    # DETACHED_PROCESS makes Windows ignore CREATE_NO_WINDOW, which is what showed the console
    assert not flags & getattr(setup.subprocess, "DETACHED_PROCESS", 0x8)


def test_popup_offers_update_now_and_later(monkeypatch):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt6", reason="PyQt6 is not installed")
    from PyQt6.QtWidgets import QApplication, QWidget

    from app.ui.widgets import update_dialog

    app = QApplication.instance() or QApplication([])
    opened: list[str] = []
    monkeypatch.setattr(update_dialog, "open_url", opened.append)

    window = QWidget()
    window.is_sending = lambda: False
    dialog = update_dialog.UpdateDialog(window, updater.parse_release(github_reply()))
    labels = {dialog.now_button.text(), dialog.later_button.text()}
    assert labels == {"Update now", "Update later"}

    # From a source checkout, Update now opens the release page instead
    dialog.now_button.click()
    assert opened == ["https://github.com/4bdulllahh/HomingPigeon/releases/tag/v9.9.9"]
    del app
