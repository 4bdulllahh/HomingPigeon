"""HomingPigeon — launcher."""
from __future__ import annotations

import sys
import traceback
from datetime import datetime

SETUP_HELP = (
    "HomingPigeon is not set up yet.\n\n"
    "On Windows, run \"HomingPigeon Setup.exe\" from the GitHub Releases page again; it repairs "
    "the installation. On a Mac or Linux, double-click the \"Start HomingPigeon\" file in the "
    "HomingPigeon folder."
)

# Qt's wheels bundle almost everything, but most Linux distributions still need
# this one system package before a window can be created.
LINUX_QT_HELP = (
    "HomingPigeon could not start its window system.\n\n"
    "On Ubuntu, Debian or Mint, run:\n"
    "    sudo apt install libxcb-cursor0 libxkbcommon-x11-0\n\n"
    "On Fedora:\n"
    "    sudo dnf install xcb-util-cursor libxkbcommon-x11"
)


def report(message: str) -> None:
    """Show a message even in a windowed build, where stdout may not exist."""
    try:
        print(message)
    except Exception:
        pass
    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(None, "HomingPigeon", message)
        del app
        return
    except Exception:
        pass
    try:
        import tkinter.messagebox as messagebox

        messagebox.showerror("HomingPigeon", message)
    except Exception:
        pass


def install_crash_guard() -> None:
    """Stop one unhandled error from killing the whole app.

    PyQt calls ``qFatal()`` when a Python exception escapes a slot, which aborts
    the process with no message at all — the user just sees the window vanish.
    Logging it and carrying on is nearly always the better answer: the action
    that failed is lost, but the campaign, the contact list and anything typed
    but not yet saved are not.
    """
    from app import config

    def hook(kind, value, trace) -> None:
        details = "".join(traceback.format_exception(kind, value, trace))
        try:
            print(details)
        except Exception:
            pass
        try:
            config.ensure_dirs()
            with (config.LOGS_DIR / "crash.log").open("a", encoding="utf-8") as log:
                log.write(f"\n--- {datetime.now().isoformat(timespec='seconds')} ---\n{details}")
        except Exception:
            pass
        try:
            from PyQt6.QtWidgets import QApplication

            from app.ui.widgets.common import toast

            window = QApplication.activeWindow()
            if window is not None:
                toast(window, f"Something went wrong: {type(value).__name__}: {value}",
                      "error", 8000)
        except Exception:
            pass

    sys.excepthook = hook


def main() -> int:
    try:
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QApplication
    except ImportError as error:
        # A missing system library shows up here too, not just a missing install
        if sys.platform.startswith("linux") and "libxcb" in str(error):
            report(LINUX_QT_HELP)
        else:
            report(SETUP_HELP)
        return 1

    if sys.platform == "win32":
        # Give the app its own taskbar identity, so it shows the pigeon rather than Python's icon
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("HomingPigeon.App")
        except (AttributeError, OSError):
            pass

    # Round the scale factor to whole quarters. Qt's default of honouring an
    # arbitrary fractional DPI leaves borders landing between physical pixels,
    # which is what shows up as shimmering and tearing on a scaled display.
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.RoundPreferFloor)

    app = QApplication(sys.argv)
    app.setApplicationName("HomingPigeon")
    app.setOrganizationName("HomingPigeon")
    app.setDesktopFileName("HomingPigeon")
    # Fusion draws identically everywhere and is the only style QSS can fully
    # restyle; the native Windows style ignores half the rules.
    app.setStyle("Fusion")

    from app import config
    from app.core import db

    config.ensure_dirs()
    install_crash_guard()
    db.init()

    # Set at application level, not just on the window: Qt then gives the icon
    # to every window the app ever creates, including the short-lived ones the
    # taskbar sometimes latched onto instead of the real one.
    from PyQt6.QtGui import QIcon

    for name in ("assets/icon.ico", "assets/logo-256.png"):
        path = config.resource_path(name)
        if path.exists():
            app.setWindowIcon(QIcon(str(path)))
            break

    from app.ui import theme

    theme.apply_preferences()  # theme, text size, contrast and bold text from Settings
    app.setStyleSheet(theme.stylesheet())

    from app.ui.main_window import MainWindow

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # noqa: BLE001 - never fail silently
        details = traceback.format_exc()
        try:
            from app import config

            config.ensure_dirs()
            (config.LOGS_DIR / "crash.log").write_text(details, encoding="utf-8")
        except Exception:
            pass
        report(f"The application could not start.\n\n{type(error).__name__}: {error}")
        sys.exit(1)
