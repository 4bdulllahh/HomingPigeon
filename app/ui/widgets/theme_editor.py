"""The theme maker: pick a few colours, a gradient and a font, and see the app change as you go.

The whole app is the preview. Every change is painted straight away with
``theme.use_theme``, and Cancel puts the saved theme back.
"""
from __future__ import annotations

from typing import Callable

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QColorDialog, QDialog, QGridLayout, QPushButton, QVBoxLayout, QWidget

from app.core import db, prefs, themes
from app.i18n import t
from app.ui import theme
from app.ui.widgets.common import (ChoiceButtons, Section, ScrollPage, column, field_label, muted,
                                   primary_button, row, secondary_button, set_tone, subheading,
                                   wrap_row)
from app.ui.widgets.dialogs import ConfirmDialog, resizable
from app.ui.widgets.inputs import checkbox, combo, line_edit

COLOUR_LABELS = {
    "background": "Page background",
    "sidebar": "Sidebar",
    "cards": "Cards and boxes",
    "text": "Text",
    "accent": "Main colour",
    "secondary": "Second button colour",
}
DIRECTION_LABELS = [("across", "Left to right"), ("down", "Top to bottom"),
                    ("diagonal", "Corner to corner")]
PLACE_LABELS = {"sidebar": "Sidebar", "buttons": "Main buttons", "page": "Page background"}
STANDARD_FONT = "Standard"


def starting_spec() -> dict:
    """The theme on screen now, as something to change. Dark and Light have no spec of their own."""
    spec = theme.current_spec()
    if spec is not None:
        return dict(spec, name="")
    tokens = theme.tokens()
    return {"name": "", "background": tokens["bg"], "sidebar": tokens["bg_sidebar"],
            "cards": tokens["bg_panel"], "text": tokens["fg"], "accent": tokens["accent"],
            "secondary": tokens["bg_panel"], "gradient": [], "direction": "down",
            "where": [], "font": ""}


class Swatch(QPushButton):
    """A button that shows a colour and opens the colour picker."""

    def __init__(self, colour: str, on_change: Callable[[str], None]):
        super().__init__()
        self._on_change = on_change
        self.setMinimumWidth(round(130 * theme.text_scale()))
        self.clicked.connect(self._pick)
        self.set(colour)

    def set(self, colour: str) -> None:
        self.colour = colour
        self.setText(colour.upper())
        self.setStyleSheet(f"background-color: {colour}; color: {themes.on_colour(colour)}; "
                           f"border: 1px solid {theme.color('border_strong')};")

    def _pick(self) -> None:
        chosen = QColorDialog.getColor(QColor(self.colour), self.window(), t("Pick a colour"))
        if chosen.isValid():
            self.set(chosen.name())
            self._on_change(self.colour)


