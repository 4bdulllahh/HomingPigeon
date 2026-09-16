"""The building blocks every page is made of.

Styling lives in the application stylesheet, so these are deliberately thin:
they set a ``role`` or ``tone`` property and let QSS do the rest. That is what
lets a theme change repaint the whole app without rebuilding a single widget.
"""
from __future__ import annotations

import webbrowser
from typing import Callable

from PyQt6.QtCore import (QEasingCurve, QEvent, QPropertyAnimation, Qt, QTimer,
                          pyqtSignal)
from PyQt6.QtGui import QAction, QActionGroup, QGuiApplication
from PyQt6.QtWidgets import (QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLayout,
                             QMenu, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
                             QVBoxLayout, QWidget)

from app.ui import theme
from app.ui.widgets.flow import FlowLayout


# --- property helpers -------------------------------------------------------
def restyle(widget: QWidget) -> None:
    """Re-apply the stylesheet after changing a dynamic property.

    Qt does not re-evaluate property selectors on its own, so every place that
    flips ``choice``/``tone``/``nav`` has to ask for it.
    """
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)


def set_role(widget: QWidget, role: str) -> QWidget:
    widget.setProperty("role", role)
    return widget


def set_tone(widget: QWidget, tone: str | None) -> QWidget:
    widget.setProperty("tone", tone or "")
    restyle(widget)
    return widget


# --- text -------------------------------------------------------------------
def _label(text: str, role: str, wrap: bool, parent=None) -> QLabel:
    label = QLabel(text, parent)
    label.setProperty("role", role)
    label.setWordWrap(wrap)
    if wrap:
        # Without heightForWidth a wrapped label is measured as one line, and
        # nested layouts then overlap the rows underneath it.
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        policy.setHeightForWidth(True)
        label.setSizePolicy(policy)
        label.setMinimumHeight(0)
    return label


def heading(text: str, parent=None) -> QLabel:
    return _label(text, "heading", False, parent)


def subheading(text: str, parent=None) -> QLabel:
    return _label(text, "subheading", False, parent)


def body(text: str, parent=None, wrap: bool = True) -> QLabel:
    return _label(text, "body", wrap, parent)


def muted(text: str, parent=None, wrap: bool = True) -> QLabel:
    return _label(text, "muted", wrap, parent)


def hint(text: str, parent=None, wrap: bool = True) -> QLabel:
    return _label(text, "hint", wrap, parent)


def field_label(text: str, parent=None) -> QLabel:
    return _label(text, "field", False, parent)


def selectable(label: QLabel) -> QLabel:
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


# --- structure --------------------------------------------------------------
def separator(parent=None, vertical: bool = False) -> QFrame:
    line = QFrame(parent)
    line.setProperty("role", "separator")
    if vertical:
        line.setFixedWidth(1)
    else:
        line.setFixedHeight(1)
    return line


def spacer(height: int = 0) -> QWidget:
    widget = QWidget()
    widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    if height:
        widget.setFixedHeight(height)
    else:
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    return widget


def row(*widgets: QWidget, spacing: int = 8, stretch: int | None = None) -> QWidget:
    """A horizontal strip.

    Pass ``None`` in place of a widget to insert a stretch there, or ``stretch``
    as the index of the widget that should take up the spare width.
    """
    container = QWidget()
    container.setProperty("role", "plain")
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    for index, widget in enumerate(widgets):
        if widget is None:
            layout.addStretch(1)
        else:
            layout.addWidget(widget, 1 if index == stretch else 0)
    return container


def column(*widgets: QWidget, spacing: int = 8, margins: tuple = (0, 0, 0, 0)) -> QWidget:
    container = QWidget()
    container.setProperty("role", "plain")
    layout = QVBoxLayout(container)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    for widget in widgets:
        if widget is None:
            layout.addStretch(1)
        else:
            layout.addWidget(widget)
    return container


def flow_row(spacing: int = 8) -> tuple[QWidget, FlowLayout]:
    """A container whose buttons wrap onto a second line when space runs out."""
    container = QWidget()
    container.setProperty("role", "plain")
    layout = FlowLayout(container, margin=0, spacing=spacing)
    return container, layout


class Card(QFrame):
    """A padded panel. ``kind`` picks the border: plain, danger or tinted."""

    def __init__(self, parent=None, kind: str = "card", padding: int = 16):
        super().__init__(parent)
        self.setProperty("role", kind)
        pad = round(padding * theme.text_scale())
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(pad, pad, pad, pad)
        self.layout_.setSpacing(round(8 * theme.text_scale()))

    def add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self.layout_.addWidget(widget, stretch)
        return widget

    def add_layout(self, layout: QLayout) -> QLayout:
        self.layout_.addLayout(layout)
        return layout

    def add_stretch(self) -> None:
        self.layout_.addStretch(1)


