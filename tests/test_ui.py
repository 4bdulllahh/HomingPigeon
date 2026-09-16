"""Tests for the PyQt6 layer: theming, the contacts model and the worker plumbing.

These run headless (``QT_QPA_PLATFORM=offscreen``) so they work in CI, and they
skip cleanly if PyQt6 is not installed.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6", reason="PyQt6 is not installed")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from app.core import db  # noqa: E402
from app.ui import theme  # noqa: E402


@pytest.fixture(scope="session")
def qt_app():
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    yield app


@pytest.fixture(autouse=True)
def restore_theme():
    """Theme state is global, so tests must not leak it into each other."""
    before = (theme._state["appearance"], theme._state["high_contrast"],
              theme._state["bold_text"], theme._state["scale"])
    yield
    theme.set_appearance(before[0])
    theme.set_high_contrast(before[1])
    theme.set_bold_text(before[2])
    theme.set_text_scale(before[3])


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A database of its own, so tests never touch the real one."""
    from app import config

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "mailer.db")
    db.init(tmp_path / "mailer.db")
    yield
    db.close()


# --- theme ------------------------------------------------------------------
def test_stylesheet_covers_every_appearance(qt_app):
    """Every combination must produce usable QSS, not a KeyError on a token."""
    for appearance in ("Dark", "Light"):
        for contrast in (False, True):
            theme.set_appearance(appearance)
            theme.set_high_contrast(contrast)
            sheet = theme.stylesheet()
            assert "QPushButton" in sheet
            assert "{" in sheet and "}" in sheet
            # An unresolved token would leave a literal 'None' in a colour slot
            assert "None" not in sheet


def test_every_palette_defines_the_same_tokens():
    names = set(theme.LIGHT)
    for palette in (theme.DARK, theme.LIGHT_HC, theme.DARK_HC):
        assert set(palette) == names


def test_text_scale_changes_pixel_sizes():
    theme.set_text_scale(1.0)
    normal = theme.px(13)
    theme.set_text_scale(1.5)
    assert theme.px(13) > normal
    theme.set_text_scale(1.15)


def test_status_colour_falls_back_for_unknown_status():
    assert theme.status_color("pass") == theme.color("success")
    assert theme.status_color("fail") == theme.color("error")
    assert theme.status_color("something-else") == theme.color("fg_muted")


# --- contacts model ---------------------------------------------------------
def _add_contacts(count: int, prefix: str = "user") -> None:
    db.execute_many(
        "INSERT INTO contacts(email, company, person, valid, imported_at) VALUES (?, ?, ?, 1, ?)",
        [(f"{prefix}{i}@example.com", f"Company {i}", f"Person {i}", db.now())
         for i in range(count)])


def test_model_pages_instead_of_loading_everything(qt_app, store):
    from app.models.contacts_model import PAGE_SIZE, ContactsModel

    _add_contacts(PAGE_SIZE * 2 + 40)
    model = ContactsModel()
    model.reload()

    assert model.rowCount() == PAGE_SIZE           # only the first page is in memory
    assert model.matching_count() == PAGE_SIZE * 2 + 40
    assert model.canFetchMore()

    model.fetchMore()
    assert model.rowCount() == PAGE_SIZE * 2


def test_model_search_filters_and_reports_matches(qt_app, store):
    _add_contacts(5, prefix="alpha")
    _add_contacts(3, prefix="beta")

    from app.models.contacts_model import ContactsModel

    model = ContactsModel()
    model.reload()
    assert model.matching_count() == 8

    model.set_search("beta")
    assert model.matching_count() == 3
    assert all("beta" in model.email_at(r) for r in range(model.rowCount()))

    model.set_search("")
    assert model.matching_count() == 8


def test_model_shows_spreadsheet_columns_beyond_the_standard_ones(qt_app, store):
    db.execute(
        "INSERT INTO contacts(email, company, person, extra_json, valid, imported_at) "
        "VALUES (?, ?, ?, ?, 1, ?)",
        ("a@example.com", "Co", "Someone", '{"Phone": "123", "City": "Dubai"}', db.now()))

    from app.models.contacts_model import ContactsModel

    model = ContactsModel()
    model.reload()
    headers = [model.headerData(i, Qt.Orientation.Horizontal)
               for i in range(model.columnCount())]
    assert "Phone" in headers and "City" in headers

    phone = headers.index("Phone")
    assert model.data(model.index(0, phone)) == "123"


