"""The application shell: sidebar navigation, page stack and status bar.

Two things here matter for how the app feels.

*Pages are built the first time they are opened.* The old build constructed all
ten pages before showing the first one, which is most of what made the cold
start slow. Here the window appears with one page in it.

*Theme, contrast, bold text and text size never rebuild anything.* They
re-render the stylesheet string and hand it to Qt, which repaints once.
"""
from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon, QKeySequence, QPixmap, QShortcut
from PyQt6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton,
                             QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

from app import config
from app.core import db, prefs, warmup
from app.ui import theme
from app.ui.widgets.common import restyle, separator, toast

# (key, icon, title, subtitle)
NAV_ITEMS = [
    ("dashboard", "home", "Home", "How things are going"),
    ("guide", "guide", "Start here", "Step-by-step setup"),
    ("account", "account", "My email account", "Connect your email"),
    ("deliverability", "shield", "Domain check", "Stay out of spam"),
    ("contacts", "contacts", "My contacts", "Your list of people"),
    ("templates", "message", "My message", "What you want to say"),
    ("campaign", "options", "Sending options", "Speed, timing, brochure"),
    ("send", "send", "Send emails", "Start and watch it run"),
    ("sent", "history", "Sent emails", "Everything you have sent"),
    ("inbox", "inbox", "My inbox", "Replies, bounces and mail"),
]
SETTINGS_ITEM = ("settings", "settings", "Settings", "Theme, text size, uninstall")


class NavButton(QPushButton):
    """One menu entry: icon, title, hint and an optional attention dot."""

    def __init__(self, key: str, icon_name: str, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        self.key = key
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("nav", "off")
        self.setCheckable(False)

        scale = theme.text_scale()
        show_subtitle = scale <= theme.SUBTITLE_MAX_SCALE
        # The height comes from theme.nav_height(), the same value the
        # stylesheet writes into min-height, and is asked for through the size
        # hints rather than setFixedHeight. Qt re-polishes a widget whenever
        # the application stylesheet changes or a dynamic property is flipped,
        # and polishing replaces size constraints set in code with the
        # stylesheet's. That is what used to collapse every entry to the height
        # of an ordinary button and clip both lines of text.
        self._height = theme.nav_height()
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(round(10 * scale), round(9 * scale), round(10 * scale),
                                  round(9 * scale))
        layout.setSpacing(round(11 * scale))

        self.icon_label = QLabel(theme.icon(icon_name))
        self.icon_label.setFixedWidth(round(20 * scale))
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.icon_label)

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(round(3 * scale))
        self.title_label = QLabel(title)
        text.addWidget(self.title_label)
        # Parented to the button from the outset. A parentless QLabel that is
        # made visible *is* a top-level window, so showing it before the layout
        # adopted it blinked one small window open per menu entry at start-up.
        self.subtitle_label = QLabel(subtitle, self)
        self.subtitle_label.setProperty("role", "hint")
        if show_subtitle:
            text.addWidget(self.subtitle_label)
        else:
            self.subtitle_label.hide()
        layout.addLayout(text, 1)

        # The "not finished yet" dot sits on the title's line, not floating
        # between the two lines of text.
        self.badge = QLabel("")
        self.badge.setFixedWidth(round(12 * scale))
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.badge)

        self.set_active(False)

    def set_active(self, active: bool) -> None:
        self.setProperty("nav", "on" if active else "off")
        restyle(self)
        family = theme.icon_family()
        self.icon_label.setStyleSheet(
            (f'font-family: "{family}"; ' if family else "")
            + f"font-size: {theme.px(17)}px; "
            + f"color: {theme.color('accent') if active else theme.color('fg_muted')};")
        self.title_label.setStyleSheet(
            f"font-size: {theme.px(13)}px; "
            f"font-weight: {'700' if (active or theme.bold_text()) else '600'}; "
            f"color: {theme.color('accent') if active else theme.color('fg')};")

    def sizeHint(self):  # noqa: N802 - Qt naming
        hint = super().sizeHint()
        hint.setHeight(self._height)
        return hint

    def minimumSizeHint(self):  # noqa: N802 - Qt naming
        hint = super().minimumSizeHint()
        hint.setHeight(self._height)
        return hint

    def set_badge(self, show: bool) -> None:
        self.badge.setText("●" if show else "")
        self.badge.setStyleSheet(
            f"color: {theme.color('warning')}; font-size: {theme.px(9)}px;")