class Section(Card):
    """A titled card. Page content goes into ``.body``."""

    def __init__(self, title: str, description: str = "", parent=None, kind: str = "section"):
        super().__init__(parent, kind=kind, padding=18)
        title_label = QLabel(title)
        title_label.setProperty("role", "section-title")
        self.layout_.addWidget(title_label)
        if description:
            note = muted(description)
            self.layout_.addWidget(note)
        self.body = QWidget()
        self.body.setProperty("role", "plain")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, round(6 * theme.text_scale()), 0, 0)
        self.body_layout.setSpacing(round(8 * theme.text_scale()))
        self.layout_.addWidget(self.body)

    def add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self.body_layout.addWidget(widget, stretch)
        return widget

    def add_layout(self, layout: QLayout) -> QLayout:
        self.body_layout.addLayout(layout)
        return layout


class FormRow(QWidget):
    """A label above an input, with an optional hint underneath."""

    def __init__(self, label: str, note: str = "", parent=None):
        super().__init__(parent)
        self.setProperty("role", "plain")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        layout.addWidget(field_label(label))
        self.input_area = QWidget()
        self.input_area.setProperty("role", "plain")
        self.input_layout = QVBoxLayout(self.input_area)
        self.input_layout.setContentsMargins(0, 0, 0, 0)
        self.input_layout.setSpacing(6)
        layout.addWidget(self.input_area)
        if note:
            layout.addWidget(hint(note))

    def add(self, widget: QWidget) -> QWidget:
        self.input_layout.addWidget(widget)
        return widget


class StatTile(Card):
    """A big number with a caption and a one-line hint."""

    def __init__(self, caption: str, value: str = "-", note: str = "", tone: str | None = None,
                 parent=None):
        super().__init__(parent, kind="card", padding=14)
        self.layout_.setSpacing(1)
        self.value_label = QLabel(value)
        self.value_label.setProperty("role", "value")
        if tone:
            self.value_label.setProperty("tone", tone)
        self.caption_label = muted(caption, wrap=False)
        self.note_label = hint(note, wrap=False)
        self.layout_.addWidget(self.value_label)
        self.layout_.addWidget(self.caption_label)
        self.layout_.addWidget(self.note_label)

    def update_value(self, value: str, note: str = "", tone: str | None = None) -> None:
        self.value_label.setText(str(value))
        if tone is not None:
            set_tone(self.value_label, tone)
        self.note_label.setText(note)


class ProgressRow(QWidget):
    """A slim progress bar with the percentage printed beside it.

    QProgressBar draws its own "42%" centred *inside* the track, and the app's
    track is six pixels tall, so the text was clipped to a smear across the
    middle of the bar. Keeping the bar thin and putting the number next to it
    is legible at every text size and in all four themes.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("role", "plain")
        scale = theme.text_scale()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(round(10 * scale))

        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        layout.addWidget(self.bar, 1)

        self.percent = QLabel("")
        self.percent.setProperty("role", "field")
        self.percent.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.percent.setFixedWidth(round(44 * scale))
        layout.addWidget(self.percent)

    def set_busy(self) -> None:
        """Sweeping bar, no number: used until the first real count arrives."""
        self.bar.setRange(0, 0)
        self.percent.setText("")

    def set_progress(self, done: int, total: int) -> None:
        if total <= 0:
            self.set_busy()
            return
        if self.bar.maximum() != total:
            self.bar.setRange(0, total)
        self.bar.setValue(min(done, total))
        self.percent.setText(f"{round(done / total * 100)}%")

    def reset(self) -> None:
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.percent.setText("")


def status_glyph(status: str, parent=None) -> QLabel:
    """A pass/warn/fail symbol sized to sit on a heading's line."""
    label = QLabel(theme.STATUS_ICONS.get(str(status).lower(), "○"), parent)
    label.setStyleSheet(f"color: {theme.status_color(status)}; font-weight: 700;")
    label.setFixedWidth(round(22 * theme.text_scale()))
    label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
    return label


