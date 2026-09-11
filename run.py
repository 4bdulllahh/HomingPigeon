"""Uniformers Mailer — launcher."""
from __future__ import annotations

import sys
import traceback


def report(message: str) -> None:
    """Show a message even in a windowed build, where stdout may not exist."""
    try:
        print(message)
    except Exception:
        pass
    try:
        import tkinter.messagebox as messagebox

        messagebox.showerror("Uniformers Mailer", message)
    except Exception:
        pass


def main() -> int:
    try:
        import customtkinter as ctk
    except ImportError:
        report("CustomTkinter is not installed.\n\nRun:  pip install -r requirements.txt")
        return 1

    from app import config, theme
    from app.core import db

    config.ensure_dirs()
    db.init()

    ctk.set_default_color_theme("blue")
    theme.apply_appearance(db.get_setting("appearance", "Dark"))

    from app.ui.shell import AppShell

    app = AppShell()
    app.mainloop()
    return 0


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
