"""An email editor that works like Outlook's: select words and make them bold, bigger, coloured.

What it saves matters as much as what it shows. Qt's own HTML is long and full
of styles on every paragraph, and the spam score counts styling as a sign of a
newsletter. So the document is written out by ``document_to_html`` the way a
person typing an email would produce it: each line a line, an empty line between
paragraphs (``<p>``), and tags only where the writer actually formatted something.
``editor_html`` reads that back, and also reads messages typed before v0.7.3.
"""
from __future__ import annotations

import base64
import html
import re
from typing import Callable

from PyQt6 import sip
from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PyQt6.QtGui import (QColor, QFont, QTextBlockFormat, QTextCharFormat, QTextCursor,
                         QTextDocument, QTextImageFormat, QTextListFormat)
from PyQt6.QtWidgets import (QColorDialog, QComboBox, QFileDialog, QInputDialog, QMenu,
                             QPushButton, QTextEdit, QWidget)

from app.core import composer, design
from app.i18n import t
from app.ui import theme
from app.ui.widgets.common import flow_row

# Point sizes, as Outlook offers them
SIZES = (8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 36, 48)
BASE_FONT = "Arial"
BASE_PIXELS = 14            # what the email itself uses when nothing is chosen
PICTURE_WIDTHS = {"message": 560, "signature": 220}

QUICK_COLOURS = ("#000000", "#333333", "#777777", "#c00000", "#e02424", "#f59e0b",
                 "#2e9e63", "#2f7fd8", "#1f3a93", "#7c3aed")
HIGHLIGHTS = ("#fff59d", "#c8f7c5", "#bde0fe", "#ffd6e7", "#ffe0b2")

# Segoe icon font glyphs, with a plain stand-in for computers without the font
ICONS = {
    "bold": ("", "B"), "italic": ("", "I"), "underline": ("", "U"),
    "strike": ("", "S"), "colour": ("", "A"), "highlight": ("", "H"),
    "bullets": ("", "•"), "outdent": ("", "<"), "indent": ("", ">"),
    "left": ("", "L"), "center": ("", "C"), "right": ("", "R"),
    "link": ("", "Link"), "picture": ("", "Pic"), "clear": ("", "X"),
}

_EMPTY = re.compile(r"^[\s  ￼]*$")


# --- reading and writing ---------------------------------------------------------
def editor_html(stored: str) -> str:
    """Saved message HTML (or text typed before v0.7.3) as the editor shows it.

    In the editor every line is a paragraph with no gap, and a gap between
    paragraphs is an empty line, as it is in the plain text people type. So each
    break between paragraphs becomes one empty line.
    """
    if not stored.strip():
        return ""
    markup = composer.text_to_html(stored) if not composer.uses_html(stored) else stored
    if not composer.uses_html(markup):
        markup = f"<p>{markup}</p>"
    markup = re.sub(r"<br\s*/?>\s*", "<br>", markup, flags=re.IGNORECASE)
    return re.sub(r"(</(?:p|ul|ol|h[1-6]|div|table)>)\s*(?=<(?:p|ul|ol|h[1-6]|div|table)\b)",
                  r'\1<p style="-qt-paragraph-type:empty;"><br /></p>', markup,
                  flags=re.IGNORECASE)


def _style(fmt: QTextCharFormat) -> str:
    rules = []
    if fmt.hasProperty(QTextCharFormat.Property.FontFamilies):
        families = fmt.fontFamilies() or []
        if families:
            rules.append(f"font-family:{design.FONTS.get(families[0], families[0])}")
    if fmt.hasProperty(QTextCharFormat.Property.FontPointSize) and fmt.fontPointSize() > 0:
        rules.append(f"font-size:{fmt.fontPointSize():g}pt")
    if not fmt.isAnchor() and fmt.hasProperty(QTextCharFormat.Property.ForegroundBrush):
        brush = fmt.foreground()
        if brush.style() != Qt.BrushStyle.NoBrush and brush.color().alpha():
            rules.append(f"color:{brush.color().name()}")
    if fmt.hasProperty(QTextCharFormat.Property.BackgroundBrush):
        brush = fmt.background()
        if brush.style() != Qt.BrushStyle.NoBrush and brush.color().alpha():
            rules.append(f"background-color:{brush.color().name()}")
    return ";".join(rules)