class StatusRow(QWidget):
    """One pass/warn/fail line with an expandable detail area."""

    def __init__(self, title: str, status: str = "pending", summary: str = "", detail: str = "",
                 record: str = "", fix: str = "", extras: list[str] | None = None, parent=None):
        super().__init__(parent)
        self.setProperty("role", "plain")
        self.record = record

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(8)
        header.addWidget(status_glyph(status), 0, Qt.AlignmentFlag.AlignTop)

        text = QVBoxLayout()
        text.setSpacing(1)
        title_label = QLabel(title)
        title_label.setProperty("role", "subheading")
        text.addWidget(title_label)
        if summary:
            text.addWidget(muted(summary))
        header.addLayout(text, 1)

        has_detail = bool(detail or record or fix or extras)
        if has_detail:
            self.toggle = small_button("Details", self._toggle)
            header.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignTop)
        outer.addLayout(header)

        if has_detail:
            self.detail_panel = self._build_detail(detail, record, fix, extras or [])
            self.detail_panel.setVisible(False)
            outer.addWidget(self.detail_panel)
        outer.addWidget(separator())

    def _build_detail(self, detail: str, record: str, fix: str, extras: list[str]) -> QWidget:
        from app.ui.widgets.inputs import read_only_box

        card = Card(kind="card", padding=12)
        if detail:
            card.add(body(detail))
        for extra in extras:
            card.add(muted(f"•  {extra}"))
        if record:
            box = read_only_box(record, role="code", lines=min(6, 1 + record.count("\n")))
            card.add(box)
            copy = small_button("Copy record", lambda: self._copy(record))
            card.add(row(copy, None))
        if fix:
            label = field_label("How to fix:")
            set_tone(label, "warning")
            card.add(label)
            card.add(body(fix))
        return card

    def _copy(self, text: str) -> None:
        copy_to_clipboard(text)
        toast(self, "Copied to clipboard", "success", 2000)

    def _toggle(self) -> None:
        showing = not self.detail_panel.isVisible()
        self.detail_panel.setVisible(showing)
        self.toggle.setText("Hide" if showing else "Details")


# --- buttons ----------------------------------------------------------------
def button_text(text: str) -> str:
    """Qt reads '&' in a button label as a keyboard-shortcut marker, so it is doubled."""
    return text.replace("&", "&&")


def _button(text: str, on_click: Callable | None, kind: str, width: int | None) -> QPushButton:
    button = QPushButton(button_text(text))
    button.setProperty("kind", kind)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if on_click:
        button.clicked.connect(lambda _checked=False: on_click())
    if width:
        button.setMinimumWidth(round(width * theme.text_scale()))
    return button


def primary_button(text: str, on_click=None, width: int | None = None) -> QPushButton:
    return _button(text, on_click, "primary", width)


def secondary_button(text: str, on_click=None, width: int | None = None) -> QPushButton:
    return _button(text, on_click, "secondary", width)


def danger_button(text: str, on_click=None, width: int | None = None) -> QPushButton:
    return _button(text, on_click, "danger", width)


def confirm_button(text: str, on_click=None, width: int | None = None) -> QPushButton:
    return _button(text, on_click, "confirm", width)


def small_button(text: str, on_click=None) -> QPushButton:
    return _button(text, on_click, "small", None)


def ghost_button(text: str, on_click=None) -> QPushButton:
    return _button(text, on_click, "ghost", None)


class MenuButton(QPushButton):
    """A drop-down for a choice with too many options to sit in a row of buttons.

    Built from a real QMenu so it picks up the application stylesheet, rather
    than a QComboBox, whose popup Qt draws with the native style and which
    therefore never looks like the rest of the app. The button always shows the
    current choice, so the setting is readable without opening it.

    ``options`` is a list of (key, label) pairs; a bare None inserts a divider.
    """

    changed = pyqtSignal(str)

    def __init__(self, options: list, value: str | None = None, prefix: str = "",
                 on_change: Callable[[str], None] | None = None, width: int | None = None,
                 short: dict[str, str] | None = None, parent=None):
        super().__init__(parent)
        self.setProperty("kind", "secondary")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._prefix = prefix
        # The menu has room to spell a choice out; the button sits in a row of
        # other controls and must not crowd them, so it can show a short form.
        self._short = short or {}
        self._labels = {key: label for entry in options if entry for key, label in [entry]}
        self.value = value if value in self._labels else next(iter(self._labels), "")
        if on_change:
            self.changed.connect(on_change)
        if width:
            self.setMinimumWidth(round(width * theme.text_scale()))

        self._menu = QMenu(self)
        group = QActionGroup(self._menu)
        group.setExclusive(True)
        self._actions: dict[str, QAction] = {}
        for entry in options:
            if entry is None:
                self._menu.addSeparator()
                continue
            key, label = entry
            action = QAction(label, self._menu)
            action.setCheckable(True)
            action.setChecked(key == self.value)
            action.triggered.connect(lambda _checked=False, k=key: self.set(k, notify=True))
            group.addAction(action)
            self._menu.addAction(action)
            self._actions[key] = action

        self.setMenu(self._menu)
        self._paint()

    def _paint(self) -> None:
        label = self._short.get(self.value) or self._labels.get(self.value, "")
        self.setText(button_text(f"{self._prefix}{label}" if self._prefix else label))
        for key, action in self._actions.items():
            action.setChecked(key == self.value)

    def set(self, key: str, notify: bool = False) -> None:
        if key not in self._labels or key == self.value:
            # Re-check the current entry: clicking the one already chosen must
            # not leave the menu showing nothing as selected.
            self._paint()
            return
        self.value = key
        self._paint()
        if notify:
            self.changed.emit(key)

    def get(self) -> str:
        return self.value


