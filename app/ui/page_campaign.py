"""Campaign setup: brochure handling, pacing slider, send window, daily cap."""
from __future__ import annotations

from pathlib import Path

import customtkinter as ctk
from tkinter import filedialog

from app import config, theme
from app.core import composer, db, importer, warmup
from app.ui.widgets.common import FormRow, Section, toast
from app.ui.widgets.range_slider import RangeSlider, format_seconds

UAE_HOLIDAYS_2026 = [
    ("2026-01-01", "New Year's Day"),
    ("2026-03-19", "Eid al-Fitr (approx.)"),
    ("2026-03-20", "Eid al-Fitr (approx.)"),
    ("2026-03-21", "Eid al-Fitr (approx.)"),
    ("2026-05-26", "Arafat Day (approx.)"),
    ("2026-05-27", "Eid al-Adha (approx.)"),
    ("2026-05-28", "Eid al-Adha (approx.)"),
    ("2026-06-16", "Islamic New Year (approx.)"),
    ("2026-08-25", "Prophet's Birthday (approx.)"),
    ("2026-12-01", "Commemoration Day"),
    ("2026-12-02", "National Day"),
    ("2026-12-03", "National Day holiday"),
]


class CampaignPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self._build()
        self.load()

    def _build(self) -> None:
        scroll = theme.scroll_frame(self)
        scroll.pack(fill="both", expand=True, padx=theme.PAD_LARGE, pady=theme.PAD)

        theme.heading(scroll, "Campaign settings").pack(anchor="w")
        theme.label(scroll, "How the emails are paced and what goes out with them.",
                    muted=True, wrap=True).pack(anchor="w", pady=(2, 16))

        # --- brochure -------------------------------------------------------
        brochure = Section(
            scroll, "Brochure",
            "Attaching a PDF to a first email from an unknown sender is one of the strongest spam "
            "signals there is. Linking to it instead is measurably safer — the attachment option "
            "is here when you need it.")
        brochure.pack(fill="x", pady=(0, 14))

        self.attach_mode = ctk.StringVar(value="link")
        for value, title in [
            ("link", "Link to the brochure (recommended)"),
            ("attach", "Attach the file to every email"),
            ("none", "No brochure"),
        ]:
            ctk.CTkRadioButton(
                brochure.body, text=title, variable=self.attach_mode, value=value,
                command=self._update_attach_mode, font=theme.font(13), text_color=theme.FG,
                fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                border_color=theme.BORDER_STRONG, radiobutton_width=18, radiobutton_height=18,
            ).pack(anchor="w", pady=3)

        self.link_frame = ctk.CTkFrame(brochure.body, fg_color="transparent")
        row = FormRow(self.link_frame, "Brochure URL",
                      "Upload the PDF to your website or Google Drive and paste the public link.")
        row.pack(fill="x", pady=(10, 8))
        self.link_entry = theme.entry(row.input_area, "https://www.yourcompany.com/brochure.pdf")
        self.link_entry.pack(fill="x")

        row = FormRow(self.link_frame, "Link text")
        row.pack(fill="x")
        self.link_text_entry = theme.entry(row.input_area, "View our brochure")
        self.link_text_entry.pack(fill="x")

        self.attach_frame = ctk.CTkFrame(brochure.body, fg_color="transparent")
        picker = ctk.CTkFrame(self.attach_frame, fg_color="transparent")
        picker.pack(fill="x", pady=(10, 0))
        self.attach_label = theme.label(picker, "No file selected", muted=True)
        self.attach_label.pack(side="left", fill="x", expand=True)
        theme.secondary_button(picker, "Choose PDF…", self._choose_attachment, width=130).pack(
            side="right")
        self.attach_warning = theme.label(self.attach_frame, "", muted=True, size=11)
        self.attach_warning.pack(anchor="w", pady=(6, 0))

        # --- pacing ---------------------------------------------------------
        pacing = Section(
            scroll, "Delay between emails",
            "A random wait is chosen inside this range before each send. Random, human-like "
            "timing is far less detectable than a fixed interval — never set both handles equal "
            "for a real campaign.")
        pacing.pack(fill="x", pady=(0, 14))

        self.slider = RangeSlider(pacing.body, low=75, high=150, command=self._slider_changed)
        self.slider.pack(fill="x", pady=(4, 0))

        presets = ctk.CTkFrame(pacing.body, fg_color="transparent")
        presets.pack(fill="x", pady=(10, 0))
        theme.label(presets, "Presets:", muted=True, size=11).pack(side="left", padx=(0, 8))
        for label, low, high in [("Very safe", 180, 420), ("Balanced", 75, 150),
                                 ("Faster", 45, 90)]:
            theme.secondary_button(presets, label, lambda l=low, h=high: self._set_delay(l, h),
                                   width=100, height=26).pack(side="left", padx=3)

        self.pace_note = theme.label(pacing.body, "", muted=True, size=11)
        self.pace_note.pack(anchor="w", pady=(10, 0))

        # --- window ---------------------------------------------------------
        window = Section(
            scroll, "When to send",
            "Bulk mail arriving at 3am looks automated. Sending inside office hours looks like a "
            "person at a desk.")
        window.pack(fill="x", pady=(0, 14))

        times = ctk.CTkFrame(window.body, fg_color="transparent")
        times.pack(fill="x")
        times.grid_columnconfigure(0, weight=1)
        times.grid_columnconfigure(1, weight=1)
        times.grid_columnconfigure(2, weight=2)

        hours = [f"{h:02d}:00" for h in range(24)]
        start_row = FormRow(times, "Start")
        start_row.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.start_menu = theme.option_menu(start_row.input_area, hours)
        self.start_menu.pack(fill="x")

        end_row = FormRow(times, "End")
        end_row.grid(row=0, column=1, sticky="ew", padx=(0, 10))
        self.end_menu = theme.option_menu(end_row.input_area, hours)
        self.end_menu.pack(fill="x")

        self.weekdays_only = ctk.BooleanVar(value=True)
        theme.checkbox(window.body, "Weekdays only (skip Saturday and Sunday)",
                       variable=self.weekdays_only).pack(anchor="w", pady=(12, 4))

        self.skip_holidays = ctk.BooleanVar(value=True)
        theme.checkbox(window.body, "Skip public holidays", variable=self.skip_holidays).pack(
            anchor="w", pady=(0, 8))

        holiday_wrap = ctk.CTkFrame(window.body, fg_color="transparent")
        holiday_wrap.pack(fill="x")
        theme.label(holiday_wrap, "Public holidays (one date per line, YYYY-MM-DD)",
                    muted=True, size=11).pack(anchor="w")
        self.holidays_box = theme.textbox(holiday_wrap, height=90, monospace=True)
        self.holidays_box.pack(fill="x", pady=(4, 6))
        theme.secondary_button(holiday_wrap, "Load UAE 2026 holidays", self._load_uae_holidays,
                               width=200, height=26).pack(anchor="w")
        theme.label(holiday_wrap,
                    "Islamic holiday dates are approximate and confirmed closer to the time — "
                    "check them against the official UAE calendar.",
                    muted=True, size=11).pack(anchor="w", pady=(4, 0))

        # --- volume ---------------------------------------------------------
        volume = Section(
            scroll, "Daily volume and warm-up",
            "A new domain that suddenly sends hundreds of emails looks compromised. The ramp "
            "raises your limit gradually so receiving servers build trust in you.")
        volume.pack(fill="x", pady=(0, 20))

        self.warmup_enabled = ctk.BooleanVar(value=True)
        theme.checkbox(volume.body, "Use the warm-up ramp (recommended)",
                       variable=self.warmup_enabled, command=self._toggle_warmup).pack(anchor="w")

        self.warmup_status = theme.label(volume.body, "", muted=True)
        self.warmup_status.pack(anchor="w", pady=(8, 0))

        self.schedule_label = theme.label(volume.body, "", muted=True, size=11)
        self.schedule_label.pack(anchor="w", pady=(4, 8))

        self.manual_cap_row = FormRow(volume.body, "Manual daily limit",
                                      "Used when the warm-up ramp is switched off.")
        self.manual_cap_entry = theme.entry(self.manual_cap_row.input_area, "100")
        self.manual_cap_entry.pack(fill="x")

        controls = ctk.CTkFrame(volume.body, fg_color="transparent")
        controls.pack(fill="x", pady=(12, 0))
        theme.secondary_button(controls, "Reset warm-up to day 1", self._reset_warmup,
                               width=190).pack(side="left")
        theme.secondary_button(controls, "Skip ahead a week", self._skip_warmup,
                               width=160).pack(side="left", padx=8)

        theme.label(volume.body,
                    "Only skip ahead if this address has already been sending normal business "
                    "email in volume for a while.", muted=True, size=11).pack(anchor="w", pady=(6, 0))

        bar = ctk.CTkFrame(scroll, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 20))
        theme.primary_button(bar, "Save settings", self.save, width=160).pack(side="left")
        self.save_status = theme.label(bar, "", muted=True)
        self.save_status.pack(side="left", padx=12)

    # --- handlers -----------------------------------------------------------
    def _update_attach_mode(self) -> None:
        mode = self.attach_mode.get()
        self.link_frame.pack_forget()
        self.attach_frame.pack_forget()
        if mode == "link":
            self.link_frame.pack(fill="x")
        elif mode == "attach":
            self.attach_frame.pack(fill="x")

    def _choose_attachment(self) -> None:
        path = filedialog.askopenfilename(
            title="Select your brochure",
            filetypes=[("PDF", "*.pdf"), ("Images", "*.png *.jpg *.jpeg"), ("All files", "*.*")])
        if not path:
            return
        file_path = Path(path)
        size = file_path.stat().st_size
        limit = config.MAX_ATTACHMENT_BYTES

        if size > limit:
            self.attach_label.configure(text=file_path.name, text_color=theme.ERROR)
            self.attach_warning.configure(
                text=f"✕ {size / 1_048_576:.1f} MB — over the {limit // 1_048_576} MB limit. "
                     f"Compress the PDF or switch to a link.",
                text_color=theme.ERROR)
            return

        db.set_setting("attachment_path", str(file_path))
        self.attach_label.configure(text=file_path.name, text_color=theme.FG)
        self.attach_warning.configure(
            text=f"⚠ {size / 1_048_576:.1f} MB. Every recipient receives this file, which raises "
                 f"your spam score on first contact.", text_color=theme.WARNING)

    def _slider_changed(self, low: int, high: int) -> None:
        self._update_pace_note(low, high)
        self.save_status.configure(text="Unsaved changes", text_color=theme.WARNING)

    def _set_delay(self, low: int, high: int) -> None:
        self.slider.set(low, high)
        self._update_pace_note(low, high)

    def _update_pace_note(self, low: int, high: int) -> None:
        average = (low + high) / 2
        per_hour = int(3600 / average) if average else 0
        cap = warmup.effective_cap()
        hours = (cap * average) / 3600 if per_hour else 0
        if low == high:
            warning = "  ⚠ A fixed interval is a bot signature — widen the range."
            color = theme.WARNING
        else:
            warning = ""
            color = theme.FG_MUTED
        self.pace_note.configure(
            text=f"About {per_hour} emails per hour. Today's limit of {cap} would take "
                 f"roughly {hours:.1f} hours.{warning}", text_color=color)

    def _load_uae_holidays(self) -> None:
        text = "\n".join(f"{date}  # {name}" for date, name in UAE_HOLIDAYS_2026)
        self.holidays_box.delete("1.0", "end")
        self.holidays_box.insert("1.0", text)

    def _toggle_warmup(self) -> None:
        if self.warmup_enabled.get():
            self.manual_cap_row.pack_forget()
        else:
            self.manual_cap_row.pack(fill="x", pady=(8, 0))
        db.set_setting("warmup_enabled", self.warmup_enabled.get())
        self._refresh_warmup()

    def _reset_warmup(self) -> None:
        warmup.reset()
        self._refresh_warmup()
        toast(self, "Warm-up reset to day 1", "success")

    def _skip_warmup(self) -> None:
        warmup.set_day(warmup.status().day_index + 7)
        self._refresh_warmup()
        toast(self, "Skipped ahead one week", "success")

    def _refresh_warmup(self) -> None:
        status = warmup.status()
        self.warmup_status.configure(
            text=f"{status.describe()} · {status.remaining} remaining today "
                 f"· provider ceiling {status.provider_limit:,}/day",
            text_color=theme.FG)
        upcoming = warmup.projected_schedule(7)
        self.schedule_label.configure(
            text="Next days: " + "  ".join(f"day {d}: {c}" for d, c in upcoming))
        low, high = self.slider.get()
        self._update_pace_note(low, high)

    # --- persistence --------------------------------------------------------
    def _parse_holidays(self) -> list[str]:
        dates = []
        for line in self.holidays_box.get("1.0", "end").splitlines():
            token = line.split("#")[0].strip()
            if len(token) == 10 and token.count("-") == 2:
                dates.append(token)
        return dates

    def save(self) -> None:
        low, high = self.slider.get()
        db.set_setting("attach_mode", self.attach_mode.get())
        db.set_setting("link_url", self.link_entry.get().strip())
        db.set_setting("link_text", self.link_text_entry.get().strip() or "View our brochure")
        db.set_setting("delay_min_s", low)
        db.set_setting("delay_max_s", high)
        db.set_setting("window_start", self.start_menu.get())
        db.set_setting("window_end", self.end_menu.get())
        db.set_setting("weekdays_only", self.weekdays_only.get())
        db.set_setting("skip_holidays", self.skip_holidays.get())
        db.set_setting("holidays", self._parse_holidays())
        db.set_setting("warmup_enabled", self.warmup_enabled.get())
        try:
            db.set_setting("manual_daily_cap", int(self.manual_cap_entry.get().strip() or 100))
        except ValueError:
            pass

        self.save_status.configure(text="Saved", text_color=theme.SUCCESS)
        toast(self, "Campaign settings saved", "success")
        self._refresh_warmup()

    def load(self) -> None:
        mode = db.get_setting("attach_mode", "link")
        self.attach_mode.set(mode)
        self._update_attach_mode()

        self.link_entry.delete(0, "end")
        self.link_entry.insert(0, db.get_setting("link_url", "") or "")
        self.link_text_entry.delete(0, "end")
        self.link_text_entry.insert(0, db.get_setting("link_text", "View our brochure"))

        attachment = db.get_setting("attachment_path", "")
        if attachment and Path(attachment).exists():
            path = Path(attachment)
            size = path.stat().st_size
            self.attach_label.configure(text=path.name, text_color=theme.FG)
            self.attach_warning.configure(
                text=f"⚠ {size / 1_048_576:.1f} MB attached to every email.",
                text_color=theme.WARNING)

        self.slider.set(int(db.get_setting("delay_min_s", 75)),
                        int(db.get_setting("delay_max_s", 150)))
        self.start_menu.set(db.get_setting("window_start", config.DEFAULT_WINDOW_START))
        self.end_menu.set(db.get_setting("window_end", config.DEFAULT_WINDOW_END))
        self.weekdays_only.set(bool(db.get_setting("weekdays_only", True)))
        self.skip_holidays.set(bool(db.get_setting("skip_holidays", True)))

        holidays = db.get_setting("holidays", [])
        if holidays:
            self.holidays_box.delete("1.0", "end")
            self.holidays_box.insert("1.0", "\n".join(holidays))

        self.warmup_enabled.set(bool(db.get_setting("warmup_enabled", True)))
        self.manual_cap_entry.delete(0, "end")
        self.manual_cap_entry.insert(0, str(db.get_setting("manual_daily_cap", 100)))
        self._toggle_warmup()
        self.save_status.configure(text="")

    def on_show(self) -> None:
        self._refresh_warmup()
