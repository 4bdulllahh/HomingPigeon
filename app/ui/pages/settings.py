"""Settings: appearance, readability, date and time, data, updates and uninstalling.

Every appearance control here is deliberately instant. Theme, contrast and bold
text re-render one stylesheet string; only text size, which changes widget
metrics rather than colours, rebuilds the pages that are already open.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from PyQt6 import sip
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (QAbstractItemView, QFileDialog, QListWidget, QListWidgetItem,
                             QPushButton, QVBoxLayout, QWidget)

from app import config
from app.core import credentials, db, prefs, shortcut, themes
from app.i18n import t
from app.services import maintenance
from app.ui import scrolling, theme
from app.ui.pages.base import Page
from app.ui.widgets.common import (Card, ChoiceButtons, Section, confirm_button, danger_button,
                                   muted, open_url, primary_button, row, secondary_button,
                                   separator, set_tone, subheading, wrap_row)
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
        area.add(self._language_section())
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

    # --- language -----------------------------------------------------------
    def _language_section(self) -> Section:
        """Each language is shown in its own words, so anyone can find theirs."""
        from app import i18n

        section = Section("Language")
        control = self._setting(
            section, "Language of the app",
            "Changes every page, button and message straight away. Arabic also turns the "
            "layout to read from right to left. The examples on My message and the unsubscribe "
            "line in your emails follow this choice too.", first=True)
        options = [(code, native) for code, native, _english in i18n.LANGUAGES]
        self._put(control, ChoiceButtons(options, i18n.language(),
                                         on_change=self.window_.change_language))
        return section

    # --- appearance ---------------------------------------------------------
    def _appearance_section(self) -> Section:
        section = Section("Appearance and reading")

        control = self._setting(
            section, "Theme",
            "Pick a ready-made theme, or make your own with your colours, a gradient and a font.",
            first=True)
        self.theme_holder = QWidget()
        self.theme_holder.setProperty("role", "plain")
        QVBoxLayout(self.theme_holder).setContentsMargins(0, 0, 0, 0)
        self._put(control, self.theme_holder)
        self.edit_theme_button = secondary_button("Change this theme...", self._edit_theme)
        self.delete_theme_button = danger_button("Delete this theme", self._delete_theme)
        self.share_theme_button = secondary_button("Save theme to a file...", self._share_theme)
        self.share_theme_button.setToolTip(t("Give your theme to someone else"))
        self._put(control, wrap_row(
            primary_button("Make my own theme...", self._new_theme),
            self.edit_theme_button, self.delete_theme_button, self.share_theme_button,
            secondary_button("Load a theme from a file...", self._load_theme)))
        self._fill_themes()

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
            section, "Smooth scrolling",
            "Pages glide when you turn the mouse wheel instead of jumping. Switch it off if "
            "scrolling feels slow on your computer.")
        self.smooth_box = checkbox("Smooth scrolling", bool(prefs.get("smooth_scroll")),
                                   on_change=self._smooth_changed)
        self._put(control, self.smooth_box)

        control = self._setting(
            section, "Menu on the left",
            "Drag the pages into the order you like. Untick a page you never use to hide it. "
            "Home is always shown.")
        self.menu_list = QListWidget()
        self.menu_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.menu_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.menu_list.setMaximumWidth(round(420 * theme.text_scale()))
        self._fill_menu_list()
        self.menu_list.model().rowsMoved.connect(lambda *_args: self._menu_changed())
        self.menu_list.itemChanged.connect(lambda _item: self._menu_changed())
        self._put(control, self.menu_list)
        self._put(control, secondary_button("Put the menu back the way it was",
                                            self._reset_menu))

        control = self._setting(
            section, "Start over",
            "Put the theme, text size, reading options and menu back to how they were when "
            "you installed the app. Themes you made are kept.")
        self._put(control, secondary_button("Reset appearance settings",
                                            self._reset_appearance, 230))
        return section

    # --- themes -------------------------------------------------------------
    def _fill_themes(self) -> None:
        layout = self.theme_holder.layout()
        while layout.count():
            layout.takeAt(0).widget().deleteLater()
        options = list(prefs.THEMES) + [(key, spec["name"]) for key, spec in themes.PRESETS.items()]
        options += [(themes.custom_key(spec["name"]), spec["name"])
                    for spec in themes.custom_themes()]
        self.theme_choice = ChoiceButtons(options, prefs.get("appearance"),
                                          on_change=self._choose_theme)
        layout.addWidget(self.theme_choice)
        self._paint_theme_buttons()

    def _paint_theme_buttons(self) -> None:
        mine = str(prefs.get("appearance")).startswith(themes.CUSTOM_PREFIX)
        self.edit_theme_button.setEnabled(mine)
        self.delete_theme_button.setEnabled(mine)
        self.share_theme_button.setEnabled(themes.find(prefs.get("appearance")) is not None)

    def _choose_theme(self, key: str) -> None:
        self.window_.change_appearance(key)
        if not sip.isdeleted(self):
            self._paint_theme_buttons()

    def _new_theme(self) -> None:
        from app.ui.widgets.theme_editor import ThemeEditor

        ThemeEditor(self.window_, on_saved=lambda _key: self._fill_themes()).exec()

    def _edit_theme(self) -> None:
        from app.ui.widgets.theme_editor import ThemeEditor

        spec = themes.find(prefs.get("appearance"))
        if spec is not None:
            ThemeEditor(self.window_, spec, on_saved=lambda _key: self._fill_themes()).exec()

    def _delete_theme(self) -> None:
        spec = themes.find(prefs.get("appearance"))
        if spec is None or not ConfirmDialog.ask(
                self, "Delete this theme?",
                t("Delete {name}? The app goes back to the Dark theme.", name=spec["name"]),
                "Delete", danger=True):
            return
        themes.delete_custom(spec["name"])
        db.set_setting("appearance", "Dark")
        self._fill_themes()
        self._choose_theme("Dark")

    def _share_theme(self) -> None:
        spec = themes.find(prefs.get("appearance"))
        if spec is None:
            return
        path, _filter = QFileDialog.getSaveFileName(
            self, t("Save theme to a file"), t(spec["name"]) + themes.FILE_SUFFIX,
            t("HomingPigeon theme (*.hptheme)"))
        if not path:
            return
        try:
            saved = themes.write_file(path, dict(spec, name=t(spec["name"])))
        except (OSError, ValueError) as error:
            self.notify(t("Could not save the theme: {message}", message=error), "error", 8000)
            return
        self.notify(t("Saved {name}. Anyone with HomingPigeon can load it in Settings.",
                      name=saved.name), "success", 8000)

    def _load_theme(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, t("Load a theme from a file"), "",
            t("HomingPigeon theme (*.hptheme);;All files (*.*)"))
        if not path:
            return
        try:
            spec = themes.read_file(path)
        except OSError as error:
            self.notify(t("Could not open the file: {message}", message=error), "error", 8000)
            return
        except ValueError as error:
            self.notify(str(error), "error", 8000)
            return
        if any(mine["name"].casefold() == spec["name"].casefold()
               for mine in themes.custom_themes()) and not ConfirmDialog.ask(
                self, "Replace the theme?",
                t("You already have a theme called {name}. Replace it?", name=spec["name"]),
                "Replace"):
            return
        themes.save_custom(spec)
        key = themes.custom_key(spec["name"])
        db.set_setting("appearance", key)
        self._fill_themes()
        window = self.window_
        self._choose_theme(key)
        window.notify(t("Theme {name} added and switched on.", name=spec["name"]),
                      "success", 6000)

    # --- menu order ---------------------------------------------------------
    def _fill_menu_list(self) -> None:
        from app.ui.main_window import NAV_ITEMS

        items = {item[0]: item for item in NAV_ITEMS}
        hidden = prefs.hidden_pages()
        blocked = self.menu_list.blockSignals(True)
        self.menu_list.clear()
        for key in prefs.ordered(list(items), prefs.get("nav_order")):
            _key, icon_name, label, _subtitle = items[key]
            entry = QListWidgetItem(QIcon(theme.icon_pixmap(theme.icon(icon_name), theme.px(18))),
                                    t(label))
            entry.setData(Qt.ItemDataRole.UserRole, key)
            flags = (entry.flags() | Qt.ItemFlag.ItemIsDragEnabled) & ~Qt.ItemFlag.ItemIsDropEnabled
            if key in prefs.ALWAYS_SHOWN:
                flags &= ~Qt.ItemFlag.ItemIsUserCheckable
            else:
                flags |= Qt.ItemFlag.ItemIsUserCheckable
                entry.setCheckState(Qt.CheckState.Unchecked if key in hidden
                                    else Qt.CheckState.Checked)
            entry.setFlags(flags)
            self.menu_list.addItem(entry)
        self.menu_list.setFixedHeight(
            self.menu_list.sizeHintForRow(0) * self.menu_list.count()
            + 2 * self.menu_list.frameWidth() + 4)
        self.menu_list.blockSignals(blocked)

    def _menu_changed(self) -> None:
        order, hidden = [], []
        for index in range(self.menu_list.count()):
            entry = self.menu_list.item(index)
            key = entry.data(Qt.ItemDataRole.UserRole)
            order.append(key)
            if key not in prefs.ALWAYS_SHOWN and entry.checkState() == Qt.CheckState.Unchecked:
                hidden.append(key)
        db.set_setting("nav_order", order)
        db.set_setting("nav_hidden", hidden)
        self.window_.apply_nav_order()

    def _reset_menu(self) -> None:
        db.set_setting("nav_order", [])
        db.set_setting("nav_hidden", [])
        self._fill_menu_list()
        self.window_.apply_nav_order()
        self.notify("The menu is back in its original order.", "success")

    @staticmethod
    def _smooth_changed(on: bool) -> None:
        db.set_setting("smooth_scroll", bool(on))
        scrolling.set_smooth(bool(on))

    def _reset_appearance(self) -> None:
        for key in ("appearance", "text_size", "high_contrast", "bold_text", "smooth_scroll",
                    "nav_order", "nav_hidden"):
            db.set_setting(key, prefs.DEFAULTS[key])
        scrolling.set_smooth(prefs.DEFAULTS["smooth_scroll"])
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
            t("Right now it's {now:%A}, {datetime}", now=now, datetime=prefs.format_datetime(now)))

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
            t("Contacts, templates, settings and campaign history are stored only on this "
              "computer, in {data_dir}", data_dir=config.DATA_DIR), first=True)
        self._put(control, secondary_button(
            "Open that folder", lambda: shortcut.open_folder(config.DATA_DIR), 180))

        control = self._setting(
            section, "Backups",
            "Save a copy of everything to a file you choose. A USB stick or cloud folder is "
            "ideal. Email passwords aren't included in backups; you type them in again after "
            "restoring.")
        self._put(control, wrap_row(
            primary_button("Back up my information...", self._backup, 230),
            secondary_button("Restore from a backup...", self._restore, 215)))

        control = self._setting(
            section, "Saved passwords",
            t("Your email passwords are stored encrypted ({backend_name}). Remove them if "
              "you're giving this computer to someone else.",
              backend_name=credentials.backend_name()))
        self._put(control, danger_button("Forget saved passwords", self._forget_passwords, 220))
        return section

    def _backup(self) -> None:
        target, _filter = QFileDialog.getSaveFileName(
            self, t("Save a backup of HomingPigeon"), maintenance.default_backup_name(),
            t("HomingPigeon backup (*.hpbackup)"))
        if not target:
            return
        Task(maintenance.write_backup, target).start(
            on_result=lambda path: self.notify(t("Backup saved: {name}",
                                                 name=Path(path).name), "success", 6000),
            on_error=lambda message: self.notify(
                t("The backup couldn't be saved: {message}", message=message), "error", 7000))

    def _restore(self) -> None:
        if self.window_.is_sending():
            self.notify("Stop sending before restoring a backup.", "warn")
            return
        source, _filter = QFileDialog.getOpenFileName(
            self, t("Choose a HomingPigeon backup"), "",
            t("HomingPigeon backup (*.hpbackup);;All files (*.*)"))
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
            self.notify(t("The backup couldn't be restored: {error}", error=error), "error", 7000)
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
                                t("You're using HomingPigeon {app_version}.",
                                  app_version=config.APP_VERSION), first=True)
        self.update_button = primary_button("Check for updates", self._check_updates, 190)
        self.update_status = muted("", wrap=False)
        self._put(control, wrap_row(self.update_button, self.update_status))
        self.download_button = confirm_button("Update now", None, 200)
        self.download_button.setVisible(False)
        self._put(control, self.download_button)

        control = self._setting(section, "Need a hand?")
        self._put(control, wrap_row(
            secondary_button("Open the setup guide", lambda: self.go("guide"), 200),
            secondary_button("Report a problem or suggest an idea",
                             lambda: open_url(f"{config.REPO_URL}/issues/new"), 300)))
        return section

    def _check_updates(self) -> None:
        self.update_button.setEnabled(False)
        self.update_button.setText(t("Checking..."))
        self.update_status.setText("")
        self.download_button.setVisible(False)

        Task(jobs.latest_release).start(on_result=self._show_update)

    def _show_update(self, result) -> None:
        self.update_button.setEnabled(True)
        self.update_button.setText(t("Check for updates"))
        if result is None:
            self.update_status.setText(
                t("Couldn't check right now. Are you connected to the internet?"))
            set_tone(self.update_status, "warning")
            return
        if maintenance.is_newer(result.tag, config.APP_VERSION):
            self.update_status.setText(t("Version {tag} is available!", tag=result.tag))
            set_tone(self.update_status, "success")
            try:
                self.download_button.clicked.disconnect()
            except TypeError:
                pass
            self.download_button.clicked.connect(
                lambda _checked=False: self.window_.offer_update(result))
            self.download_button.setVisible(True)
        else:
            self.update_status.setText(t("You have the latest version."))
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
            card.add(wrap_row(
                secondary_button("Open the app's folder",
                                 lambda: shortcut.open_folder(shortcut.app_location()), 200),
                danger_button("Delete my saved information...", self._delete_data_only, 270)))
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
            self.notify(t("The uninstaller couldn't start: {error}. Use Settings > Apps in Windows "
                          "instead.", error=error), "error", 8000)
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
