"""The concrete background jobs, one per slow thing the app does.

Each is a thin wrapper: the real work stays in ``app.core``, untouched. All this
layer does is get it off the UI thread and report back by signal.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from app import config
from app.core import (composer, db, dns_tools, exporter, imap_sync, importer, merge, scorer,
                      sender, tls)
from app.workers.base import Task, Worker


# --- Email account ----------------------------------------------------------
def test_smtp(settings: sender.SmtpSettings) -> tuple[bool, str]:
    return sender.test_connection(settings)


def test_imap(settings: imap_sync.ImapSettings) -> tuple[bool, str]:
    return imap_sync.test_connection(settings)


def sync_inbox(settings: imap_sync.ImapSettings) -> imap_sync.SyncResult:
    return imap_sync.sync(settings)


# --- DNS --------------------------------------------------------------------
def dns_report(domain: str, smtp_host: str, selectors: list[str]) -> list[dns_tools.CheckResult]:
    return dns_tools.full_report(domain, smtp_host, selectors)


def generate_dkim(selector: str, domain: str) -> dict:
    return dns_tools.generate_dkim_keypair(selector, domain)


# --- Spreadsheets -----------------------------------------------------------
def read_sheet_names(path: Path) -> list[str]:
    return importer.list_sheets(path)


def read_preview(path: Path, sheet: str | None):
    """Load a sheet and detect its columns. Both are slow on a large workbook."""
    frame = importer.read_sheet(path, sheet)
    return frame, importer.detect_columns(frame)


class ImportWorker(Worker):
    """Import a prepared DataFrame, optionally checking every domain's MX record."""

    def __init__(self, dataframe, mapping: importer.ColumnMapping, source_file: str,
                 check_mx: bool):
        super().__init__()
        self.dataframe = dataframe
        self.mapping = mapping
        self.source_file = source_file
        self.check_mx = check_mx

    def work(self) -> importer.ImportResult:
        def progress(done: int, total: int) -> None:
            self.report(done, total, f"Checked {done:,} of {total:,} rows")

        return importer.import_dataframe(
            self.dataframe, self.mapping, source_file=self.source_file,
            check_mx=self.check_mx, progress=progress)


def export_contacts(path: str | Path) -> Path:
    return exporter.export_campaign(None, path)


def import_suppression(path: str | Path) -> int:
    return exporter.import_suppression(path)


def export_suppression(path: str | Path | None = None) -> Path:
    return exporter.export_suppression(path)


# --- Content scoring --------------------------------------------------------
def score_content(content: composer.Content, sender_email: str, reply_to: str,
                  known_tags: list[str], dns_results) -> scorer.ScoreReport:
    return scorer.score(content, sender_email=sender_email, reply_to=reply_to,
                        known_tags=known_tags, dns_results=dns_results)


def build_preview(identity: composer.SenderIdentity, context: dict, content: composer.Content,
                  index: int) -> tuple[str, str, str]:
    return composer.preview_message(identity, context, content, subject_index=index,
                                    body_index=index, seed=index)


# --- Updates ----------------------------------------------------------------
def latest_release() -> tuple[str, str] | None:
    api = config.REPO_URL.replace("https://github.com/", "https://api.github.com/repos/")
    try:
        request = urllib.request.Request(
            f"{api}/releases/latest",
            headers={"User-Agent": config.APP_NAME, "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(request, timeout=15, context=tls.secure_context()) as reply:
            release = json.loads(reply.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - offline, rate limited, no releases yet
        return None
    return release.get("tag_name", ""), release.get("html_url", "")


# --- Sending ----------------------------------------------------------------
class SendPump(QThread):
    """Bridges the send worker's event queue onto Qt signals.

    ``app.core.sender.SendWorker`` is a plain ``threading.Thread`` writing into a
    ``queue.Queue``, and it stays exactly that — the sending logic is not touched
    by this migration. This thread blocks on that queue and re-emits each event
    as a signal, so the UI never polls and never blocks.
    """

    event = pyqtSignal(object)
    stopped = pyqtSignal()

    def __init__(self, worker: sender.SendWorker, events, parent: QObject | None = None):
        super().__init__(parent)
        self.worker = worker
        self.events = events
        self._running = True

    def run(self) -> None:
        import queue as queue_module

        while self._running:
            try:
                item = self.events.get(timeout=0.25)
            except queue_module.Empty:
                if not self.worker.is_alive() and self.events.empty():
                    break
                continue
            self.event.emit(item)
            if getattr(item, "type", None) == sender.EventType.DONE:
                break
        self.stopped.emit()

    def stop(self) -> None:
        self._running = False


__all__ = [
    "Task", "Worker", "ImportWorker", "SendPump",
    "test_smtp", "test_imap", "sync_inbox", "dns_report", "generate_dkim",
    "read_sheet_names", "read_preview", "export_contacts", "import_suppression",
    "export_suppression", "score_content", "build_preview", "latest_release",
    "composer", "db", "merge", "Any",
]
