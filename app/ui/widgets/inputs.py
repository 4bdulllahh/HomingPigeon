"""Text inputs, drop-downs and the debounce helper the editors rely on."""
from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QCompleter, QLineEdit, QPlainTextEdit,
                             QRadioButton, QWidget)

from app.i18n import t
from app.ui import theme


# --- text -------------------------------------------------------------------
def line_edit(placeholder: str = "", text: str = "", parent=None) -> QLineEdit:
    widget = QLineEdit(parent)
    widget.setPlaceholderText(t(placeholder))
    if text:
        widget.setText(t(text))
    widget.setClearButtonEnabled(False)
    return widget


def password_edit(placeholder: str = "", parent=None) -> QLineEdit:
    widget = line_edit(placeholder, parent=parent)
    widget.setEchoMode(QLineEdit.EchoMode.Password)
    return widget


class TextBox(QPlainTextEdit):
    """A plain-text editor where every Enter key starts a new line.

    Qt only treats a bare Enter as a new line. Ctrl+Enter, which people use in
    chat programs and webmail, did nothing at all, and Shift+Enter inserted an
    invisible Unicode line separator rather than an ordinary one.
    """

    def keyPressEvent(self, event):  # noqa: N802 - Qt naming
        if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not self.isReadOnly()
                and event.modifiers() & (Qt.KeyboardModifier.ControlModifier
                                         | Qt.KeyboardModifier.ShiftModifier)):
            self.insertPlainText("\n")
            self.ensureCursorVisible()
            event.accept()
            return
        super().keyPressEvent(event)


def text_box(placeholder: str = "", monospace: bool = False, lines: int | None = None,
             parent=None) -> QPlainTextEdit:
    widget = TextBox(parent)
    widget.setPlaceholderText(t(placeholder))
    if monospace:
        widget.setProperty("role", "mono")
    widget.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
    widget.setTabChangesFocus(True)
    widget.verticalScrollBar().setSingleStep(18)
    if lines:
        widget.setFixedHeight(_height_for_lines(widget, lines))
    return widget


def read_only_box(text: str = "", role: str = "mono", lines: int = 4, parent=None) -> QPlainTextEdit:
    widget = QPlainTextEdit(parent)
    widget.setProperty("role", role)
    widget.setPlainText(text)
    widget.setReadOnly(True)
    widget.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
    widget.setFixedHeight(_height_for_lines(widget, lines))
    return widget


def _height_for_lines(widget: QPlainTextEdit, lines: int) -> int:
    spacing = widget.fontMetrics().lineSpacing()
    return int(spacing * lines + 16 * theme.text_scale())


def set_text(widget: QPlainTextEdit, text: str) -> None:
    """Replace the contents without losing the scroll position or firing edits twice."""
    if widget.toPlainText() == text:
        return
    blocked = widget.blockSignals(True)
    widget.setPlainText(text)
    widget.blockSignals(blocked)


def get_text(widget: QPlainTextEdit) -> str:
    return widget.toPlainText().rstrip("\n")


# --- choosers ---------------------------------------------------------------
class Combo(QComboBox):
    """A drop-down that shows its choices translated but hands the code the English.

    Page code compares and saves the English value ("Automatic", "(none)"), so
    ``currentText()`` and ``setCurrentText()`` work in English whatever language
    is on screen. Choices that are the user's own data (sheet names, column
    headings, times) are shown exactly as they are.

    ``translate`` is True for every choice, False for none, or a set of the
    English values to translate (for a list of data with one app choice in it).
    """

    def __init__(self, translate: bool | set = True, parent=None):
        super().__init__(parent)
        self._translate = translate

    def _shown(self, value: str) -> str:
        wanted = self._translate is True or (
            isinstance(self._translate, set) and value in self._translate)
        return t(value) if wanted else value

    def set_values(self, values: list[str]) -> None:
        self.clear()
        for value in values:
            self.addItem(self._shown(value), value)

    def currentText(self) -> str:  # noqa: N802 - Qt naming
        value = self.currentData()
        return value if isinstance(value, str) else super().currentText()

    def setCurrentText(self, text: str) -> None:  # noqa: N802 - Qt naming
        index = self.findData(text)
        if index >= 0:
            self.setCurrentIndex(index)
        else:
            super().setCurrentText(text)


