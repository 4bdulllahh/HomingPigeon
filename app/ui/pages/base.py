"""Shared page scaffolding: a title, an intro line and a body."""
from __future__ import annotations

from PyQt6 import sip
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from app.ui import theme
from app.ui.widgets.common import ScrollPage, heading, muted


class Page(QWidget):
    """Base for every page in the stack.

    ``self.window_`` is the MainWindow, used for navigation, toasts and the
    status bar. Pages never talk to each other directly.
    """

    def __init__(self, window):
        super().__init__()
        self.window_ = window
        self.setProperty("role", "plain")
        scale = theme.text_scale()
        pad = round(theme.PAD_LARGE * scale)

        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(pad, round(theme.PAD * scale), pad, round(theme.PAD * scale))
        self.root.setSpacing(round(10 * scale))

    # --- convenience --------------------------------------------------------
    def add_header(self, title: str, intro: str = "") -> None:
        self.root.addWidget(heading(title))
        if intro:
            self.root.addWidget(muted(intro))

    def scroll_body(self, spacing: int = 12) -> ScrollPage:
        area = ScrollPage(margins=(0, 0, round(8 * theme.text_scale()), 0), spacing=spacing)
        self.root.addWidget(area, 1)
        return area

    def notify(self, message: str, level: str = "info", duration: int = 4000) -> None:
        self.window_.notify(message, level, duration)

    def go(self, page: str) -> None:
        self.window_.show_page(page)

    def on_show(self) -> None:
        """Called every time the page becomes visible. Keep it cheap."""

    def guard(self, callback):
        """Wrap a worker callback so it is dropped if this page no longer exists.

        Refresh and a text-size change both destroy pages and build them again.
        A job started beforehand still delivers its result afterwards, and a
        callback that then writes into a destroyed widget raises "wrapped C/C++
        object has been deleted", which reads to the user as the app crashing.

        PyQt disconnects a bound method of a QObject when that object goes, so
        those are safe already. A lambda closing over the page is not, and every
        one of those goes through here.
        """

        def run(*args, **kwargs):
            if sip.isdeleted(self):
                return None
            return callback(*args, **kwargs)

        return run

    def busy_reason(self) -> str | None:
        """Why this page must not be thrown away and rebuilt right now, if so.

        Refresh rebuilds the page it is looking at. A page with a worker still
        running would have its callbacks fire into destroyed widgets, so a busy
        page is re-read in place instead. Pages that start long jobs override
        this; the default is that nothing is in flight.
        """
        return None