def _fragment(fragment) -> str:
    fmt = fragment.charFormat()
    if fmt.isImageFormat():
        image = fmt.toImageFormat()
        size = f' width="{round(image.width())}"' if image.width() > 0 else ""
        return f'<img src="{html.escape(image.name())}"{size} alt="">'
    words = html.escape(fragment.text(), quote=False).replace(" ", "<br>")
    words = words.replace("￼", "")
    if not words:
        return ""
    style = _style(fmt)
    if style:
        words = f'<span style="{style}">{words}</span>'
    for on, tag in ((fmt.fontStrikeOut(), "s"),
                    (fmt.fontUnderline() and not fmt.isAnchor(), "u"),
                    (fmt.fontItalic(), "em"),
                    (fmt.fontWeight() >= QFont.Weight.DemiBold.value, "strong")):
        if on:
            words = f"<{tag}>{words}</{tag}>"
    if fmt.isAnchor() and fmt.anchorHref():
        words = f'<a href="{html.escape(fmt.anchorHref())}">{words}</a>'
    return words


def _line(block) -> str:
    parts = []
    iterator = block.begin()
    while not iterator.atEnd():
        fragment = iterator.fragment()
        if fragment.isValid():
            parts.append(_fragment(fragment))
        iterator += 1
    return "".join(parts)


_ALIGN = {Qt.AlignmentFlag.AlignHCenter: "center", Qt.AlignmentFlag.AlignRight: "right",
          Qt.AlignmentFlag.AlignJustify: "justify"}


def document_to_html(document: QTextDocument) -> str:
    """The editor's contents as tidy email HTML. Empty when there is nothing in it."""
    out: list[str] = []
    lines: list[str] = []
    key: tuple | None = None
    open_list = None

    def end_paragraph() -> None:
        nonlocal lines
        if lines:
            align, indent = key
            styles = []
            if align:
                styles.append(f"text-align:{align}")
            if indent:
                styles.append(f"margin-left:{indent * 40}px")
            attrs = f' style="{";".join(styles)}"' if styles else ""
            out.append(f"<p{attrs}>" + "<br>\n".join(lines) + "</p>")
            lines = []

    def end_list() -> None:
        nonlocal open_list
        if open_list is not None:
            out.append("</ol>" if _numbered(open_list) else "</ul>")
            open_list = None

    block = document.begin()
    while block.isValid():
        text = _line(block)
        listed = block.textList()
        if listed is not None:
            end_paragraph()
            if open_list is None or sip.unwrapinstance(listed) != sip.unwrapinstance(open_list):
                end_list()
                open_list = listed
                indent = listed.format().indent()
                extra = f' style="margin-left:{(indent - 1) * 40}px"' if indent > 1 else ""
                out.append(("<ol" if _numbered(listed) else "<ul") + extra + ">")
            out.append(f"  <li>{text.rstrip() or '<br>'}</li>")
        else:
            end_list()
            if _EMPTY.match(block.text()) and "<img" not in text:
                end_paragraph()
            else:
                flag = block.blockFormat().alignment() & Qt.AlignmentFlag.AlignHorizontal_Mask
                this = (_ALIGN.get(Qt.AlignmentFlag(flag), ""), block.blockFormat().indent())
                if lines and this != key:
                    end_paragraph()
                key = this
                lines.append(text.rstrip())
        block = block.next()
    end_paragraph()
    end_list()
    return "\n\n".join(_join_lists(out))


def _numbered(text_list) -> bool:
    return text_list.format().style() in (QTextListFormat.Style.ListDecimal,
                                          QTextListFormat.Style.ListLowerAlpha,
                                          QTextListFormat.Style.ListUpperAlpha,
                                          QTextListFormat.Style.ListLowerRoman,
                                          QTextListFormat.Style.ListUpperRoman)


def _join_lists(chunks: list[str]) -> list[str]:
    """Each list's items belong in one chunk with its opening and closing tag."""
    joined: list[str] = []
    for chunk in chunks:
        if joined and (chunk.startswith("  <li>") or chunk in ("</ul>", "</ol>")):
            joined[-1] += "\n" + chunk
        else:
            joined.append(chunk)
    return joined


