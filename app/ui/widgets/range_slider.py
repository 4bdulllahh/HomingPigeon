"""Two-handle range slider.

CustomTkinter only ships a single-handle slider, so this is drawn on a canvas.
Values snap to a step table rather than a linear scale: most people want fine
control around 1-5 minutes and coarse control above that, and a linear 15s-60m
slider makes the useful part unusably cramped.
"""
from __future__ import annotations

import customtkinter as ctk

from app import theme


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
    if rest == 0:
        return f"{minutes}m"
    return f"{minutes}m {rest}s"


def nearest_index(seconds: int) -> int:
    best = 0
    smallest = abs(STEPS[0] - seconds)
    for index, value in enumerate(STEPS):
        gap = abs(value - seconds)
        if gap < smallest:
            smallest, best = gap, index
    return best


def _resolve(color) -> str:
    """Pick the light or dark half of a theme token for canvas drawing."""
    if isinstance(color, (tuple, list)):
        return color[1] if ctk.get_appearance_mode() == "Dark" else color[0]
    return color


class RangeSlider(ctk.CTkFrame):
    """Min/max delay selector. Reports values in seconds."""

    HANDLE_RADIUS = 9
    TRACK_HEIGHT = 4
    CANVAS_HEIGHT = 44
    SIDE_PAD = 14

    def __init__(self, master, low: int = 75, high: int = 150, command=None, **kwargs):
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(master, **kwargs)

        self.command = command
        self._low_index = nearest_index(low)
        self._high_index = nearest_index(high)
        if self._low_index > self._high_index:
            self._low_index, self._high_index = self._high_index, self._low_index

        self._dragging: str | None = None
        self._focus_handle = "low"

        self.canvas = ctk.CTkCanvas(
            self, height=self.CANVAS_HEIGHT, highlightthickness=0, bd=0,
            bg=_resolve(theme.BG_PANEL),
        )
        self.canvas.pack(fill="x", expand=True)

        self.readout = theme.label(self, self._readout_text(), size=13)
        self.readout.pack(anchor="w", pady=(2, 0))

        self.canvas.bind("<Configure>", lambda e: self._render())
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Left>", lambda e: self._nudge(-1))
        self.canvas.bind("<Right>", lambda e: self._nudge(1))
        self.canvas.bind("<Tab>", self._switch_handle)
        self.canvas.configure(takefocus=True)

        self.after(50, self._render)

    # -- values --------------------------------------------------------------
    @property
    def low(self) -> int:
        return STEPS[self._low_index]

    @property
    def high(self) -> int:
        return STEPS[self._high_index]

    def get(self) -> tuple[int, int]:
        return self.low, self.high

    def set(self, low: int, high: int) -> None:
        self._low_index = nearest_index(low)
        self._high_index = nearest_index(high)
        if self._low_index > self._high_index:
            self._low_index, self._high_index = self._high_index, self._low_index
        self._render()
        self._update_readout()

    def _readout_text(self) -> str:
        if self.low == self.high:
            return f"Exactly {format_seconds(self.low)} between each email"
        per_hour = int(3600 / ((self.low + self.high) / 2))
        return (f"{format_seconds(self.low)} – {format_seconds(self.high)} between each email"
                f"   ·   roughly {per_hour} per hour")

    def _update_readout(self) -> None:
        self.readout.configure(text=self._readout_text())

    # -- geometry ------------------------------------------------------------
    def _track_bounds(self) -> tuple[int, int]:
        width = self.canvas.winfo_width()
        return self.SIDE_PAD, max(self.SIDE_PAD + 10, width - self.SIDE_PAD)

    def _index_to_x(self, index: int) -> float:
        left, right = self._track_bounds()
        if len(STEPS) <= 1:
            return left
        return left + (right - left) * (index / (len(STEPS) - 1))

    def _x_to_index(self, x: float) -> int:
        left, right = self._track_bounds()
        if right <= left:
            return 0
        ratio = (x - left) / (right - left)
        ratio = max(0.0, min(1.0, ratio))
        return int(round(ratio * (len(STEPS) - 1)))

    # -- drawing -------------------------------------------------------------
    def _render(self) -> None:
        canvas = self.canvas
        canvas.delete("all")
        canvas.configure(bg=_resolve(theme.BG_PANEL))

        left, right = self._track_bounds()
        mid = self.CANVAS_HEIGHT // 2 - 4
        half = self.TRACK_HEIGHT / 2

        canvas.create_rectangle(left, mid - half, right, mid + half,
                                fill=_resolve(theme.BORDER_STRONG), outline="")

        low_x = self._index_to_x(self._low_index)
        high_x = self._index_to_x(self._high_index)
        canvas.create_rectangle(low_x, mid - half, high_x, mid + half,
                                fill=_resolve(theme.ACCENT), outline="")

        for name, x in (("low", low_x), ("high", high_x)):
            focused = self._focus_handle == name and self._dragging == name
            radius = self.HANDLE_RADIUS + (1 if focused else 0)
            canvas.create_oval(
                x - radius, mid - radius, x + radius, mid + radius,
                fill=_resolve(theme.ACCENT if focused else theme.BG_INPUT),
                outline=_resolve(theme.ACCENT), width=2,
            )

        label_y = self.CANVAS_HEIGHT - 8
        font = (theme.mono_family(), 9)
        canvas.create_text(low_x, label_y, text=format_seconds(self.low),
                           fill=_resolve(theme.FG_MUTED), font=font)
        if abs(high_x - low_x) > 46:
            canvas.create_text(high_x, label_y, text=format_seconds(self.high),
                               fill=_resolve(theme.FG_MUTED), font=font)

    def refresh_theme(self) -> None:
        self._render()

    # -- interaction ---------------------------------------------------------
    def _pick_handle(self, x: float) -> str:
        low_x = self._index_to_x(self._low_index)
        high_x = self._index_to_x(self._high_index)
        if abs(x - low_x) == abs(x - high_x):
            # Exactly between (or handles stacked): move whichever direction is free
            return "high" if x > low_x else "low"
        return "low" if abs(x - low_x) < abs(x - high_x) else "high"

    def _on_press(self, event) -> None:
        self.canvas.focus_set()
        self._dragging = self._pick_handle(event.x)
        self._focus_handle = self._dragging
        self._apply_drag(event.x)

    def _on_drag(self, event) -> None:
        if self._dragging:
            self._apply_drag(event.x)

    def _on_release(self, event) -> None:
        self._dragging = None
        self._render()
        self._fire()

    def _apply_drag(self, x: float) -> None:
        index = self._x_to_index(x)
        if self._dragging == "low":
            self._low_index = min(index, self._high_index)
        else:
            self._high_index = max(index, self._low_index)
        self._render()
        self._update_readout()

    def _nudge(self, direction: int) -> None:
        if self._focus_handle == "low":
            self._low_index = max(0, min(self._low_index + direction, self._high_index))
        else:
            self._high_index = min(len(STEPS) - 1, max(self._high_index + direction, self._low_index))
        self._render()
        self._update_readout()
        self._fire()

    def _switch_handle(self, event):
        self._focus_handle = "high" if self._focus_handle == "low" else "low"
        self._render()
        return "break"

    def _fire(self) -> None:
        if self.command:
            self.command(self.low, self.high)