def test_deleting_rows_removes_the_contacts(qt_app, store):
    _add_contacts(4)
    from app.models.contacts_model import ContactsModel

    model = ContactsModel()
    model.reload()
    doomed = model.email_at(1)

    assert model.delete_rows([1]) == 1
    assert model.matching_count() == 3
    assert db.query_one("SELECT 1 FROM contacts WHERE email = ?", (doomed,)) is None


def test_clearing_the_list_keeps_the_do_not_contact_list(qt_app, store):
    _add_contacts(6)
    db.suppress("gone@example.com", "unsubscribed", source="reply")

    from app.models.contacts_model import ContactsModel

    assert ContactsModel.clear_all() == 6
    assert db.query_one("SELECT COUNT(*) AS n FROM contacts")["n"] == 0
    # Suppression must survive, or re-importing would mail opted-out people again
    assert db.is_suppressed("gone@example.com")


def test_completer_source_lists_every_address(qt_app, store):
    _add_contacts(3)
    from app.models.contacts_model import all_contact_emails

    assert len(all_contact_emails()) == 3


# --- workers ----------------------------------------------------------------
def test_task_delivers_its_result_on_the_main_thread(qt_app):
    from app.workers.base import Task, pool

    received = []
    Task(lambda a, b: a + b, 2, 3).start(on_result=received.append)
    pool().waitForDone(5000)
    qt_app.processEvents()
    assert received == [5]


def test_task_reports_failure_instead_of_raising(qt_app):
    from app.workers.base import Task, pool

    errors = []

    def boom():
        raise ValueError("no good")

    Task(boom).start(on_error=errors.append)
    pool().waitForDone(5000)
    qt_app.processEvents()
    assert errors == ["no good"]


def test_debouncer_fires_once_after_the_last_poke(qt_app):
    from PyQt6.QtCore import QEventLoop, QTimer

    from app.ui.widgets.inputs import Debouncer

    fired = []
    debouncer = Debouncer(40)
    debouncer.connect(lambda: fired.append(1))
    for _ in range(5):
        debouncer.poke()

    loop = QEventLoop()
    QTimer.singleShot(250, loop.quit)
    loop.exec()
    assert fired == [1]


# --- start-up hygiene -------------------------------------------------------
def test_no_page_leaves_a_widget_as_a_stray_window(qt_app, store):
    """Every widget must be inside a parent before it is made visible.

    A parentless QWidget that is shown *is* a top-level window, which is how
    four small empty windows came to blink open ahead of the real one. Building
    each page with a watchful event filter catches it happening again.
    """
    from PyQt6.QtCore import QEvent, QObject
    from PyQt6.QtWidgets import QWidget

    from app.ui.main_window import MainWindow

    strays: list[str] = []

    class Spy(QObject):
        def eventFilter(self, obj, event):  # noqa: N802 - Qt naming
            if (event.type() == QEvent.Type.Show
                    and isinstance(obj, QWidget)
                    and obj.parent() is None
                    and type(obj).__name__ != "MainWindow"):
                strays.append(type(obj).__name__)
            return False

    spy = Spy()
    qt_app.installEventFilter(spy)
    try:
        window = MainWindow()
        for key in window._builders:
            window.show_page(key)
    finally:
        qt_app.removeEventFilter(spy)
        window.close()
        window.deleteLater()
        qt_app.processEvents()

    assert strays == [], f"shown before being parented: {sorted(set(strays))}"


# --- sent log ---------------------------------------------------------------
def _record_send(email: str, status: str = "sent", replied: bool = False) -> None:
    contact_id = db.execute(
        "INSERT INTO contacts(email, company, person, valid, imported_at, replied_at) "
        "VALUES (?, ?, ?, 1, ?, ?)",
        (email, "Co", "Someone", db.now(), db.now() if replied else None))
    campaign = db.query_one("SELECT id FROM campaigns LIMIT 1")
    if campaign is None:
        campaign_id = db.execute(
            "INSERT INTO campaigns(name, status, created_at) VALUES ('Test', 'draft', ?)",
            (db.now(),))
    else:
        campaign_id = campaign["id"]
    db.execute(
        "INSERT INTO campaign_recipients(campaign_id, contact_id, status, attempts, "
        "subject_used, sent_at) VALUES (?, ?, ?, 1, 'Hello', ?)",
        (campaign_id, contact_id, status, db.now() if status == "sent" else None))


def test_sent_log_lists_only_attempted_emails(qt_app, store):
    from app.models.sent_model import SentModel

    _record_send("sent@example.com", "sent")
    _record_send("bounced@example.com", "bounced")
    _record_send("failed@example.com", "failed")
    _record_send("waiting@example.com", "pending")

    model = SentModel()
    model.reload()
    assert model.rowCount() == 3
    assert "waiting@example.com" not in [model.email_at(r) for r in range(model.rowCount())]


