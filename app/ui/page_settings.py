"""Settings: appearance, readability, date and time, data, updates, and uninstalling."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import urllib.request
from datetime import datetime
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from app import config, theme
from app.core import credentials, db, prefs, shortcut, tls
from app.ui.widgets.common import (ChoiceButtons, ChoiceDialog, ConfirmDialog, Section, open_url,
                                   toast)

EXAMPLE_DATE = datetime(2026, 12, 31, 17, 30)  # unambiguous: day 31, month 12, 5:30 PM


class SettingsPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self._build()

    # --- layout helpers -----------------------------------------------------
    def _setting(self, parent, title: str, description: str = "", first: bool = False) -> ctk.CTkFrame:
        """A titled block inside a section; returns the frame the control goes in."""
        if not first:
            theme.separator(parent).pack(fill="x", pady=14)
        ctk.CTkLabel(parent, text=title, font=theme.font(14, "bold"), text_color=theme.FG_BRIGHT,
                     anchor="w").pack(anchor="w")
        if description:
            theme.label(parent, description, muted=True, size=12, wrap=True).pack(
                anchor="w", fill="x", pady=(0, 2))
        control = ctk.CTkFrame(parent, fg_color="transparent")
        control.pack(fill="x", pady=(8, 0))
        return control

    def _switch(self, parent, text: str, value: bool, command) -> ctk.CTkSwitch:
        variable = ctk.BooleanVar(value=value)
        widget = theme.switch(parent, text, variable=variable, command=lambda: command(variable.get()),
                              font=theme.font(13, "bold"), switch_width=46, switch_height=24)
        widget.variable = variable
        return widget

    def _build(self) -> None:
        scroll = theme.scroll_frame(self)
        scroll.pack(fill="both", expand=True, padx=theme.PAD_LARGE, pady=theme.PAD)

        theme.heading(scroll, "Settings").pack(anchor="w")
        theme.label(scroll, "Make HomingPigeon comfortable to use. Changes apply straight away and "
                            "are remembered next time.", muted=True, wrap=True).pack(anchor="w",
                                                                                   pady=(2, 16))
        self._build_appearance(scroll)
        self._build_datetime(scroll)
        self._build_startup(scroll)
        self._build_data(scroll)
        self._build_updates(scroll)
        self._build_uninstall(scroll)

    # --- appearance -----------------------------------------------------------
    def _build_appearance(self, parent) -> None:
        section = Section(parent, "Appearance and reading")
        section.pack(fill="x", pady=(0, 14))
        body = section.body

        control = self._setting(body, "Theme", "Dark is easy on the eyes; Light suits bright rooms.",
                                first=True)
        ChoiceButtons(control, prefs.THEMES, prefs.get("appearance"),
                      command=self.app.change_appearance).pack(anchor="w")

        control = self._setting(body, "Text size",
                                "Makes everything in the app bigger — text, buttons and boxes.")
        ChoiceButtons(control, [(key, label) for key, label, _scale in prefs.TEXT_SIZES],
                      prefs.get("text_size"), command=self._change_text_size).pack(anchor="w")

        control = self._setting(body, "Easier to read",
                                "High contrast uses stronger colours for text and borders. "
                                "Bold text makes all writing heavier.")
        self.contrast_switch = self._switch(control, "High contrast", bool(prefs.get("high_contrast")),
                                            self._change_contrast)
        self.contrast_switch.pack(anchor="w", pady=(0, 10))
        self._switch(control, "Bold text", bool(prefs.get("bold_text")), self._change_bold).pack(anchor="w")

        control = self._setting(body, "Start over", "Put the theme, text size and reading options "
                                                    "back to how they were when you installed the app.")
        theme.secondary_button(control, "Reset appearance settings", self._reset_appearance,
                               width=220).pack(anchor="w")

    def _change_text_size(self, key: str) -> None:
        db.set_setting("text_size", key)
        scale = prefs.text_scale()
        if self.app.is_sending():
            theme.set_text_scale(scale)  # applies live; the menu layout updates next time
            return
        self.app.rebuild("settings", before_build=lambda: theme.set_text_scale(scale))

    def _change_contrast(self, enabled: bool) -> None:
        if self.app.is_sending():
            self.contrast_switch.variable.set(not enabled)
            toast(self, "You can change this once sending has finished.", "warn")
            return
        db.set_setting("high_contrast", enabled)
        self.app.rebuild("settings", before_build=lambda: theme.set_high_contrast(enabled))

    def _change_bold(self, enabled: bool) -> None:
        db.set_setting("bold_text", enabled)
        theme.set_bold_text(enabled)

    def _reset_appearance(self) -> None:
        if self.app.is_sending():
            toast(self, "You can change this once sending has finished.", "warn")
            return
        for key in ("appearance", "text_size", "high_contrast", "bold_text"):
            db.set_setting(key, prefs.DEFAULTS[key])

        def apply() -> None:
            theme.apply_appearance(prefs.DEFAULTS["appearance"])
            theme.set_text_scale(prefs.text_scale())
            theme.set_high_contrast(False)
            theme.set_bold_text(False)

        self.app.rebuild("settings", before_build=apply)
        toast(self.app, "Appearance settings reset.", "success")

    # --- date and time --------------------------------------------------------
    def _build_datetime(self, parent) -> None:
        section = Section(parent, "Date and time")
        section.pack(fill="x", pady=(0, 14))
        body = section.body

        control = self._setting(body, "Date format", "How dates are shown across the app.", first=True)
        options = [(key, prefs.format_date(EXAMPLE_DATE, key)) for key in prefs.DATE_FORMATS]
        ChoiceButtons(control, options, prefs.get("date_format"),
                      command=lambda key: self._change_format("date_format", key)).pack(anchor="w")

        control = self._setting(body, "Time format")
        options = [(key, f"{prefs.format_time(EXAMPLE_DATE, key=key)}  ({label})")
                   for key, label in prefs.TIME_FORMATS.items()]
        ChoiceButtons(control, options, prefs.get("time_format"),
                      command=lambda key: self._change_format("time_format", key)).pack(anchor="w")

        self.clock_preview = theme.label(body, "", muted=True, size=12)
        self.clock_preview.pack(anchor="w", pady=(12, 0))
        self._update_clock_preview()

    def _update_clock_preview(self) -> None:
        now = datetime.now()
        self.clock_preview.configure(text=f"Right now it's {now:%A}, {prefs.format_datetime(now)}")

    def _change_format(self, key: str, value: str) -> None:
        db.set_setting(key, value)
        self._update_clock_preview()
        if not self.app.rebuild("settings"):
            return  # sending: pages pick the new format up as they refresh

    # --- startup --------------------------------------------------------------
    def _build_startup(self, parent) -> None:
        section = Section(parent, "When the app opens")
        section.pack(fill="x", pady=(0, 14))
        control = self._setting(section.body, "First page to show", first=True)
        ChoiceButtons(control, prefs.START_PAGES, prefs.get("start_page"),
                      command=lambda key: db.set_setting("start_page", key)).pack(anchor="w")

    # --- data -----------------------------------------------------------------
    def _build_data(self, parent) -> None:
        section = Section(parent, "Your information")
        section.pack(fill="x", pady=(0, 14))
        body = section.body

        control = self._setting(
            body, "Where it's kept",
            f"Contacts, templates, settings and campaign history are stored only on this computer, "
            f"in {config.DATA_DIR}", first=True)
        theme.secondary_button(control, "Open that folder",
                               lambda: shortcut.open_folder(config.DATA_DIR), width=170).pack(anchor="w")

        control = self._setting(
            body, "Backups",
            "Save a copy of everything to a file you choose — a USB stick or cloud folder is "
            "ideal. Email passwords aren't included in backups; you type them in again after "
            "restoring.")
        row = ctk.CTkFrame(control, fg_color="transparent")
        row.pack(anchor="w")
        theme.primary_button(row, "Back up my information…", self._backup, width=210).pack(side="left")
        theme.secondary_button(row, "Restore from a backup…", self._restore, width=200).pack(
            side="left", padx=(8, 0))

        control = self._setting(
            body, "Saved passwords",
            f"Your email passwords are stored encrypted ({credentials.backend_name()}). Remove them "
            f"if you're giving this computer to someone else.")
        theme.danger_button(control, "Forget saved passwords", self._forget_passwords,
                            width=210).pack(anchor="w")

    def _backup(self) -> None:
        target = filedialog.asksaveasfilename(
            parent=self, title="Save a backup of HomingPigeon",
            initialfile=f"HomingPigeon backup {datetime.now():%Y-%m-%d}.hpbackup",
            defaultextension=".hpbackup", filetypes=[("HomingPigeon backup", "*.hpbackup")])
        if not target:
            return
        try:
            destination = sqlite3.connect(target)
            with destination:
                db.connect().backup(destination)
            destination.close()
        except (sqlite3.Error, OSError) as error:
            toast(self, f"The backup couldn't be saved: {error}", "error", 7000)
            return
        toast(self, f"Backup saved: {Path(target).name}", "success", 6000)

    def _restore(self) -> None:
        if self.app.is_sending():
            toast(self, "Stop sending before restoring a backup.", "warn")
            return
        source = filedialog.askopenfilename(
            parent=self, title="Choose a HomingPigeon backup",
            filetypes=[("HomingPigeon backup", "*.hpbackup"), ("All files", "*.*")])
        if not source:
            return
        try:
            backup = sqlite3.connect(f"file:{Path(source).as_posix()}?mode=ro", uri=True)
            backup.execute("SELECT key FROM settings LIMIT 1")
        except sqlite3.Error:
            toast(self, "That file isn't a HomingPigeon backup.", "error", 6000)
            return
        if not ConfirmDialog.ask(
                self, "Restore this backup?",
                "Everything in the app will be replaced with the contents of the backup. A copy of "
                "your current information is saved first, just in case.\n\nHomingPigeon will "
                "close and open again.", confirm_text="Restore", danger=True):
            backup.close()
            return
        try:
            safety = config.DATA_DIR / f"before-restore {datetime.now():%Y-%m-%d %H%M}.hpbackup"
            keep = sqlite3.connect(safety)
            with keep:
                db.connect().backup(keep)
            keep.close()
            with db.connect() as live:
                backup.backup(live)
            backup.close()
        except (sqlite3.Error, OSError) as error:
            toast(self, f"The backup couldn't be restored: {error}", "error", 7000)
            return
        self._restart()

    def _restart(self) -> None:
        flags = [flag for flag, on in (("-E", sys.flags.ignore_environment),
                                       ("-s", sys.flags.no_user_site)) if on]
        subprocess.Popen([sys.executable, *flags, str(shortcut.app_location() / "run.py")],
                         cwd=shortcut.app_location(), close_fds=True)
        self.app.quit_app()

    def _forget_passwords(self) -> None:
        if ConfirmDialog.ask(self, "Forget saved passwords?",
                             "Your email account settings stay, but you'll need to type your "
                             "passwords again before sending or checking replies.",
                             confirm_text="Forget them", danger=True):
            credentials.clear_all()
            toast(self, "Saved passwords removed.", "success")

    # --- updates and help -------------------------------------------------------
    def _build_updates(self, parent) -> None:
        section = Section(parent, "Updates and help")
        section.pack(fill="x", pady=(0, 14))
        body = section.body

        control = self._setting(body, "Version", f"You're using HomingPigeon {config.APP_VERSION}.",
                                first=True)
        row = ctk.CTkFrame(control, fg_color="transparent")
        row.pack(anchor="w", fill="x")
        self.update_button = theme.primary_button(row, "Check for updates", self._check_updates, width=180)
        self.update_button.pack(side="left")
        self.update_status = theme.label(row, "", muted=True, size=12)
        self.update_status.pack(side="left", padx=(12, 0))
        self.download_button = theme.confirm_button(control, "Download the new version", None,
                                                    width=240, height=40)

        control = self._setting(body, "Need a hand?")
        row = ctk.CTkFrame(control, fg_color="transparent")
        row.pack(anchor="w")
        theme.secondary_button(row, "Open the setup guide", lambda: self.app.show("guide"),
                               width=190).pack(side="left")
        theme.secondary_button(row, "Report a problem or suggest an idea",
                               lambda: open_url(f"{config.REPO_URL}/issues/new"), width=290).pack(
            side="left", padx=(8, 0))

    def _check_updates(self) -> None:
        self.update_button.configure(state="disabled", text="Checking…")
        self.update_status.configure(text="")
        self.download_button.pack_forget()

        def work() -> None:
            api = config.REPO_URL.replace("https://github.com/", "https://api.github.com/repos/")
            try:
                request = urllib.request.Request(f"{api}/releases/latest",
                                                 headers={"User-Agent": config.APP_NAME,
                                                          "Accept": "application/vnd.github+json"})
                with urllib.request.urlopen(request, timeout=15, context=tls.secure_context()) as reply:
                    release = json.loads(reply.read().decode("utf-8"))
                result = (release.get("tag_name", ""), release.get("html_url", ""))
            except Exception:  # noqa: BLE001 - offline, rate limited, no releases...
                result = None
            self.after(0, lambda: self._show_update(result))

        threading.Thread(target=work, daemon=True).start()

    def _show_update(self, result) -> None:
        if not self.winfo_exists():
            return
        self.update_button.configure(state="normal", text="Check for updates")
        if result is None:
            self.update_status.configure(text="Couldn't check right now. Are you connected to the "
                                              "internet?", text_color=theme.WARNING)
            return
        tag, url = result
        if _version(tag) > _version(config.APP_VERSION):
            self.update_status.configure(text=f"Version {tag} is available!", text_color=theme.SUCCESS)
            self.download_button.configure(command=lambda: open_url(url or f"{config.REPO_URL}/releases"))
            self.download_button.pack(anchor="w", pady=(10, 0))
        else:
            self.update_status.configure(text="You have the latest version.", text_color=theme.SUCCESS)

    # --- uninstall ------------------------------------------------------------
    def _build_uninstall(self, parent) -> None:
        section = ctk.CTkFrame(parent, fg_color=theme.BG_PANEL, corner_radius=theme.RADIUS_CARD,
                               border_width=1, border_color=theme.ERROR)
        section.pack(fill="x", pady=(10, 24))
        body = ctk.CTkFrame(section, fg_color="transparent")
        body.pack(fill="x", padx=18, pady=16)

        ctk.CTkLabel(body, text="Uninstall HomingPigeon", font=theme.font(15, "bold"),
                     text_color=theme.ERROR, anchor="w").pack(anchor="w")
        if sys.platform == "win32" and shortcut.is_installed():
            theme.label(body, "Removes HomingPigeon, its shortcuts and its private copy of Python "
                              "from this computer. You'll be asked whether to keep your contacts, "
                              "templates and settings.", muted=True, size=12, wrap=True).pack(
                anchor="w", fill="x", pady=(2, 10))
            theme.danger_button(body, "Uninstall HomingPigeon…", self._uninstall, width=230).pack(anchor="w")
        else:
            theme.label(body, f"This copy wasn't installed with HomingPigeon Setup, so there's "
                              f"nothing to uninstall. To remove it, close the app and delete its "
                              f"folder: {shortcut.app_location()}\n\nYour saved information is kept "
                              f"separately; you can delete it here.", muted=True, size=12,
                        wrap=True).pack(anchor="w", fill="x", pady=(2, 10))
            row = ctk.CTkFrame(body, fg_color="transparent")
            row.pack(anchor="w")
            theme.secondary_button(row, "Open the app's folder",
                                   lambda: shortcut.open_folder(shortcut.app_location()),
                                   width=190).pack(side="left")
            theme.danger_button(row, "Delete my saved information…", self._delete_data_only,
                                width=250).pack(side="left", padx=(8, 0))

    def _uninstall(self) -> None:
        if self.app.is_sending():
            toast(self, "Stop sending before uninstalling.", "warn")
            return
        choice = ChoiceDialog.ask(
            self, "Uninstall HomingPigeon?",
            "HomingPigeon, its shortcuts and its private copy of Python will be removed.\n\n"
            "What should happen to your saved information — contacts, templates, settings and "
            "campaign history?",
            [("keep", "Uninstall, and keep my information", "primary"),
             ("delete", "Uninstall, and delete my information too", "danger"),
             ("cancel", "Cancel", "secondary")])
        if choice not in ("keep", "delete"):
            return
        if choice == "delete" and not ConfirmDialog.ask(
                self, "Delete your information for good?",
                "Your contacts, templates, settings and campaign history will be permanently "
                "deleted. This can't be undone.\n\nTip: cancel and use \"Back up my information\" "
                "first if you might want it later.", confirm_text="Delete and uninstall", danger=True):
            return

        home = shortcut.app_location()
        command = [str(home / "python" / "pythonw.exe"), "-E", "-s",
                   str(home / "installer" / "setup_app.py"), "--uninstall", "--confirmed",
                   "--target", str(home)]
        if choice == "delete":
            command.append("--delete-data")
        try:
            subprocess.Popen(command, cwd=tempfile.gettempdir(), close_fds=True,
                             creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
        except OSError as error:
            toast(self, f"The uninstaller couldn't start: {error}. Use Settings > Apps in Windows "
                        f"instead.", "error", 8000)
            return
        self.app.quit_app()  # the uninstaller waits for the app to close

    def _delete_data_only(self) -> None:
        if self.app.is_sending():
            toast(self, "Stop sending first.", "warn")
            return
        if not ConfirmDialog.ask(
                self, "Delete your saved information?",
                "Your contacts, templates, settings, campaign history and saved passwords will be "
                "permanently deleted, and HomingPigeon will close. This can't be undone.",
                confirm_text="Delete everything", danger=True):
            return
        self.app.quit_app()
        shutil.rmtree(config.DATA_DIR, ignore_errors=True)
        os._exit(0)


def _version(text: str) -> tuple[int, ...]:
    """'v0.2.1 beta' -> (0, 2, 1)."""
    digits = "".join(ch if ch.isdigit() or ch == "." else " " for ch in str(text)).split()
    if not digits:
        return (0,)
    return tuple(int(part) for part in digits[0].split(".") if part)
