"""Two-handle range slider for the delay between emails.

Qt ships a single-handle QSlider, so this paints its own. Values snap to a step
table rather than a linear scale: most people want fine control around 1-5
minutes and coarse control above that, and a linear 15s-60m slider makes the
useful part unusably cramped.
"""
from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from app.ui import theme


def build_steps() -> list[int]:
    """Denser steps where people actually work, so the useful range is not cramped."""
    steps: list[int] = []
    steps.extend(range(15, 301, 15))       # 15s .. 5m  in 15s increments
    steps.extend(range(330, 901, 30))      # 5m30 .. 15m in 30s increments
    steps.extend(range(1200, 3601, 300))   # 20m .. 60m  in 5m increments
    return steps


STEPS = build_steps()


def format_seconds(seconds: int) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, rest = divmod(seconds, 60)
    return f"{minutes}m" if rest == 0 else f"{minutes}m {rest}s"


def nearest_index(seconds: int) -> int:
    best, smallest = 0, abs(STEPS[0] - seconds)
    for index, value in enumerate(STEPS):
        gap = abs(value - seconds)
        if gap < smallest:
            smallest, best = gap, index
    return best


class RangeSlider(QWidget):
    """Min/max delay selector. Reports values in seconds."""

    changed = pyqtSignal(int, int)       # live, while dragging
    released = pyqtSignal(int, int)      # once, when the handle is let go

    TRACK_HEIGHT = 4
    SIDE_PAD = 14

    def __init__(self, low: int = 75, high: int = 150, parent=None):
        super().__init__(parent)
        self.setProperty("role", "plain")
        self._low = nearest_index(low)
        self._high = nearest_index(high)
        if self._low > self._high:
            self._low, self._high = self._high, self._low
        self._dragging: str | None = None
        self._hover: str | None = None

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(self._natural_height())

    # --- metrics ------------------------------------------------------------
    def _scale(self) -> float:
        return theme.text_scale()

    def _radius(self) -> float:
        return 9 * self._scale()

    def _natural_height(self) -> int:
        return int(46 * self._scale())

    def sizeHint(self):
        from PyQt6.QtCore import QSize

        return QSize(320, self._natural_height())

    def _bounds(self) -> tuple[float, float]:
        pad = self.SIDE_PAD * self._scale()
        return pad, max(pad + 10, self.width() - pad)

    def _index_to_x(self, index: int) -> float:
        left, right = self._bounds()
        if len(STEPS) <= 1:
            return left
        return left + (right - left) * (index / (len(STEPS) - 1))

    def _x_to_index(self, x: float) -> int:
        left, right = self._bounds()
        if right <= left:
            return 0
        ratio = min(1.0, max(0.0, (x - left) / (right - left)))
        return int(round(ratio * (len(STEPS) - 1)))

    # --- values -------------------------------------------------------------
    @property
    def low(self) -> int:
        return STEPS[self._low]

    @property
    def high(self) -> int:
        return STEPS[self._high]

    def get(self) -> tuple[int, int]:
        return self.low, self.high

    def set(self, low: int, high: int) -> None:
        self._low = nearest_index(low)
        self._high = nearest_index(high)
        if self._low > self._high:
            self._low, self._high = self._high, self._low
        self.update()

    def readout(self) -> str:
        if self.low == self.high:
            return f"Exactly {format_seconds(self.low)} between each email"
        per_hour = int(3600 / ((self.low + self.high) / 2))
        return (f"{format_seconds(self.low)} – {format_seconds(self.high)} between each email"
                f"   ·   roughly {per_hour} per hour")

    # --- painting -----------------------------------------------------------
    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        scale = self._scale()
        mid = self.height() / 2 - 5 * scale
        half = self.TRACK_HEIGHT * scale / 2
        left, right = self._bounds()
        low_x, high_x = self._index_to_x(self._low), self._index_to_x(self._high)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.qcolor("border_strong"))
        painter.drawRoundedRect(QRectF(left, mid - half, right - left, half * 2), half, half)

        painter.setBrush(theme.qcolor("accent"))
        painter.drawRoundedRect(QRectF(low_x, mid - half, max(1.0, high_x - low_x), half * 2),
                                half, half)

        radius = self._radius()
        pen = QPen(theme.qcolor("accent"))
        pen.setWidthF(2 * scale)
        painter.setPen(pen)
        for name, x in (("low", low_x), ("high", high_x)):
            active = self._dragging == name or self._hover == name
            painter.setBrush(theme.qcolor("accent" if active else "bg_input"))
            grow = radius + (1 if active else 0)
            painter.drawEllipse(QRectF(x - grow, mid - grow, grow * 2, grow * 2))

        painter.setPen(theme.qcolor("fg_muted"))
        font = painter.font()
        font.setFamily(theme.mono_family())
        font.setPixelSize(max(8, int(9 * scale)))
        painter.setFont(font)
        label_y = self.height() - 2
        painter.drawText(QRectF(low_x - 40, label_y - 14 * scale, 80, 14 * scale),
                         int(Qt.AlignmentFlag.AlignCenter), format_seconds(self.low))
        if abs(high_x - low_x) > 46 * scale:
            painter.drawText(QRectF(high_x - 40, label_y - 14 * scale, 80, 14 * scale),
                             int(Qt.AlignmentFlag.AlignCenter), format_seconds(self.high))
        painter.end()

    # --- interaction --------------------------------------------------------
    def _pick(self, x: float) -> str:
        low_x, high_x = self._index_to_x(self._low), self._index_to_x(self._high)
        if abs(x - low_x) == abs(x - high_x):
            return "high" if x > low_x else "low"
        return "low" if abs(x - low_x) < abs(x - high_x) else "high"

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        x = event.position().x()
        self._dragging = self._pick(x)
        self._apply(x)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        x = event.position().x()
        if self._dragging:
            self._apply(x)
            return
        near = self._pick(x)
        hover = near if abs(x - self._index_to_x(
            self._low if near == "low" else self._high)) <= self._radius() * 1.6 else None
        if hover != self._hover:
            self._hover = hover
            self.update()

    def mouseReleaseEvent(self, _event) -> None:  # noqa: N802
        if self._dragging:
            self._dragging = None
            self.update()
            self.released.emit(self.low, self.high)

    def leaveEvent(self, _event) -> None:  # noqa: N802
        if self._hover is not None:
            self._hover = None
            self.update()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        step = {Qt.Key.Key_Left: -1, Qt.Key.Key_Down: -1,
                Qt.Key.Key_Right: 1, Qt.Key.Key_Up: 1}.get(event.key())
        if step is None:
            super().keyPressEvent(event)
            return
        handle = "high" if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else "low"
        if handle == "low":
            self._low = max(0, min(self._low + step, self._high))
        else:
            self._high = min(len(STEPS) - 1, max(self._high + step, self._low))
        self.update()
        self.changed.emit(self.low, self.high)
        self.released.emit(self.low, self.high)

    def _apply(self, x: float) -> None:
        index = self._x_to_index(x)
        if self._dragging == "low":
            self._low = min(index, self._high)
        else:
            self._high = max(index, self._low)
        self.update()
        self.changed.emit(self.low, self.high)

    def refresh_theme(self) -> None:
        self.setMinimumHeight(self._natural_height())
        self.update()