def test_sent_log_outcome_puts_a_reply_above_everything_else(qt_app, store):
    from app.models.sent_model import SentModel

    _record_send("answered@example.com", "sent", replied=True)
    model = SentModel()
    model.reload()
    assert model.row_at(0)["_outcome"] == "Replied"


def test_sent_log_filters_and_counts(qt_app, store):
    from app.models.sent_model import SentModel

    _record_send("one@example.com", "sent")
    _record_send("two@example.com", "sent", replied=True)
    _record_send("three@example.com", "bounced")

    model = SentModel()
    model.reload()
    assert model.counts() == {"attempted": 3, "sent": 2, "replied": 1, "bounced": 1, "failed": 0}

    model.set_filter("replied")
    assert [model.email_at(r) for r in range(model.rowCount())] == ["two@example.com"]

    model.set_filter("all")
    model.set_search("three")
    assert model.rowCount() == 1


def test_sent_log_keeps_the_spreadsheet_columns(qt_app, store):
    from app.models.sent_model import SentModel

    contact_id = db.execute(
        "INSERT INTO contacts(email, company, person, extra_json, valid, imported_at) "
        "VALUES (?, ?, ?, ?, 1, ?)",
        ("x@example.com", "Co", "Someone", '{"Phone": "555", "City": "Dubai"}', db.now()))
    campaign_id = db.execute(
        "INSERT INTO campaigns(name, status, created_at) VALUES ('Test', 'draft', ?)", (db.now(),))
    db.execute(
        "INSERT INTO campaign_recipients(campaign_id, contact_id, status, sent_at) "
        "VALUES (?, ?, 'sent', ?)", (campaign_id, contact_id, db.now()))

    model = SentModel()
    model.reload()
    headers = [model.headerData(i, Qt.Orientation.Horizontal)
               for i in range(model.columnCount())]
    assert "Phone" in headers and "City" in headers


# --- selection --------------------------------------------------------------
def test_clicking_blank_space_lets_go_of_the_selection(qt_app, store):
    from app.models.table_model import SimpleTableModel
    from app.ui.widgets.tables import DataTable

    model = SimpleTableModel(["A"])
    model.set_rows([["one"], ["two"]])
    table = DataTable(model, multi_select=True)
    table.view.selectRow(0)
    assert table.selected_rows() == [0]

    table.clear_selection()
    assert table.selected_rows() == []


