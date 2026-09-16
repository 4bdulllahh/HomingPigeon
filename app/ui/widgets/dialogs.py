"""Modal dialogs: a yes/no confirm and a pick-one-of-several."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout,
                             QWidget)

from app.ui import theme
from app.ui.widgets.common import danger_button, primary_button, secondary_button


class ConfirmDialog(QDialog):
    def __init__(self, parent: QWidget | None, title: str, message: str,
                 confirm_text: str = "Continue", cancel_text: str = "Cancel",
                 danger: bool = False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(round(460 * theme.text_scale()))

        pad = round(22 * theme.text_scale())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(pad, pad, pad, pad)
        layout.setSpacing(12)

        heading = QLabel(title)
        heading.setProperty("role", "subheading")
        layout.addWidget(heading)

        text = QLabel(message)
        text.setWordWrap(True)
        layout.addWidget(text)
        layout.addSpacing(6)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = secondary_button(cancel_text, self.reject, width=110)
        confirm = (danger_button if danger else primary_button)(confirm_text, self.accept, width=150)
        buttons.addWidget(cancel)
        buttons.addWidget(confirm)
        layout.addLayout(buttons)
        confirm.setDefault(True)
        confirm.setFocus()

    @classmethod
    def ask(cls, parent, title: str, message: str, confirm_text: str = "Continue",
            danger: bool = False) -> bool:
        dialog = cls(parent.window() if parent else None, title, message, confirm_text,
                     danger=danger)
        return dialog.exec() == QDialog.DialogCode.Accepted


class ChoiceDialog(QDialog):
    """Like ConfirmDialog but with several answers. Returns the chosen value, or None."""

    def __init__(self, parent: QWidget | None, title: str, message: str,
                 choices: list[tuple[str, str, str]]):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(round(500 * theme.text_scale()))
        self.result_value: str | None = None

        pad = round(22 * theme.text_scale())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(pad, pad, pad, pad)
        layout.setSpacing(12)

        heading = QLabel(title)
        heading.setProperty("role", "subheading")
        layout.addWidget(heading)

        text = QLabel(message)
        text.setWordWrap(True)
        layout.addWidget(text)
        layout.addSpacing(6)

        makers = {"primary": primary_button, "danger": danger_button,
                  "secondary": secondary_button}
        for value, label, kind in choices:
            button = makers.get(kind, secondary_button)(label, lambda v=value: self._choose(v))
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            layout.addWidget(button)

    def _choose(self, value: str | None) -> None:
        self.result_value = value
        self.accept()

    @classmethod
    def ask(cls, parent, title: str, message: str,
            choices: list[tuple[str, str, str]]) -> str | None:
        dialog = cls(parent.window() if parent else None, title, message, choices)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.result_value
        return None


class InfoDialog(QDialog):
    """A read-only explainer: a title, scrolling sections and one Close button.

    Used where a number on screen needs its reasoning shown, such as the spam score,
    without sending the user to a separate page or a website.
    """

    def __init__(self, parent: QWidget | None, title: str, intro: str,
                 sections: list[tuple[str, list[str]]], footer: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        scale = theme.text_scale()
        self.setMinimumWidth(round(560 * scale))
        self.resize(round(620 * scale), round(620 * scale))

        pad = round(22 * scale)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(pad, pad, pad, pad)
        layout.setSpacing(round(10 * scale))

        heading = QLabel(title)
        heading.setProperty("role", "heading")
        layout.addWidget(heading)

        if intro:
            lead = QLabel(intro)
            lead.setProperty("role", "muted")
            lead.setWordWrap(True)
            layout.addWidget(lead)

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.verticalScrollBar().setSingleStep(24)

        content = QWidget()
        content.setProperty("role", "plain")
        inner = QVBoxLayout(content)
        inner.setContentsMargins(0, 0, round(8 * scale), 0)
        inner.setSpacing(round(6 * scale))

        for section_title, points in sections:
            label = QLabel(section_title)
            label.setProperty("role", "subheading")
            inner.addWidget(label)
            for point in points:
                item = QLabel(f"•  {point}")
                item.setWordWrap(True)
                item.setProperty("role", "muted")
                item.setContentsMargins(round(6 * scale), 0, 0, 0)
                inner.addWidget(item)
            inner.addSpacing(round(6 * scale))
        inner.addStretch(1)

        area.setWidget(content)
        layout.addWidget(area, 1)

        if footer:
            note = QLabel(footer)
            note.setProperty("role", "hint")
            note.setWordWrap(True)
            layout.addWidget(note)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(primary_button("Close", self.accept, width=120))
        layout.addLayout(buttons)

    @classmethod
    def show_for(cls, parent, title: str, intro: str,
                 sections: list[tuple[str, list[str]]], footer: str = "") -> None:
        cls(parent.window() if parent else None, title, intro, sections, footer).exec()
