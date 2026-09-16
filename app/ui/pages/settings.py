"""Settings: appearance, readability, date and time, data, updates and uninstalling.

Every appearance control here is deliberately instant. Theme, contrast and bold
text re-render one stylesheet string; only text size, which changes widget
metrics rather than colours, rebuilds the pages that are already open.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import QFileDialog, QPushButton, QVBoxLayout, QWidget

from app import config
from app.core import credentials, db, prefs, shortcut
from app.services import maintenance
from app.ui import theme
from app.ui.pages.base import Page
from app.ui.widgets.common import (Card, ChoiceButtons, Section, confirm_button, danger_button,
                                   muted, open_url, primary_button, row, secondary_button,
                                   separator, set_tone, subheading)
from app.ui.widgets.dialogs import ChoiceDialog, ConfirmDialog
from app.ui.widgets.inputs import checkbox
from app.workers import jobs
from app.workers.base import Task

EXAMPLE_DATE = datetime(2026, 12, 31, 17, 30)  # unambiguous: day 31, month 12, 5:30 PM


class SettingsPage(Page):
    def __init__(self, window):
        super().__init__(window)
        self.add_header(
            "Settings",
            "Make HomingPigeon comfortable to use. Changes apply straight away and are "
            "remembered next time.")
        area = self.scroll_body()
        area.add(self._appearance_section())
        area.add(self._datetime_section())
        area.add(self._startup_section())
        area.add(self._data_section())
        area.add(self._updates_section())
        area.add(self._uninstall_card())
        area.add_stretch()

    # --- layout helpers -----------------------------------------------------
    @staticmethod
    def _setting(section: Section, title: str, description: str = "",
                 first: bool = False) -> QWidget:
        """A titled block inside a section; returns the widget the control goes in."""
        if not first:
            section.add(separator())
        heading = subheading(title)
        section.add(heading)
        if description:
            section.add(muted(description))
        control = QWidget()
        control.setProperty("role", "plain")
        layout = QVBoxLayout(control)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(8)
        section.add(control)
        return control

    @staticmethod
    def _put(control: QWidget, widget: QWidget) -> QWidget:
        """A lone button would stretch across the card, so it is left-aligned."""
        if isinstance(widget, QPushButton):
            control.layout().addWidget(row(widget, None))
        else:
            control.layout().addWidget(widget)
        return widget

    # --- appearance ---------------------------------------------------------
    def _appearance_section(self) -> Section:
        section = Section("Appearance and reading")

        control = self._setting(section, "Theme",
                                "Dark is easy on the eyes; Light suits bright rooms.", first=True)
        self._put(control, ChoiceButtons(prefs.THEMES, prefs.get("appearance"),
                                         on_change=self.window_.change_appearance))

        control = self._setting(section, "Text size",
                                "Makes everything in the app bigger: text, buttons and boxes.")
        self._put(control, ChoiceButtons(
            [(key, label) for key, label, _scale in prefs.TEXT_SIZES],
            prefs.get("text_size"), on_change=self.window_.change_text_size))

        control = self._setting(
            section, "Easier to read",
            "High contrast uses stronger colours for text and borders. Bold text makes all "
            "writing heavier.")
        self.contrast_box = checkbox("High contrast", bool(prefs.get("high_contrast")),
                                     on_change=self.window_.change_contrast)
        self._put(control, self.contrast_box)
        self._put(control, checkbox("Bold text", bool(prefs.get("bold_text")),
                                    on_change=self.window_.change_bold_text))

        control = self._setting(
            section, "Start over",
            "Put the theme, text size and reading options back to how they were when you "
            "installed the app.")
        self._put(control, secondary_button("Reset appearance settings",
                                            self._reset_appearance, 230))
        return section

    def _reset_appearance(self) -> None:
        for key in ("appearance", "text_size", "high_contrast", "bold_text"):
            db.set_setting(key, prefs.DEFAULTS[key])
        theme.set_appearance(prefs.DEFAULTS["appearance"])
        theme.set_high_contrast(False)
        theme.set_bold_text(False)
        self.window_.change_text_size(prefs.DEFAULTS["text_size"])
        self.notify("Appearance settings reset.", "success")

    # --- date and time ------------------------------------------------------
    def _datetime_section(self) -> Section:
        section = Section("Date and time")

        control = self._setting(section, "Date format", "How dates are shown across the app.",
                                first=True)
        options = [(key, prefs.format_date(EXAMPLE_DATE, key)) for key in prefs.DATE_FORMATS]
        self._put(control, ChoiceButtons(
            options, prefs.get("date_format"),
            on_change=lambda key: self._change_format("date_format", key)))

        control = self._setting(section, "Time format")
        options = [(key, f"{prefs.format_time(EXAMPLE_DATE, key=key)}  ({label})")
                   for key, label in prefs.TIME_FORMATS.items()]
        self._put(control, ChoiceButtons(
            options, prefs.get("time_format"),
            on_change=lambda key: self._change_format("time_format", key)))

        self.clock_preview = muted("")
        section.add(self.clock_preview)
        self._update_clock_preview()
        return section

    def _update_clock_preview(self) -> None:
        now = datetime.now()
        self.clock_preview.setText(
            f"Right now it's {now:%A}, {prefs.format_datetime(now)}")

    def _change_format(self, key: str, value: str) -> None:
        db.set_setting(key, value)
        self._update_clock_preview()
        # Pages read the format when they refresh; the visible one is refreshed now
        current = self.window_.current
        if current and current != "settings":
            page = self.window_.page(current)
            if page is not None and hasattr(page, "on_show"):
                page.on_show()

    # --- startup ------------------------------------------------------------
    def _startup_section(self) -> Section:
        section = Section("When the app opens")
        control = self._setting(section, "First page to show", first=True)
        self._put(control, ChoiceButtons(
            prefs.START_PAGES, prefs.get("start_page"),
            on_change=lambda key: db.set_setting("start_page", key)))
        return section

    # --- data ---------------------------------------------------------------
    def _data_section(self) -> Section:
        section = Section("Your information")

        control = self._setting(
            section, "Where it's kept",
            f"Contacts, templates, settings and campaign history are stored only on this "
            f"computer, in {config.DATA_DIR}", first=True)
        self._put(control, secondary_button(
            "Open that folder", lambda: shortcut.open_folder(config.DATA_DIR), 180))

        control = self._setting(
            section, "Backups",
            "Save a copy of everything to a file you choose. A USB stick or cloud folder is "
            "ideal. Email passwords aren't included in backups; you type them in again after "
            "restoring.")
        self._put(control, row(
            primary_button("Back up my information...", self._backup, 230),
            secondary_button("Restore from a backup...", self._restore, 215), None))

        control = self._setting(
            section, "Saved passwords",
            f"Your email passwords are stored encrypted ({credentials.backend_name()}). Remove "
            f"them if you're giving this computer to someone else.")
        self._put(control, danger_button("Forget saved passwords", self._forget_passwords, 220))
        return section

    def _backup(self) -> None:
        target, _filter = QFileDialog.getSaveFileName(
            self, "Save a backup of HomingPigeon", maintenance.default_backup_name(),
            "HomingPigeon backup (*.hpbackup)")
        if not target:
            return
        Task(maintenance.write_backup, target).start(
            on_result=lambda path: self.notify(f"Backup saved: {Path(path).name}", "success", 6000),
            on_error=lambda message: self.notify(
                f"The backup couldn't be saved: {message}", "error", 7000))

    def _restore(self) -> None:
        if self.window_.is_sending():
            self.notify("Stop sending before restoring a backup.", "warn")
            return
        source, _filter = QFileDialog.getOpenFileName(
            self, "Choose a HomingPigeon backup", "",
            "HomingPigeon backup (*.hpbackup);;All files (*.*)")
        if not source:
            return
        if not maintenance.is_backup(source):
            self.notify("That file isn't a HomingPigeon backup.", "error", 6000)
            return
        if not ConfirmDialog.ask(
            self, "Restore this backup?",
            "Everything in the app will be replaced with the contents of the backup. A copy of "
            "your current information is saved first, just in case.\n\nHomingPigeon will close "
            "and open again.", confirm_text="Restore", danger=True,
        ):
            return
        try:
            maintenance.restore_backup(source)
        except Exception as error:  # noqa: BLE001 - always tell the user
            self.notify(f"The backup couldn't be restored: {error}", "error", 7000)
            return
        maintenance.restart()
        self.window_.quit_app()

    def _forget_passwords(self) -> None:
        if ConfirmDialog.ask(
            self, "Forget saved passwords?",
            "Your email account settings stay, but you'll need to type your passwords again "
            "before sending or checking replies.", confirm_text="Forget them", danger=True,
        ):
            credentials.clear_all()
            self.notify("Saved passwords removed.", "success")

    # --- updates and help ---------------------------------------------------
    def _updates_section(self) -> Section:
        section = Section("Updates and help")

        control = self._setting(section, "Version",
                                f"You're using HomingPigeon {config.APP_VERSION}.", first=True)
        self.update_button = primary_button("Check for updates", self._check_updates, 190)
        self.update_status = muted("", wrap=False)
        self._put(control, row(self.update_button, self.update_status, None))
        self.download_button = confirm_button("Download the new version", None, 250)
        self.download_button.setVisible(False)
        self._put(control, self.download_button)

        control = self._setting(section, "Need a hand?")
        self._put(control, row(
            secondary_button("Open the setup guide", lambda: self.go("guide"), 200),
            secondary_button("Report a problem or suggest an idea",
                             lambda: open_url(f"{config.REPO_URL}/issues/new"), 300), None))
        return section

    def _check_updates(self) -> None:
        self.update_button.setEnabled(False)
        self.update_button.setText("Checking...")
        self.update_status.setText("")
        self.download_button.setVisible(False)

        Task(jobs.latest_release).start(on_result=self._show_update)

    def _show_update(self, result) -> None:
        self.update_button.setEnabled(True)
        self.update_button.setText("Check for updates")
        if result is None:
            self.update_status.setText(
                "Couldn't check right now. Are you connected to the internet?")
            set_tone(self.update_status, "warning")
            return
        tag, url = result
        if maintenance.is_newer(tag, config.APP_VERSION):
            self.update_status.setText(f"Version {tag} is available!")
            set_tone(self.update_status, "success")
            try:
                self.download_button.clicked.disconnect()
            except TypeError:
                pass
            self.download_button.clicked.connect(
                lambda _checked=False: open_url(url or f"{config.REPO_URL}/releases"))
            self.download_button.setVisible(True)
        else:
            self.update_status.setText("You have the latest version.")
            set_tone(self.update_status, "success")

    # --- uninstall ----------------------------------------------------------
    def _uninstall_card(self) -> Card:
        card = Card(kind="danger-card", padding=18)
        title = subheading("Uninstall HomingPigeon")
        set_tone(title, "error")
        card.add(title)

        if sys.platform == "win32" and shortcut.is_installed():
            card.add(muted(
                "Removes HomingPigeon, its shortcuts and its private copy of Python from this "
                "computer. You'll be asked whether to keep your contacts, templates and settings."))
            card.add(row(danger_button("Uninstall HomingPigeon...", self._uninstall, 250), None))
        else:
            card.add(muted(
                f"This copy wasn't installed with HomingPigeon Setup, so there's nothing to "
                f"uninstall. To remove it, close the app and delete its folder: "
                f"{shortcut.app_location()}\n\nYour saved information is kept separately; you "
                f"can delete it here."))
            card.add(row(
                secondary_button("Open the app's folder",
                                 lambda: shortcut.open_folder(shortcut.app_location()), 200),
                danger_button("Delete my saved information...", self._delete_data_only, 270),
                None))
        return card

    def _uninstall(self) -> None:
        if self.window_.is_sending():
            self.notify("Stop sending before uninstalling.", "warn")
            return
        choice = ChoiceDialog.ask(
            self, "Uninstall HomingPigeon?",
            "HomingPigeon, its shortcuts and its private copy of Python will be removed.\n\n"
            "What should happen to your saved information: contacts, templates, settings "
            "and campaign history?",
            [("keep", "Uninstall, and keep my information", "primary"),
             ("delete", "Uninstall, and delete my information too", "danger"),
             ("cancel", "Cancel", "secondary")])
        if choice not in ("keep", "delete"):
            return
        if choice == "delete" and not ConfirmDialog.ask(
            self, "Delete your information for good?",
            "Your contacts, templates, settings and campaign history will be permanently "
            "deleted. This can't be undone.\n\nTip: cancel and use \"Back up my information\" "
            "first if you might want it later.",
            confirm_text="Delete and uninstall", danger=True,
        ):
            return

        try:
            maintenance.start_uninstaller(delete_data=choice == "delete")
        except OSError as error:
            self.notify(f"The uninstaller couldn't start: {error}. Use Settings > Apps in "
                        f"Windows instead.", "error", 8000)
            return
        self.window_.quit_app()  # the uninstaller waits for the app to close

    def _delete_data_only(self) -> None:
        if self.window_.is_sending():
            self.notify("Stop sending first.", "warn")
            return
        if not ConfirmDialog.ask(
            self, "Delete your saved information?",
            "Your contacts, templates, settings, campaign history and saved passwords will be "
            "permanently deleted, and HomingPigeon will close. This can't be undone.",
            confirm_text="Delete everything", danger=True,
        ):
            return
        db.close()
        maintenance.delete_all_data()

    def on_show(self) -> None:
        self._update_clock_preview()
