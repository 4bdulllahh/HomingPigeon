"""The live picture of an email design in the Email design page.

It is drawn with ordinary Qt widgets rather than a web browser: a browser
engine would add a hundred megabytes to the download, and Windows Smart App
Control blocks some of its parts. The layout follows the real email closely;
"Open in browser" shows the exact HTML.

Clicking a block selects it and clicking outside the email selects the page
itself. Blocks are dragged in from the Add panel and dragged around the email
to move them; a blue line shows where they will land. Double-clicking a block
with words lets the user type straight onto the email, and pictures, buttons
and empty space have a handle to drag them bigger or smaller.
"""
from __future__ import annotations

import base64
import random
from typing import Callable

from PyQt6.QtCore import QMimeData, QPoint, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QDrag, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (QApplication, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
                             QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout,
                             QWidget)

from app.core import composer, design, merge
from app.i18n import t
from app.ui import theme
from app.ui.widgets.common import small_button

PHONE_WIDTH = 375
RICH_STYLE = "<style>p{margin:0 0 10px 0;} ul{margin:0 0 10px 0;}</style>"

# What a drag carries: a new block's kind from the Add panel, or the id of a block being moved
MIME_NEW = "application/x-homingpigeon-new-block"
MIME_MOVE = "application/x-homingpigeon-move-block"

# The words each block lets the user type straight onto the email
INLINE = {"heading": "text", "text": "text", "quote": "text", "button": "label",
          "footer": "text", "banner": "title", "card": "title"}

# The setting a resize handle changes
RESIZE = {"logo": "width", "image": "width", "video": "width", "button": "size",
          "spacer": "height"}
BUTTON_SIZES = ("small", "medium", "large")


def faded(widget: QWidget, width: int = 320) -> QPixmap:
    """A see-through picture of a widget to carry under the pointer while dragging."""
    picture = widget.grab()
    if picture.width() > width:
        picture = picture.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
    out = QPixmap(picture.size())
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setOpacity(0.75)
    painter.drawPixmap(0, 0, picture)
    painter.end()
    return out


