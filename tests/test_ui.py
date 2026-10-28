"""Tests for the PyQt6 layer: theming, the contacts model and the worker plumbing.

These run headless (``QT_QPA_PLATFORM=offscreen``) so they work in CI, and they
skip cleanly if PyQt6 is not installed.
"""
from __future__ import annotations

import os
from pathlib import Path

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
def delete_closed_windows():
    """Destroy each test's windows when it ends, as the running app's event loop would.

    Tests close their windows with deleteLater(), which only happens once events
    are processed. Without this they piled up, and the next test that waited on
    the event loop tore a dozen windows down at once, which crashed Qt.
    """
    yield
    from PyQt6.QtCore import QCoreApplication, QEvent

    app = QCoreApplication.instance()
    if app is not None:
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        app.processEvents()


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
    sent_at = db.now() if status == "sent" else None
    db.execute(
        "INSERT INTO campaign_recipients(campaign_id, contact_id, status, attempts, "
        "subject_used, sent_at) VALUES (?, ?, ?, 1, 'Hello', ?)",
        (campaign_id, contact_id, status, sent_at))
    # What the send worker does alongside: the permanent copy for Sent emails
    contact = db.query_one("SELECT * FROM contacts WHERE id = ?", (contact_id,))
    db.log_sent(campaign_id=campaign_id, contact=contact, status=status, subject="Hello",
                body_html="<p>Hi there</p>", sent_at=sent_at)


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
    assert model.counts() == {"attempted": 3, "sent": 2, "replied": 1, "bounced": 1, "failed": 0,
                              "opened": 0}

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
    db.log_sent(campaign_id=campaign_id,
                contact=db.query_one("SELECT * FROM contacts WHERE id = ?", (contact_id,)),
                status="sent", sent_at=db.now())

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
def test_the_named_copy_of_python_is_left_byte_for_byte_identical():
    """HomingPigeon.exe has to stay a plain copy, so python.org's signature holds.

    An earlier version rewrote the copy's version resource, which fixed the
    description column in Task Manager and invalidated its Authenticode
    signature at the same time. A file carrying a signature that no longer
    checks out looks worse to Windows and to antivirus than a file that was
    never signed, so the copy is now left exactly as python.org shipped it.
    """
    import importlib.util
    import shutil
    import subprocess
    import sys
    import tempfile
    from pathlib import Path as _Path

    path = _Path(__file__).resolve().parent.parent / "installer" / "setup_app.py"
    spec = importlib.util.spec_from_file_location("setup_app_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    for gone in ("stamp_version", "version_resource"):
        assert not hasattr(module, gone), f"{gone} is back, and it breaks the signature"
    assert "UpdateResourceW" not in path.read_text(encoding="utf-8")

    # Stand in for the "prove it runs" check: a bare copy of python.exe in an
    # empty folder has no DLLs beside it, so it could not start here anyway.
    class Finished:
        returncode = 0
        stderr = b""

    class FakeSubprocess:
        TimeoutExpired = subprocess.TimeoutExpired

        @staticmethod
        def run(*_args, **_kwargs):
            return Finished()

    real = module.subprocess
    module.subprocess = FakeSubprocess
    try:
        with tempfile.TemporaryDirectory() as tmp:
            python_dir = _Path(tmp) / "python"
            python_dir.mkdir()
            shutil.copy2(sys.executable, python_dir / "pythonw.exe")
            before = (python_dir / "pythonw.exe").read_bytes()

            made = module.build_named_exe(_Path(tmp))

            assert made.name == "HomingPigeon.exe", "the shortcuts lost the app's name"
            assert made.read_bytes() == before, "something wrote into the copy"
    finally:
        module.subprocess = real


def test_the_installer_is_built_as_one_folder_and_never_upx_packed():
    """A one-file build is what Defender's model read as a dropper.

    "HomingPigeon Setup.exe" was detected as Trojan:Win32/Wacatac.B!ml on
    download. A one-file build is a small stub followed by megabytes of
    compressed data, which is structurally what a self-extracting dropper is,
    and none of the strings showing what it actually does survive the packing.
    UPX packing would make it worse again, so it is refused explicitly rather
    than left to depend on whether the build machine happens to have UPX.
    """
    from pathlib import Path as _Path

    source = (_Path(__file__).resolve().parent.parent
              / "tools" / "build_installer.py").read_text(encoding="utf-8")
    command = source[source.index("command = ["):source.index("str(ROOT / \"installer\"")]
    assert '"--onedir"' in command
    assert '"--noupx"' in command
    assert '"--onefile"' not in command, "back to a one-file build"
    assert '"--contents-directory"' in command


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
    for pattern in ("*.py", "*.md", "*.txt", "*.bat", "*.sh", "*.command", "*.json"):
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



# --- the My message page ----------------------------------------------------
def test_ctrl_and_shift_enter_start_a_new_line(qt_app):
    from PyQt6.QtTest import QTest

    from app.ui.widgets.inputs import text_box

    box = text_box()
    QTest.keyClicks(box, "one")
    QTest.keyClick(box, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClicks(box, "two")
    QTest.keyClick(box, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    QTest.keyClicks(box, "three")
    assert box.toPlainText() == "one\ntwo\nthree"   # plain new lines, no U+2028


def test_my_message_page_scrolls_when_it_fills_up(qt_app, store):
    """Many subjects used to be squeezed into a fixed frame with no way to reach them."""
    from PyQt6.QtTest import QTest

    from app.ui.main_window import MainWindow

    qt_app.setStyleSheet(theme.stylesheet())
    window = MainWindow()
    window.resize(1000, 650)
    window.show()
    try:
        window.show_page("templates")
        page = window.page("templates")
        for index in range(15):
            page._add_subject(f"Subject {index}")
        QTest.qWait(100)   # let the layout grow to fit them
        bar = page.scroll.verticalScrollBar()
        assert bar.maximum() > 0, "the page does not scroll"
        last = page.subject_editors[-1]
        page.scroll.ensureWidgetVisible(last)
        qt_app.processEvents()
        assert bar.value() > 0
        # Every box keeps its own height rather than being squashed to fit
        assert all(e.editor.height() == last.editor.height() for e in page.subject_editors)
    finally:
        window.close()
        window.deleteLater()


def test_toolbar_buttons_act_on_the_box_last_typed_in(qt_app, store):
    from app.ui.main_window import MainWindow

    window = MainWindow()
    try:
        window.show_page("templates")
        page = window.page("templates")
        first = page._add_body("")
        page._add_body("")
        page._remember_focus(first)
        page._insert(True, "{{Company}}")
        assert first.get_text() == "<p>{{Company}}</p>"
        assert page.body_editors[1].get_text() == ""
        first.editor.selectAll()
        page._toolbars["message"][0].buttons["bold"].click()
        assert first.get_text() == "<p><strong>{{Company}}</strong></p>"
    finally:
        window.close()
        window.deleteLater()


# --- v0.6.2 -----------------------------------------------------------------
def test_the_contact_list_shows_every_imported_column(qt_app, store):
    import pandas as pd

    from app.core import importer
    from app.models.contacts_model import ContactsModel

    columns = {f"Detail {n}": [f"v{n}"] for n in range(25)}
    df = pd.DataFrame({"Email": ["many@example.com"], **columns})
    importer.import_dataframe(df, importer.detect_columns(df), check_mx=False)

    model = ContactsModel()
    model.reload()
    headers = [model.headerData(i, Qt.Orientation.Horizontal) for i in range(model.columnCount())]
    assert all(f"Detail {n}" in headers for n in range(25))


def test_new_columns_reach_the_personal_touch_buttons_without_a_restart(qt_app, store):
    import pandas as pd

    from app.core import importer
    from app.ui.main_window import MainWindow

    window = MainWindow()
    try:
        window.show_page("templates")
        page = window.page("templates")
        df = pd.DataFrame({"Email": ["tags@example.com"],
                           **{f"Field {n}": ["x"] for n in range(10)}})
        importer.import_dataframe(df, importer.detect_columns(df), check_mx=False)

        page.on_show()
        assert all(f"Field {n}" in page._tag_names for n in range(10))
        for layout in page._tag_layouts[True]:   # the toolbar and its pinned copy
            texts = [layout.itemAt(i).widget().text() for i in range(layout.count())]
            assert "{{Field 9}}" in texts
    finally:
        window.close()
        window.deleteLater()


def test_the_unsubscribe_switch_is_saved_straight_away(qt_app, store):
    from app.ui.main_window import MainWindow

    window = MainWindow()
    try:
        window.show_page("templates")
        page = window.page("templates")
        assert page.unsubscribe_box.isChecked()
        page.unsubscribe_box.setChecked(False)
        assert db.get_setting("unsubscribe_note", True) is False
        assert page.current_content().unsubscribe_note is False
    finally:
        window.close()
        window.deleteLater()


def test_a_sent_email_opens_in_its_own_window(qt_app, store):
    from app.ui.pages.sent import SentEmailDialog

    _record_send("viewer@example.com", "sent")
    row = db.query_one("SELECT id FROM sent_log WHERE email = 'viewer@example.com'")
    dialog = SentEmailDialog(None, db.sent_message(row["id"]))
    assert dialog._html == "<p>Hi there</p>"
    dialog.deleteLater()

    # One recorded before v0.6.2 has no body: it still opens, with a note instead
    old = db.sent_message(row["id"])
    old["body_html"] = ""
    SentEmailDialog(None, old).deleteLater()


def test_deleting_from_the_sent_page_keeps_the_rest(qt_app, store):
    from app.models.sent_model import SentModel

    for name in ("a", "b", "c"):
        _record_send(f"{name}@delete.test", "sent")
    model = SentModel()
    model.reload()
    assert model.delete_rows([0]) == 1
    assert model.rowCount() == 2
    # Who was contacted is still known, so nobody is emailed twice
    assert db.query_one("SELECT COUNT(*) AS n FROM campaign_recipients")["n"] == 3


# --- v0.7.1 -----------------------------------------------------------------
def test_a_new_subject_or_message_goes_to_the_top(qt_app, store):
    from app.ui.main_window import MainWindow

    window = MainWindow()
    try:
        window.show_page("templates")
        page = window.page("templates")
        page._add_subject("old one")
        page._new_subject()
        assert page.subject_editors[0].get_text() == ""
        assert page.subject_editors[1].get_text() == "old one"
        assert page.subject_editors[0].enabled_box.text().endswith("1")
        assert page.subjects_layout.indexOf(page.subject_editors[0]) == 0
        page._add_body("old message")
        page._new_body()
        assert page.body_editors[0].get_text() == ""
    finally:
        window.close()
        window.deleteLater()


def test_the_personal_touch_bar_stays_in_view_when_scrolling(qt_app, store):
    from PyQt6.QtTest import QTest

    from app.ui.main_window import MainWindow

    qt_app.setStyleSheet(theme.stylesheet())
    window = MainWindow()
    window.resize(1000, 650)
    window.show()
    try:
        window.show_page("templates")
        page = window.page("templates")
        for index in range(15):
            page._add_subject(f"Subject {index}")
        QTest.qWait(100)
        bar = page.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())
        QTest.qWait(50)
        sticky = page._subjects_sticky
        assert sticky.floating
        assert sticky.bar.y() == page.scroll.viewport().y()
        bar.setValue(0)
        QTest.qWait(50)
        assert not sticky.floating
        bar.setValue(bar.maximum())
        QTest.qWait(50)
        page.tabs.set("Message")
        assert not sticky.floating
    finally:
        window.close()
        window.deleteLater()


def test_the_design_page_builds_edits_and_protects_the_message(qt_app, store):
    from app.core import design
    from app.ui.main_window import MainWindow

    window = MainWindow()
    window.resize(1300, 800)
    window.show()
    try:
        window.show_page("design")
        page = window.page("design")
        assert page.library.isVisible() and page.none_title.isVisible()
        assert design.list_designs() == []
        page._create("announcement", "Announcement")
        assert page.editor.isVisible() and not page.library.isVisible()
        blocks = page._design["blocks"]
        message = next(b for b in blocks if b["type"] == "message")
        count = len(blocks)
        page._block_action(message["id"], "remove")
        assert len(page._design["blocks"]) == count
        page._select("")
        page._add_block("quote")
        assert len(page._design["blocks"]) == count + 1
        page._remember.flush()
        page.undo()
        assert len(page._design["blocks"]) == count
        page.redo()
        assert len(page._design["blocks"]) == count + 1
        page.save()
        page.use_box.setChecked(True)
        assert design.active_id() == page._id
        assert len(design.active()["blocks"]) == count + 1
        page.view_choice.set("phone", notify=True)
        assert page.layers.count() == count + 1
        quote = next(b for b in page._design["blocks"] if b["type"] == "quote")
        page._select(quote["id"])
        page._set(quote, "text", "Changed")
        assert page._dirty
    finally:
        window.close()
        window.deleteLater()


def test_designs_page_lists_renames_autosaves_and_keeps_a_file(qt_app, store, monkeypatch):
    from app import config
    from app.core import design
    from app.ui.main_window import MainWindow
    from app.workers import base as workers

    recycled = []
    monkeypatch.setattr(design, "recycle_file", recycled.append)
    window = MainWindow()
    window.resize(1300, 800)
    window.show()
    try:
        window.show_page("design")
        page = window.page("design")
        page._create("blank", "Blank")
        workers.pool().waitForDone(3000)
        assert (Path(config.DESIGNS_DIR) / "Blank.hpdesign").exists()

        # Renamed in place, beside the Undo buttons; the file follows the name
        page._rename_clicked()
        assert not page.name_edit.isHidden()
        page.name_edit.setText("Spring offer")
        page._rename_clicked()
        workers.pool().waitForDone(3000)
        assert page.name_edit.isHidden() and page.name_label.text() == "Spring offer"
        assert [d["name"] for d in design.list_designs()] == ["Spring offer"]
        assert sorted(f.name for f in Path(config.DESIGNS_DIR).iterdir()) == ["Spring offer.hpdesign"]

        # Changes save themselves
        page._add_block("quote")
        assert page._dirty
        page._autosave.flush()
        assert not page._dirty
        assert any(b["type"] == "quote" for b in design.load(page._id)["blocks"])

        # New design goes back to the page of designs, which lists this one
        page._new_design()
        assert page.library.isVisible() and not page.editor.isVisible()
        assert page.mine_layout.count() == 1 and page.mine_title.isVisible()
        page._duplicate(page._id)
        assert page.mine_layout.count() == 2

        page.notify = lambda *a, **k: None
        from app.ui.widgets import dialogs
        monkeypatch.setattr(dialogs.ConfirmDialog, "ask", staticmethod(lambda *a, **k: True))
        page._delete(design.list_designs()[0]["id"])
        assert recycled == ["Spring offer"] and page.mine_layout.count() == 1
    finally:
        window.close()
        window.deleteLater()


def test_the_design_page_drops_types_and_resizes_on_the_email(qt_app, store):
    from PyQt6.QtCore import QPoint

    from app.ui.main_window import MainWindow

    window = MainWindow()
    window.resize(1300, 800)
    window.show()
    try:
        window.show_page("design")
        page = window.page("design")
        page._create("announcement", "Announcement")
        page._redraw.flush()
        blocks = page._design["blocks"]
        count = len(blocks)

        # A block dragged in from the Add panel lands where it was dropped
        page._dropped("new", "spacer", 0)
        assert blocks[0]["type"] == "spacer" and len(blocks) == count + 1
        page._dropped("new", "message", 0)      # never a second message block
        assert len(blocks) == count + 1

        # Dragging a block on the email moves it
        spacer = blocks[0]
        page._dropped("move", spacer["id"], len(blocks))
        assert blocks[-1] is spacer

        # Typing straight onto the email
        from app.ui.widgets.email_canvas import INLINE

        words = next(b for b in blocks if b["type"] in INLINE)
        page._edit_on_email(words["id"])
        assert page.canvas._typing is not None
        page.canvas._typing[0].setPlainText("Hello there")
        page.canvas.finish_typing()
        assert words[INLINE[words["type"]]] == "Hello there"

        # The handle under empty space changes its height, within its limits
        page._select(spacer["id"])
        page._redraw.flush()
        page.canvas.begin_resize()
        page.canvas.resize_by(QPoint(0, 40))
        assert spacer["height"] == 64
        page.canvas.resize_by(QPoint(0, 9000))
        assert spacer["height"] == 200
        page.canvas.end_resize()
    finally:
        window.close()
        window.deleteLater()


def test_the_custom_warmup_plan_is_saved(qt_app, store):
    from app.core import warmup
    from app.ui.main_window import MainWindow

    window = MainWindow()
    try:
        window.show_page("campaign")
        page = window.page("campaign")
        page.plan_choice.set("custom", notify=True)
        assert page.ramp_editor.isVisibleTo(page)
        page.ramp_editor.start.setValue(10)
        page.ramp_editor.step.setValue(10)
        page.ramp_editor.stop.setValue(30)
        page.ramp_editor._fill()
        assert page.ramp_editor.ramp() == [10, 20, 30]
        page.save()
        assert warmup.preset() == "custom" and warmup.custom_ramp() == [10, 20, 30]
    finally:
        window.close()
        window.deleteLater()


# --- v0.7.3: the Outlook-style editor ------------------------------------------
def test_the_editor_writes_tidy_email_html(qt_app):
    from PyQt6.QtGui import QTextCursor

    from app.ui.widgets.rich_text import RichBox

    box = RichBox()
    assert box.html() == ""
    typed = "Hi {{FirstName}},\n\nI run a small shop.\nSecond line.\n\n- one\n- two\n\nThanks,\nSam"
    box.set_html(typed)
    plain = box.html()
    # Typed text comes out as plain paragraphs, with no styling the spam score would count
    assert "style=" not in plain and "<strong>" not in plain
    assert plain.startswith("<p>Hi {{FirstName}},</p>")
    assert "<p>I run a small shop.<br>Second line.</p>" in plain
    assert "<ul>\n  <li>one</li>\n  <li>two</li>\n</ul>" in plain
    box.set_html(plain)
    assert box.html() == plain          # reading it back changes nothing

    # Select "small" and change it the way the toolbar does
    cursor = box.textCursor()
    start = box.toPlainText().index("small")
    cursor.setPosition(start)
    cursor.setPosition(start + len("small"), QTextCursor.MoveMode.KeepAnchor)
    box.setTextCursor(cursor)
    box.toggle_bold()
    box.toggle_italic()
    box.set_size(18)
    box.set_colour("#c00000")
    html = box.html()
    assert '<strong><em><span style="font-size:18pt;color:#c00000">small</span></em></strong>' in html
    box.clear_formatting()
    assert box.html() == plain


def test_the_signature_and_footer_are_saved_with_the_message(qt_app, store):
    from app.core import db
    from app.ui.main_window import MainWindow

    window = MainWindow()
    try:
        window.show_page("templates")
        page = window.page("templates")
        page._add_subject("Hello")
        page._add_body("Hi there, a quick question?")
        page.signature_box.set_html("Sam Jones\nJones Supplies")
        page._insert_example_footer()
        page.save()
        record = db.query_one("SELECT * FROM template_sets")
        assert record["signature_html"] == "<p>Sam Jones<br>Jones Supplies</p>"
        assert "confidential" in record["footer_html"]
        assert page.current_content().footer_html == record["footer_html"]
        page.load()
        assert page.footer_box.html() == record["footer_html"]
    finally:
        window.close()
        window.deleteLater()


def test_smooth_scrolling_ignores_the_window_and_scrolls_the_page(qt_app, store):
    from PyQt6.QtCore import QPoint, QPointF
    from PyQt6.QtGui import QWheelEvent
    from PyQt6.QtTest import QTest

    from app.ui import scrolling
    from app.ui.main_window import MainWindow

    def wheel():
        return QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(), QPoint(0, -120),
                           Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                           Qt.ScrollPhase.NoScrollPhase, False)

    window = MainWindow()
    window.resize(1000, 650)
    window.show()
    try:
        window.show_page("templates")
        page = window.page("templates")
        for index in range(15):
            page._add_subject(f"Subject {index}")
        QTest.qWait(100)
        smooth = scrolling.ScrollFilter()
        # Qt hands every wheel turn to the QWindow first; that used to raise
        assert smooth.eventFilter(window.windowHandle(), wheel()) is False
        bar = page.scroll.verticalScrollBar()
        assert smooth.eventFilter(page.scroll.viewport(), wheel()) is True
        QTest.qWait(scrolling.DURATION_MS + 100)
        assert bar.value() > 0
    finally:
        window.close()
        window.deleteLater()


# --- v0.7.5: narrow windows, popups, importing one kind at a time --------------
class _BigScreen:
    """The offscreen test screen is 800 pixels wide; a real monitor is wider."""

    def availableGeometry(self):
        from PyQt6.QtCore import QRect

        return QRect(0, 0, 1920, 1040)


def test_send_buttons_never_overlap_in_a_narrow_window(qt_app, store):
    from PyQt6.QtTest import QTest

    from app.ui.main_window import MainWindow

    qt_app.setStyleSheet(theme.stylesheet())
    window = MainWindow()
    window.screen = lambda: _BigScreen()
    window.resize(760, 640)
    window.show()
    try:
        window.show_page("send")
        QTest.qWait(100)   # the window widens once the page has worked out its size
        page = window.page("send")
        # The window may not be squeezed below what the page on screen needs
        assert window.width() >= window.sidebar.width() + page.minimumSizeHint().width()
        widgets = [page.start_button, page.pause_button, page.stop_button, page.state_label,
                   page.new_campaign_button]
        boxes = [w.geometry().translated(w.parentWidget().mapTo(window, w.pos()) - w.pos())
                 for w in widgets]
        for index, box in enumerate(boxes):
            for other in boxes[index + 1:]:
                assert not box.intersects(other)
    finally:
        window.close()
        window.deleteLater()


def test_every_popup_can_be_resized_and_maximised(qt_app):
    from PyQt6.QtCore import Qt

    from app.ui.widgets.dialogs import ConfirmDialog, InfoDialog

    for dialog in (ConfirmDialog(None, "Title", "Message"),
                   InfoDialog(None, "Title", "Intro", [("Section", ["Point"])])):
        assert dialog.isSizeGripEnabled()
        assert dialog.windowFlags() & Qt.WindowType.WindowMaximizeButtonHint
        dialog.deleteLater()


def test_the_import_popup_adds_only_what_is_chosen(qt_app, store):
    from app.ui.main_window import MainWindow
    from app.ui.pages import templates

    window = MainWindow()
    try:
        window.show_page("templates")
        page = window.page("templates")
        dialog = templates.ImportDialog(page, "body", ["<p>One</p>", "Two"], "x.xlsx")
        assert page.body_editors == []
        dialog._cards[1][1].setFocus()
        dialog._focused = dialog._cards[1][1]
        dialog._insert("{{Company}}")
        dialog._add(dialog._cards[1])
        assert len(page.body_editors) == 1 and "{{Company}}" in page.body_editors[0].get_text()
        assert dialog.rest.isEnabled()
        dialog._add_rest()
        assert len(page.body_editors) == 2 and not dialog.rest.isEnabled()
        assert len(dialog.added) == 2
        dialog.deleteLater()

        subjects = templates.ImportDialog(page, "subject", ["Hello {{Company}}"], "x.xlsx")
        subjects._add(subjects._cards[0])
        assert [e.get_text() for e in page.subject_editors] == ["Hello {{Company}}"]
        subjects.deleteLater()
    finally:
        window.close()
        window.deleteLater()


def test_a_file_with_messages_too_opens_only_subjects_and_says_so(qt_app, store, monkeypatch):
    from PyQt6.QtWidgets import QLabel

    from app.core import importer
    from app.ui.main_window import MainWindow
    from app.ui.pages import templates

    opened = []
    monkeypatch.setattr(templates.ImportDialog, "exec", lambda self: opened.append(self) or 0)
    window = MainWindow()
    try:
        window.show_page("templates")
        page = window.page("templates")
        sheet = importer.TemplateSheet(subjects=["S1"], bodies=["B1"])
        page._sheet_ready("subject", sheet, "both.xlsx")
        assert [opened[0].kind, len(opened[0]._cards)] == ["subject", 1]
        notes = [label.text() for label in opened[0].findChildren(QLabel)]
        assert any("Message tab" in text for text in notes)
        opened[0].deleteLater()
    finally:
        window.close()
        window.deleteLater()


# --- v0.8: themes, menu order, date filters, import undo ------------------------
def test_every_ready_made_theme_builds_a_full_stylesheet(qt_app):
    from app.core import themes

    try:
        for key, spec in themes.PRESETS.items():
            theme.set_appearance(key)
            assert set(theme.derive(spec)) >= set(theme.DARK), key
            sheet = theme.stylesheet()
            assert "None" not in sheet
            if spec["gradient"]:
                assert "qlineargradient" in sheet, key
    finally:
        theme.set_appearance("Dark")


def test_import_undo_takes_the_item_back_out(qt_app, store):
    from app.ui.main_window import MainWindow
    from app.ui.pages import templates

    window = MainWindow()
    try:
        window.show_page("templates")
        page = window.page("templates")
        dialog = templates.ImportDialog(page, "subject", ["One", "Two"], "x.xlsx")
        dialog._press(dialog._cards[0])
        dialog._press(dialog._cards[1])
        assert [e.get_text() for e in page.subject_editors] == ["One", "Two"]
        dialog._press(dialog._cards[0])   # Undo
        assert [e.get_text() for e in page.subject_editors] == ["Two"]
        assert dialog.added == ["Two"] and dialog.rest.isEnabled()
        dialog._press(dialog._cards[0])   # and add it again
        assert sorted(e.get_text() for e in page.subject_editors) == ["One", "Two"]
        dialog.deleteLater()

        page.signature_box.set_html("<p>Old</p>")
        signatures = templates.ImportDialog(page, "signature", ["<p>New</p>"], "x.xlsx")
        from app.ui.widgets.dialogs import ConfirmDialog
        ConfirmDialog.ask, real = (lambda *a, **k: True), ConfirmDialog.ask
        try:
            signatures._press(signatures._cards[0])
        finally:
            ConfirmDialog.ask = real
        assert "New" in page.signature_box.html()
        signatures._press(signatures._cards[0])
        assert "Old" in page.signature_box.html()
        signatures.deleteLater()
    finally:
        window.close()
        window.deleteLater()


def test_import_and_export_follow_the_open_tab(qt_app, store):
    from app.ui.main_window import MainWindow

    window = MainWindow()
    try:
        window.show_page("templates")
        page = window.page("templates")
        page.tabs.set("Message")
        assert page.import_button.isEnabled() and "message" in page.import_button.toolTip()
        page.tabs.set("Preview & score")
        assert not page.import_button.isEnabled() and not page.export_button.isEnabled()
    finally:
        window.close()
        window.deleteLater()


def test_sent_log_date_filter(qt_app, store):
    from datetime import date, timedelta

    from app.models.sent_model import SentModel

    _record_send("today@example.com", "sent")
    db.execute("UPDATE sent_log SET sent_at = '2020-01-05T10:00:00' WHERE email = ?",
               ("today@example.com",))
    _record_send("now@example.com", "sent")
    model = SentModel()
    model.reload()
    model.set_dates(date(2020, 1, 5), date(2020, 1, 5))
    assert [model.email_at(r) for r in range(model.rowCount())] == ["today@example.com"]
    assert model.counts(*model.dates())["attempted"] == 1
    # The dates stay while another filter button is pressed
    model.set_filter("replied")
    model.set_filter("all")
    assert model.rowCount() == 1
    model.set_dates(date.today() - timedelta(days=1), date.today())
    assert [model.email_at(r) for r in range(model.rowCount())] == ["now@example.com"]


def test_inbox_search_and_dates(store):
    for uid, (name, subject, when) in enumerate([
            ("Sam", "Re: hello", "2026-10-01T09:00:00"),
            ("Ana", "Out of office", "2026-10-20T09:00:00")], start=1):
        db.save_message("INBOX", uid, from_name=name, from_email=f"{name}@x.example",
                        subject=subject, body="", received_at=when, kind="reply", known=True)
    assert [m["from_name"] for m in db.inbox_messages(search="office")] == ["Ana"]
    assert [m["from_name"] for m in db.inbox_messages(since="2026-10-01",
                                                      before="2026-10-02")] == ["Sam"]


def test_menu_order_and_hidden_pages_apply_to_the_sidebar(qt_app, store):
    from app.ui.main_window import MainWindow

    db.set_setting("nav_order", ["send", "dashboard"])
    db.set_setting("nav_hidden", ["guide", "dashboard"])
    window = MainWindow()
    try:
        layout = window._nav_layout
        assert layout.itemAt(0).widget() is window._nav["send"]
        assert window._nav["guide"].isHidden()
        assert not window._nav["dashboard"].isHidden()
    finally:
        window.close()
        window.deleteLater()


def test_phone_preview_keeps_the_email_inside_its_frame():
    from app.core import composer

    page = composer.phone_page('<p class="x">Hi & bye</p>', "Subject <b>", "Jamie")
    assert 'srcdoc="&lt;p class=&quot;x&quot;&gt;Hi &amp; bye&lt;/p&gt;"' in page
    assert "Subject &lt;b&gt;" in page


def test_making_a_theme_from_a_ready_made_one_leaves_it_alone(qt_app, store):
    from app.core import themes
    from app.ui.main_window import MainWindow
    from app.ui.widgets.theme_editor import ThemeEditor

    before = [list(spec["gradient"]) for spec in themes.PRESETS.values()]
    theme.set_appearance("midnight")
    window = MainWindow()
    try:
        editor = ThemeEditor(window)
        editor._set_stop(0, "#000000")
        editor.reject()
        assert [spec["gradient"] for spec in themes.PRESETS.values()] == before
        theme.set_appearance("custom:Gone")
        assert theme.is_dark()
    finally:
        theme.set_appearance("Dark")
        window.close()
        window.deleteLater()


# --- v0.8.1: sign in with Google or Microsoft ---------------------------------------
def test_account_page_signs_in_and_hides_the_password_boxes(qt_app, store, monkeypatch):
    from app import config
    from app.core import credentials
    from app.ui.main_window import MainWindow

    secrets: dict = {}
    monkeypatch.setattr(credentials, "save_secret", secrets.__setitem__)
    monkeypatch.setattr(credentials, "load_secret", lambda name, default="":
                        secrets.get(name, default))
    monkeypatch.setattr(credentials, "delete_secret", lambda name: secrets.pop(name, None))
    monkeypatch.setattr(config, "GOOGLE_CLIENT_ID", "id.apps.googleusercontent.com")
    monkeypatch.setattr(config, "MICROSOFT_CLIENT_ID", "")

    qt_app.setStyleSheet(theme.stylesheet())
    window = MainWindow()
    window.show()
    try:
        window.show_page("account")
        qt_app.processEvents()
        page = window.page("account")
        assert [button.text() for button in page.smtp_sign_in.buttons] == ["Sign in with Google"]
        assert page.password_row.isVisible() and page.imap_user_row.isVisible()

        page._signed_in("smtp", {"provider": "google", "email": "me@gmail.com",
                                 "refresh_token": "r"})
        qt_app.processEvents()
        assert not page.password_row.isVisible() and not page.imap_password_row.isVisible()
        assert page.imap_host_box.text() == "imap.gmail.com"
        assert db.get_setting("imap_username") == "me@gmail.com"
        assert "me@gmail.com" in page.smtp_sign_in.status.text()

        page.sign_out("smtp")
        qt_app.processEvents()
        assert page.password_row.isVisible()
        assert not page.imap_password_row.isVisible(), "the inbox stays signed in"

        for key in ("sent", "dashboard"):
            window.show_page(key)
            qt_app.processEvents()
    finally:
        window.close()
        window.deleteLater()