# --- installer --------------------------------------------------------------
def test_version_resource_is_a_well_formed_tree():
    """Windows rejects the whole resource if a node's length is wrong."""
    import importlib.util
    import struct
    from pathlib import Path as _Path

    spec = importlib.util.spec_from_file_location(
        "setup_app_probe",
        _Path(__file__).resolve().parent.parent / "installer" / "setup_app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    data = module.version_resource({"FileDescription": "HomingPigeon"}, (0, 4, 1, 0))
    length, value_length, kind = struct.unpack("<HHH", data[:6])
    assert length == len(data)          # the root covers everything
    assert value_length == 52           # VS_FIXEDFILEINFO
    assert kind == 0                    # binary value
    assert struct.unpack("<L", data[40:44])[0] == 0xFEEF04BD
    assert "HomingPigeon".encode("utf-16-le") in data


# --- sidebar ----------------------------------------------------------------
def test_menu_entries_are_tall_enough_for_two_lines_of_text(qt_app, store):
    """Guards the bug where re-polishing collapsed every entry to a button's height.

    Qt replaces size constraints set in code with the stylesheet's own
    ``min-height`` every time it polishes a widget, which it does whenever the
    application stylesheet changes or a dynamic property is flipped. Both lines
    of text were being clipped as a result, so the height has to come from the
    stylesheet and from the widget's size hints, and the two must agree.
    """
    from app.ui.main_window import NavButton

    qt_app.setStyleSheet(theme.stylesheet())
    button = NavButton("account", "account", "My email account", "Connect your email")
    button.show()
    try:
        wanted = theme.nav_height()
        needed = button.layout().minimumSize().height()
        assert button.sizeHint().height() == wanted
        assert button.minimumSizeHint().height() == wanted
        assert wanted >= needed, "an entry is shorter than its own two lines of text"

        # A restyle, which is what happens on every theme change and on every
        # selection change, must not shrink it.
        button.set_active(True)
        button.set_active(False)
        assert button.minimumSizeHint().height() == wanted
        assert f"min-height: {wanted}px" in theme.stylesheet()
    finally:
        button.deleteLater()


def test_the_menu_can_always_be_scrolled_to_reach_every_page(qt_app, store):
    """A menu taller than the window must never hide the pages at the bottom."""
    from PyQt6.QtWidgets import QScrollArea

    from app.ui.main_window import MainWindow

    theme.set_text_scale(1.5)          # the largest text size, the tightest fit
    qt_app.setStyleSheet(theme.stylesheet())
    window = MainWindow()
    window.resize(1000, 640)
    window.show()
    try:
        scroller = window._nav_scroll
        assert isinstance(scroller, QScrollArea)
        assert scroller.widgetResizable()
        # Every menu entry lives inside the scrolling area, so none can be cut off
        for key, button in window._nav.items():
            if key == "settings":
                continue          # pinned below the menu on purpose
            assert button.parentWidget() is scroller.widget(), key
    finally:
        window.close()
        window.deleteLater()


# --- house style ------------------------------------------------------------
def test_no_em_dashes_or_typographic_ellipses_anywhere():
    """These read as machine-written, so the app and its docs use plain punctuation."""
    from pathlib import Path as _Path

    root = _Path(__file__).resolve().parent.parent
    skip = {"build", "dist", ".git", "__pycache__", ".pytest_cache"}
    # Built from code points so that this test is not itself an offender
    banned = {chr(0x2014), chr(0x2013), chr(0x2026)}   # em dash, en dash, ellipsis
    offenders = []
    for pattern in ("*.py", "*.md", "*.txt", "*.bat", "*.sh", "*.command"):
        for path in root.rglob(pattern):
            if any(part in skip for part in path.parts):
                continue
            text = path.read_text(encoding="utf-8")
            for number, line in enumerate(text.splitlines(), 1):
                if banned & set(line):
                    offenders.append(f"{path.relative_to(root).as_posix()}:{number}")
    assert not offenders, "use '.', ',', ':' or '...' instead: " + ", ".join(offenders[:10])

# --- widget lifetimes -------------------------------------------------------
def test_a_combo_box_still_works_after_its_wheel_guard_owner_is_gone(qt_app, store):
    """The user saw "wrapped C/C++ object of type _WheelGuard has been deleted".

    The guard was a class-level singleton parented to whichever widget asked for
    it first. That widget goes away on any text-size change, leaving the cached
    Python reference pointing at a destroyed object, and the next combo box
    built anywhere in the app raised.
    """
    from PyQt6.QtWidgets import QWidget

    from app.ui.widgets import inputs

    owner = QWidget()
    owner.show()
    inputs.combo(["a", "b"], parent=owner)
    guard = inputs._WheelGuard._instance
    assert guard is not None
    assert guard.parent() is qt_app, "the guard must outlive every page"

    # Force the exact state the old code got into
    victim = QWidget()
    victim.show()
    inputs._WheelGuard._instance = inputs._WheelGuard(victim)
    victim.deleteLater()
    del victim
    qt_app.processEvents()
    inputs.combo(["a", "b"])          # must not raise
    owner.deleteLater()


def test_a_dismissed_toast_does_not_break_the_next_one(qt_app, store):
    """Every toast reads the list of live ones, including the crash handler's.

    A dismissed toast is deleteLater'd, so the entry left in the list pointed at
    a destroyed widget, and asking it anything raised. That turned any later
    message into a second error, which is how one fault became a cascade.
    """
    from PyQt6.QtWidgets import QWidget

    from app.ui.widgets import common

    window = QWidget()
    window.resize(800, 600)
    window.show()

    common.toast(window, "First", "info", 10)
    stale = common._toasts[-1]
    stale.deleteLater()
    del stale
    qt_app.processEvents()
    assert common._toasts, "the list should still hold the stale entry"

    common.toast(window, "Second", "error", 10)      # used to raise here
    assert all(common._on_screen(t) or True for t in common._toasts)
    window.deleteLater()


def test_a_worker_callback_is_dropped_once_its_page_is_gone(qt_app, store):
    """Refresh destroys a page; a job it started still delivers afterwards."""
    from app.ui.pages.base import Page

    page = Page(None)
    calls = []
    guarded = page.guard(lambda value: calls.append(value))
    guarded("while alive")
    assert calls == ["while alive"]

    from PyQt6 import sip

    sip.delete(page)
    guarded("after deletion")
    assert calls == ["while alive"], "a dead page's callback still ran"


# --- refresh ----------------------------------------------------------------
def test_refresh_rebuilds_the_page_on_screen(qt_app, store):
    from app.ui.main_window import MainWindow

    qt_app.setStyleSheet(theme.stylesheet())
    window = MainWindow()
    window.show()
    try:
        for key in ("dashboard", "contacts", "templates", "settings"):
            window.show_page(key)
            qt_app.processEvents()
            before = window.page(key)
            window.refresh_app()
            qt_app.processEvents()
            after = window.page(key)
            assert after is not before, f"{key} was not rebuilt"
            assert window.current == key, "refresh navigated away"
    finally:
        window.close()
        window.deleteLater()


def test_refresh_leaves_a_busy_page_alone(qt_app, store):
    """Rebuilding a page with a worker running would crash rather than help."""
    from app.ui.main_window import MainWindow

    qt_app.setStyleSheet(theme.stylesheet())
    window = MainWindow()
    window.show()
    try:
        window.show_page("inbox")
        qt_app.processEvents()
        page = window.page("inbox")
        assert page.busy_reason() is None

        page._syncing = True             # as if a check were running
        assert page.busy_reason()
        window.refresh_app()
        qt_app.processEvents()
        assert window.page("inbox") is page, "a busy page was thrown away"

        page._syncing = False
        window.refresh_app()
        qt_app.processEvents()
        assert window.page("inbox") is not page
    finally:
        window.close()
        window.deleteLater()


def test_refresh_is_reachable_by_button_and_by_key(qt_app, store):
    from PyQt6.QtGui import QKeySequence, QShortcut

    from app.ui.main_window import MainWindow

    qt_app.setStyleSheet(theme.stylesheet())
    window = MainWindow()
    window.show()
    try:
        assert window.refresh_button.isVisible()
        assert window.refresh_button.text(), "the button has no icon glyph"
        assert "F5" in window.refresh_button.toolTip()
        keys = {s.key().toString() for s in window.findChildren(QShortcut)}
        assert QKeySequence(Qt.Key.Key_F5).toString() in keys
        assert "Ctrl+R" in keys
    finally:
        window.close()
        window.deleteLater()


# --- the sort control -------------------------------------------------------
def test_the_sort_menu_is_a_themed_menu_with_every_column_both_ways(qt_app, store):
    from app.models.contacts_model import SORT_MENU, SORT_SHORT
    from app.ui.widgets.common import MenuButton

    qt_app.setStyleSheet(theme.stylesheet())
    keys = [entry[0] for entry in SORT_MENU if entry]
    for column in ("email", "company", "person"):
        assert f"{column}_az" in keys and f"{column}_za" in keys
    assert None in SORT_MENU, "the menu has no dividers"
    assert set(keys) <= set(SORT_SHORT), "every entry needs a short button label"

    picked = []
    button = MenuButton(SORT_MENU, "import", prefix="Sort: ", short=SORT_SHORT,
                        on_change=picked.append)
    assert button.text() == "Sort: Import order"
    button.set("company_za", notify=True)
    assert picked == ["company_za"]
    assert button.text() == "Sort: Company Z-A"
    # The menu is a real QMenu, so the application stylesheet reaches it
    assert button.menu() is not None
    assert len([a for a in button.menu().actions() if not a.isSeparator()]) == len(keys)
    checked = [a for a in button.menu().actions() if a.isChecked()]
    assert len(checked) == 1 and checked[0].text() == "Company: Z to A"
    button.deleteLater()


def test_a_finished_import_shows_up_without_reopening_the_app(qt_app, store):
    """Switching to My contacts must re-read, not show what it loaded earlier."""
    from app.ui.main_window import MainWindow

    qt_app.setStyleSheet(theme.stylesheet())
    window = MainWindow()
    window.show()
    try:
        window.show_page("contacts")
        qt_app.processEvents()
        page = window.page("contacts")
        page.tabs.set("My contacts")
        qt_app.processEvents()
        assert page.contacts_model.rowCount() == 0

        page.tabs.set("Import")
        qt_app.processEvents()
        # Rows arrive from somewhere else, as a worker thread's import does
        db.execute_many(
            "INSERT INTO contacts(email, company, person, valid, imported_at) "
            "VALUES (?,?,?,1,?)",
            [(f"late{n}@arrival.test", "Arrived Late", f"Person {n}", "2026-09-16T09:00:00")
             for n in range(12)])

        page.tabs.set("My contacts")
        qt_app.processEvents()
        assert page.contacts_model.rowCount() == 12, "the tab showed stale rows"
    finally:
        window.close()
        window.deleteLater()

