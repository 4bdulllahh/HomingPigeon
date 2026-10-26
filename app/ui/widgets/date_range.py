"""A From / To date filter: one button that shows the chosen dates, and a cross to clear them.

The dates stay chosen until the user changes or clears them, whatever other
filter buttons on the page are pressed meanwhile.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Callable

from PyQt6.QtCore import QDate, pyqtSignal
from PyQt6.QtWidgets import QDateEdit, QDialog, QHBoxLayout, QVBoxLayout, QWidget

from app.core import prefs
from app.i18n import t
from app.ui import theme
from app.ui.widgets.common import (field_label, muted, primary_button, row, secondary_button,
                                   small_button, subheading, wrap_row)
from app.ui.widgets.dialogs import resizable


def _quick_picks(today: date) -> list[tuple[str, date, date]]:
    return [
        ("Today", today, today),
        ("Last 7 days", today - timedelta(days=6), today),
        ("Last 30 days", today - timedelta(days=29), today),
        ("This month", today.replace(day=1), today),
        ("This year", today.replace(month=1, day=1), today),
    ]


def _qdate(value: date) -> QDate:
    return QDate(value.year, value.month, value.day)


class DateRangeDialog(QDialog):
    def __init__(self, parent: QWidget, start: date | None, end: date | None):
        super().__init__(parent.window())
        self.setWindowTitle(t("Pick dates"))
        self.setModal(True)
        resizable(self)
        scale = theme.text_scale()
        pad = round(20 * scale)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(pad, pad, pad, pad)
        layout.setSpacing(round(10 * scale))
        layout.addWidget(subheading("Pick dates"))
        layout.addWidget(muted("Show only what happened between these two days, both included."))

        today = date.today()
        pattern = prefs.DATE_FORMATS.get(prefs.get("date_format"),
                                         prefs.DATE_FORMATS[prefs.DEFAULT_DATE_FORMAT])[0]
        qt_pattern = pattern.replace("DD", "dd").replace("YYYY", "yyyy").replace("Mon", "MMM")
        self.start_box, self.end_box = QDateEdit(), QDateEdit()
        for box, value in ((self.start_box, start or today - timedelta(days=29)),
                           (self.end_box, end or today)):
            box.setCalendarPopup(True)
            box.setDisplayFormat(qt_pattern)
            box.setDate(_qdate(value))
            box.setMinimumWidth(round(150 * scale))
        layout.addWidget(row(field_label("First day"), self.start_box, field_label("Last day"),
                             self.end_box, None))

        picks = [secondary_button(label, lambda a=first, b=last: self._fill(a, b))
                 for label, first, last in _quick_picks(today)]
        layout.addWidget(wrap_row(*picks))
        layout.addStretch(1)
        layout.addWidget(row(None, secondary_button("Cancel", self.reject, 110),
                             primary_button("Show these dates", self.accept, 180)))

    def _fill(self, first: date, last: date) -> None:
        self.start_box.setDate(_qdate(first))
        self.end_box.setDate(_qdate(last))

    def chosen(self) -> tuple[date, date]:
        first, last = self.start_box.date().toPyDate(), self.end_box.date().toPyDate()
        return (first, last) if first <= last else (last, first)


class DateRange(QWidget):
    """The button on a page. ``changed`` fires with the new (start, end); both None is any date."""

    changed = pyqtSignal(object, object)

    def __init__(self, on_change: Callable[[date | None, date | None], None] | None = None,
                 labels: tuple[str, str] = ("Dates: any", "Dates: {start} to {end}"),
                 parent=None):
        super().__init__(parent)
        self.setProperty("role", "plain")
        self.start: date | None = None
        self.end: date | None = None
        self._labels = labels   # (nothing picked, a template with {start} and {end})
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.button = secondary_button(labels[0], self._pick)
        self.button.setToolTip(t("Show only a range of dates"))
        self.clear_button = small_button("✕", self.clear)
        self.clear_button.setToolTip(t("Show every date again"))
        layout.addWidget(self.button)
        layout.addWidget(self.clear_button)
        if on_change:
            self.changed.connect(on_change)
        self._paint()

    def _paint(self) -> None:
        on = self.start is not None
        self.button.setText(t(self._labels[1], start=prefs.format_date(self.start),
                              end=prefs.format_date(self.end)) if on else t(self._labels[0]))
        self.clear_button.setVisible(on)

    def _pick(self) -> None:
        dialog = DateRangeDialog(self, self.start, self.end)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.set(*dialog.chosen())

    def set(self, start: date | None, end: date | None) -> None:
        self.start, self.end = start, end
        self._paint()
        self.changed.emit(start, end)

    def clear(self) -> None:
        self.set(None, None)

    def get(self) -> tuple[date | None, date | None]:
        return self.start, self.end