def picture_uri(asset: dict) -> str:
    return f"data:{asset['mime']};base64,{asset['data']}"


# --- the editor -------------------------------------------------------------------------
class RichBox(QTextEdit):
    """A box for one message, signature or footer, white like the email itself."""

    def __init__(self, placeholder: str = "", kind: str = "message", lines: int = 12,
                 parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setAcceptRichText(True)
        self.setTabChangesFocus(True)
        self.setPlaceholderText(t(placeholder))
        document = self.document()
        document.setDefaultStyleSheet("p, ul, ol, li, h1, h2, h3 { margin-top: 0px; "
                                      "margin-bottom: 0px; }")
        font = QFont(BASE_FONT)
        font.setPixelSize(round(BASE_PIXELS * theme.text_scale()))
        document.setDefaultFont(font)
        document.setDocumentMargin(round(10 * theme.text_scale()))
        # The email's own font and colours, not the app's, so it looks as it will be read.
        # Set here because the app's stylesheet would otherwise replace the document's font.
        self.setStyleSheet(f"QTextEdit {{ background-color: #ffffff; color: #333333; "
                           f"font-family: {BASE_FONT}; font-size: {font.pixelSize()}px; "
                           "selection-background-color: #b3d4fc; selection-color: #000000; }")
        self.verticalScrollBar().setSingleStep(18)
        spacing = self.fontMetrics().lineSpacing()
        self.setMinimumHeight(int(spacing * lines + 16 * theme.text_scale()))
        self.setToolTip(t("Double-click a picture to change its size"))

    # -- contents --
    def html(self) -> str:
        return document_to_html(self.document())

    def set_html(self, stored: str) -> None:
        blocked = self.blockSignals(True)
        self.setHtml(editor_html(stored))
        self.blockSignals(blocked)

    def is_empty(self) -> bool:
        return not self.html().strip()

    # -- keys --
    def keyPressEvent(self, event):  # noqa: N802 - Qt naming
        control = event.modifiers() & Qt.KeyboardModifier.ControlModifier
        if control and not self.isReadOnly():
            action = {Qt.Key.Key_B: self.toggle_bold, Qt.Key.Key_I: self.toggle_italic,
                      Qt.Key.Key_U: self.toggle_underline}.get(Qt.Key(event.key()))
            if action:
                action()
                event.accept()
                return
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                # Ctrl+Enter starts a new line, as it does in chat programs and webmail
                self.textCursor().insertBlock()
                self.ensureCursorVisible()
                event.accept()
                return
        super().keyPressEvent(event)

    # -- pasting: keep the formatting, and pictures copied on their own --
    def insertFromMimeData(self, source):  # noqa: N802 - Qt naming
        if source.hasImage() and not source.hasHtml():
            image = source.imageData()
            if image is not None and not image.isNull():
                data = QByteArray()
                buffer = QBuffer(data)
                buffer.open(QIODevice.OpenModeFlag.WriteOnly)
                image.save(buffer, "PNG")
                asset = {"mime": "image/png", "w": image.width(), "h": image.height(),
                         "data": base64.b64encode(bytes(data)).decode("ascii")}
                self.insert_picture(asset)
                return
        super().insertFromMimeData(source)

    def mouseDoubleClickEvent(self, event):  # noqa: N802 - Qt naming
        cursor = self.cursorForPosition(event.position().toPoint())
        for probe in (cursor, QTextCursor(cursor)):
            if probe is not cursor:
                probe.movePosition(QTextCursor.MoveOperation.Right)
            fmt = probe.charFormat()
            if fmt.isImageFormat():
                self._resize_picture(cursor if probe is cursor else probe)
                return
        super().mouseDoubleClickEvent(event)

    def _resize_picture(self, cursor: QTextCursor) -> None:
        image = cursor.charFormat().toImageFormat()
        current = round(image.width()) or 200
        width, ok = QInputDialog.getInt(self, t("Picture size"),
                                        t("How wide the picture is, in pixels"), current, 16, 1200)
        if not ok or width == current:
            return
        ratio = image.height() / image.width() if image.width() > 0 else 0
        cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.KeepAnchor)
        if not cursor.charFormat().isImageFormat():
            cursor.movePosition(QTextCursor.MoveOperation.Right)
            cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor)
        image.setWidth(width)
        if ratio:
            image.setHeight(round(width * ratio))
        cursor.setCharFormat(image)

    # -- formatting --
    def _merge(self, fmt: QTextCharFormat) -> None:
        self.mergeCurrentCharFormat(fmt)
        self.setFocus()

    def toggle_bold(self) -> None:
        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Weight.Normal if self.fontWeight() >= QFont.Weight.DemiBold.value
                          else QFont.Weight.Bold)
        self._merge(fmt)

    def toggle_italic(self) -> None:
        fmt = QTextCharFormat()
        fmt.setFontItalic(not self.fontItalic())
        self._merge(fmt)

    def toggle_underline(self) -> None:
        fmt = QTextCharFormat()
        fmt.setFontUnderline(not self.fontUnderline())
        self._merge(fmt)

    def toggle_strike(self) -> None:
        fmt = QTextCharFormat()
        fmt.setFontStrikeOut(not self.currentCharFormat().fontStrikeOut())
        self._merge(fmt)

    def set_family(self, family: str) -> None:
        fmt = QTextCharFormat()
        fmt.setFontFamilies([family])
        self._merge(fmt)

    def set_size(self, points: float) -> None:
        fmt = QTextCharFormat()
        fmt.setFontPointSize(points)
        self._merge(fmt)

    def set_colour(self, colour: str) -> None:
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(colour))
        self._merge(fmt)

    def set_highlight(self, colour: str) -> None:
        fmt = QTextCharFormat()
        fmt.setBackground(QColor(colour) if colour else QColor(0, 0, 0, 0))
        self._merge(fmt)

    def set_align(self, align: Qt.AlignmentFlag) -> None:
        self.setAlignment(align)
        self.setFocus()

    def toggle_list(self, numbered: bool) -> None:
        cursor = self.textCursor()
        style = QTextListFormat.Style.ListDecimal if numbered else QTextListFormat.Style.ListDisc
        current = cursor.currentList()
        cursor.beginEditBlock()
        if current is not None and current.format().style() == style:
            # Pressed again: the lines go back to ordinary lines
            start, end = cursor.selectionStart(), cursor.selectionEnd()
            block = self.document().findBlock(start)
            while block.isValid() and block.position() <= end:
                if block.textList() is not None:
                    block.textList().remove(block)
                    plain = QTextCursor(block)
                    fmt = block.blockFormat()
                    fmt.setIndent(0)
                    plain.setBlockFormat(fmt)
                block = block.next()
        elif current is not None:
            fmt = current.format()
            fmt.setStyle(style)
            current.setFormat(fmt)
        else:
            cursor.createList(style)
        cursor.endEditBlock()
        self.setFocus()

    def change_indent(self, step: int) -> None:
        cursor = self.textCursor()
        current = cursor.currentList()
        if current is not None:
            fmt = current.format()
            fmt.setIndent(max(1, fmt.indent() + step))
            current.setFormat(fmt)
        else:
            fmt = cursor.blockFormat()
            fmt.setIndent(max(0, fmt.indent() + step))
            cursor.setBlockFormat(fmt)
        self.setFocus()

    def add_link(self) -> None:
        cursor = self.textCursor()
        current = cursor.charFormat().anchorHref() if cursor.charFormat().isAnchor() else ""
        address, ok = QInputDialog.getText(
            self, t("Add a link"), t("Web address the link opens, for example "
                                     "www.yourcompany.com"), text=current)
        address = address.strip()
        if not ok:
            return
        if not address:
            # An empty address takes the link off the selected words
            fmt = QTextCharFormat()
            fmt.setAnchor(False)
            fmt.setAnchorHref("")
            fmt.setFontUnderline(False)
            fmt.setForeground(QColor("#333333"))
            cursor.mergeCharFormat(fmt)
            return
        if "://" not in address and not address.startswith("mailto:"):
            address = ("mailto:" + address) if "@" in address and "/" not in address \
                else "https://" + address
        fmt = QTextCharFormat()
        fmt.setAnchor(True)
        fmt.setAnchorHref(address)
        fmt.setForeground(QColor("#005fb8"))
        fmt.setFontUnderline(True)
        if cursor.hasSelection():
            cursor.mergeCharFormat(fmt)
        else:
            shown = address.removeprefix("mailto:")
            cursor.insertText(shown, fmt)
            cursor.setCharFormat(QTextCharFormat())
            self.setCurrentCharFormat(QTextCharFormat())
        self.setFocus()

    def clear_formatting(self) -> None:
        cursor = self.textCursor()
        if cursor.hasSelection():
            cursor.setCharFormat(QTextCharFormat())
            fmt = QTextBlockFormat()
            cursor.setBlockFormat(fmt)
        self.setCurrentCharFormat(QTextCharFormat())
        self.setFocus()

    def insert_picture(self, asset: dict) -> None:
        widest = PICTURE_WIDTHS.get(self.kind, PICTURE_WIDTHS["message"])
        width = min(int(asset.get("w") or widest), widest)
        image = QTextImageFormat()
        image.setName(picture_uri(asset))
        image.setWidth(width)
        if asset.get("w") and asset.get("h"):
            image.setHeight(round(width * int(asset["h"]) / int(asset["w"])))
        self.textCursor().insertImage(image)
        self.setFocus()