def start_drag(source: QWidget, mime_type: str, value: str, picture: QPixmap) -> None:
    """Drag a block, new or existing, from ``source``."""
    data = QMimeData()
    data.setData(mime_type, value.encode("utf-8"))
    drag = QDrag(source)
    drag.setMimeData(data)
    drag.setPixmap(picture)
    drag.setHotSpot(QPoint(picture.width() // 2, min(16, picture.height() // 2)))
    drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction)


def _family(font: str) -> str:
    return font if font in design.FONTS else "Arial"


def _pixmap(data: bytes) -> QPixmap:
    pixmap = QPixmap()
    pixmap.loadFromData(data)
    return pixmap


def _rounded(pixmap: QPixmap, radius: int) -> QPixmap:
    if radius <= 0 or pixmap.isNull():
        return pixmap
    out = QPixmap(pixmap.size())
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(out.rect()), radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    return out


class _Outline(QWidget):
    """Draws the hover and selection frame on top of a block, without catching clicks."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.state = ""

    def paintEvent(self, _event):  # noqa: N802 - Qt naming
        if not self.state:
            return
        painter = QPainter(self)
        pen = QPen(theme.qcolor("accent"))
        pen.setWidth(2 if self.state == "selected" else 1)
        if self.state == "hover":
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawRect(self.rect().adjusted(1, 1, -1, -1))


class BlockView(QFrame):
    """One block of the email. Owns its padding, background and selection frame."""

    def __init__(self, block: dict, canvas: "EmailCanvas"):
        super().__init__()
        self.block = block
        self.canvas = canvas
        self.setObjectName("Blk")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        bg = design._colour(block.get("bg"))
        self.setStyleSheet(f"#Blk {{ background-color: {bg or 'transparent'}; border: none; }}")
        self.layout_ = QVBoxLayout(self)
        self.layout_.setSpacing(0)
        self.outline = _Outline(self)
        self.target: QWidget | None = self   # what the resize handle sits on
        self._press: QPoint | None = None

    def pad(self, top=None, side=None, bottom=None) -> None:
        b = self.block
        side = int(b.get("pad_side", 0)) if side is None else side
        self.layout_.setContentsMargins(side, int(b.get("pad_top", 0)) if top is None else top,
                                        side, int(b.get("pad_bottom", 0)) if bottom is None
                                        else bottom)

    def set_state(self, state: str) -> None:
        self.outline.state = state
        self.outline.update()

    def resizeEvent(self, event):  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self.outline.setGeometry(self.rect())
        self.outline.raise_()
        if self.outline.state == "selected":
            self.canvas.place_tools()

    def moveEvent(self, event):  # noqa: N802 - Qt naming
        super().moveEvent(event)
        if self.outline.state == "selected":
            self.canvas.place_tools()

    def enterEvent(self, event):  # noqa: N802 - Qt naming
        if self.outline.state != "selected":
            self.set_state("hover")
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802 - Qt naming
        if self.outline.state == "hover":
            self.set_state("")
        super().leaveEvent(event)

    def mousePressEvent(self, event):  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()
            self.canvas.selected.emit(self.block["id"])
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802 - Qt naming
        if (self._press is not None and event.buttons() & Qt.MouseButton.LeftButton
                and (event.position().toPoint() - self._press).manhattanLength()
                >= QApplication.startDragDistance()):
            self._press = None
            # Started from the event loop, not from here: dropping rebuilds the
            # email, and this block must not be deleted while its handler runs.
            block_id = self.block["id"]
            QTimer.singleShot(0, lambda: self.canvas.drag_block(block_id))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt naming
        self._press = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):  # noqa: N802 - Qt naming
        self.canvas.edit.emit(self.block["id"])
        event.accept()


class _Surface(QFrame):
    """The coloured area the email sits on. Takes the drops for the whole email."""

    def __init__(self, canvas: "EmailCanvas"):
        super().__init__()
        self.canvas = canvas
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):  # noqa: N802 - Qt naming
        self.canvas.drag_over(event)

    def dragMoveEvent(self, event):  # noqa: N802 - Qt naming
        self.canvas.drag_over(event)

    def dragLeaveEvent(self, event):  # noqa: N802 - Qt naming
        self.canvas.marker.hide()

    def dropEvent(self, event):  # noqa: N802 - Qt naming
        self.canvas.drop(event)


class _Grip(QPushButton):
    """The move handle on the toolbar: drag it to move the selected block."""

    def __init__(self, canvas: "EmailCanvas"):
        super().__init__(theme.icon("move"))
        self.canvas = canvas
        self._press: QPoint | None = None
        self.setCursor(Qt.CursorShape.SizeAllCursor)

    def mousePressEvent(self, event):  # noqa: N802 - Qt naming
        self._press = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802 - Qt naming
        if (self._press is not None and event.buttons() & Qt.MouseButton.LeftButton
                and (event.position().toPoint() - self._press).manhattanLength()
                >= QApplication.startDragDistance()):
            self._press = None
            self.setDown(False)
            QTimer.singleShot(0, lambda: self.canvas.drag_block(self.canvas._selected))
        super().mouseMoveEvent(event)


class _Handle(QFrame):
    """A small square on a picture's corner, or under empty space, to drag its size."""

    def __init__(self, canvas: "EmailCanvas"):
        super().__init__(canvas.outer)
        self.canvas = canvas
        self._start: QPoint | None = None
        self.setFixedSize(12, 12)
        self.setStyleSheet(f"background-color: #ffffff; border: 2px solid {theme.color('accent')}; "
                           "border-radius: 3px;")
        self.setToolTip(t("Drag to make it bigger or smaller"))
        self.hide()

    def mousePressEvent(self, event):  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            self._start = event.globalPosition().toPoint()
            self.canvas.begin_resize()
            event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802 - Qt naming
        if self._start is not None:
            self.canvas.resize_by(event.globalPosition().toPoint() - self._start)

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt naming
        if self._start is not None:
            self._start = None
            self.canvas.end_resize()


class _Typing(QPlainTextEdit):
    """Typing straight onto the email. Enter or clicking away keeps it, Esc cancels."""

    finished = pyqtSignal(bool)

    def __init__(self, parent: QWidget, multiline: bool):
        super().__init__(parent)
        self.multiline = multiline
        self._done = False

    def keyPressEvent(self, event):  # noqa: N802 - Qt naming
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self._finish(False)
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and (
                not self.multiline or event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self._finish(True)
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):  # noqa: N802 - Qt naming
        super().focusOutEvent(event)
        self._finish(True)

    def _finish(self, keep: bool) -> None:
        if not self._done:
            self._done = True
            self.finished.emit(keep)


class EmailCanvas(QScrollArea):
    """Shows a design. ``selected`` carries a block id, or "" for the page itself."""

    selected = pyqtSignal(str)
    action = pyqtSignal(str, str)
    edit = pyqtSignal(str)
    dropped = pyqtSignal(str, str, int)     # "new" and a kind, or "move" and a block id; where
    typed = pyqtSignal(str, str, str)       # block id, setting, the words typed
    resized = pyqtSignal(str, str, object)  # block id, setting, new value
    resize_done = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.verticalScrollBar().setSingleStep(24)
        self.phone = False
        self._design: dict | None = None
        self._sample: dict = {}
        self._selected = ""
        self._views: dict[str, BlockView] = {}
        self._pixmaps: dict[str, QPixmap] = {}
        self._typing: tuple[_Typing, str, str] | None = None
        self._resizing: tuple | None = None

        self.outer = _Surface(self)
        self.outer.setObjectName("CanvasOuter")
        self.outer_layout = QVBoxLayout(self.outer)
        self.card = QFrame()
        self.card.setObjectName("EmailCard")
        self.card_layout = QVBoxLayout(self.card)
        self.card_layout.setContentsMargins(0, 0, 0, 0)
        self.card_layout.setSpacing(0)
        self.outer_layout.addWidget(self.card, 0, Qt.AlignmentFlag.AlignTop
                                    | Qt.AlignmentFlag.AlignHCenter)
        self.outer_layout.addStretch(1)
        self.setWidget(self.outer)
        self.tools = self._toolbar()
        self.handle = _Handle(self)
        self.marker = QFrame(self.outer)
        self.marker.setStyleSheet(f"background-color: {theme.color('accent')}; border-radius: 2px;")
        self.marker.hide()

    # --- public -----------------------------------------------------------------
    def show_design(self, data: dict, sample: dict, selected: str = "") -> None:
        """Draw ``data``. ``sample`` has the message, signature and unsubscribe line to show."""
        self._design = data
        self._sample = sample
        self._selected = selected
        self._rebuild()

    def select(self, block_id: str) -> None:
        # Blocks never take the keyboard, so clicking another one would not end the typing
        if self._typing is not None and self._typing[1] != block_id:
            self.finish_typing()
        self._selected = block_id
        for key, view in self._views.items():
            view.set_state("selected" if key == block_id else "")
        self.place_tools()

    def _toolbar(self) -> QWidget:
        """Drag to move, copy and remove, beside the selected block."""
        bar = QFrame(self.outer)
        bar.setProperty("role", "card")
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(3)
        grip = _Grip(self)
        grip.setToolTip(t("Drag to move this block"))
        buttons = [grip]
        for name, action, tip in (("copy", "copy", "Make a copy"), ("delete", "remove", "Remove")):
            button = small_button(theme.icon(name),
                                  lambda a=action: self.action.emit(self._selected, a))
            button.setToolTip(t(tip))
            buttons.append(button)
        side = round(30 * theme.text_scale())
        for button in buttons:
            button.setFixedSize(side, side)
            button.setStyleSheet(theme.icon_css(14) + " padding: 0; min-height: 0;")
            layout.addWidget(button)
        bar.adjustSize()
        bar.hide()
        return bar

    def place_tools(self) -> None:
        """Beside the email, level with the selected block; inside it when there is no room."""
        view = self._views.get(self._selected)
        if view is None or self._typing is not None:
            self.tools.hide()
            if self._resizing is None:
                self.handle.hide()
            return
        corner = view.mapTo(self.outer, QPoint(view.width(), 0))
        x = corner.x() + 8
        if x + self.tools.width() > self.outer.width():
            x = corner.x() - self.tools.width() - 4
        self.tools.move(x, corner.y())
        self.tools.show()
        self.tools.raise_()
        self._place_handle(view)

    def _place_handle(self, view: BlockView) -> None:
        target = view.target
        if view.block["type"] not in RESIZE or target is None:
            self.handle.hide()
            return
        if view.block["type"] == "spacer":
            point = target.mapTo(self.outer, QPoint(target.width() // 2, target.height()))
            self.handle.setCursor(Qt.CursorShape.SizeVerCursor)
        elif view.block.get("align") == "right" and not view.block.get("full"):
            point = target.mapTo(self.outer, QPoint(0, target.height()))
            self.handle.setCursor(Qt.CursorShape.SizeBDiagCursor)
        else:
            point = target.mapTo(self.outer, QPoint(target.width(), target.height()))
            self.handle.setCursor(Qt.CursorShape.SizeFDiagCursor)
        half = self.handle.width() // 2
        self.handle.move(point.x() - half, point.y() - half)
        self.handle.show()
        self.handle.raise_()

    # --- dragging blocks ----------------------------------------------------------------
    def drag_block(self, block_id: str) -> None:
        view = self._views.get(block_id)
        if view is None:
            return
        self.tools.hide()
        self.handle.hide()
        start_drag(self, MIME_MOVE, block_id, faded(view))
        self.marker.hide()
        self.place_tools()

    def _index_at(self, y: int) -> int:
        """Where a block dropped at height ``y`` goes: before the first block whose middle is lower."""
        blocks = self._design["blocks"] if self._design else []
        for index, block in enumerate(blocks):
            view = self._views.get(block["id"])
            if view is not None and y < view.mapTo(self.outer, QPoint(0, view.height() // 2)).y():
                return index
        return len(blocks)

    def drag_over(self, event) -> None:
        data = event.mimeData()
        if self._design is None or not (data.hasFormat(MIME_NEW) or data.hasFormat(MIME_MOVE)):
            event.ignore()
            return
        event.acceptProposedAction()
        point = event.position().toPoint()
        index = self._index_at(point.y())
        blocks = self._design["blocks"]
        card = self.card.geometry()
        if index < len(blocks) and blocks[index]["id"] in self._views:
            y = self._views[blocks[index]["id"]].mapTo(self.outer, QPoint(0, 0)).y()
        elif blocks and blocks[-1]["id"] in self._views:
            last = self._views[blocks[-1]["id"]]
            y = last.mapTo(self.outer, QPoint(0, last.height())).y()
        else:
            y = card.top() + 20
        self.marker.setGeometry(card.left(), y - 2, card.width(), 4)
        self.marker.show()
        self.marker.raise_()
        # Near the top or bottom edge the email scrolls, so a long one can be dragged across
        edge = self.outer.mapTo(self.viewport(), point).y()
        bar = self.verticalScrollBar()
        if edge < 48:
            bar.setValue(bar.value() - 24)
        elif edge > self.viewport().height() - 48:
            bar.setValue(bar.value() + 24)

    def drop(self, event) -> None:
        self.marker.hide()
        data = event.mimeData()
        index = self._index_at(event.position().toPoint().y())
        if data.hasFormat(MIME_NEW):
            kind, value = "new", bytes(data.data(MIME_NEW)).decode("utf-8")
        elif data.hasFormat(MIME_MOVE):
            kind, value = "move", bytes(data.data(MIME_MOVE)).decode("utf-8")
        else:
            event.ignore()
            return
        event.acceptProposedAction()
        # After the drag has finished, so the email is rebuilt from the normal event loop
        QTimer.singleShot(0, lambda: self.dropped.emit(kind, value, index))

    # --- typing on the email ------------------------------------------------------------
    def start_typing(self, block_id: str, key: str, multiline: bool) -> None:
        view = self._views.get(block_id)
        if view is None:
            return
        self.finish_typing()
        block = view.block
        if block["type"] == "banner":
            size = int(block.get("title_size", 30))
        elif key == "title":
            size = 18
        elif block["type"] == "button":
            size = 15
        else:
            size = int(block.get("size", 15))
        bold = (block.get("weight") == "bold" if block["type"] == "heading"
                else block["type"] in ("button", "banner", "card"))
        editor = _Typing(self.outer, multiline)
        editor.setPlainText(str(block.get(key, "")))
        editor.setStyleSheet(
            f"QPlainTextEdit {{ background-color: #ffffff; color: #1f2530; "
            f"border: 2px solid {theme.color('accent')}; border-radius: 4px; padding: 4px; "
            f"font-family: '{_family(block.get('font') or self._design['page']['font'])}'; "
            f"font-size: {size}px; "
            f"font-weight: {700 if bold else 400}; }}")
        option = editor.document().defaultTextOption()
        option.setAlignment(self._qt_align(block.get("align", "left")))
        editor.document().setDefaultTextOption(option)
        lines =editor.toPlainText().count("\n") + (2 if multiline else 1)
        height = max(view.height(), round(size * 1.5 * lines) + 20)
        editor.setGeometry(QRect(view.mapTo(self.outer, QPoint(0, 0)),
                                 view.size()).adjusted(0, 0, 0, height - view.height()))
        editor.finished.connect(self.finish_typing)
        self._typing = (editor, block_id, key)
        self.tools.hide()
        self.handle.hide()
        editor.show()
        editor.raise_()
        editor.setFocus()
        editor.selectAll()

    def finish_typing(self, keep: bool = True) -> None:
        if self._typing is None:
            return
        editor, block_id, key = self._typing
        self._typing = None
        text = editor.toPlainText()
        if not editor.multiline:
            text = " ".join(text.splitlines())
        editor.hide()
        editor.deleteLater()
        if keep:
            self.typed.emit(block_id, key, text)
        self.place_tools()

    # --- resizing -----------------------------------------------------------------------
    def begin_resize(self) -> None:
        view = self._views.get(self._selected)
        if view is None or view.block["type"] not in RESIZE:
            return
        key = RESIZE[view.block["type"]]
        self._resizing = (self._selected, key, view.block.get(key), self._inner(view.block))

    def resize_by(self, delta: QPoint) -> None:
        if self._resizing is None:
            return
        block_id, key, start, inner = self._resizing
        view = self._views.get(block_id)
        if view is None:
            return
        block = view.block
        kind = block["type"]
        if kind == "spacer":
            value = int(start) + delta.y()
        else:
            # A centred picture grows on both sides, so it follows the pointer at half speed
            align = "left" if block.get("full") else block.get("align", "left")
            grow = delta.x() * (-1 if align == "right" else 1) * (2 if align == "center" else 1)
            if kind == "button":
                step = BUTTON_SIZES.index(start) + round(grow / 60)
                value = BUTTON_SIZES[max(0, min(len(BUTTON_SIZES) - 1, step))]
            elif kind == "logo":
                value = int(start) + grow
            else:
                value = int(start) + round(grow * 100 / inner)
        if not isinstance(value, str):
            field = next(f for f in design.fields_for(kind) if f.key == key)
            value = max(field.low, min(field.high, value))
        if value != block.get(key):
            self.resized.emit(block_id, key, value)

    def end_resize(self) -> None:
        if self._resizing is not None:
            self._resizing = None
            self.resize_done.emit()
            self.place_tools()

    def reveal(self, block_id: str) -> None:
        view = self._views.get(block_id)
        if view is not None:
            self.ensureWidgetVisible(view, 0, 40)

    def mousePressEvent(self, event):  # noqa: N802 - Qt naming
        self.selected.emit("")
        super().mousePressEvent(event)

    def resizeEvent(self, event):  # noqa: N802 - Qt naming
        before = self._card_width()
        super().resizeEvent(event)
        if self._design is not None and self._card_width() != before:
            self._rebuild()

    # --- drawing ----------------------------------------------------------------
    def _card_width(self) -> int:
        if self._design is None:
            return 600
        page = self._design["page"]
        wanted = PHONE_WIDTH if self.phone else int(page["width"])
        room = self.viewport().width() - 2 * (12 if self.phone else int(page["outer_pad"])) - 4
        return max(260, min(wanted, room)) if room > 0 else wanted

    def _rebuild(self) -> None:
        if self._design is None:
            return
        self.finish_typing()
        self.setUpdatesEnabled(False)
        try:
            while self.card_layout.count():
                # Held in a name: once unparented, a label only Python refers to is freed at
                # the end of the line, and asking the item for it again crashed the app
                widget = self.card_layout.takeAt(0).widget()
                if widget is not None:
                    widget.setParent(None)
                    widget.deleteLater()
            self._views.clear()
            self.tools.hide()
            if self._resizing is None:
                # Hiding the handle mid-drag would let go of the mouse, so it stays put then
                self.handle.hide()
            self._paint_page()
            for block in self._design["blocks"]:
                view = BlockView(block, self)
                self._fill(view, block)
                self.card_layout.addWidget(view)
                self._views[block["id"]] = view
                if block["id"] == self._selected:
                    view.set_state("selected")
            if self._sample.get("unsubscribe") and not any(
                    b["type"] == "footer" for b in self._design["blocks"]):
                end = QLabel(self._sample["unsubscribe"])
                end.setTextFormat(Qt.TextFormat.RichText)
                end.setWordWrap(True)
                end.setStyleSheet("color:#777777;font-size:11px;padding:12px 32px 20px 32px;"
                                  "background:transparent;")
                self.card_layout.addWidget(end)
            if not self._design["blocks"]:
                empty = QLabel(t("Add blocks from the left to build your email."))
                empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
                empty.setStyleSheet("color:#8a8f98;padding:40px;")
                self.card_layout.addWidget(empty)
        finally:
            self.setUpdatesEnabled(True)

    def _paint_page(self) -> None:
        page = self._design["page"]
        bg = design._colour(page["bg"], "#f4f5f7")
        fill = bg
        if page["gradient"] != "none":
            second = design._colour(page["bg2"], bg)
            x2, y2 = {"down": (0, 1), "across": (1, 0)}.get(page["gradient"], (1, 1))
            fill = (f"qlineargradient(x1:0, y1:0, x2:{x2}, y2:{y2}, stop:0 {bg}, "
                    f"stop:1 {second})")
        self.outer.setStyleSheet(f"#CanvasOuter {{ background: {fill}; }}")
        pad = 12 if self.phone else int(page["outer_pad"])
        self.outer_layout.setContentsMargins(pad, pad, pad, pad)
        align = Qt.AlignmentFlag.AlignLeft if page["position"] == "left" and not self.phone \
            else Qt.AlignmentFlag.AlignHCenter
        self.outer_layout.setAlignment(self.card, Qt.AlignmentFlag.AlignTop | align)

        border = design._colour(page.get("border"))
        self.card.setStyleSheet(
            f"#EmailCard {{ background-color: {design._colour(page['card_bg'], '#ffffff')}; "
            f"border-radius: {int(page['radius'])}px; "
            f"border: {'1px solid ' + border if border else 'none'}; }}")
        self.card.setFixedWidth(self._card_width())
        if page.get("shadow"):
            shadow = QGraphicsDropShadowEffect(self.card)
            shadow.setBlurRadius(28)
            shadow.setOffset(0, 6)
            shadow.setColor(QColor(0, 0, 0, 40))
            self.card.setGraphicsEffect(shadow)
        else:
            self.card.setGraphicsEffect(None)

    # --- pieces -------------------------------------------------------------------
    def _text(self, html: str, size: int, colour: str, align: str = "left", font: str = "",
              weight: str = "normal", italic: bool = False, line: str | None = None) -> QLabel:
        page = self._design["page"]
        label = QLabel()
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        spacing = int(float(line or page["line"]) * 100)
        style = (f"font-family:'{_family(font or page['font'])}';font-size:{int(size)}px;"
                 f"color:{colour};line-height:{spacing}%;font-weight:"
                 f"{'700' if weight == 'bold' else '400'};"
                 + ("font-style:italic;" if italic else ""))
        label.setText(f'{RICH_STYLE}<div style="{style}">{html}</div>')
        label.setStyleSheet(f"background: transparent; color: {colour};")
        label.setAlignment(self._qt_align(align) | Qt.AlignmentFlag.AlignTop)
        return label

    def _w(self, text) -> str:
        """Words as one person reads them: {{FirstName}} and {a|b} filled in from a contact."""
        context = self._sample.get("context")
        text = str(text or "")
        return merge.render(text, context, html=True, rng=random.Random(7)) if context else text

    def _p(self, text) -> str:
        return composer.text_to_html(self._w(text))

    @staticmethod
    def _qt_align(align: str) -> Qt.AlignmentFlag:
        return {"center": Qt.AlignmentFlag.AlignHCenter,
                "right": Qt.AlignmentFlag.AlignRight}.get(align, Qt.AlignmentFlag.AlignLeft)

    def _aligned(self, widget: QWidget, align: str) -> QWidget:
        holder = QWidget()
        holder.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        if align in ("center", "right"):
            layout.addStretch(1)
        layout.addWidget(widget)
        if align in ("center", "left"):
            layout.addStretch(1)
        return holder

    def _picture(self, ref, width: int, radius: int = 0, play: str = "") -> QWidget:
        """The picture behind an image setting, or a box saying where to choose one."""
        found = design.asset_bytes(self._design, ref)
        label = QLabel()
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        if not found:
            web = isinstance(ref, str) and ref.startswith(("http://", "https://"))
            label.setText(t("Picture from the web. It shows in the email.") if web else
                          t("No picture yet. Choose one on the right."))
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setWordWrap(True)
            label.setFixedSize(max(120, width), max(70, min(160, width // 3)))
            label.setStyleSheet("background:#eef1f5;color:#8a8f98;border:1px dashed #b9c1cc;"
                                "border-radius:6px;font-size:12px;")
            return label
        data, _mime = found
        key = f"{ref}-{play}"
        pixmap = self._pixmaps.get(key)
        if pixmap is None:
            pixmap = _pixmap(design.video_thumbnail(data, play) if play else data)
            self._pixmaps[key] = pixmap
        width = max(10, min(width, pixmap.width()))
        scaled = pixmap.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
        label.setPixmap(_rounded(scaled, radius))
        label.setFixedSize(scaled.size())
        return label

    def _button(self, words: str, colour: str, text_colour: str = "#ffffff", radius: int = 6,
                size: str = "medium", full: bool = False, border: str = "") -> QLabel:
        pad, font = {"small": ((8, 16), 13), "large": ((16, 36), 17)}.get(size, ((12, 26), 15))
        label = QLabel(words)
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        edge = f"1px solid {border}" if design._colour(border) else "none"
        label.setStyleSheet(
            f"background-color:{colour};color:{text_colour};border-radius:{int(radius)}px;"
            f"padding:{pad[0]}px {pad[1]}px;font-size:{font}px;font-weight:700;"
            f"font-family:'{_family(self._design['page']['font'])}';border:{edge};")
        if full:
            label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return label

    def _inner(self, block: dict) -> int:
        return max(60, self._card_width() - 2 * int(block.get("pad_side", 0)))

    # --- blocks ---------------------------------------------------------------------
    def _fill(self, view: BlockView, b: dict) -> None:
        handler: Callable = getattr(self, "_draw_" + b["type"], None)
        view.pad()
        if handler is not None:
            handler(view, b)

    def _draw_heading(self, view: BlockView, b: dict) -> None:
        view.layout_.addWidget(self._text(self._w(b["text"]), b["size"], b["color"], b["align"],
                                          b.get("font", ""), b["weight"], line="1.25"))

    def _draw_message(self, view: BlockView, b: dict) -> None:
        html = self._sample.get("message") or (
            "<p><i>" + t("Your message goes here. Each person gets one of the messages you "
                         "wrote on the My message page.") + "</i></p>")
        if b.get("signature", True) and self._sample.get("signature"):
            html += "<br>" + self._sample["signature"]
        view.layout_.addWidget(self._text(html, b["size"], b["color"], b["align"]))

    def _draw_text(self, view: BlockView, b: dict) -> None:
        view.layout_.addWidget(self._text(self._p(b["text"]), b["size"], b["color"],
                                          b["align"], italic=b.get("italic")))

    def _draw_quote(self, view: BlockView, b: dict) -> None:
        box = QFrame()
        box.setObjectName("Quote")
        box.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        box.setStyleSheet(f"#Quote {{ border: none; border-left: 4px solid {b['bar']}; }}")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(16, 4, 0, 4)
        layout.addWidget(self._text(self._p(b["text"]), b["size"], b["color"],
                                    italic=b.get("italic")))
        if str(b.get("author", "")).strip():
            layout.addWidget(self._text(self._w(b["author"]), 13, "#777777"))
        view.layout_.addWidget(box)

    def _draw_links(self, view: BlockView, b: dict) -> None:
        decoration = "underline" if b.get("underline", True) else "none"
        items = []
        for line in str(b.get("items", "")).splitlines():
            if line.strip():
                label = self._w(line.partition("|")[0].strip())
                items.append(f'<span style="color:{b["color"]};text-decoration:{decoration};">'
                             f'{label}</span>')
        view.layout_.addWidget(self._text("&nbsp;&nbsp;&nbsp;".join(items), b["size"],
                                          b["color"], b["align"]))

    def _draw_logo(self, view: BlockView, b: dict) -> None:
        view.target = self._picture(b.get("image"), int(b["width"]))
        view.layout_.addWidget(self._aligned(view.target, b["align"]))

    def _draw_banner(self, view: BlockView, b: dict) -> None:
        view.pad(0, 0, 0)
        if b.get("image"):
            view.layout_.addWidget(self._picture(b.get("image"), self._card_width()))
        title, subtitle = str(b.get("title", "")).strip(), str(b.get("subtitle", "")).strip()
        if not (title or subtitle):
            return
        band = QFrame()
        band.setObjectName("Band")
        band.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        second = design._colour(b.get("color2"))
        fill = (f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {b['color']}, stop:1 {second})"
                if second else b["color"])
        band.setStyleSheet(f"#Band {{ background: {fill}; border: none; }}")
        layout = QVBoxLayout(band)
        side = int(b.get("pad_side", 0))
        layout.setContentsMargins(side, int(b.get("pad_top", 0)), side, int(b.get("pad_bottom", 0)))
        layout.setSpacing(8)
        if title:
            layout.addWidget(self._text(self._w(title), b["title_size"], b["text_color"],
                                        b["align"], weight="bold", line="1.2"))
        if subtitle:
            layout.addWidget(self._text(self._w(subtitle), 16, b["text_color"], b["align"]))
        view.layout_.addWidget(band)

    def _draw_image(self, view: BlockView, b: dict) -> None:
        width = round(self._inner(b) * int(b["width"]) / 100)
        view.target = self._picture(b.get("image"), width, int(b["radius"]))
        view.layout_.addWidget(self._aligned(view.target, b["align"]))
        if str(b.get("caption", "")).strip():
            view.layout_.addSpacing(8)
            view.layout_.addWidget(self._text(self._w(b["caption"]), 13, "#777777", b["align"]))

    def _draw_video(self, view: BlockView, b: dict) -> None:
        width = round(self._inner(b) * int(b["width"]) / 100)
        view.target = self._picture(b.get("image"), width, int(b["radius"]), play=b["play"])
        view.layout_.addWidget(self._aligned(view.target, b["align"]))

    def _draw_button(self, view: BlockView, b: dict) -> None:
        if not str(b["label"]).strip():
            view.layout_.addWidget(self._text(t("Double-click here to type the button's words."),
                                              12, "#8a8f98", "center"))
            view.target = None
            return
        button = self._button(self._w(b["label"]), b["color"], b["text_color"], b["radius"], b["size"],
                              b.get("full"), b.get("border", ""))
        view.target = button
        view.layout_.addWidget(button if b.get("full") else self._aligned(button, b["align"]))

    def _draw_social(self, view: BlockView, b: dict) -> None:
        row = QWidget()
        row.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        size = int(b["size"])
        shown = 0
        for network, (label, brand, _letters) in design.NETWORKS.items():
            if not str(b.get(network, "")).strip():
                continue
            shown += 1
            if b["style"] == "text":
                layout.addWidget(self._text(t(label), 14, b["color"]))
                continue
            colour = brand if b["colours"] == "brand" else b["color"]
            key = f"social-{network}-{b['style']}-{colour}-{size}"
            pixmap = self._pixmaps.get(key)
            if pixmap is None:
                pixmap = _pixmap(design.social_icon(network, colour, b["style"], size))
                pixmap = pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
                self._pixmaps[key] = pixmap
            icon = QLabel()
            icon.setPixmap(pixmap)
            icon.setFixedSize(size, size)
            layout.addWidget(icon)
        if not shown:
            view.layout_.addWidget(self._text(t("Add your social media links on the right."), 12,
                                              "#8a8f98", "center"))
            return
        view.layout_.addWidget(self._aligned(row, b["align"]))

    def _column(self, b: dict, side: str, width: int) -> QWidget:
        holder = QWidget()
        holder.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        if b.get(f"{side}_image") or not (b.get(f"{side}_title") or b.get(f"{side}_text")):
            layout.addWidget(self._aligned(self._picture(b.get(f"{side}_image"), width, 6),
                                           "center"))
        if str(b.get(f"{side}_title", "")).strip():
            layout.addWidget(self._text(self._w(b[f"{side}_title"]), 18, b["title_color"],
                                        b["align"], weight="bold"))
        if str(b.get(f"{side}_text", "")).strip():
            layout.addWidget(self._text(self._p(b[f"{side}_text"]), 14, b["color"], b["align"]))
        if str(b.get(f"{side}_button", "")).strip():
            layout.addWidget(self._aligned(self._button(self._w(b[f"{side}_button"]),
                                                        b["button_color"],
                                                        size="small"), b["align"]))
        layout.addStretch(1)
        return holder

    def _draw_columns(self, view: BlockView, b: dict) -> None:
        total = self._inner(b)
        gap = int(b["gap"])
        if self.phone:
            view.layout_.addWidget(self._column(b, "left", total))
            view.layout_.addSpacing(16)
            view.layout_.addWidget(self._column(b, "right", total))
            return
        share = {"33": 0.34, "67": 0.66}.get(b["ratio"], 0.5)
        left = round((total - gap) * share)
        row = QWidget()
        row.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(gap)
        first, second = self._column(b, "left", left), self._column(b, "right", total - gap - left)
        first.setFixedWidth(left)
        layout.addWidget(first, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(second, 1, Qt.AlignmentFlag.AlignTop)
        view.layout_.addWidget(row)

    def _draw_card(self, view: BlockView, b: dict) -> None:
        box = QFrame()
        box.setObjectName("Box")
        box.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        border = design._colour(b.get("border"))
        box.setStyleSheet(f"#Box {{ background-color: {b['card_bg']}; border-radius: "
                          f"{int(b['radius'])}px; border: "
                          f"{'1px solid ' + border if border else 'none'}; }}")
        layout = QVBoxLayout(box)
        inner = int(b["inner"])
        layout.setContentsMargins(inner, inner, inner, inner)
        layout.setSpacing(8)
        if b.get("image"):
            layout.addWidget(self._aligned(self._picture(b["image"], self._inner(b) - 2 * inner, 6),
                                           "center"))
        if str(b.get("title", "")).strip():
            layout.addWidget(self._text(self._w(b["title"]), 18, b["title_color"], b["align"],
                                        weight="bold"))
        if str(b.get("text", "")).strip():
            layout.addWidget(self._text(self._p(b["text"]), 14, b["color"], b["align"]))
        if str(b.get("button", "")).strip():
            layout.addSpacing(6)
            layout.addWidget(self._aligned(
                self._button(self._w(b["button"]), b["button_color"], radius=min(int(b["radius"]), 24)),
                b["align"]))
        view.layout_.addWidget(box)

    def _draw_divider(self, view: BlockView, b: dict) -> None:
        line = QFrame()
        line.setObjectName("Line")
        line.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        thickness = int(b["thickness"])
        line.setFixedHeight(thickness)
        line.setStyleSheet(f"#Line {{ border: none; border-top: {thickness}px {b['style']} "
                           f"{b['color']}; }}")
        line.setFixedWidth(max(10, round(self._inner(b) * int(b["width"]) / 100)))
        view.layout_.addWidget(self._aligned(line, "center"))

    def _draw_spacer(self, view: BlockView, b: dict) -> None:
        view.pad(0, 0, 0)
        view.setFixedHeight(int(b["height"]))

    def _draw_footer(self, view: BlockView, b: dict) -> None:
        if str(b.get("text", "")).strip():
            view.layout_.addWidget(self._text(self._p(b["text"]), b["size"], b["color"],
                                              b["align"]))
        if self._sample.get("unsubscribe"):
            view.layout_.addSpacing(8)
            view.layout_.addWidget(self._text(self._sample["unsubscribe"], b["size"], b["color"],
                                              b["align"]))

    def _draw_html(self, view: BlockView, b: dict) -> None:
        view.layout_.addWidget(self._text(self._w(b.get("code", "")), 14, "#333333"))


def picture_thumbnail(data: str, width: int) -> QPixmap:
    """A small preview of a stored picture for the settings panel."""
    pixmap = _pixmap(base64.b64decode(data))
    if pixmap.isNull():
        return pixmap
    return pixmap.scaledToWidth(min(width, pixmap.width()),
                                Qt.TransformationMode.SmoothTransformation)


def snapshot(data: dict, sample: dict, width: int, height: int) -> QPixmap:
    """A miniature of a design for the gallery of starting designs: its top part, scaled down."""
    canvas = EmailCanvas()
    canvas.resize(int(data["page"]["width"]) + 2 * int(data["page"]["outer_pad"]) + 24, 1600)
    canvas.show_design(data, sample)
    # Rendered without ever being shown, so no window flashes up on screen
    outer = canvas.takeWidget()
    outer.resize(canvas.width(), 1600)
    outer.layout().activate()
    full = outer.grab()
    outer.deleteLater()
    canvas.deleteLater()
    scaled = full.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
    return scaled.copy(0, 0, width, min(height, scaled.height()))

