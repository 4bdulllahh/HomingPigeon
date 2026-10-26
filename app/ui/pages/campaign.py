"""Campaign setup: brochure handling, pacing, send window, daily cap and warm-up."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QButtonGroup, QFileDialog, QGridLayout, QVBoxLayout, QWidget

from app import config
from app.core import db, prefs, warmup
from app.i18n import t
from app.ui.pages.base import Page
from app.ui import theme
from app.ui.widgets.common import (ChoiceButtons, FormRow, Section, clear_layout, column,
                                   flow_row, hint, muted, primary_button, row, secondary_button,
                                   set_tone, small_button, wrap_row)
from app.ui.widgets.inputs import (checkbox, combo, get_text, line_edit, radio, set_text,
                                   spin_box, text_box)
from app.ui.widgets.range_slider import RangeSlider

ATTACH_MODES = [
    ("link", "Link to the brochure (recommended)"),
    ("attach", "Attach the file to every email"),
    ("none", "No brochure"),
]

DELAY_PRESETS = [("Very safe", 180, 420), ("Balanced", 75, 150), ("Faster", 45, 90)]


class RampEditor(QWidget):
    """The user's own warm-up plan: a box for every day, which three numbers can fill in."""

    changed = pyqtSignal()

    def __init__(self, ramp: list[int], parent=None):
        super().__init__(parent)
        self.setProperty("role", "plain")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.start = spin_box(ramp[0] if ramp else 20, 1, 5000)
        self.step = spin_box(5, 1, 1000)
        self.stop = spin_box(max(ramp) if ramp else 150, 1, 5000)
        fields = []
        for label, box in (("Start with", self.start), ("Add each day", self.step),
                           ("Stop at", self.stop)):
            form = FormRow(label)
            form.add(box)
            fields.append(form)
        fill = secondary_button("Fill in the days", self._fill, 150)
        fill.setToolTip(t("Replace the days below with a plan made from these three numbers"))
        layout.addWidget(row(*fields, column(None, fill), None))

        self.days_holder, self.days_layout = flow_row(6)
        layout.addWidget(self.days_holder)
        layout.addWidget(wrap_row(small_button("+ Add a day", self._add_day),
                                  small_button("Remove the last day", self._remove_day)))
        self.boxes: list = []
        self.set_ramp(ramp)

    def _cell(self, day: int, count: int) -> QWidget:
        box = spin_box(count, 1, 5000, on_change=lambda _v: self.changed.emit())
        box.setFixedWidth(round(78 * theme.text_scale()))
        self.boxes.append(box)
        return column(hint(t("Day {day}", day=day), wrap=False), box, spacing=2)

    def set_ramp(self, ramp: list[int]) -> None:
        clear_layout(self.days_layout)
        self.boxes = []
        for day, count in enumerate(ramp, start=1):
            self.days_layout.addWidget(self._cell(day, count))
        self.changed.emit()

    def ramp(self) -> list[int]:
        return [box.value() for box in self.boxes]

    def _fill(self) -> None:
        self.set_ramp(warmup.build_ramp(self.start.value(), self.step.value(), self.stop.value()))

    def _add_day(self) -> None:
        if len(self.boxes) >= warmup.MAX_CUSTOM_DAYS:
            return
        last = self.boxes[-1].value() if self.boxes else 20
        self.days_layout.addWidget(self._cell(len(self.boxes) + 1, last))
        self.changed.emit()

    def _remove_day(self) -> None:
        if len(self.boxes) <= 1:
            return
        self.boxes.pop()
        item = self.days_layout.takeAt(self.days_layout.count() - 1)
        widget = item.widget() if item is not None else None
        if widget is not None:
            # Held in a name: an unparented cell only Python refers to is freed at once
            widget.setParent(None)
            widget.deleteLater()
        self.changed.emit()


