"""Email design: how the email looks. Blocks on the left, the email in the middle, settings on the right."""
from __future__ import annotations

import copy
import json
import random
import tempfile
import webbrowser
from pathlib import Path

from PyQt6 import sip
from PyQt6.QtCore import QPoint, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import (QAction, QColor, QDesktopServices, QIcon, QKeySequence, QPixmap,
                         QShortcut)
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QColorDialog, QFileDialog,
                             QFrame, QHBoxLayout, QInputDialog, QLabel, QListWidget,
                             QListWidgetItem, QMenu, QPushButton, QSplitter, QVBoxLayout, QWidget)

from app import config
from app.core import composer, credentials, db, design, importer, merge, prefs, scorer, sender
from app.i18n import t
from app.ui import theme
from app.ui.pages.base import Page
from app.ui.widgets.common import (Card, ChoiceButtons, FormRow, ScrollPage, TabBar, clear_layout,
                                   column, flow_row, ghost_button, heading, hint, muted,
                                   primary_button, row, secondary_button, set_tone, small_button,
                                   subheading)
from app.ui.widgets.dialogs import ConfirmDialog, InfoDialog
from app.ui.widgets.email_canvas import (INLINE, MIME_NEW, EmailCanvas, faded, picture_thumbnail,
                                         snapshot, start_drag)
from app.ui.widgets.inputs import (Debouncer, checkbox, combo, get_text, line_edit, set_text,
                                   spin_box, text_box)
from app.workers.base import Task

HELP_INTRO = (
    "Make your emails look the way you want: your logo, colours, pictures, buttons and more. "
    "Build a design from blocks, then switch on \"Send my emails with this design\". Your "
    "message still comes from the My message page, so every person still gets a slightly "
    "different email.")

HELP_SECTIONS = [
    ("The quick way", [
        "Step 1. Pick a starting design you like, or Blank to build your own from scratch.",
        "Step 2. Click anything in the email in the middle to change it on the right.",
        "Step 3. Drag blocks from the left into the email. A blue line shows where they will "
        "land. Drag any block in the email to move it.",
        "Step 4. Changes are saved as you make them. Tick \"Send my emails with this "
        "design\" to use it.",
        "Step 5. Press \"Send me a test\" to see it in your own inbox before sending to anyone.",
    ]),
    ("Click and change", [
        "Click a block in the email to select it. Its settings appear on the right.",
        "Double-click a heading, text, quote or button to type straight onto the email. Press "
        "Enter or click somewhere else when you are done.",
        "Pictures, buttons and empty space get a small square handle when selected. Drag it "
        "to make them bigger or smaller.",
        "Click the coloured area around the email to change the email's own style: width, "
        "colours, corners, font and the inbox preview text.",
        "The small buttons beside a selected block move it (drag), make a copy or remove it.",
        "Ctrl+Z undoes a change and Ctrl+Y does it again. Ctrl+S saves.",
    ]),
    ("Your message block", [
        "Every design has one \"Your message\" block. That is where each person's message "
        "goes, picked from the versions you wrote on the My message page, with your signature.",
        "Move it wherever you want it. It cannot be removed, because then nobody would get "
        "your message.",
        "{{FirstName}}, {{Company}} and {Hi|Hello} work in every block, not only the message.",
    ]),
    ("Pictures", [
        "Choose a picture from your computer and it is packed inside every email, so it shows "
        "for everyone without a website. Big photos are made smaller automatically.",
        "If your picture is already online, \"Use a web link\" puts it in by its address "
        "instead, which keeps each email smaller.",
        "Keep all pictures together under about 1 MB. The app warns you if they are bigger.",
        "Many email programs hide pictures until the reader allows them, so never put "
        "important words only inside a picture.",
    ]),
    ("Your brand kit", [
        "Click the area around the email and scroll down to \"My brand kit\". Save your logo, "
        "main colour, text colour, background and font there once.",
        "New designs and new blocks use your brand kit automatically. \"Use my brand kit on "
        "this design\" recolours a design you already made.",
    ]),
    ("Main inbox or Promotions?", [
        "Gmail files emails with pictures, buttons and colours under the Promotions tab more "
        "often than plain ones.",
        "For a first email to someone who does not know you yet, a plain email usually reaches "
        "the main inbox more often. Designs are great for newsletters, offers and customers who "
        "already know you.",
        "Preview & score on the My message page scores the designed email exactly as it will "
        "be sent.",
    ]),
    ("Sharing a design", [
        "Every design is also saved as a file in your Documents folder, in "
        "HomingPigeon\\Designs. A design file includes its pictures, so it works on another "
        "computer.",
        "Press Rename next to a design's name to change it. \"More\" lets you copy, delete, "
        "save a design to a file and open one from a file. \"My designs\" shows them all.",
    ]),
]

HELP_FOOTER = ("Nothing is sent from this page except a test to your own address when you ask "
               "for one.")

QUICK_COLOURS = ("#ffffff", "#f4f5f7", "#1f2530", "#555555", "#e02424", "#f59e0b", "#2e9e63",
                 "#7c3aed")
PICTURE_WARNING_BYTES = 1024 * 1024


class Collapsible(QWidget):
    """A titled group of settings that opens and closes, so a block never shows everything at once."""

    def __init__(self, title: str, opened: bool = True, parent=None):
        super().__init__(parent)
        self.setProperty("role", "plain")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._title = t(title)
        self.toggle = ghost_button("", self._flip)
        self.toggle.setStyleSheet("text-align: left; padding-left: 0;")
        layout.addWidget(self.toggle)
        self.body = QWidget()
        self.body.setProperty("role", "plain")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(10)
        layout.addWidget(self.body)
        self._set(opened)

    def add(self, widget: QWidget) -> None:
        self.body_layout.addWidget(widget)

    def _set(self, opened: bool) -> None:
        self.body.setVisible(opened)
        self.toggle.setText(("▾  " if opened else "▸  ") + self._title)

    def _flip(self) -> None:
        self._set(not self.body.isVisible())