class ThemeEditor(QDialog):
    def __init__(self, window, spec: dict | None = None, on_saved: Callable[[str], None] = None):
        super().__init__(window)
        self.window_ = window
        self.on_saved = on_saved
        self.original = spec["name"] if spec else None
        self.spec = dict(spec) if spec else starting_spec()
        # Own copies: the lists are changed in place, and must not reach a ready-made theme
        self.spec["gradient"] = list(self.spec["gradient"])
        self.spec["where"] = list(self.spec["where"])
        if not self.spec["gradient"]:
            # A gentle start: the sidebar fading towards the main colour, still easy to read
            self.spec["gradient"] = [self.spec["sidebar"],
                                     themes.mix(self.spec["sidebar"], self.spec["accent"], 0.3)]
            self._gradient_on = False
        else:
            self._gradient_on = True
        self.font_before = theme.ui_family()

        self.setWindowTitle(t("Change this theme") if spec else t("Make my own theme"))
        self.setModal(True)
        resizable(self)
        scale = theme.text_scale()
        self.resize(round(620 * scale), round(640 * scale))
        pad = round(20 * scale)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(pad, pad, pad, pad)
        layout.setSpacing(round(10 * scale))
        layout.addWidget(subheading(self.windowTitle()))
        layout.addWidget(muted("The whole app changes as you pick, so you can see the result. "
                               "Nothing is kept until you press Save theme."))

        area = ScrollPage(spacing=round(10 * scale))
        layout.addWidget(area, 1)

        self.name_box = line_edit("For example: My company colours", self.spec["name"])
        area.add(column(field_label("Name"), self.name_box, spacing=4))

        colours = Section("Colours")
        grid_holder = QWidget()
        grid_holder.setProperty("role", "plain")
        grid = QGridLayout(grid_holder)
        grid.setContentsMargins(0, 0, 0, 0)
        self.swatches: dict[str, Swatch] = {}
        for index, key in enumerate(themes.COLOURS):
            swatch = Swatch(self.spec[key], lambda colour, k=key: self._set(k, colour))
            self.swatches[key] = swatch
            grid.addWidget(field_label(COLOUR_LABELS[key]), index, 0)
            grid.addWidget(swatch, index, 1)
        grid.setColumnStretch(2, 1)
        colours.add(grid_holder)
        area.add(colours)

        gradient = Section("Gradient")
        self.gradient_box = checkbox("Add a gradient", self._gradient_on,
                                     on_change=self._toggle_gradient)
        gradient.add(self.gradient_box)
        self.gradient_parts = QWidget()
        self.gradient_parts.setProperty("role", "plain")
        parts = QVBoxLayout(self.gradient_parts)
        parts.setContentsMargins(0, 0, 0, 0)
        self.from_swatch = Swatch(self.spec["gradient"][0], lambda c: self._set_stop(0, c))
        self.to_swatch = Swatch(self.spec["gradient"][1], lambda c: self._set_stop(1, c))
        parts.addWidget(row(field_label("Start colour"), self.from_swatch,
                            field_label("End colour"), self.to_swatch, None))
        parts.addWidget(field_label("Direction"))
        parts.addWidget(ChoiceButtons(DIRECTION_LABELS, self.spec["direction"],
                                      on_change=lambda d: self._set("direction", d)))
        parts.addWidget(field_label("Where"))
        self.place_boxes = {
            place: checkbox(label, place in self.spec["where"],
                            on_change=lambda _on: self._set_places())
            for place, label in PLACE_LABELS.items()}
        parts.addWidget(wrap_row(*self.place_boxes.values()))
        gradient.add(self.gradient_parts)
        self.gradient_parts.setVisible(self._gradient_on)
        area.add(gradient)

        fonts = Section("Font")
        names = [STANDARD_FONT] + [font for font in themes.FONTS if font]
        self.font_box = combo(names, self.spec["font"] or STANDARD_FONT,
                              on_change=self._set_font, translate={STANDARD_FONT})
        fonts.add(row(self.font_box, None))
        area.add(fonts)
        area.add_stretch()

        self.warnings = muted("")
        set_tone(self.warnings, "warning")
        layout.addWidget(self.warnings)
        layout.addWidget(row(None, secondary_button("Cancel", self.reject, 120),
                             primary_button("Save theme", self._save, 160)))
        self._show()

    # -- changes paint the app straight away --
    def _set(self, key: str, value) -> None:
        self.spec[key] = value
        self._show()

    def _set_stop(self, index: int, colour: str) -> None:
        self.spec["gradient"][index] = colour
        self._show()

    def _toggle_gradient(self, on: bool) -> None:
        self._gradient_on = on
        self.gradient_parts.setVisible(on)
        if on and not any(box.isChecked() for box in self.place_boxes.values()):
            self.place_boxes["sidebar"].setChecked(True)
        self._show()

    def _set_places(self) -> None:
        self.spec["where"] = [place for place, box in self.place_boxes.items() if box.isChecked()]
        self._show()

    def _set_font(self, name: str) -> None:
        self._set("font", "" if name == STANDARD_FONT else name)

    def _result(self) -> dict:
        spec = dict(self.spec, name=self.name_box.text().strip())
        if not self._gradient_on:
            spec["gradient"], spec["where"] = [], []
        return spec

    def _show(self) -> None:
        spec = self._result()
        theme.use_theme(spec)
        self.window_.apply_theme()
        for swatch in (*self.swatches.values(), self.from_swatch, self.to_swatch):
            swatch.set(swatch.colour)
        problems = themes.readability_problems(spec)
        self.warnings.setText(" ".join(t(problem) for problem in problems))
        self.warnings.setVisible(bool(problems))

    # -- closing --
    def _save(self) -> None:
        spec = self._result()
        if not spec["name"]:
            self.warnings.setText(t("The theme needs a name."))
            self.warnings.setVisible(True)
            self.name_box.setFocus()
            return
        taken = {existing["name"].casefold() for existing in themes.custom_themes()}
        if spec["name"].casefold() in taken and spec["name"].casefold() != (
                self.original or "").casefold() and not ConfirmDialog.ask(
                self, "Replace the theme?",
                t("You already have a theme called {name}. Replace it?", name=spec["name"]),
                "Replace"):
            return
        try:
            saved = themes.save_custom(spec, replacing=self.original)
        except ValueError as error:
            self.warnings.setText(t(str(error)))
            self.warnings.setVisible(True)
            return
        key = themes.custom_key(saved["name"])
        db.set_setting("appearance", key)
        self.accept()
        if self.on_saved:
            self.on_saved(key)
        self.window_.show_theme(lambda: theme.set_appearance(key), font=self.font_before)

    def reject(self) -> None:
        super().reject()
        self.window_.show_theme(lambda: theme.set_appearance(prefs.get("appearance")),
                                font=self.font_before)