class MainWindow(QMainWindow):
    """The one window. Pages register a builder and are made on first use."""

    theme_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{config.APP_TITLE} {config.APP_VERSION}  ·  {config.APP_TAGLINE}")
        self._set_icon()

        self._builders: dict[str, Callable[[], QWidget]] = {}
        self._pages: dict[str, QWidget] = {}
        self._nav: dict[str, NavButton] = {}
        self.current: str | None = None

        self._build()
        self._size_to_screen()
        self._register_pages()

        start = prefs.get("start_page")
        if start == "last":
            start = db.get_setting("last_page", "dashboard")
        self.show_page(start if start in self._builders else "dashboard")

        for sequence in (QKeySequence(Qt.Key.Key_F5), QKeySequence("Ctrl+R")):
            QShortcut(sequence, self).activated.connect(self.refresh_app)

        # The status bar reads the database; keep it off the startup path
        QTimer.singleShot(200, self.refresh_status)

    # --- chrome -------------------------------------------------------------
    def _set_icon(self) -> None:
        try:
            path = config.resource_path("assets/icon.ico")
            if path.exists():
                self.setWindowIcon(QIcon(str(path)))
                return
            png = config.resource_path("assets/logo-256.png")
            if png.exists():
                self.setWindowIcon(QIcon(str(png)))
        except OSError:
            pass

    def _size_to_screen(self) -> None:
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else None
        # availableGeometry already excludes the taskbar, so only the title bar
        # and a little breathing room need subtracting. The extra height is what
        # lets the whole menu, and a readable message pane, fit on screen.
        width = min(1280, (available.width() - 80) if available else 1280)
        height = min(920, (available.height() - 60) if available else 920)
        self.resize(width, height)
        self.setMinimumSize(min(1000, width), min(640, height))

    def _build(self) -> None:
        central = QWidget()
        central.setProperty("role", "plain")
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        self.stack.setProperty("role", "plain")
        body.addWidget(self.stack, 1)
        outer.addLayout(body, 1)

        outer.addWidget(self._build_status_bar())
        self.setCentralWidget(central)

    def _build_sidebar(self) -> QWidget:
        scale = theme.text_scale()
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(round(theme.SIDEBAR_WIDTH * scale))

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(round(10 * scale), round(14 * scale), round(10 * scale),
                                  round(10 * scale))
        layout.setSpacing(round(4 * scale))

        header = QHBoxLayout()
        header.setSpacing(round(10 * scale))
        logo = QLabel()
        size = round(40 * scale)
        try:
            pixmap = QPixmap(str(config.resource_path("assets/logo-96.png")))
            if not pixmap.isNull():
                logo.setPixmap(pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation))
            else:
                raise ValueError
        except Exception:  # noqa: BLE001 - a missing logo must not stop startup
            logo.setText("\U0001f54a")
            logo.setStyleSheet(f"font-size: {theme.px(22)}px; color: {theme.color('accent')};")
        logo.setFixedSize(QSize(size, size))
        header.addWidget(logo)

        names = QVBoxLayout()
        names.setSpacing(0)
        title = QLabel(config.APP_TITLE)
        title.setProperty("role", "app-title")
        names.addWidget(title)
        version = QLabel(config.APP_VERSION)
        version.setProperty("role", "hint")
        names.addWidget(version)
        header.addLayout(names, 1)

        # Refresh. Not decoration: if a page has got itself into a bad state,
        # this rebuilds it from scratch, which is the fix a user can reach for
        # without restarting the app.
        self.refresh_button = QPushButton(theme.icon("refresh"))
        self.refresh_button.setProperty("kind", "ghost")
        self.refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_button.setFixedSize(QSize(round(30 * scale), round(30 * scale)))
        self.refresh_button.setToolTip("Refresh this page (F5)")
        family = theme.icon_family()
        self.refresh_button.setStyleSheet(
            (f'font-family: "{family}"; ' if family else "")
            + f"font-size: {theme.px(16)}px; border: none; padding: 0;")
        self.refresh_button.clicked.connect(self.refresh_app)
        header.addWidget(self.refresh_button, 0, Qt.AlignmentFlag.AlignTop)
        self._paint_refresh_button()

        layout.addLayout(header)
        layout.addSpacing(round(8 * scale))
        layout.addWidget(separator())
        layout.addSpacing(round(6 * scale))

        # The menu scrolls. Ten roomy entries do not fit a short laptop screen at
        # the largest text sizes, and a clipped menu hides the pages at the
        # bottom of it with no way to reach them. Settings stays pinned below.
        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.Shape.NoFrame)
        scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroller.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroller.viewport().setAutoFillBackground(False)

        items = QWidget()
        items.setProperty("role", "plain")
        item_layout = QVBoxLayout(items)
        item_layout.setContentsMargins(0, 0, 0, 0)
        item_layout.setSpacing(round(6 * scale))

        for key, icon_name, label, subtitle in NAV_ITEMS:
            button = NavButton(key, icon_name, label, subtitle)
            button.clicked.connect(lambda _checked=False, k=key: self.show_page(k))
            item_layout.addWidget(button)
            self._nav[key] = button
        item_layout.addStretch(1)

        scroller.setWidget(items)
        self._nav_scroll = scroller
        layout.addWidget(scroller, 1)
        layout.addSpacing(round(6 * scale))
        layout.addWidget(separator())
        layout.addSpacing(round(6 * scale))

        key, icon_name, label, subtitle = SETTINGS_ITEM
        settings = NavButton(key, icon_name, label, subtitle)
        settings.clicked.connect(lambda _checked=False: self.show_page("settings"))
        layout.addWidget(settings)
        self._nav[key] = settings
        return sidebar

    def _paint_refresh_button(self) -> None:
        button = getattr(self, "refresh_button", None)
        if button is None:
            return
        family = theme.icon_family()
        button.setStyleSheet(
            (f'font-family: "{family}"; ' if family else "")
            + f"font-size: {theme.px(16)}px; border: none; padding: 0; "
            + f"color: {theme.color('fg_muted')};")

    def _build_status_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("StatusBar")
        bar.setFixedHeight(round(26 * theme.text_scale()))
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(16)

        self.status_account = QLabel("No account configured")
        self.status_middle = QLabel("")
        self.status_right = QLabel("")
        layout.addWidget(self.status_account)
        layout.addStretch(1)
        layout.addWidget(self.status_middle)
        layout.addWidget(self.status_right)
        return bar

    # --- pages --------------------------------------------------------------
    def _register_pages(self) -> None:
        """Record how to build each page. Nothing is constructed until it is shown."""

        def builder(module_name: str, class_name: str) -> Callable[[], QWidget]:
            def make() -> QWidget:
                import importlib

                module = importlib.import_module(f"app.ui.pages.{module_name}")
                return getattr(module, class_name)(self)

            return make

        self._builders = {
            "dashboard": builder("dashboard", "DashboardPage"),
            "guide": builder("guide", "GuidePage"),
            "account": builder("account", "AccountPage"),
            "deliverability": builder("deliverability", "DeliverabilityPage"),
            "contacts": builder("contacts", "ContactsPage"),
            "templates": builder("templates", "TemplatesPage"),
            "campaign": builder("campaign", "CampaignPage"),
            "send": builder("send", "SendPage"),
            "sent": builder("sent", "SentPage"),
            "inbox": builder("inbox", "InboxPage"),
            "settings": builder("settings", "SettingsPage"),
        }

    def page(self, key: str) -> QWidget | None:
        """The page if it has been opened, else None. Never builds one."""
        return self._pages.get(key)

    def ensure_page(self, key: str) -> QWidget | None:
        if key in self._pages:
            return self._pages[key]
        builder = self._builders.get(key)
        if builder is None:
            return None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            page = builder()
        finally:
            QApplication.restoreOverrideCursor()
        self._pages[key] = page
        self.stack.addWidget(page)
        return page

    def show_page(self, key: str) -> None:
        if key not in self._builders:
            return
        page = self.ensure_page(key)
        if page is None:
            return
        if self.current and self.current in self._nav:
            self._nav[self.current].set_active(False)
        self.current = key
        self._nav[key].set_active(True)
        # Reaching a page from somewhere other than the menu (a button on the
        # Home page, say) must bring its menu entry into view on a short screen.
        scroller = getattr(self, "_nav_scroll", None)
        if scroller is not None and self._nav[key].parentWidget() is scroller.widget():
            scroller.ensureWidgetVisible(self._nav[key])
        self.stack.setCurrentWidget(page)
        # Soft: remembering the last page is a convenience, and a background
        # import holding the write lock must never stall navigation for it.
        db.set_setting_soft("last_page", key)

        on_show = getattr(page, "on_show", None)
        if callable(on_show):
            try:
                on_show()
            except Exception as error:  # noqa: BLE001 - a broken page must not break navigation
                toast(self, f"Could not refresh this page: {error}", "error")
        self.refresh_status()

    def refresh_app(self) -> None:
        """Reload the page on screen, like F5 in a browser.

        A page is thrown away and built again, so anything wedged in its widgets
        is gone and every number on it is re-read from the database. A page with
        a worker still running is re-read in place instead: destroying it would
        leave that worker holding callbacks into deleted widgets, which is a
        crash rather than a fix.
        """
        current = self.current
        if current is None:
            return

        page = self._pages.get(current)
        reason = None
        if page is not None:
            try:
                reason = page.busy_reason() if hasattr(page, "busy_reason") else None
            except Exception:  # noqa: BLE001 - a broken page is exactly what this is for
                reason = None

        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme.stylesheet())

        if reason:
            self._soft_refresh(page)
            toast(self, f"Reloaded what is on screen. Left the page alone because {reason}.",
                  "info", 5000)
            return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.setUpdatesEnabled(False)
        try:
            if page is not None:
                self._pages.pop(current, None)
                self.stack.removeWidget(page)
                page.deleteLater()
            self.current = None
            self.show_page(current)
        finally:
            self.setUpdatesEnabled(True)
            QApplication.restoreOverrideCursor()
        toast(self, "Refreshed", "success", 2000)

    def _soft_refresh(self, page: QWidget | None) -> None:
        """Re-read a page's data without rebuilding it."""
        if page is not None:
            on_show = getattr(page, "on_show", None)
            if callable(on_show):
                try:
                    on_show()
                except Exception:  # noqa: BLE001
                    pass
        self.refresh_status()

    def notify(self, message: str, level: str = "info", duration: int = 4000) -> None:
        toast(self, message, level, duration)

    # --- status -------------------------------------------------------------
    def refresh_status(self) -> None:
        email = db.get_setting("sender_email", "")
        host = db.get_setting("smtp_host", "")
        if email:
            self.status_account.setText(email + (f"  ·  {host}" if host else ""))
        else:
            self.status_account.setText("No account configured. Open 'My email account'")

        try:
            self.status_middle.setText(warmup.status().describe())
        except Exception:  # noqa: BLE001
            self.status_middle.setText("")

        from app.core import importer

        try:
            self.status_right.setText(f"{importer.contact_count():,} contacts")
        except Exception:  # noqa: BLE001
            self.status_right.setText("")

        self._refresh_badges()

    def _refresh_badges(self) -> None:
        """A dot next to steps that are not done yet, so setup is self-guiding."""
        from app.core import importer

        incomplete = {
            "account": not bool(db.get_setting("sender_email", "")),
            "contacts": importer.contact_count() == 0,
            "templates": db.query_one("SELECT 1 FROM bodies WHERE enabled = 1") is None,
            # Not a setup step: this one means "there is mail you have not read"
            "inbox": db.inbox_unseen() > 0,
        }
        for key, button in self._nav.items():
            button.set_badge(bool(incomplete.get(key)))

    # --- appearance ---------------------------------------------------------
    def apply_theme(self) -> None:
        """Repaint the whole app from the current tokens. No widget is rebuilt."""
        app = QApplication.instance()
        # Repainting while Qt re-polishes the tree is what shows up as a flash of
        # half-old, half-new colours; one repaint at the end instead.
        self.setUpdatesEnabled(False)
        try:
            if app is not None:
                app.setStyleSheet(theme.stylesheet())
            # Sidebar entries and self-painting widgets hold explicit colours
            for key, button in self._nav.items():
                button.set_active(key == self.current)
                button.set_badge(bool(button.badge.text()))
            self._paint_refresh_button()
            for widget in self.findChildren(QWidget):
                refresh = getattr(widget, "refresh_theme", None)
                if callable(refresh):
                    try:
                        refresh()
                    except Exception:  # noqa: BLE001
                        pass
        finally:
            self.setUpdatesEnabled(True)
        self.theme_changed.emit()

    def change_appearance(self, mode: str) -> None:
        db.set_setting("appearance", mode)
        theme.set_appearance(mode)
        self.apply_theme()

    def change_contrast(self, enabled: bool) -> None:
        db.set_setting("high_contrast", enabled)
        theme.set_high_contrast(enabled)
        self.apply_theme()

    def change_bold_text(self, enabled: bool) -> None:
        db.set_setting("bold_text", enabled)
        theme.set_bold_text(enabled)
        self.apply_theme()

    def change_text_size(self, key: str) -> None:
        """Text size changes metrics, not just colours, so built pages are discarded.

        Only pages the user has actually opened are affected, and the one on
        screen is rebuilt immediately; the rest are made again when next opened.
        This is the one setting that cannot be done with a stylesheet alone,
        because fixed widget heights are computed from the scale.
        """
        db.set_setting("text_size", key)
        theme.set_text_scale(prefs.text_scale())

        # Every built page is destroyed below, so a page with a worker running
        # would lose the result it is waiting for. Repaint only, and finish the
        # resize once the work is done.
        reason = self.busy_page_reason()
        if reason:
            self.apply_theme()
            toast(self, f"Text size applies fully once {reason} has finished.", "warn", 6000)
            return

        current = self.current or "dashboard"
        self.setUpdatesEnabled(False)
        try:
            for page in self._pages.values():
                self.stack.removeWidget(page)
                page.deleteLater()
            self._pages.clear()
            self.current = None

            # The sidebar and status bar are sized from the scale too
            old = self.centralWidget()
            self._nav.clear()
            self._build()
            if old is not None:
                old.deleteLater()
            self.apply_theme()
            self.show_page(current)
        finally:
            self.setUpdatesEnabled(True)

    # --- lifecycle ----------------------------------------------------------
    def busy_page_reason(self) -> str | None:
        """The first reason any built page gives for not being torn down."""
        for page in self._pages.values():
            ask = getattr(page, "busy_reason", None)
            if not callable(ask):
                continue
            try:
                reason = ask()
            except Exception:  # noqa: BLE001
                continue
            if reason:
                return reason
        return None

    def is_sending(self) -> bool:
        page = self._pages.get("send")
        return bool(page is not None and getattr(page, "is_running", lambda: False)())

    def stop_sending(self) -> None:
        page = self._pages.get("send")
        if page is not None and hasattr(page, "stop_worker"):
            page.stop_worker()

    def quit_app(self) -> None:
        """Close without questions (used by the uninstaller and by restore)."""
        self.stop_sending()
        db.close()
        QApplication.quit()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self.is_sending():
            from app.ui.widgets.dialogs import ConfirmDialog

            if not ConfirmDialog.ask(
                self, "A campaign is still running",
                "Closing now stops sending. Everything already sent is saved, and you can resume "
                "the campaign next time you open the app.\n\nClose anyway?",
                confirm_text="Close and stop", danger=True,
            ):
                event.ignore()
                return
            self.stop_sending()

        from app.workers import base as workers

        workers.shutdown(2000)
        db.close()
        event.accept()