class ColorField(QWidget):
    """A colour: a swatch that opens a colour picker, the code, and a row of quick colours."""

    changed = pyqtSignal(str)

    def __init__(self, value: str, optional: bool = False, brand: tuple = (), parent=None):
        super().__init__(parent)
        self.setProperty("role", "plain")
        self.value = value or ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        size = round(28 * theme.text_scale())
        self.swatch = QPushButton()
        self.swatch.setFixedSize(size, size)
        self.swatch.setCursor(Qt.CursorShape.PointingHandCursor)
        self.swatch.setToolTip(t("Choose a colour"))
        self.swatch.clicked.connect(self._pick)
        self.code = line_edit("#rrggbb")
        self.code.setFixedWidth(round(96 * theme.text_scale()))
        # The same height as the swatch beside it; the stylesheet's minimum would make it taller
        self.code.setStyleSheet("min-height: 0px; padding-top: 0px; padding-bottom: 0px;")
        self.code.setFixedHeight(size)
        self.code.editingFinished.connect(self._typed)
        parts = [self.swatch, self.code]
        if optional:
            none = small_button("None", lambda: self.set(""))
            none.setToolTip(t("No colour: see through to what is behind"))
            parts.append(none)
        layout.addWidget(row(*parts, None, spacing=6))

        quick, quick_layout = flow_row(4)
        small = round(18 * theme.text_scale())
        for colour in dict.fromkeys(tuple(brand) + QUICK_COLOURS):
            button = QPushButton()
            button.setFixedSize(small, small)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(colour)
            button.setStyleSheet(f"background-color:{colour};border:1px solid #9aa3ae;"
                                 f"border-radius:{small // 2}px;padding:0;min-height:0;")
            button.clicked.connect(lambda _c=False, c=colour: self.set(c))
            quick_layout.addWidget(button)
        layout.addWidget(quick)
        self._paint()

    def _paint(self) -> None:
        shown = self.value or "transparent"
        self.swatch.setStyleSheet(f"background-color:{shown};border:1px solid #9aa3ae;"
                                  f"border-radius:4px;padding:0;min-height:0;")
        self.code.setText(self.value)

    def set(self, value: str) -> None:
        if value == self.value:
            return
        self.value = value
        self._paint()
        self.changed.emit(value)

    def _typed(self) -> None:
        text = self.code.text().strip()
        if text and not text.startswith("#"):
            text = "#" + text
        if design.HEX.match(text) or text == "":
            self.set(text.lower())
        else:
            self._paint()

    def _pick(self) -> None:
        colour = QColorDialog.getColor(QColor(self.value or "#ffffff"), self.window(),
                                       t("Choose a colour"))
        if colour.isValid():
            self.set(colour.name())


class ImageField(QWidget):
    """A picture: a preview, choose from the computer, use a web link, or remove."""

    def __init__(self, page: "DesignPage", current, on_asset, on_link, on_clear, parent=None):
        super().__init__(parent)
        self.setProperty("role", "plain")
        self.page = page
        self._on_asset, self._on_link, self._on_clear = on_asset, on_link, on_clear
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.thumb = QLabel()
        self.thumb.setProperty("role", "plain")
        if isinstance(current, dict) and current.get("data"):
            self.thumb.setPixmap(picture_thumbnail(current["data"], round(200 * theme.text_scale())))
        elif isinstance(current, str) and current:
            self.thumb.setText(t("Picture from the web: {address}", address=current))
            self.thumb.setWordWrap(True)
            set_tone(self.thumb, "muted")
        else:
            self.thumb.setText(t("No picture yet"))
            set_tone(self.thumb, "muted")
        layout.addWidget(self.thumb)
        choose = secondary_button("Choose a picture...", self._choose)
        choose.setToolTip(t("Pick a photo or picture from your computer"))
        link = small_button("Use a web link...", self._link)
        link.setToolTip(t("Use a picture that is already online, by its address"))
        parts = [choose, link]
        if current:
            parts.append(small_button("Remove", self._on_clear))
        layout.addWidget(row(*parts, None, spacing=6))

    def _choose(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, t("Choose a picture"), "",
            t("Pictures (*.png *.jpg *.jpeg *.gif *.webp *.bmp);;All files (*.*)"))
        if not path:
            return
        page = self.page
        page.notify("Getting the picture ready...", "info", 2000)
        page.busy += 1

        def done(asset: dict) -> None:
            page.busy -= 1
            self._on_asset(asset)

        def failed(message: str) -> None:
            page.busy -= 1
            page.notify(t("Could not use that picture: {message}", message=message), "error", 8000)

        Task(design.prepare_image, path).start(on_result=page.guard(done),
                                               on_error=page.guard(failed))

    def _link(self) -> None:
        address, ok = QInputDialog.getText(self, t("Use a picture from the web"),
                                           t("The picture's web address, starting with https://"))
        address = address.strip()
        if not ok or not address:
            return
        if not address.startswith(("http://", "https://")):
            self.page.notify("The address must start with https://", "warn")
            return
        self._on_link(address)


# The second line under each block's name in the Add list. The longer note is its tooltip.
BLOCK_LINES = {
    "heading": "A big title", "text": "A paragraph of your words",
    "quote": "Words from a happy customer", "links": "A row of small links",
    "logo": "Your logo", "banner": "A wide picture or coloured band",
    "image": "A photo or picture", "video": "A picture that opens a video",
    "button": "A coloured button with a link", "social": "Links to your social pages",
    "columns": "Two things side by side", "card": "A box that stands out",
    "divider": "A thin line", "spacer": "Empty space",
    "footer": "Company name and address", "html": "For people who know HTML",
}


class BlockRow(QFrame):
    """One block in the Add list: drag it into the email, or click it to add it."""

    def __init__(self, spec: design.BlockSpec, on_click):
        super().__init__()
        self.spec = spec
        self._on_click = on_click
        self._press: QPoint | None = None
        self.setProperty("role", "blockrow")
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip(t(spec.note))
        scale = theme.text_scale()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(round(8 * scale), round(6 * scale), round(8 * scale),
                                  round(6 * scale))
        layout.setSpacing(round(10 * scale))
        icon = QLabel(theme.block_icon(spec.kind, spec.glyph))
        icon.setFixedWidth(round(22 * scale))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(theme.icon_css(18) + f" color: {theme.color('accent')}; "
                                                "background: transparent; border: none;")
        layout.addWidget(icon)
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(round(1 * scale))
        name = QLabel(t(spec.label))
        name.setStyleSheet("font-weight: 600; background: transparent; border: none;")
        line = QLabel(t(BLOCK_LINES.get(spec.kind, "")))
        line.setProperty("role", "hint")
        line.setWordWrap(True)
        line.setStyleSheet("background: transparent; border: none;")
        text.addWidget(name)
        text.addWidget(line)
        layout.addLayout(text, 1)
        for label in (icon, name, line):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def mousePressEvent(self, event):  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()

    def mouseMoveEvent(self, event):  # noqa: N802 - Qt naming
        if (self._press is not None and event.buttons() & Qt.MouseButton.LeftButton
                and (event.position().toPoint() - self._press).manhattanLength()
                >= QApplication.startDragDistance()):
            self._press = None
            start_drag(self, MIME_NEW, self.spec.kind, faded(self))

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt naming
        if self._press is not None and self.rect().contains(event.position().toPoint()):
            self._on_click()
        self._press = None


def thumb_button(picture: QPixmap, on_click) -> QPushButton:
    """A miniature email that opens when clicked."""
    button = QPushButton()
    button.setIcon(QIcon(picture))
    button.setIconSize(picture.size())
    button.setFixedSize(picture.size())
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setStyleSheet("QPushButton { border: none; background: transparent; padding: 0; "
                         "min-height: 0; }")
    button.clicked.connect(lambda _c=False: on_click())
    return button


# Settings shown straight away for a block; the rest wait under "More options"
QUICK_STYLE = {"color", "align", "size", "width", "height", "bar", "play", "card_bg",
               "text_color", "title_size"}
QUICK_PAGE = {"width", "bg", "card_bg", "font", "size"}


