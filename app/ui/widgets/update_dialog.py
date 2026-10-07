"""The "a new version is available" popup, and the download that follows "Update now"."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QTextBrowser, QVBoxLayout, QWidget

from app import config
from app.i18n import t
from app.services import updater
from app.ui import theme
from app.ui.widgets.common import (ProgressRow, confirm_button, open_url, secondary_button,
                                   set_tone)
from app.workers import jobs


def _mb(count: int) -> str:
    return f"{count / 1_048_576:.1f} MB"


class UpdateDialog(QDialog):
    def __init__(self, window: QWidget, release: updater.Release):
        super().__init__(window)
        self.window_ = window
        self.release = release
        self.automatic = updater.can_update_itself(release)
        self.worker: jobs.UpdateDownloadWorker | None = None

        scale = theme.text_scale()
        self.setWindowTitle(t("Update available"))
        self.setModal(True)
        self.setMinimumWidth(round(520 * scale))

        pad = round(22 * scale)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(pad, pad, pad, pad)
        layout.setSpacing(round(12 * scale))

        heading = QLabel(t("A new version of HomingPigeon is available"))
        heading.setProperty("role", "subheading")
        heading.setWordWrap(True)
        layout.addWidget(heading)

        if self.automatic:
            how = ("Updating takes a minute or two. HomingPigeon closes, installs the new "
                   "version and opens again by itself. Your contacts, templates and settings "
                   "are kept.")
        else:
            how = ("Update now opens the download page. Your contacts, templates and settings "
                   "are kept when you install the new version.")
        self.message = QLabel(t("Version {tag} is ready. You have {app_version}.\n\n{how}",
                                tag=release.tag, app_version=config.APP_VERSION, how=how))
        self.message.setWordWrap(True)
        layout.addWidget(self.message)

        if release.notes.strip():
            label = QLabel(t("What's new"))
            label.setProperty("role", "field")
            layout.addWidget(label)
            notes = QTextBrowser()
            notes.setOpenExternalLinks(True)
            notes.setMarkdown(release.notes)
            notes.setMaximumHeight(round(220 * scale))
            layout.addWidget(notes)

        self.progress = ProgressRow()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        self.status = QLabel("")
        self.status.setProperty("role", "muted")
        self.status.setWordWrap(True)
        self.status.setVisible(False)
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.later_button = secondary_button("Update later", self._later, width=140)
        self.now_button = confirm_button("Update now", self._update_now, width=150)
        buttons.addWidget(self.later_button)
        buttons.addWidget(self.now_button)
        layout.addLayout(buttons)
        self.now_button.setDefault(True)
        self.now_button.setFocus()

    # --- choices ------------------------------------------------------------
    def _later(self) -> None:
        self.reject()

    def reject(self) -> None:  # Escape and the window's X behave like "Update later"
        if self.worker is not None:
            self.worker.cancel()
            self.worker = None
        super().reject()

    def _update_now(self) -> None:
        if not self.automatic:
            open_url(self.release.page_url)
            self.accept()
            return
        if self.window_.is_sending():
            self._say("A campaign is sending right now. Stop it, or wait for it to finish, "
                      "then choose Update now again.", "warning")
            return

        self.now_button.setEnabled(False)
        self.later_button.setText(t("Cancel"))
        self.progress.setVisible(True)
        self.progress.set_busy()
        self._say("Downloading the update...")

        self.worker = jobs.UpdateDownloadWorker(self.release)
        self.worker.signals.progress.connect(self._on_progress)
        self.worker.signals.finished.connect(self._on_downloaded)
        self.worker.signals.failed.connect(self._on_failed)
        self.worker.start()

    # --- download -----------------------------------------------------------
    def _on_progress(self, received: int, total: int, _detail: str) -> None:
        self.progress.set_progress(received, total)
        if total:
            self._say(t("Downloading the update: {mb} of {mb2}", mb=_mb(received), mb2=_mb(total)))

    def _on_downloaded(self, staged: Path) -> None:
        if self.worker is None:
            return  # cancelled
        self.worker = None
        self._say("Installing. HomingPigeon will close now and open again in a minute or two.")
        try:
            updater.start_install(staged)
        except OSError as error:
            self._on_failed(str(error))
            return
        self.accept()
        self.window_.quit_app()   # the installer waits for the app to close

    def _on_failed(self, message: str) -> None:
        self.worker = None
        self.progress.setVisible(False)
        self.now_button.setEnabled(True)
        self.now_button.setText(t("Try again"))
        self.later_button.setText(t("Update later"))
        self._say(t("The update didn't download: {message}. Check your internet connection and "
                    "try again, or choose Update later.", message=message), "error")

    def _say(self, text: str, tone: str | None = None) -> None:
        self.status.setText(t(text))
        self.status.setVisible(True)
        set_tone(self.status, tone)

    @classmethod
    def offer(cls, window: QWidget, release: updater.Release) -> None:
        cls(window, release).exec()