class ChoiceButtons(QWidget):
    """A row of buttons where exactly one is selected: radio buttons that look like buttons."""

    changed = pyqtSignal(str)

    def __init__(self, options: list[tuple[str, str]], value: str | None = None,
                 on_change: Callable[[str], None] | None = None, parent=None):
        super().__init__(parent)
        self.setProperty("role", "plain")
        self._layout = FlowLayout(self, margin=0, spacing=8)
        self.buttons: dict[str, QPushButton] = {}
        self.value = value if value is not None else (options[0][0] if options else "")
        if on_change:
            self.changed.connect(on_change)
        for key, label in options:
            button = QPushButton(button_text(label))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, k=key: self.set(k, notify=True))
            self._layout.addWidget(button)
            self.buttons[key] = button
        self._paint()

    def _paint(self) -> None:
        for key, button in self.buttons.items():
            button.setProperty("choice", "on" if key == self.value else "off")
            restyle(button)

    def set(self, key: str, notify: bool = False) -> None:
        if key not in self.buttons:
            return
        self.value = key
        self._paint()
        if notify:
            self.changed.emit(key)

    def get(self) -> str:
        return self.value


class TabBar(QWidget):
    """Tabs as a row of real buttons, with the pages in a card underneath.

    Pages are built the first time their tab is opened, not up front, so opening
    a section with four tabs costs one tab's worth of widgets.
    """

    changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("role", "plain")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        self.bar = QWidget()
        self.bar.setProperty("role", "plain")
        self.bar_layout = FlowLayout(self.bar, margin=0, spacing=8)
        outer.addWidget(self.bar)

        self.card = QFrame()
        self.card.setProperty("role", "card")
        pad = round(16 * theme.text_scale())
        self.card_layout = QVBoxLayout(self.card)
        self.card_layout.setContentsMargins(pad, pad, pad, pad)
        outer.addWidget(self.card, 1)

        self.buttons: dict[str, QPushButton] = {}
        self._builders: dict[str, Callable[[], QWidget]] = {}
        self._pages: dict[str, QWidget] = {}
        self._current: str | None = None

    def add(self, name: str, builder: Callable[[], QWidget]) -> None:
        button = QPushButton(button_text(name))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setProperty("choice", "off")
        button.clicked.connect(lambda _checked=False, n=name: self.set(n))
        self.bar_layout.addWidget(button)
        self.buttons[name] = button
        self._builders[name] = builder

    def page(self, name: str) -> QWidget | None:
        return self._pages.get(name)

    def build_all(self) -> None:
        """Construct every tab now.

        Only for a section whose tabs share state, where a lazily-built tab
        would not exist when another one needs to write into it.
        """
        showing = self._current
        for name in self._builders:
            if name not in self._pages:
                page = self._builders[name]()
                page.setVisible(False)
                self._pages[name] = page
                self.card_layout.addWidget(page, 1)
        if showing is not None:
            self._pages[showing].setVisible(True)

    def current(self) -> str:
        return self._current or ""

    def set(self, name: str) -> None:
        if name not in self._builders or name == self._current:
            return
        if self._current is not None:
            self._pages[self._current].setVisible(False)
        if name not in self._pages:
            page = self._builders[name]()
            self._pages[name] = page
            self.card_layout.addWidget(page, 1)
        self._current = name
        self._pages[name].setVisible(True)
        for key, button in self.buttons.items():
            button.setProperty("choice", "on" if key == name else "off")
            restyle(button)
        self.changed.emit(name)