class DesignPage(Page):
    def __init__(self, window):
        super().__init__(window)
        self._design: dict | None = None
        self._id: int | None = None
        self._name = ""
        self._selected = ""
        self._history: list[str] = []
        self._position = -1
        self._sample: dict = {}
        self._loading = False
        self.busy = 0

        self._build()
        self._redraw = Debouncer(120, self)
        self._redraw.connect(self._draw)
        self._remember = Debouncer(500, self)
        self._remember.connect(self._snapshot)
        self._autosave = Debouncer(1000, self)
        self._autosave.connect(self._save)

        for keys, slot in ((QKeySequence.StandardKey.Save, self.save),
                           (QKeySequence.StandardKey.Undo, self.undo),
                           (QKeySequence.StandardKey.Redo, self.redo),
                           (QKeySequence("Ctrl+Y"), self.redo)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)
        self.load()

    # --- building -------------------------------------------------------------------
    def _build(self) -> None:
        scale = theme.text_scale()
        help_button = secondary_button("?  How it works", self._explain)
        help_button.setToolTip(t("A short guide to this page, in plain English"))
        self.back_button = secondary_button("My designs", self._show_library)
        self.back_button.setToolTip(t("See all your designs"))
        self.new_button = primary_button("New design", self._new_design, 140)
        self.new_button.setToolTip(t("Start a new design from a blank page or a starting design"))
        self.more = secondary_button("More")
        menu = QMenu(self.more)
        for label, slot in (("Rename...", self._start_rename), ("Make a copy", self._duplicate),
                            (None, None), ("Save to a file...", self._export),
                            ("Open a design file...", self._import), (None, None),
                            ("Delete this design", self._delete)):
            if label is None:
                menu.addSeparator()
                continue
            action = QAction(t(label), menu)
            action.triggered.connect(lambda _c=False, s=slot: s())
            menu.addAction(action)
        self.more.setMenu(menu)
        self.open_file_button = secondary_button("Open a design file...", self._import)
        self.open_file_button.setToolTip(t("Open a design someone saved to a file"))
        self.root.addWidget(row(heading("Email design"), None, self.back_button, self.new_button,
                                self.more, self.open_file_button, help_button))
        self.root.addWidget(muted(
            "Give your emails your own look: logo, colours, pictures and buttons. Click anything "
            "in the email to change it. Your message still comes from the My message page."))

        self.editor = QWidget()
        self.editor.setProperty("role", "plain")
        editor_layout = QVBoxLayout(self.editor)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(round(8 * scale))

        strip = Card(kind="tint-card", padding=10)
        self.use_box = checkbox("Send my emails with this design", False,
                                on_change=self._use_changed)
        self.use_note = hint("")
        strip.add(row(self.use_box, self.use_note, stretch=1))
        editor_layout.addWidget(strip)

        self.undo_button = small_button("↶ Undo", self.undo)
        self.undo_button.setToolTip(t("Undo the last change (Ctrl+Z)"))
        self.redo_button = small_button("↷ Redo", self.redo)
        self.redo_button.setToolTip(t("Do it again (Ctrl+Y)"))
        self.view_choice = ChoiceButtons([("desktop", "Computer"), ("phone", "Phone")], "desktop",
                                         on_change=self._view_changed)
        # Kept on one line: as a wrapping row it would stack the two buttons
        self.view_choice.setMinimumWidth(sum(b.sizeHint().width() for b in
                                             self.view_choice.buttons.values()) + 12)

        # The design's name, with a button to change it right there
        self.name_label = QLabel()
        self.name_label.setProperty("role", "subheading")
        self.name_label.setToolTip(t("The name of this design"))
        self.name_edit = line_edit("A name for this design")
        self.name_edit.setMaxLength(80)
        self.name_edit.setMinimumWidth(round(220 * scale))
        self.name_edit.editingFinished.connect(self._finish_rename)
        self.name_edit.hide()
        cancel = QShortcut(QKeySequence(Qt.Key.Key_Escape), self.name_edit)
        cancel.setContext(Qt.ShortcutContext.WidgetShortcut)
        cancel.activated.connect(self._cancel_rename)
        self.rename_button = small_button("✎  Rename", self._rename_clicked)
        self.rename_button.setToolTip(t("Change the name of this design"))
        # Clicking it must not take the focus: that would end the typing before the click
        self.rename_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        browser = secondary_button("Open in browser", self._open_in_browser)
        browser.setToolTip(t("See the finished email exactly as email programs will show it"))
        test = secondary_button("Send me a test", self._send_test)
        test.setToolTip(t("Send this design to your own email address to check it"))
        self.save_status = muted("", wrap=False)
        save = primary_button("Save", self.save, 120)
        save.setToolTip(t("Save this design now (Ctrl+S). Changes are also saved as you make them."))
        gap = QWidget()
        gap.setFixedWidth(round(10 * scale))
        editor_layout.addWidget(row(self.undo_button, self.redo_button, self.view_choice, gap,
                                    self.name_label, self.name_edit, self.rename_button, None,
                                    self.save_status, browser, test, save))
        self.size_note = hint("")
        set_tone(self.size_note, "warning")
        self.size_note.setVisible(False)
        editor_layout.addWidget(self.size_note)

        self.splitter = splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)
        splitter.addWidget(self._left_panel())

        self.canvas = EmailCanvas()
        self.canvas.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.canvas.selected.connect(self._select)
        self.canvas.action.connect(self._block_action)
        self.canvas.edit.connect(self._edit_on_email)
        self.canvas.dropped.connect(self._dropped)
        self.canvas.typed.connect(self._typed)
        self.canvas.resized.connect(self._resized)
        self.canvas.resize_done.connect(self._show_properties)
        canvas_card = Card(kind="card", padding=0)
        canvas_card.add(self.canvas, 1)
        splitter.addWidget(canvas_card)

        self.props = ScrollPage(margins=(round(12 * scale), round(12 * scale),
                                         round(14 * scale), round(12 * scale)), spacing=12)
        props_card = Card(kind="card", padding=0)
        props_card.add(self.props, 1)
        splitter.addWidget(props_card)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        props_card.setMinimumWidth(round(270 * scale))
        self._sized = False
        editor_layout.addWidget(splitter, 1)
        self.root.addWidget(self.editor, 1)

        # The first thing on the page: every design made so far, then the ways to start one
        self.library = ScrollPage(spacing=12)
        folder = secondary_button("Open the folder", self._open_folder)
        folder.setToolTip(t("Show the design files in File Explorer"))
        self.mine_title = self.library.add(row(subheading("Your designs"), None, folder))
        self.mine_note = muted("")
        self.mine_row = self.library.add(self.mine_note)
        self.mine_holder, self.mine_layout = flow_row(10)
        self.library.add(self.mine_holder)
        self.none_title = self.library.add(subheading("You have no designs yet"))
        self.none_note = self.library.add(muted(
            "Your emails are sent as plain messages, which is best for a first email to someone "
            "new. To give them your own look, pick a starting design below. You can change "
            "everything in it."))
        self.start_title = self.library.add(subheading("Start a new design"))
        self.library.add(muted("Pick Blank to build your own email from scratch, or start from "
                               "a design and change anything in it."))
        self._gallery_box = self.library.add(column(spacing=0))
        self._gallery = None       # drawn the first time it is needed: it renders eight emails
        self.library.add_stretch()
        self.root.addWidget(self.library, 1)
        self._thumbs: dict[tuple, QPixmap] = {}
        self._files_checked = False

    def showEvent(self, event):  # noqa: N802 - Qt naming
        super().showEvent(event)
        if not self._sized and self.splitter.width() > 0:
            # Sized once it is on screen, when the real width is known: the email in the
            # middle gets whatever the two panels do not need.
            self._sized = True
            scale = theme.text_scale()
            left, right = round(215 * scale), round(310 * scale)
            self.splitter.setSizes([left, max(300, self.splitter.width() - left - right), right])

    def _left_panel(self) -> QWidget:
        scale = theme.text_scale()
        tabs = TabBar()
        tabs.add("Add", self._palette)
        tabs.add("Your blocks", self._layers_tab)
        tabs.build_all()
        tabs.set("Add")
        tabs.setMinimumWidth(round(190 * scale))
        return tabs

    def _palette(self) -> QWidget:
        area = ScrollPage(spacing=2)
        # The wheel still scrolls it; a bar beside such a narrow list only gets in the way
        area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.add(hint("Drag a block into the email, or click it to add it below the selected "
                      "one."))
        for group in design.GROUPS:
            title = hint(group)
            title.setStyleSheet(f"font-weight: 600; padding-top: {round(10 * theme.text_scale())}px;")
            area.add(title)
            for spec in design.BLOCKS.values():
                if spec.group == group and spec.kind != "message":
                    area.add(BlockRow(spec, lambda k=spec.kind: self._add_block(k)))
        area.add_stretch()
        return area

    def _layers_tab(self) -> QWidget:
        holder = QWidget()
        holder.setProperty("role", "plain")
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(hint("Drag to change the order. Click one to change it."))
        self.layers = QListWidget()
        self.layers.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.layers.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.layers.currentItemChanged.connect(self._layer_clicked)
        self.layers.model().rowsMoved.connect(lambda *_: self._layers_moved())
        layout.addWidget(self.layers, 1)
        return holder

    def _starters(self, on_pick) -> QWidget:
        holder, layout = flow_row(10)
        width = round(250 * theme.text_scale())
        kit = design.brand_kit()
        for key, name, note in design.STARTERS:
            tile = Card(kind="card", padding=12)
            tile.setFixedWidth(width)
            tile.add(subheading(name))
            picture = snapshot(design.starter(key, kit), self._sample,
                               width - round(26 * theme.text_scale()),
                               round(170 * theme.text_scale()))
            tile.add(thumb_button(picture, lambda k=key, n=name: on_pick(k, n)))
            tile.add(muted(note))
            tile.add(row(primary_button("Start with this", lambda k=key, n=name: on_pick(k, n)),
                         None))
            tile.add_stretch()      # a taller neighbour must not push this one's title down
            layout.addWidget(tile)
        return holder

    def _design_card(self, record: dict, width: int) -> QWidget:
        """One saved design on the library page: its picture, name and what can be done to it."""
        design_id = record["id"]
        tile = Card(kind="card", padding=12)
        tile.setFixedWidth(width)
        name = QLabel(record["name"])           # the user's own words, never translated
        name.setProperty("role", "subheading")
        name.setWordWrap(True)
        parts = [name, None]
        if design.active_id() == design_id:
            badge = hint("In use", wrap=False)
            badge.setToolTip(t("Your emails are sent with this design"))
            set_tone(badge, "success")
            parts.append(badge)
        tile.add(row(*parts))

        key = (design_id, record["updated_at"])
        if key not in self._thumbs:
            data = design.load(design_id) or design.blank_design()
            self._thumbs[key] = snapshot(data, self._sample, width - round(26 * theme.text_scale()),
                                         round(170 * theme.text_scale()))
        tile.add(thumb_button(self._thumbs[key], lambda: self._open(design_id)))
        tile.add(hint(t("Changed {when}", when=prefs.format_datetime(record["updated_at"]))))

        more = secondary_button("More")
        menu = QMenu(more)
        using = design.active_id() == design_id
        for label, slot in (
                ("Rename...", lambda: self._rename_from_library(design_id)),
                ("Make a copy", lambda: self._duplicate(design_id)),
                ("Send plain emails instead" if using else "Send my emails with this design",
                 lambda: self._use_from_library(design_id, not using)),
                (None, None),
                ("Save to a file...", lambda: self._export(design_id)),
                (None, None),
                ("Delete this design", lambda: self._delete(design_id))):
            if label is None:
                menu.addSeparator()
                continue
            action = QAction(t(label), menu)
            action.triggered.connect(lambda _c=False, s=slot: s())
            menu.addAction(action)
        more.setMenu(menu)
        tile.add(row(primary_button("Open", lambda: self._open(design_id)), more, None))
        tile.add_stretch()
        return tile

    def _explain(self) -> None:
        InfoDialog.show_for(self, "How email designs work", HELP_INTRO, HELP_SECTIONS, HELP_FOOTER)

    # --- loading and saving -----------------------------------------------------------
    def load(self) -> None:
        self._show_library()

    def _header_for(self, editing: bool) -> None:
        for button in (self.back_button, self.new_button, self.more):
            button.setVisible(editing)
        self.open_file_button.setVisible(not editing)

    def _show_library(self, starters: bool = False) -> None:
        """The page of designs: the ones made so far, then Blank and the starting designs."""
        if getattr(self, "_dirty", False):
            self._save()
        self._cancel_rename()
        self._refresh_sample()
        self._fill_library()
        self.editor.setVisible(False)
        self.library.setVisible(True)
        self._header_for(False)
        if starters:
            QTimer.singleShot(0, self._scroll_to_starters)    # once the layout has placed it

    def _scroll_to_starters(self) -> None:
        if not sip.isdeleted(self):
            self.library.verticalScrollBar().setValue(
                self.start_title.mapTo(self.library.content, QPoint(0, 0)).y())

    def _fill_library(self) -> None:
        designs = design.list_designs()
        clear_layout(self.mine_layout)
        width = round(250 * theme.text_scale())
        for record in designs:
            self.mine_layout.addWidget(self._design_card(record, width))
        mine = bool(designs)
        for widget in (self.mine_title, self.mine_row, self.mine_holder):
            widget.setVisible(mine)
        for widget in (self.none_title, self.none_note):
            widget.setVisible(not mine)
        self.mine_note.setText(t("Click a design to open it. Each one is also saved as a file in "
                                 "{folder}", folder=str(config.DESIGNS_DIR)))
        if self._gallery is None:
            self._gallery = self._starters(self._create)
            self._gallery_box.layout().addWidget(self._gallery)
        if not self._files_checked:
            # Designs made before v0.7.3 get their copy in the Documents folder too
            self._files_checked = True
            for record in designs:
                if not design.file_path(record["name"]).exists():
                    self._write_file(record["name"], design.load(record["id"]))

    def _open_folder(self) -> None:
        try:
            Path(config.DESIGNS_DIR).mkdir(parents=True, exist_ok=True)
        except OSError as error:
            self.notify(t("Could not open the folder: {message}", message=error), "error", 8000)
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(config.DESIGNS_DIR)))

    def _open(self, design_id: int) -> None:
        if getattr(self, "_dirty", False) and design_id != self._id:
            self._save()
        loaded = design.load(design_id)
        if loaded is None:
            return
        record = next((d for d in design.list_designs() if d["id"] == design_id), None)
        self._design, self._id = loaded, design_id
        self._name = record["name"] if record else ""
        self.name_label.setText(self._name)
        self._selected = ""
        self._history, self._position = [], -1
        self._snapshot()
        self.library.setVisible(False)
        self.editor.setVisible(True)
        self._header_for(True)
        self._refresh_sample()
        self._refresh_use()
        self._draw()
        self._fill_layers()
        self._show_properties()
        self._mark_saved()

    def _mark_saved(self) -> None:
        self._dirty = False
        self.save_status.setText("")

    def _touch(self) -> None:
        """Something changed: redraw soon, remember it for Undo, save it a moment later."""
        if self._loading:
            return
        self._dirty = True
        self.save_status.setText(t("Saving..."))
        set_tone(self.save_status, "muted")
        self._redraw.poke()
        self._remember.poke()
        self._autosave.poke()

    def save(self) -> None:
        self._save(quiet=False)

    def _save(self, quiet: bool = True) -> None:
        """Store the design, and its copy in the Documents folder. Autosave is quiet."""
        if self._design is None:
            return
        self._autosave.cancel()
        self._remember.flush()
        self._name = self._name or t("My design")
        self._id = design.save(self._design, self._name, self._id)
        self._mark_saved()
        self.save_status.setText(t("Saved"))
        set_tone(self.save_status, "success")
        if not quiet:
            self.notify("Design saved", "success")
        self._write_file(self._name, self._design)

    def _write_file(self, name: str, data: dict | None, old_name: str = "") -> None:
        if data is None:
            return
        Task(design.write_file, name, design.export_text(data, name), old_name).start(
            on_error=self.guard(self._file_failed))

    def _file_failed(self, message: str) -> None:
        # Once is enough: an autosave every second would otherwise repeat it
        if not getattr(self, "_file_warned", False):
            self._file_warned = True
            self.notify(t("The design is saved in the app, but its copy in your Documents "
                          "folder could not be written: {message}", message=message), "warn", 8000)

    def _unique_name(self, name: str) -> str:
        names = {d["name"] for d in design.list_designs()}
        if name not in names:
            return name
        number = 2
        while t("{name} {number}", name=name, number=number) in names:
            number += 1
        return t("{name} {number}", name=name, number=number)

    def _create(self, key: str, name: str) -> None:
        data = design.starter(key)
        name = self._unique_name(t(name))
        new_id = design.save(data, name)
        self._write_file(name, data)
        self._open(new_id)
        self.notify("Click anything in the email to change it. Press Rename to give it your own "
                    "name.", "info", 6000)

    def _new_design(self) -> None:
        self._show_library(starters=True)

    # --- the name -------------------------------------------------------------------
    def _rename_clicked(self) -> None:
        if not self.name_edit.isHidden():
            self._finish_rename()
        else:
            self._start_rename()

    def _start_rename(self) -> None:
        if self._id is None:
            return
        self.name_edit.setText(self._name)
        self.name_label.hide()
        self.name_edit.show()
        self.rename_button.setText(t("✓  Save name"))
        self.name_edit.setFocus()
        self.name_edit.selectAll()

    def _cancel_rename(self) -> None:
        if self.name_edit.isHidden():
            return
        self.name_edit.hide()
        self.name_label.show()
        self.rename_button.setText(t("✎  Rename"))

    def _finish_rename(self) -> None:
        if self.name_edit.isHidden():
            return
        if self._apply_rename(self._id, self.name_edit.text()):
            self._cancel_rename()

    def _rename_from_library(self, design_id: int) -> None:
        record = next((d for d in design.list_designs() if d["id"] == design_id), None)
        if record is None:
            return
        name, ok = QInputDialog.getText(self, t("Rename design"), t("A name for this design"),
                                        text=record["name"])
        if ok and self._apply_rename(design_id, name):
            self._fill_library()

    def _apply_rename(self, design_id: int | None, name: str) -> bool:
        """Rename a design and its file. False when the name cannot be used."""
        name = name.strip()[:80]
        records = design.list_designs()
        old = next((d["name"] for d in records if d["id"] == design_id), None)
        if design_id is None or old is None:
            return True
        if not name or name == old:
            return True
        if any(d["id"] != design_id and design.file_path(d["name"]) == design.file_path(name)
               for d in records):
            self.notify(t("You already have a design called \"{name}\". Pick another name.",
                          name=name), "warn", 6000)
            return False
        design.rename(design_id, name)
        if design_id == self._id:
            self._name = name
            self.name_label.setText(name)
            data = self._design
        else:
            data = design.load(design_id)
        self._write_file(name, data, old)
        self.notify("Design renamed", "success")
        return True

    def _duplicate(self, design_id: int | None = None) -> None:
        """A copy of a design. From the editor the copy opens; from the library it is listed."""
        editing = design_id is None
        source_id = self._id if editing else design_id
        if editing:
            self._save()
        data = design.load(source_id) if source_id is not None else None
        record = next((d for d in design.list_designs() if d["id"] == source_id), None)
        if data is None or record is None:
            return
        name = self._unique_name(t("{name} copy", name=record["name"]))
        new_id = design.save(data, name)
        self._write_file(name, data)
        if editing:
            self._open(new_id)
            self.notify("Copy made. You are now changing the copy", "success")
        else:
            self._fill_library()
            self.notify("Copy made", "success")

    def _use_from_library(self, design_id: int, on: bool) -> None:
        design.set_active(design_id if on else 0)
        self.notify("Your emails will be sent with this design" if on else
                    "Your emails will be sent as plain messages", "success")
        self._fill_library()

    def _delete(self, design_id: int | None = None) -> None:
        design_id = self._id if design_id is None else design_id
        record = next((d for d in design.list_designs() if d["id"] == design_id), None)
        if record is None:
            return
        if not ConfirmDialog.ask(
                self, "Delete this design?",
                t("\"{name}\" will be deleted, and its file moved to the Recycle Bin. Your "
                  "messages, contacts and sent emails are not touched. If your emails use this "
                  "design, they go back to plain messages.", name=record["name"]),
                "Delete design", danger=True):
            return
        design.delete(design_id)
        Task(design.recycle_file, record["name"]).start(on_error=self.guard(self._file_failed))
        if design_id == self._id:
            self._autosave.cancel()
            self._id, self._design, self._dirty = None, None, False
        self.notify("Design deleted", "success")
        self._show_library()

    def _export(self, design_id: int | None = None) -> None:
        design_id = self._id if design_id is None else design_id
        if design_id == self._id and self._design is not None:
            self._save()
        record = next((d for d in design.list_designs() if d["id"] == design_id), None)
        data = design.load(design_id) if record else None
        if data is None:
            return
        path, _filter = QFileDialog.getSaveFileName(
            self, t("Save the design to a file"), f"{record['name'] or 'design'}.hpdesign",
            t("HomingPigeon designs (*.hpdesign)"))
        if not path:
            return
        try:
            Path(path).write_text(design.export_text(data, record["name"]), encoding="utf-8")
        except OSError as error:
            self.notify(t("Could not save the file: {message}", message=error), "error", 8000)
            return
        self.notify(t("Saved {name}", name=Path(path).name), "success")

    def _import(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, t("Open a design file"), str(config.DESIGNS_DIR),
            t("HomingPigeon designs (*.hpdesign);;All files (*.*)"))
        if not path:
            return

        def read() -> tuple[str, dict]:
            return design.import_text(Path(path).read_text(encoding="utf-8"))

        def opened(result: tuple[str, dict]) -> None:
            name, data = result
            name = self._unique_name(name)
            new_id = design.save(data, name)
            self._write_file(name, data)
            self._open(new_id)
            self.notify(t("Opened {name}", name=name), "success")

        Task(read).start(on_result=self.guard(opened), on_error=self.guard(
            lambda message: self.notify(t("Could not open that file: {message}",
                                          message=message), "error", 8000)))

    # --- using the design -------------------------------------------------------------
    def _refresh_use(self) -> None:
        using = self._id is not None and design.active_id() == self._id
        blocked = self.use_box.blockSignals(True)
        self.use_box.setChecked(using)
        self.use_box.blockSignals(blocked)
        if using:
            self.use_note.setText(t("Your emails are sent with this design. Changes are saved "
                                    "as you make them."))
            set_tone(self.use_note, "success")
        else:
            self.use_note.setText(t("Your emails are sent as plain messages. Designs with pictures "
                                    "and buttons often land in Gmail's Promotions tab, so plain is "
                                    "best for a first email to someone new."))
            set_tone(self.use_note, "muted")

    def _use_changed(self, on: bool) -> None:
        if on:
            if getattr(self, "_dirty", False) or self._id is None:
                self._save()
            design.set_active(self._id or 0)
            self.notify("Your emails will be sent with this design", "success")
        else:
            design.set_active(0)
            self.notify("Your emails will be sent as plain messages", "success")
        self._refresh_use()

    # --- drawing ---------------------------------------------------------------------------
    def _refresh_sample(self) -> None:
        """The message, signature and unsubscribe line the canvas shows, from My message."""
        body = db.query_one("SELECT html FROM bodies WHERE enabled = 1 ORDER BY position LIMIT 1")
        signature = db.query_one("SELECT signature_html, footer_html FROM template_sets "
                                 "ORDER BY id LIMIT 1")
        identity = composer.SenderIdentity(db.get_setting("sender_name", ""),
                                           db.get_setting("sender_email", "you@example.com"))
        context = self._context()
        self._sample = {
            "context": context,
            "message": composer.text_to_html(
                merge.render(body["html"], context, html=True, rng=random.Random(7)))
            if body else "",
            "signature": composer.text_to_html(signature["signature_html"] or "")
            + (composer.footer_block(signature["footer_html"]) if signature["footer_html"] else "")
            if signature else "",
            "unsubscribe": composer.unsubscribe_footer(identity)
            if db.get_setting("unsubscribe_note", True) else "",
        }

    def _draw(self) -> None:
        if self._design is None:
            return
        self.canvas.show_design(self._design, self._sample, self._selected)
        size = design.pictures_size(self._design)
        self.size_note.setVisible(size > PICTURE_WARNING_BYTES)
        self.size_note.setText(t("⚠ The pictures add {size:.1f} MB to every email. Keep them under "
                                 "1 MB: use fewer or smaller pictures, or web links.",
                                 size=size / 1_048_576))
        self.undo_button.setEnabled(self._position > 0)
        self.redo_button.setEnabled(self._position < len(self._history) - 1)

    def _view_changed(self, view: str) -> None:
        self.canvas.phone = view == "phone"
        self._draw()

    # --- selection and the blocks list ---------------------------------------------------
    def _block(self, block_id: str) -> dict | None:
        if self._design is None:
            return None
        return next((b for b in self._design["blocks"] if b["id"] == block_id), None)

    def _summary(self, block: dict) -> str:
        spec = design.BLOCKS[block["type"]]
        words = ""
        for key in ("text", "title", "label", "left_title"):
            value = str(block.get(key, "")).strip()
            if value and spec.kind not in ("footer", "html"):
                words = value.splitlines()[0][:28]
                break
        return t(spec.label) + (f"  ·  {words}" if words else "")

    def _fill_layers(self) -> None:
        if self._design is None:
            return
        blocked = self.layers.blockSignals(True)
        self.layers.clear()
        size = theme.px(18)
        for block in self._design["blocks"]:
            spec = design.BLOCKS[block["type"]]
            item = QListWidgetItem(self._summary(block))
            item.setIcon(QIcon(theme.icon_pixmap(theme.block_icon(spec.kind, spec.glyph), size,
                                                 "accent")))
            item.setData(Qt.ItemDataRole.UserRole, block["id"])
            self.layers.addItem(item)
            if block["id"] == self._selected:
                self.layers.setCurrentItem(item)
        self.layers.blockSignals(blocked)

    def _layer_clicked(self, item, _previous=None) -> None:
        if item is not None:
            block_id = item.data(Qt.ItemDataRole.UserRole)
            if block_id != self._selected:
                self._select(block_id)
                self.canvas.reveal(block_id)

    def _layers_moved(self) -> None:
        order = [self.layers.item(i).data(Qt.ItemDataRole.UserRole)
                 for i in range(self.layers.count())]
        by_id = {b["id"]: b for b in self._design["blocks"]}
        self._design["blocks"] = [by_id[i] for i in order if i in by_id]
        self._touch()

    def _select(self, block_id: str) -> None:
        self._selected = block_id if self._block(block_id) else ""
        self.canvas.select(self._selected)
        blocked = self.layers.blockSignals(True)
        self.layers.clearSelection()
        for i in range(self.layers.count()):
            if self.layers.item(i).data(Qt.ItemDataRole.UserRole) == self._selected:
                self.layers.setCurrentRow(i)
        self.layers.blockSignals(blocked)
        self._show_properties()

    def _focus_first_field(self, block_id: str) -> None:
        self._select(block_id)
        first = getattr(self, "_first_editor", None)
        if first is not None:
            first.setFocus()

    def _edit_on_email(self, block_id: str) -> None:
        """Double-click: type on the email when the block has words, else go to its first setting."""
        block = self._block(block_id)
        key = INLINE.get(block["type"]) if block else None
        if key is None:
            self._focus_first_field(block_id)
            return
        self._select(block_id)
        field = next(f for f in design.fields_for(block["type"]) if f.key == key)
        self.canvas.start_typing(block_id, key, field.kind == "multiline")

    def _typed(self, block_id: str, key: str, text: str) -> None:
        block = self._block(block_id)
        if block is None or block.get(key) == text:
            return
        block[key] = text
        self._touch()
        self._fill_layers()
        if block_id == self._selected:
            self._show_properties()

    def _resized(self, block_id: str, key: str, value) -> None:
        block = self._block(block_id)
        if block is not None:
            block[key] = value
            self._touch()

    # --- adding, moving, removing ----------------------------------------------------------
    def _add_block(self, kind: str, index: int | None = None) -> None:
        """Add a block at ``index``, or below the selected one when it was clicked, not dropped."""
        if self._design is None:
            return
        blocks = self._design["blocks"]
        block = design.new_block(kind, design.brand_kit(), self._design)
        current = self._block(self._selected)
        if index is not None:
            index = max(0, min(index, len(blocks)))
        elif current is not None:
            index = blocks.index(current) + 1
        elif blocks and blocks[-1]["type"] == "footer" and kind != "footer":
            index = len(blocks) - 1
        else:
            index = len(blocks)
        blocks.insert(index, block)
        self._selected = block["id"]
        self._structure_changed()
        self.canvas.reveal(block["id"])

    def _dropped(self, kind: str, value: str, index: int) -> None:
        if self._design is None:
            return
        if kind == "new":
            if value in design.BLOCKS and value != "message":
                self._add_block(value, index)
            return
        block = self._block(value)
        if block is None:
            return
        self._selected = value
        if not design.move_block(self._design["blocks"], block, index):
            self.canvas.select(value)
            return
        self._structure_changed()

    def _block_action(self, block_id: str, action: str) -> None:
        block = self._block(block_id)
        if block is None:
            return
        blocks = self._design["blocks"]
        index = blocks.index(block)
        if action == "up" and index > 0:
            blocks[index - 1], blocks[index] = blocks[index], blocks[index - 1]
        elif action == "down" and index < len(blocks) - 1:
            blocks[index + 1], blocks[index] = blocks[index], blocks[index + 1]
        elif action == "copy":
            if block["type"] == "message":
                self.notify("There can only be one message block", "warn")
                return
            twin = copy.deepcopy(block)
            twin["id"] = design._new_id()
            blocks.insert(index + 1, twin)
            self._selected = twin["id"]
        elif action == "remove":
            if block["type"] == "message":
                self.notify("Your message must stay in the design. Move it where you want it "
                            "instead", "warn", 6000)
                return
            blocks.remove(block)
            self._selected = ""
        else:
            return
        self._structure_changed()

    def _structure_changed(self) -> None:
        self._touch()
        self._redraw.flush()
        self._fill_layers()
        self._show_properties()

    # --- undo ------------------------------------------------------------------------------
    def _state(self) -> str:
        return json.dumps({"page": self._design["page"], "blocks": self._design["blocks"]})

    def _snapshot(self) -> None:
        if self._design is None:
            return
        state = self._state()
        if self._history and self._history[self._position] == state:
            return
        del self._history[self._position + 1:]
        self._history.append(state)
        self._history = self._history[-80:]
        self._position = len(self._history) - 1
        self.undo_button.setEnabled(self._position > 0)
        self.redo_button.setEnabled(False)

    def _restore(self, position: int) -> None:
        self._position = position
        state = json.loads(self._history[position])
        self._design["page"], self._design["blocks"] = state["page"], state["blocks"]
        if not self._block(self._selected):
            self._selected = ""
        self._dirty = True
        self.save_status.setText(t("Unsaved changes"))
        set_tone(self.save_status, "warning")
        self._draw()
        self._fill_layers()
        self._show_properties()

    def undo(self) -> None:
        self._remember.flush()
        if self._design is not None and self._position > 0:
            self._restore(self._position - 1)

    def redo(self) -> None:
        if self._design is not None and self._position < len(self._history) - 1:
            self._restore(self._position + 1)

    # --- the settings panel ----------------------------------------------------------------
    def _show_properties(self) -> None:
        self.props.setUpdatesEnabled(False)
        try:
            self.props.clear()
            self._first_editor = None
            if self._design is None:
                return
            block = self._block(self._selected)
            if block is None:
                self._page_properties()
            else:
                self._block_properties(block)
            self.props.add_stretch()
        finally:
            self.props.setUpdatesEnabled(True)

    def _sections(self, fields, target: dict, closed: tuple = ()) -> None:
        groups: dict[str, Collapsible] = {}
        for field in fields:
            group = groups.get(field.section)
            if group is None:
                group = Collapsible(field.section, field.section not in closed)
                groups[field.section] = group
                self.props.add(group)
            group.add(self._field(field, target))

    def _simple_sections(self, fields, target: dict, quick: set, quick_title: str) -> None:
        """The few settings most people want, open; everything else under "More options"."""
        fields = list(fields)
        words = [f for f in fields if f.section not in ("Style", design.SPACING)
                 and target is not self._design["page"]]
        look = [f for f in fields if f not in words and f.key in quick]
        more = [f for f in fields if f not in words and f not in look]
        self._sections(words, target)
        for title, group_fields, opened in ((quick_title, look, True),
                                            ("More options", more, False)):
            if group_fields:
                group = Collapsible(title, opened)
                for field in group_fields:
                    group.add(self._field(field, target))
                self.props.add(group)

    def _page_properties(self) -> None:
        self.props.add(subheading("Email style"))
        self.props.add(hint("Settings for the whole email. Click a block in the email to change "
                            "that block instead."))
        self._simple_sections(design.PAGE_FIELDS, self._design["page"], QUICK_PAGE, "Look")
        self.props.add(self._brand_section())

    def _block_properties(self, block: dict) -> None:
        spec = design.BLOCKS[block["type"]]
        back = ghost_button("‹  Email style", lambda: self._select(""))
        back.setToolTip(t("Back to the settings for the whole email"))
        self.props.add(row(back, None))
        icon = QLabel(theme.block_icon(spec.kind, spec.glyph))
        icon.setStyleSheet(theme.icon_css(18) + f" color: {theme.color('accent')};")
        self.props.add(row(icon, subheading(spec.label), None, spacing=8))
        note = spec.note
        if spec.kind in INLINE:
            note = t("{note} Double-click it in the email to type straight onto it.",
                     note=t(spec.note))
        self.props.add(hint(note))
        tools = [small_button(label, lambda a=action: self._block_action(block["id"], a))
                 for label, action in (("Make a copy", "copy"), ("Remove", "remove"))]
        self.props.add(row(*tools, None, spacing=4))
        self._simple_sections(design.fields_for(block["type"]), block, QUICK_STYLE, "Look")

    def _set(self, target: dict, key: str, value) -> None:
        target[key] = value
        self._touch()
        if target is not self._design["page"]:
            current = self.layers.currentItem()
            block = self._block(self._selected)
            if current is not None and block is not None:
                current.setText(self._summary(block))

    def _field(self, field: design.Field, target: dict) -> QWidget:
        form = FormRow(field.label, field.note)
        value = target.get(field.key, field.default)
        kind = field.kind
        if kind in ("text", "url"):
            editor = line_edit("www.yourcompany.com" if kind == "url" else "")
            editor.setText(str(value))
            editor.textChanged.connect(lambda v, k=field.key: self._set(target, k, v))
            form.add(editor)
            self._first_editor = self._first_editor or editor
        elif kind in ("multiline", "code"):
            editor = text_box("", monospace=kind == "code", lines=8 if kind == "code" else 4)
            set_text(editor, str(value))
            editor.textChanged.connect(
                lambda e=editor, k=field.key: self._set(target, k, get_text(e)))
            form.add(editor)
            if kind == "multiline":
                form.add(self._tag_menu(editor))
            self._first_editor = self._first_editor or editor
        elif kind == "number":
            editor = spin_box(int(value), field.low, field.high,
                              on_change=lambda v, k=field.key: self._set(target, k, v),
                              suffix=field.suffix)
            form.add(row(editor, None))
        elif kind == "bool":
            form = FormRow("", field.note)
            form.add(checkbox(field.label, bool(value),
                              on_change=lambda v, k=field.key: self._set(target, k, bool(v))))
        elif kind == "choice":
            form.add(ChoiceButtons(list(field.options), value,
                                   on_change=lambda v, k=field.key: self._set(target, k, v)))
        elif kind == "font":
            choices = ([""] if field.default == "" else []) + list(design.FONTS)
            labels = {"": "Same as the email"}
            editor = combo([labels.get(c, c) for c in choices], labels.get(value, value),
                           translate={"Same as the email"})
            editor.currentIndexChanged.connect(
                lambda i, k=field.key, c=choices: self._set(target, k, c[i]))
            form.add(editor)
        elif kind == "color":
            kit = design.brand_kit()
            editor = ColorField(str(value), field.optional or field.default == "",
                                (kit["primary"], kit["text"], kit["background"]))
            editor.changed.connect(lambda v, k=field.key: self._set(target, k, v))
            form.add(editor)
        elif kind == "image":
            form.add(self._image_field(field, target))
        return form

    def _tag_menu(self, editor) -> QWidget:
        button = small_button("+ Personal touch")
        button.setToolTip(t("Put in a detail from your contact list, such as their first name"))
        menu = QMenu(button)
        for tag in importer.merge_tag_names():
            action = QAction("{{" + tag + "}}", menu)
            action.triggered.connect(lambda _c=False, s="{{" + tag + "}}": (
                editor.insertPlainText(s), editor.setFocus()))
            menu.addAction(action)
        button.setMenu(menu)
        return row(button, None)

    def _image_field(self, field: design.Field, target: dict) -> QWidget:
        value = target.get(field.key, "")
        found = self._design["assets"].get(value[6:]) if str(value).startswith("asset:") else None

        def use_asset(asset: dict) -> None:
            self._set(target, field.key, design.add_asset(self._design, asset))
            self._redraw.flush()
            self._show_properties()

        def use_link(address: str) -> None:
            self._set(target, field.key, address)
            self._show_properties()

        def clear() -> None:
            self._set(target, field.key, "")
            self._redraw.flush()
            self._show_properties()

        return ImageField(self, found or value, use_asset, use_link, clear)

    def _brand_section(self) -> QWidget:
        group = Collapsible("My brand kit", False)
        group.add(hint("Save your logo, colours and font once. New designs and new blocks use "
                       "them automatically."))
        kit = design.brand_kit()

        def save_kit(key: str, value) -> None:
            fresh = design.brand_kit()
            fresh[key] = value
            design.save_brand_kit(fresh)

        logo = FormRow("Logo")
        logo.add(ImageField(self, kit.get("logo"),
                            lambda asset: (save_kit("logo", asset), self._show_properties()),
                            lambda _url: self.notify("The brand kit logo must be a picture from "
                                                     "your computer", "warn"),
                            lambda: (save_kit("logo", None), self._show_properties())))
        group.add(logo)
        for key, label in (("primary", "Main colour (buttons, banners)"), ("text", "Text colour"),
                           ("background", "Background colour")):
            form = FormRow(label)
            editor = ColorField(kit[key])
            editor.changed.connect(lambda v, k=key: save_kit(k, v))
            form.add(editor)
            group.add(form)
        form = FormRow("Font")
        fonts = list(design.FONTS)
        editor = combo(fonts, kit["font"], translate=False)
        editor.currentIndexChanged.connect(lambda i: save_kit("font", fonts[i]))
        form.add(editor)
        group.add(form)
        group.add(row(secondary_button("Use my brand kit on this design", self._apply_kit), None))
        return group

    def _apply_kit(self) -> None:
        design.apply_brand(self._design, design.brand_kit())
        self._structure_changed()
        self.notify("Brand kit applied. Press Undo if you prefer it as it was", "success", 6000)

    # --- previews ----------------------------------------------------------------------------
    def _preview_content(self) -> composer.Content:
        subjects = [r["text"] for r in
                    db.query("SELECT text FROM subjects WHERE enabled = 1 ORDER BY position")]
        bodies = [r["html"] for r in
                  db.query("SELECT html FROM bodies WHERE enabled = 1 ORDER BY position")]
        signature = db.query_one("SELECT signature_html, footer_html FROM template_sets "
                                 "ORDER BY id LIMIT 1")
        return composer.Content(
            subject_variants=subjects or [t("A test of my email design")],
            body_variants=bodies or [t("Your message goes here. Each person gets one of the "
                                       "messages you wrote on the My message page.")],
            signature_html=(signature["signature_html"] or "") if signature else "",
            attach_mode=db.get_setting("attach_mode", "link"),
            link_url=db.get_setting("link_url", ""),
            link_text=db.get_setting("link_text", "View our brochure"),
            unsubscribe_note=bool(db.get_setting("unsubscribe_note", True)),
            design=copy.deepcopy(self._design),
            footer_html=(signature["footer_html"] or "") if signature else "",
        )

    def _context(self) -> dict:
        contact = db.query_one("SELECT * FROM contacts WHERE valid = 1 ORDER BY id LIMIT 1")
        return merge.build_context(merge.as_mapping(contact) if contact else
                                   scorer.SAMPLE_CONTACT, importer.extra_columns())

    def _open_in_browser(self) -> None:
        if self._design is None:
            return
        identity = composer.SenderIdentity(db.get_setting("sender_name", ""),
                                           db.get_setting("sender_email", "you@example.com"))
        content, context = self._preview_content(), self._context()

        def build() -> str:
            _subject, html, _text = composer.preview_message(identity, context, content)
            path = Path(tempfile.gettempdir()) / "homingpigeon_design.html"
            path.write_text(html, encoding="utf-8")
            return path.as_uri()

        Task(build).start(on_result=webbrowser.open, on_error=self.guard(
            lambda message: self.notify(t("Could not build the preview: {message}",
                                          message=message), "error", 8000)))

    def _send_test(self) -> None:
        if self._design is None:
            return
        email = db.get_setting("sender_email", "")
        host = db.get_setting("smtp_host", "")
        password = credentials.load_secret(credentials.SMTP_PASSWORD)
        if not (email and host and password):
            self.notify("Finish setting up your email account first", "warn")
            self.go("account")
            return
        try:
            port = int(db.get_setting("smtp_port", 587))
        except (TypeError, ValueError):
            port = 587
        settings = sender.SmtpSettings(
            host=host, port=port, username=db.get_setting("smtp_username", "") or email,
            password=password, security=db.get_setting("smtp_security", "auto"))
        identity = composer.SenderIdentity(db.get_setting("sender_name", ""), email,
                                           db.get_setting("reply_to", ""))
        content, context = self._preview_content(), self._context()

        def send() -> tuple[bool, str]:
            message, subject, _variant = composer.build_message(identity, email, context, content)
            del message["Subject"]
            message["Subject"] = t("Test: {subject}", subject=subject)
            return sender.send_one(settings, message)

        def done(result: tuple[bool, str]) -> None:
            self.busy -= 1
            ok, text = result
            self.notify(text, "success" if ok else "error", 8000)

        def failed(message: str) -> None:
            self.busy -= 1
            self.notify(t("Could not send the test: {message}", message=message), "error", 8000)

        self.busy += 1
        self.notify(t("Sending a test to {email}...", email=email), "info", 3000)
        Task(send).start(on_result=self.guard(done), on_error=self.guard(failed))

    # --- page hooks ---------------------------------------------------------------------------
    def on_show(self) -> None:
        if not self.editor.isHidden() and self._design is not None:
            self._refresh_sample()
            self._refresh_use()
            self._draw()
        elif not self.library.isHidden():
            self._fill_library()

    def hideEvent(self, event):  # noqa: N802 - Qt naming
        # Leaving the page saves what is waiting to be saved
        self._autosave.flush()
        super().hideEvent(event)

    def before_close(self) -> None:
        self._autosave.flush()

    def busy_reason(self) -> str | None:
        if self.busy > 0:
            return t("A picture or test email is still on its way")
        if getattr(self, "_dirty", False):
            return t("The design has unsaved changes")
        return None