# --- the toolbar ------------------------------------------------------------------------
class RichToolbar(QWidget):
    """Outlook's Format Text bar: font, size, bold, colours, lists, alignment, link, picture.

    It acts on whichever box ``target()`` returns. Its buttons never take the
    focus, so the words selected in the box stay selected.
    """

    def __init__(self, target: Callable[[], RichBox | None], on_picture=None, parent=None):
        super().__init__(parent)
        self.setProperty("role", "plain")
        self._target = target
        self._on_picture = on_picture
        self._syncing = False
        from PyQt6.QtWidgets import QVBoxLayout

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        container, layout = flow_row(4)
        outer.addWidget(container)

        self.family_box = QComboBox()
        self.family_box.addItem(t("Font"), "")
        for name in design.FONTS:
            self.family_box.addItem(name, name)
        self.family_box.setToolTip(t("Font"))
        self.family_box.activated.connect(lambda _i: self._family())
        self.size_box = QComboBox()
        self.size_box.addItem(t("Size"), 0)
        for points in SIZES:
            self.size_box.addItem(str(points), points)
        self.size_box.setToolTip(t("Text size"))
        self.size_box.activated.connect(lambda _i: self._size())
        for box in (self.family_box, self.size_box):
            box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            layout.addWidget(box)

        self.buttons: dict[str, QPushButton] = {}
        for key, tip, action, checkable in (
                ("bold", "Bold (Ctrl+B)", lambda b: b.toggle_bold(), True),
                ("italic", "Italic (Ctrl+I)", lambda b: b.toggle_italic(), True),
                ("underline", "Underline (Ctrl+U)", lambda b: b.toggle_underline(), True),
                ("strike", "Strikethrough", lambda b: b.toggle_strike(), True),
                ("colour", "Text colour", None, False),
                ("highlight", "Highlight", None, False),
                ("bullets", "Bullet points", lambda b: b.toggle_list(False), True),
                ("numbers", "Numbered list", lambda b: b.toggle_list(True), True),
                ("outdent", "Move the line back", lambda b: b.change_indent(-1), False),
                ("indent", "Move the line in", lambda b: b.change_indent(1), False),
                ("left", "Line up on the left", lambda b: b.set_align(Qt.AlignmentFlag.AlignLeft),
                 True),
                ("center", "Centre", lambda b: b.set_align(Qt.AlignmentFlag.AlignHCenter), True),
                ("right", "Line up on the right",
                 lambda b: b.set_align(Qt.AlignmentFlag.AlignRight), True),
                ("link", "Add a link to the selected words", lambda b: b.add_link(), False),
                ("picture", "Add a picture or logo", None, False),
                ("clear", "Clear the formatting of the selected words",
                 lambda b: b.clear_formatting(), False)):
            button = self._button(key, tip, checkable)
            if key == "colour":
                button.setMenu(self._colour_menu(QUICK_COLOURS, "set_colour", None))
            elif key == "highlight":
                button.setMenu(self._colour_menu(HIGHLIGHTS, "set_highlight", "No highlight"))
            elif key == "picture":
                button.clicked.connect(lambda _c=False: self._picture())
            else:
                button.clicked.connect(lambda _c=False, a=action: self._run(a))
            self.buttons[key] = button
            layout.addWidget(button)

    def _button(self, key: str, tip: str, checkable: bool) -> QPushButton:
        glyph, fallback = ICONS.get(key, ("", "1."))
        family = theme.icon_family()
        button = QPushButton(glyph if family and glyph else fallback)
        button.setProperty("choice", "off")
        button.setToolTip(t(tip))
        button.setAccessibleName(t(tip))
        button.setCheckable(checkable)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        # As tall as the Font and Size boxes beside it (the stylesheet's button height)
        button.setMinimumWidth(round(34 * theme.text_scale()))
        css = theme.icon_css(15) if family and glyph else f"font-size: {theme.px(13)}px; " \
                                                           "font-weight: 700;"
        button.setStyleSheet(f"QPushButton {{ {css} padding: 0 {theme.px(8)}px; }}")
        return button

    def _colour_menu(self, colours: tuple, method: str, none_label: str | None) -> QMenu:
        menu = QMenu(self)
        for colour in colours:
            action = menu.addAction(colour)
            from PyQt6.QtGui import QIcon, QPixmap

            swatch = QPixmap(14, 14)
            swatch.fill(QColor(colour))
            action.setIcon(QIcon(swatch))
            action.triggered.connect(lambda _c=False, c=colour: self._run(
                lambda b: getattr(b, method)(c)))
        menu.addSeparator()
        if none_label:
            menu.addAction(t(none_label)).triggered.connect(
                lambda _c=False: self._run(lambda b: getattr(b, method)("")))
        menu.addAction(t("More colours...")).triggered.connect(
            lambda _c=False: self._pick(method))
        return menu

    def _pick(self, method: str) -> None:
        box = self._target()
        if box is None:
            return
        colour = QColorDialog.getColor(QColor("#333333"), self.window(), t("Choose a colour"))
        if colour.isValid():
            getattr(box, method)(colour.name())

    def _run(self, action) -> None:
        box = self._target()
        if box is not None and action is not None:
            action(box)
            self.sync(box)

    def _family(self) -> None:
        name = self.family_box.currentData()
        if name:
            self._run(lambda b: b.set_family(name))

    def _size(self) -> None:
        points = self.size_box.currentData()
        if points:
            self._run(lambda b: b.set_size(float(points)))

    def _picture(self) -> None:
        box = self._target()
        if box is None:
            return
        path, _filter = QFileDialog.getOpenFileName(
            self, t("Choose a picture"), "",
            t("Pictures (*.png *.jpg *.jpeg *.gif *.webp *.bmp);;All files (*.*)"))
        if path and self._on_picture:
            self._on_picture(box, path)

    def sync(self, box: RichBox | None) -> None:
        """Show the formatting where the cursor is: Bold pressed in, the size, and so on."""
        if box is None:
            return
        fmt = box.currentCharFormat()
        cursor = box.textCursor()
        listed = cursor.currentList()
        align = box.alignment() & Qt.AlignmentFlag.AlignHorizontal_Mask
        states = {
            "bold": fmt.fontWeight() >= QFont.Weight.DemiBold.value,
            "italic": fmt.fontItalic(), "underline": fmt.fontUnderline() and not fmt.isAnchor(),
            "strike": fmt.fontStrikeOut(),
            "bullets": listed is not None and not _numbered(listed),
            "numbers": listed is not None and _numbered(listed),
            "left": not (align & (Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignRight)),
            "center": bool(align & Qt.AlignmentFlag.AlignHCenter),
            "right": bool(align & Qt.AlignmentFlag.AlignRight),
        }
        from app.ui.widgets.common import restyle

        for key, on in states.items():
            button = self.buttons[key]
            button.setChecked(bool(on))
            if button.property("choice") != ("on" if on else "off"):
                button.setProperty("choice", "on" if on else "off")
                restyle(button)
        families = fmt.fontFamilies() if fmt.hasProperty(
            QTextCharFormat.Property.FontFamilies) else None
        index = self.family_box.findData(families[0]) if families else 0
        self.family_box.setCurrentIndex(max(0, index))
        points = fmt.fontPointSize() if fmt.hasProperty(
            QTextCharFormat.Property.FontPointSize) else 0
        index = self.size_box.findData(int(points)) if points else 0
        self.size_box.setCurrentIndex(max(0, index))