class CampaignPage(Page):
    def __init__(self, window):
        super().__init__(window)
        self._build()
        self.load()

    def _build(self) -> None:
        self.add_header("Sending options",
                        "How the emails are paced and what goes out with them.")
        area = self.scroll_body()

        area.add(self._brochure_section())
        area.add(self._pacing_section())
        area.add(self._window_section())
        area.add(self._volume_section())

        self.save_status = muted("", wrap=False)
        area.add(row(primary_button("Save settings", self.save, 170), self.save_status, None))
        area.add_stretch()

    # --- brochure -----------------------------------------------------------
    def _brochure_section(self) -> Section:
        section = Section(
            "Brochure",
            "Attaching a PDF to a first email from an unknown sender is one of the strongest spam "
            "signals there is. Linking to it instead is measurably safer. The attachment "
            "option is here when you need it.")

        self.attach_group = QButtonGroup(self)
        self.attach_buttons: dict[str, object] = {}
        for value, label in ATTACH_MODES:
            button = radio(label, value == "link")
            button.toggled.connect(lambda checked, v=value: checked and self._update_attach_mode(v))
            self.attach_group.addButton(button)
            self.attach_buttons[value] = button
            section.add(button)

        self.link_panel = QWidget()
        self.link_panel.setProperty("role", "plain")
        link_layout = QVBoxLayout(self.link_panel)
        link_layout.setContentsMargins(0, 6, 0, 0)
        link_layout.setSpacing(8)
        url_row = FormRow("Brochure URL",
                          "Upload the PDF to your website or Google Drive and paste the public link.")
        self.link_box = line_edit("https://www.yourcompany.com/brochure.pdf")
        url_row.add(self.link_box)
        link_layout.addWidget(url_row)
        text_row = FormRow("Link text")
        self.link_text_box = line_edit("View our brochure")
        text_row.add(self.link_text_box)
        link_layout.addWidget(text_row)
        section.add(self.link_panel)

        self.attach_panel = QWidget()
        self.attach_panel.setProperty("role", "plain")
        attach_layout = QVBoxLayout(self.attach_panel)
        attach_layout.setContentsMargins(0, 6, 0, 0)
        attach_layout.setSpacing(6)
        self.attach_label = muted("No file selected", wrap=False)
        attach_layout.addWidget(row(self.attach_label, None,
                                    secondary_button("Choose PDF...", self._choose_attachment, 150)))
        self.attach_warning = hint("")
        attach_layout.addWidget(self.attach_warning)
        section.add(self.attach_panel)
        return section

    def _update_attach_mode(self, mode: str) -> None:
        self.link_panel.setVisible(mode == "link")
        self.attach_panel.setVisible(mode == "attach")
        self._mark_dirty()

    def _attach_mode(self) -> str:
        for value, button in self.attach_buttons.items():
            if button.isChecked():
                return value
        return "link"

    def _choose_attachment(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, t("Select your brochure"), "",
            t("PDF (*.pdf);;Images (*.png *.jpg *.jpeg);;All files (*.*)"))
        if not path:
            return
        file_path = Path(path)
        size = file_path.stat().st_size
        limit = config.MAX_ATTACHMENT_BYTES

        if size > limit:
            self.attach_label.setText(t(file_path.name))
            set_tone(self.attach_label, "error")
            self.attach_warning.setText(
                t("✕ {number:.1f} MB, over the {number2} MB limit. Compress the PDF or switch "
                  "to a link.", number=size / 1_048_576, number2=limit // 1_048_576))
            set_tone(self.attach_warning, "error")
            return

        db.set_setting("attachment_path", str(file_path))
        self.attach_label.setText(t(file_path.name))
        set_tone(self.attach_label, "bright")
        self.attach_warning.setText(
            t("⚠ {number:.1f} MB. Every recipient receives this file, which raises your "
              "spam score on first contact.", number=size / 1_048_576))
        set_tone(self.attach_warning, "warning")

    # --- pacing -------------------------------------------------------------
    def _pacing_section(self) -> Section:
        section = Section(
            "Delay between emails",
            "A random wait is chosen inside this range before each send. Random, human-like "
            "timing is far less detectable than a fixed interval. Never set both handles "
            "equal for a real campaign.")

        self.slider = RangeSlider(75, 150)
        self.slider.changed.connect(self._slider_moved)
        self.slider.released.connect(self._slider_released)
        section.add(self.slider)

        self.slider_readout = muted(self.slider.readout(), wrap=False)
        section.add(self.slider_readout)

        presets = [hint("Presets:", wrap=False)]
        for label, low, high in DELAY_PRESETS:
            presets.append(secondary_button(label, lambda l=low, h=high: self._set_delay(l, h), 110))
        section.add(wrap_row(*presets))

        self.pace_note = hint("")
        section.add(self.pace_note)
        return section

    def _slider_moved(self, low: int, high: int) -> None:
        self.slider_readout.setText(t(self.slider.readout()))
        self._update_pace_note(low, high)

    def _slider_released(self, low: int, high: int) -> None:
        self._slider_moved(low, high)
        self._mark_dirty()

    def _set_delay(self, low: int, high: int) -> None:
        self.slider.set(low, high)
        self._slider_released(low, high)

    def _update_pace_note(self, low: int, high: int) -> None:
        average = (low + high) / 2
        per_hour = int(3600 / average) if average else 0
        cap = warmup.effective_cap()
        hours = (cap * average) / 3600 if per_hour else 0
        if low == high:
            warning = "  ⚠ A fixed interval is a bot signature. Widen the range."
            tone = "warning"
        else:
            warning, tone = "", "muted"
        self.pace_note.setText(
            t("About {per_hour} emails per hour. Today's limit of {cap} would take roughly "
              "{hours:.1f} hours.{warning}",
              per_hour=per_hour, cap=cap, hours=hours, warning=warning))
        set_tone(self.pace_note, tone)

    # --- window -------------------------------------------------------------
    def _window_section(self) -> Section:
        section = Section(
            "When to send",
            "Bulk mail arriving at 3am looks automated. Sending inside office hours looks like a "
            "person at a desk.")

        holder = QWidget()
        holder.setProperty("role", "plain")
        grid = QGridLayout(holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 2)

        hours = [prefs.format_clock(f"{h:02d}:00") for h in range(24)]
        start_row = FormRow("Start")
        self.start_picker = combo(hours, on_change=lambda _t: self._mark_dirty(), translate=False)
        start_row.add(self.start_picker)
        grid.addWidget(start_row, 0, 0)

        end_row = FormRow("End")
        self.end_picker = combo(hours, on_change=lambda _t: self._mark_dirty(), translate=False)
        end_row.add(self.end_picker)
        grid.addWidget(end_row, 0, 1)
        section.add(holder)

        self.weekdays_only = checkbox("Weekdays only (skip Saturday and Sunday)", True,
                                      on_change=lambda _c: self._mark_dirty())
        section.add(self.weekdays_only)
        self.skip_holidays = checkbox("Skip public holidays", True,
                                      on_change=lambda _c: self._mark_dirty())
        section.add(self.skip_holidays)

        section.add(hint("Public holidays (one date per line, YYYY-MM-DD)"))
        self.holidays_box = text_box("", monospace=True, lines=5)
        self.holidays_box.textChanged.connect(self._mark_dirty)
        section.add(self.holidays_box)
        section.add(hint("Add the public holidays of the country your recipients are in, "
                         "for example  2026-12-25"))
        return section

    # --- volume -------------------------------------------------------------
    def _volume_section(self) -> Section:
        section = Section(
            "Daily volume and warm-up",
            "A new domain that suddenly sends hundreds of emails looks compromised. The ramp "
            "raises your limit gradually so receiving servers build trust in you.")

        self.warmup_enabled = checkbox("Use the warm-up ramp (recommended)", True,
                                       on_change=lambda _c: self._toggle_warmup())
        section.add(self.warmup_enabled)

        self.plan_row = FormRow("Warm-up plan")
        self.plan_choice = ChoiceButtons(list(warmup.PRESET_NAMES.items()), warmup.DEFAULT_PRESET,
                                         on_change=self._plan_changed)
        self.plan_row.add(self.plan_choice)
        section.add(self.plan_row)
        self.plan_note = hint("")
        section.add(self.plan_note)
        self.ramp_editor = RampEditor(warmup.custom_ramp())
        self.ramp_editor.changed.connect(self._ramp_edited)
        section.add(self.ramp_editor)
        self.ramp_warning = hint("")
        set_tone(self.ramp_warning, "warning")
        section.add(self.ramp_warning)

        self.warmup_status = muted("")
        section.add(self.warmup_status)
        self.schedule_label = hint("")
        section.add(self.schedule_label)

        self.manual_cap_row = FormRow("Manual daily limit",
                                      "Used when the warm-up ramp is switched off.")
        self.manual_cap_box = line_edit("100")
        self.manual_cap_box.textChanged.connect(lambda _t: self._mark_dirty())
        self.manual_cap_row.add(self.manual_cap_box)
        section.add(self.manual_cap_row)

        section.add(wrap_row(
            secondary_button("Reset warm-up to day 1", self._reset_warmup, 200),
            secondary_button("Skip ahead a week", self._skip_warmup, 175)))
        section.add(hint("Only skip ahead if this address has already been sending normal "
                         "business email in volume for a while."))
        return section

    def _toggle_warmup(self) -> None:
        self.manual_cap_row.setVisible(not self.warmup_enabled.isChecked())
        db.set_setting("warmup_enabled", self.warmup_enabled.isChecked())
        self._show_plan()
        self._refresh_warmup()
        self._mark_dirty()

    def _plan_changed(self, _key: str) -> None:
        self._show_plan()
        self._refresh_warmup()
        self._mark_dirty()

    def _ramp_edited(self) -> None:
        if not hasattr(self, "save_status"):
            return          # still being built
        self._show_plan()
        self._refresh_warmup()
        self._mark_dirty()

    def _current_ramp(self) -> list[int]:
        key = self.plan_choice.get()
        return self.ramp_editor.ramp() if key == "custom" else warmup.ramp_for(key)

    def _show_plan(self) -> None:
        """Show the plan controls that apply: the day boxes only for the user's own plan."""
        on = self.warmup_enabled.isChecked()
        key = self.plan_choice.get()
        custom = key == "custom"
        self.plan_row.setVisible(on)
        self.plan_note.setVisible(on)
        self.plan_note.setText(t(warmup.PRESET_NOTES[key]))
        self.ramp_editor.setVisible(on and custom)
        warnings = warmup.ramp_warnings(self.ramp_editor.ramp()) if on and custom else []
        self.ramp_warning.setText("\n".join("⚠ " + w for w in warnings))
        self.ramp_warning.setVisible(bool(warnings))

    def _reset_warmup(self) -> None:
        warmup.reset()
        self._refresh_warmup()
        self.notify("Warm-up reset to day 1", "success")

    def _skip_warmup(self) -> None:
        warmup.set_day(warmup.status().day_index + 7)
        self._refresh_warmup()
        self.notify("Skipped ahead one week", "success")

    def _refresh_warmup(self) -> None:
        status = warmup.status()
        self.warmup_status.setText(
            t("{describe} · {remaining} remaining today · provider ceiling {provider_limit:,}/day",
              describe=status.describe(), remaining=status.remaining,
              provider_limit=status.provider_limit))
        upcoming = warmup.projected_schedule(7, self._current_ramp())
        self.schedule_label.setText(
            t("Next days: {days}", days="  ".join(t("day {day}: {count}", day=d, count=c)
                                                  for d, c in upcoming)))
        low, high = self.slider.get()
        self._update_pace_note(low, high)

    # --- persistence --------------------------------------------------------
    def _mark_dirty(self) -> None:
        self.save_status.setText(t("Unsaved changes"))
        set_tone(self.save_status, "warning")

    def _parse_holidays(self) -> list[str]:
        dates = []
        for line in get_text(self.holidays_box).splitlines():
            token = line.split("#")[0].strip()
            if len(token) == 10 and token.count("-") == 2:
                dates.append(token)
        return dates

    def save(self) -> None:
        low, high = self.slider.get()
        db.set_setting("attach_mode", self._attach_mode())
        db.set_setting("link_url", self.link_box.text().strip())
        db.set_setting("link_text", self.link_text_box.text().strip() or "View our brochure")
        db.set_setting("delay_min_s", low)
        db.set_setting("delay_max_s", high)
        db.set_setting("window_start", prefs.parse_clock(self.start_picker.currentText()))
        db.set_setting("window_end", prefs.parse_clock(self.end_picker.currentText()))
        db.set_setting("weekdays_only", self.weekdays_only.isChecked())
        db.set_setting("skip_holidays", self.skip_holidays.isChecked())
        db.set_setting("holidays", self._parse_holidays())
        db.set_setting("warmup_enabled", self.warmup_enabled.isChecked())
        db.set_setting("warmup_preset", self.plan_choice.get())
        if self.plan_choice.get() == "custom":
            db.set_setting("warmup_ramp", self.ramp_editor.ramp())
        try:
            db.set_setting("manual_daily_cap", int(self.manual_cap_box.text().strip() or 100))
        except ValueError:
            pass

        self.save_status.setText(t("Saved"))
        set_tone(self.save_status, "success")
        self.notify("Campaign settings saved", "success")
        self._refresh_warmup()

    def load(self) -> None:
        mode = db.get_setting("attach_mode", "link")
        button = self.attach_buttons.get(mode) or self.attach_buttons["link"]
        button.setChecked(True)
        self._update_attach_mode(mode)

        self.link_box.setText(str(db.get_setting("link_url", "") or ""))
        self.link_text_box.setText(str(db.get_setting("link_text", "View our brochure")))

        attachment = db.get_setting("attachment_path", "")
        if attachment and Path(attachment).exists():
            path = Path(attachment)
            self.attach_label.setText(t(path.name))
            set_tone(self.attach_label, "bright")
            self.attach_warning.setText(
                t("⚠ {number:.1f} MB attached to every email.",
                  number=path.stat().st_size / 1_048_576))
            set_tone(self.attach_warning, "warning")

        self.slider.set(int(db.get_setting("delay_min_s", 75)),
                        int(db.get_setting("delay_max_s", 150)))
        self.slider_readout.setText(t(self.slider.readout()))
        self.start_picker.setCurrentText(
            prefs.format_clock(db.get_setting("window_start", config.DEFAULT_WINDOW_START)))
        self.end_picker.setCurrentText(
            prefs.format_clock(db.get_setting("window_end", config.DEFAULT_WINDOW_END)))
        self.weekdays_only.setChecked(bool(db.get_setting("weekdays_only", True)))
        self.skip_holidays.setChecked(bool(db.get_setting("skip_holidays", True)))

        holidays = db.get_setting("holidays", [])
        if holidays:
            set_text(self.holidays_box, "\n".join(holidays))

        self.warmup_enabled.setChecked(bool(db.get_setting("warmup_enabled", True)))
        self.manual_cap_box.setText(str(db.get_setting("manual_daily_cap", 100)))
        self.manual_cap_row.setVisible(not self.warmup_enabled.isChecked())
        self.plan_choice.set(warmup.preset())
        self.ramp_editor.set_ramp(warmup.custom_ramp())
        self._show_plan()
        self._refresh_warmup()

        self.save_status.setText("")
        set_tone(self.save_status, "muted")

    def on_show(self) -> None:
        self._refresh_warmup()