def combo(values: list[str], value: str | None = None, on_change: Callable | None = None,
          parent=None, translate: bool | set = True) -> QComboBox:
    widget = Combo(translate, parent)
    widget.set_values(values)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    # Wheel over a drop-down inside a scrolling page should scroll the page,
    # not silently change the setting under the pointer.
    widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    widget.installEventFilter(_WheelGuard.instance(widget))
    if value is not None and value in values:
        widget.setCurrentText(value)
    if on_change:
        # Called with the English value, like currentText()
        widget.currentIndexChanged.connect(lambda _index: on_change(widget.currentText()))
    return widget


def set_combo_values(widget: QComboBox, values: list[str], value: str | None = None) -> None:
    blocked = widget.blockSignals(True)
    if isinstance(widget, Combo):
        widget.set_values(values)
    else:
        widget.clear()
        widget.addItems(values)
    if value and value in values:
        widget.setCurrentText(value)
    widget.blockSignals(blocked)


def checkbox(text: str, checked: bool = False, on_change: Callable | None = None,
             parent=None) -> QCheckBox:
    widget = QCheckBox(t(text), parent)
    widget.setChecked(checked)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    if on_change:
        widget.toggled.connect(on_change)
    return widget


def radio(text: str, checked: bool = False, on_change: Callable | None = None,
          parent=None) -> QRadioButton:
    widget = QRadioButton(t(text), parent)
    widget.setChecked(checked)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    if on_change:
        widget.toggled.connect(on_change)
    return widget


def attach_completer(widget: QLineEdit, options: list[str]) -> QCompleter:
    """Type-ahead over a list of addresses, matching anywhere in the string."""
    completer = QCompleter(options, widget)
    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    completer.setFilterMode(Qt.MatchFlag.MatchContains)
    completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
    completer.setMaxVisibleItems(10)
    widget.setCompleter(completer)
    return completer


def update_completer(widget: QLineEdit, options: list[str]) -> None:
    from PyQt6.QtCore import QStringListModel

    completer = widget.completer()
    if completer is None:
        attach_completer(widget, options)
        return
    model = completer.model()
    if isinstance(model, QStringListModel):
        model.setStringList(options)
    else:
        completer.setModel(QStringListModel(options, completer))


class _WheelGuard(QObject):
    """Stops the wheel from changing a combo box that merely has the pointer over it.

    One guard for the whole application, owned by the application object. It
    used to be parented to whichever widget happened to ask for it first, and
    the cached Python reference outlived that widget: the next combo box built
    after the owner was destroyed got handed a dead wrapper and Qt raised
    "wrapped C/C++ object of type _WheelGuard has been deleted". Changing the
    text size destroys every page, so this happened routinely.
    """

    _instance: "_WheelGuard | None" = None

    @classmethod
    def instance(cls, parent: QWidget) -> "_WheelGuard":
        guard = cls._instance
        if guard is not None:
            try:
                guard.objectName()      # touching a deleted wrapper raises
            except RuntimeError:
                guard = cls._instance = None
        if guard is None:
            from PyQt6.QtWidgets import QApplication

            owner = QApplication.instance() or parent.window() or parent
            guard = cls._instance = _WheelGuard(owner)
        return guard

    def eventFilter(self, obj, event):  # noqa: N802 - Qt naming
        from PyQt6.QtCore import QEvent

        if event.type() == QEvent.Type.Wheel and isinstance(obj, QComboBox):
            if not obj.hasFocus():
                event.ignore()
                return True
        return False


# --- debounce ---------------------------------------------------------------
class Debouncer(QObject):
    """Run a callback once the user stops typing.

    Spam scoring parses the whole message body and runs a dozen regular
    expressions; doing that per keystroke is what made the old editor stutter.
    Every keystroke restarts this timer instead, so the work happens once.
    """

    triggered = pyqtSignal()

    def __init__(self, delay_ms: int = 400, parent=None):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(self.triggered.emit)

    def poke(self) -> None:
        self._timer.start()

    def cancel(self) -> None:
        self._timer.stop()

    def flush(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
            self.triggered.emit()

    def connect(self, callback: Callable[[], None]) -> None:
        self.triggered.connect(callback)
