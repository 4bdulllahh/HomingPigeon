"""A layout that wraps its children onto new lines when they do not fit.

Rows of buttons have to survive the largest text size, where a row that fits at
100% runs off the edge at 150%. Qt has no built-in flow layout, so this is the
standard implementation, adapted to report a sensible height for the width it is
given (otherwise the surrounding scroll area clips the wrapped rows).
"""
from __future__ import annotations

from PyQt6.QtCore import QMargins, QPoint, QRect, QSize, Qt
from PyQt6.QtWidgets import QLayout, QWidgetItem


class FlowLayout(QLayout):
    def __init__(self, parent=None, margin: int = 0, spacing: int = 8):
        super().__init__(parent)
        self._items: list[QWidgetItem] = []
        self._spacing = spacing
        self.setContentsMargins(QMargins(margin, margin, margin, margin))

    def __del__(self):
        while self.count():
            self.takeAt(0)

    # --- QLayout plumbing ---------------------------------------------------
    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        height = self._arrange(rect, apply=True)
        # Qt only asks for the height of one line when space is short, and a page
        # that cannot scroll then squeezes the wrapped lines on top of each other.
        # Asking for the real height of the lines at this width stops that.
        owner = self.parentWidget()
        if owner is not None and owner.layout() is self and owner.minimumHeight() != height:
            owner.setMinimumHeight(height)

    def sizeHint(self) -> QSize:
        """Everything on one line: the width a row of buttons would like beside other widgets."""
        items = [item for item in self._items if not self._hidden(item)]
        width = sum(item.sizeHint().width() for item in items)
        width += self._spacing * max(0, len(items) - 1)
        height = max((item.sizeHint().height() for item in items), default=0)
        margins = self.contentsMargins()
        return QSize(width + margins.left() + margins.right(),
                     height + margins.top() + margins.bottom())

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def setSpacing(self, spacing: int) -> None:
        self._spacing = spacing

    def spacing(self) -> int:
        return self._spacing

    @staticmethod
    def _hidden(item) -> bool:
        widget = item.widget()
        return widget is not None and not widget.isVisible() and widget.isHidden()

    # --- the actual flow ----------------------------------------------------
    def _arrange(self, rect: QRect, apply: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x, y, line_height = area.x(), area.y(), 0
        # Qt mirrors its own layouts for Arabic; this one is hand-made, so it
        # mirrors itself: rows start at the right edge and run leftwards.
        owner = self.parentWidget()
        mirrored = owner is not None and owner.isRightToLeft()

        for item in self._items:
            if self._hidden(item):
                continue
            hint = item.sizeHint()
            # Wider than the whole row: as narrow as the row, but never below its minimum
            if hint.width() > area.width():
                hint.setWidth(max(area.width(), item.minimumSize().width()))
            next_x = x + hint.width() + self._spacing
            # Not area.right(), which is one pixel short: a row exactly as wide as its
            # buttons would put the last one on a line of its own
            if next_x - self._spacing > area.x() + area.width() and line_height > 0:
                x = area.x()
                y = y + line_height + self._spacing
                next_x = x + hint.width() + self._spacing
                line_height = 0
            if apply:
                place = QRect(QPoint(x, y), hint)
                if mirrored:
                    place.moveLeft(area.right() - (x - area.x()) - hint.width() + 1)
                item.setGeometry(place)
            x = next_x
            line_height = max(line_height, hint.height())

        return y + line_height - rect.y() + margins.bottom()