# --- scrolling --------------------------------------------------------------
class ScrollPage(QScrollArea):
    """A vertically scrolling page body with sensible defaults.

    Per-pixel scrolling keeps the wheel smooth on a low-end machine, where the
    default row-at-a-time step reads as stutter.

    QScrollArea sizes its widget from ``sizeHint()`` and ignores
    ``heightForWidth``, so a word-wrapped label inside one is measured as a
    single line and the rows below it end up drawn on top of each other. This
    re-measures the content at the real viewport width whenever the area is
    resized or the layout changes.
    """

    def __init__(self, parent=None, margins: tuple = (0, 0, 0, 0), spacing: int = 12):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.verticalScrollBar().setSingleStep(24)

        self.content = QWidget()
        self.content.setProperty("role", "plain")
        self.body_layout = QVBoxLayout(self.content)
        self.body_layout.setContentsMargins(*margins)
        self.body_layout.setSpacing(spacing)
        self.setWidget(self.content)
        self.content.installEventFilter(self)

    # -- wrapped-text height -------------------------------------------------
    def resizeEvent(self, event):  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._remeasure()

    def eventFilter(self, obj, event):  # noqa: N802 - Qt naming
        if obj is self.content and event.type() == QEvent.Type.LayoutRequest:
            self._remeasure()
        return False

    def _remeasure(self) -> None:
        layout = self.content.layout()
        if layout is None or not layout.hasHeightForWidth():
            return
        needed = layout.heightForWidth(self.viewport().width())
        if needed > 0 and needed != self.content.minimumHeight():
            self.content.setMinimumHeight(needed)

    def add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self.body_layout.addWidget(widget, stretch)
        return widget

    def add_layout(self, layout: QLayout) -> QLayout:
        self.body_layout.addLayout(layout)
        return layout

    def add_stretch(self) -> None:
        self.body_layout.addStretch(1)

    def clear(self) -> None:
        clear_layout(self.body_layout)


def clear_layout(layout: QLayout) -> None:
    """Remove and delete everything in a layout. Used where a list is rebuilt."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        else:
            child = item.layout()
            if child is not None:
                clear_layout(child)


# --- toast ------------------------------------------------------------------
class Toast(QFrame):
    """A transient message in the bottom-right corner of the window."""

    def __init__(self, parent: QWidget, message: str, level: str = "info", duration: int = 4000):
        super().__init__(parent)
        self.setProperty("role", "toast")
        self.setProperty("level", level)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 14, 10)
        label = QLabel(message)
        label.setWordWrap(True)
        label.setMaximumWidth(round(360 * theme.text_scale()))
        layout.addWidget(label)

        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._effect.setOpacity(0.0)
        self.adjustSize()
        self._place()
        self.show()
        self.raise_()

        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(140)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.start()

        QTimer.singleShot(duration, self._dismiss)

    def _place(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        margin = 20
        self.move(max(margin, parent.width() - self.width() - margin),
                  max(margin, parent.height() - self.height() - margin - 26))

    def _dismiss(self) -> None:
        if not self.isVisible():
            return
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(180)
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self.deleteLater)
        self._fade.start()


_toasts: list[Toast] = []


def _on_screen(item: Toast) -> bool:
    """Is this toast still a real widget?

    A dismissed toast is deleteLater'd, which destroys the C++ object while the
    entry in ``_toasts`` still points at the Python wrapper. Asking a dead
    wrapper anything raises RuntimeError, and this list is read by every call to
    toast(), including the one the crash handler makes, so a stale entry turned
    any later message into a second error.
    """
    try:
        return item.isVisible()
    except RuntimeError:
        return False


def toast(widget: QWidget | None, message: str, level: str = "info", duration: int = 4000) -> None:
    """Show a message over the main window. Safe to call from any page."""
    window = widget.window() if widget is not None else None
    if window is None:
        return
    _toasts[:] = [t for t in _toasts if _on_screen(t)]
    # Stack new toasts above any still on screen rather than covering them
    live = [t for t in _toasts if t.parentWidget() is window]
    item = Toast(window, message, level, duration)
    offset = sum(t.height() + 8 for t in live)
    if offset:
        item.move(item.x(), max(20, item.y() - offset))
    _toasts.append(item)
    del _toasts[:-6]


# --- misc helpers -----------------------------------------------------------
def copy_to_clipboard(text: str) -> None:
    clipboard = QGuiApplication.clipboard()
    if clipboard is not None:
        clipboard.setText(text)


def open_url(url: str) -> None:
    webbrowser.open(url)
