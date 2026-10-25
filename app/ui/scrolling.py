"""Smooth wheel scrolling and scrollbars that widen when the mouse is over them.

One filter on the whole application, so every scrolling list, page and box in
the app gets both without each one having to ask.

Smooth scrolling: a mouse wheel moves a page in jumps of three lines, which on
a slow machine reads as a low frame rate. Each notch here starts a short eased
animation to where the jump would have landed instead, and further notches
extend it. Touchpads already scroll by the pixel and are left alone. Settings
can switch it off (``smooth_scroll``).

Scrollbars: drawn thin, and given the ``hot`` property while the mouse is over
one (or dragging it) so the stylesheet can draw the handle wide enough to grab.
"""
from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, Qt
from PyQt6.QtWidgets import (QAbstractScrollArea, QAbstractSpinBox, QApplication, QComboBox,
                             QScrollBar, QWidget)

DURATION_MS = 220


class ScrollFilter(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.smooth = True
        self._targets: dict[QScrollBar, tuple[QPropertyAnimation, int]] = {}

    def eventFilter(self, obj, event):  # noqa: N802 - Qt naming
        kind = event.type()
        if kind == QEvent.Type.Wheel:
            return self.smooth and self._wheel(obj, event)
        if isinstance(obj, QScrollBar):
            if kind == QEvent.Type.Enter:
                _set_hot(obj, True)
            elif kind == QEvent.Type.Leave and not obj.isSliderDown():
                _set_hot(obj, False)
            elif kind == QEvent.Type.MouseButtonRelease:
                _set_hot(obj, obj.rect().contains(event.position().toPoint()))
        return False

    def _wheel(self, obj, event) -> bool:
        delta = event.angleDelta().y()
        if (not delta or not event.pixelDelta().isNull() or event.angleDelta().x()
                or event.modifiers() != Qt.KeyboardModifier.NoModifier):
            return False
        # Qt shows the wheel to the window (a QWindow, not a widget) before the
        # widget under the mouse; let it through, the widget's turn comes next
        if not isinstance(obj, QWidget):
            return False
        widget = obj
        while widget is not None:
            if isinstance(widget, (QComboBox, QAbstractSpinBox)):
                return False
            if isinstance(widget, QAbstractScrollArea):
                bar = widget.verticalScrollBar()
                if bar.maximum() > bar.minimum():
                    target = self._target(bar)
                    if (delta < 0 and target < bar.maximum()) or (delta > 0 and target > bar.minimum()):
                        step = QApplication.wheelScrollLines() * bar.singleStep()
                        self._scroll(bar, target - round(delta / 120 * step))
                        return True
            widget = widget.parentWidget()
        return False

    def _target(self, bar: QScrollBar) -> int:
        """Where the bar is heading: the end of a running animation, else where it is."""
        running = self._targets.get(bar)
        if running and running[0].state() == QPropertyAnimation.State.Running:
            return running[1]
        return bar.value()

    def _scroll(self, bar: QScrollBar, target: int) -> None:
        target = max(bar.minimum(), min(bar.maximum(), target))
        running = self._targets.get(bar)
        if running is None:
            animation = QPropertyAnimation(bar, b"value", bar)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            bar.destroyed.connect(lambda *_: self._targets.pop(bar, None))
        else:
            animation = running[0]
            animation.stop()
        animation.setDuration(DURATION_MS)
        animation.setStartValue(bar.value())
        animation.setEndValue(target)
        self._targets[bar] = (animation, target)
        animation.start()


def _set_hot(bar: QScrollBar, hot: bool) -> None:
    if bool(bar.property("hot")) == hot:
        return
    bar.setProperty("hot", hot)
    bar.style().unpolish(bar)
    bar.style().polish(bar)
    bar.update()


_filter: ScrollFilter | None = None


def install(app: QApplication, smooth: bool = True) -> None:
    global _filter
    if _filter is None:
        _filter = ScrollFilter(app)
        app.installEventFilter(_filter)
    _filter.smooth = smooth


def set_smooth(on: bool) -> None:
    if _filter is not None:
        _filter.smooth = on
