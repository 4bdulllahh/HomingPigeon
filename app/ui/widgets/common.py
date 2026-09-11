"""Small shared widgets: toasts, status rows, stat tiles, tables, dialogs."""
from __future__ import annotations

import tkinter as tk
import webbrowser
from typing import Callable

import customtkinter as ctk

from app import theme


# --- Toast ------------------------------------------------------------------
class Toast(ctk.CTkFrame):
    """Transient message in the bottom-right corner."""

    def __init__(self, master, message: str, level: str = "info", duration: int = 4000):
        colors = {"success": theme.SUCCESS, "error": theme.ERROR,
                  "warn": theme.WARNING, "info": theme.ACCENT}
        accent = colors.get(level, theme.ACCENT)
        super().__init__(master, fg_color=theme.BG_PANEL, border_color=accent,
                         border_width=1, corner_radius=theme.RADIUS)

        bar = ctk.CTkFrame(self, fg_color=accent, width=3, height=1, corner_radius=0)
        bar.pack(side="left", fill="y")
        label = ctk.CTkLabel(self, text=message, font=theme.font(12), text_color=theme.FG,
                             wraplength=340, justify="left", anchor="w")
        label.pack(side="left", padx=10, pady=8)

        self.place(relx=0.98, rely=0.96, anchor="se")
        self.after(duration, self.destroy)


def toast(widget, message: str, level: str = "info", duration: int = 4000) -> None:
    root = widget.winfo_toplevel()
    Toast(root, message, level, duration)


# --- Status row -------------------------------------------------------------
class StatusRow(ctk.CTkFrame):
    """One pass/warn/fail line with an optional expandable detail area."""

    def __init__(self, master, title: str, status: str = "pending", summary: str = "",
                 detail: str = "", record: str = "", fix: str = "", extras: list[str] | None = None,
                 on_copy: Callable[[str], None] | None = None):
        super().__init__(master, fg_color="transparent")
        self._expanded = False
        self._on_copy = on_copy
        self.record = record

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x")

        icon = theme.STATUS_ICONS.get(status, "○")
        self.icon_label = ctk.CTkLabel(header, text=icon, font=theme.font(15, "bold"),
                                       text_color=theme.status_color(status), width=24)
        self.icon_label.pack(side="left", padx=(0, 6))

        text_wrap = ctk.CTkFrame(header, fg_color="transparent")
        text_wrap.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(text_wrap, text=title, font=theme.font(13, "bold"),
                     text_color=theme.FG_BRIGHT, anchor="w").pack(anchor="w")
        ctk.CTkLabel(text_wrap, text=summary, font=theme.font(12), text_color=theme.FG_MUTED,
                     anchor="w", justify="left", wraplength=620).pack(anchor="w")

        has_detail = bool(detail or record or fix or extras)
        if has_detail:
            self.toggle = theme.secondary_button(header, "Details", self._toggle, width=78, height=26)
            self.toggle.pack(side="right", padx=(8, 0))

        self.body = ctk.CTkFrame(self, fg_color=theme.BG_PANEL, corner_radius=theme.RADIUS)
        self._build_body(detail, record, fix, extras or [])

        theme.separator(self).pack(fill="x", pady=(10, 10))

    def _build_body(self, detail: str, record: str, fix: str, extras: list[str]) -> None:
        pad = {"padx": 12, "pady": (8, 0)}
        if detail:
            ctk.CTkLabel(self.body, text=detail, font=theme.font(12), text_color=theme.FG,
                         wraplength=640, justify="left", anchor="w").pack(anchor="w", **pad)
        for extra in extras:
            ctk.CTkLabel(self.body, text=f"• {extra}", font=theme.font(12),
                         text_color=theme.FG_MUTED, anchor="w").pack(anchor="w", padx=12, pady=1)
        if record:
            box = ctk.CTkTextbox(self.body, height=min(120, 22 + 16 * record.count("\n")),
                                 font=theme.mono(11), fg_color=theme.BG_INPUT,
                                 text_color=theme.CODE_STRING, wrap="word",
                                 border_width=1, border_color=theme.BORDER)
            box.pack(fill="x", padx=12, pady=(8, 0))
            box.insert("1.0", record)
            box.configure(state="disabled")
            theme.secondary_button(self.body, "Copy record", lambda: self._copy(record),
                                   width=110, height=26).pack(anchor="w", padx=12, pady=(6, 0))
        if fix:
            frame = ctk.CTkFrame(self.body, fg_color="transparent")
            frame.pack(fill="x", padx=12, pady=(8, 0))
            ctk.CTkLabel(frame, text="How to fix:", font=theme.font(12, "bold"),
                         text_color=theme.WARNING, anchor="w").pack(anchor="w")
            ctk.CTkLabel(frame, text=fix, font=theme.font(12), text_color=theme.FG,
                         wraplength=620, justify="left", anchor="w").pack(anchor="w")
        ctk.CTkFrame(self.body, fg_color="transparent", height=8).pack()

    def _copy(self, text: str) -> None:
        copy_to_clipboard(self, text)
        toast(self, "Copied to clipboard", "success", 2000)

    def _toggle(self) -> None:
        if self._expanded:
            self.body.pack_forget()
            self.toggle.configure(text="Details")
        else:
            self.body.pack(fill="x", pady=(8, 0))
            self.toggle.configure(text="Hide")
        self._expanded = not self._expanded


# --- Stat tile --------------------------------------------------------------
class StatTile(ctk.CTkFrame):
    def __init__(self, master, label: str, value: str = "—", hint: str = "", accent=None):
        super().__init__(master, fg_color=theme.BG_PANEL, corner_radius=theme.RADIUS_CARD,
                         border_width=1, border_color=theme.BORDER)
        self.value_label = ctk.CTkLabel(self, text=value, font=theme.font(26, "bold"),
                                        text_color=accent or theme.FG_BRIGHT, anchor="w")
        self.value_label.pack(anchor="w", padx=16, pady=(14, 0))
        ctk.CTkLabel(self, text=label, font=theme.font(12), text_color=theme.FG_MUTED,
                     anchor="w").pack(anchor="w", padx=16, pady=(0, 2))
        self.hint_label = ctk.CTkLabel(self, text=hint, font=theme.font(11),
                                       text_color=theme.FG_MUTED, anchor="w")
        self.hint_label.pack(anchor="w", padx=16, pady=(0, 12))

    def update_value(self, value: str, hint: str = "", accent=None) -> None:
        self.value_label.configure(text=value)
        if accent:
            self.value_label.configure(text_color=accent)
        self.hint_label.configure(text=hint)


# --- Simple table -----------------------------------------------------------
class DataTable(ctk.CTkFrame):
    """Lightweight scrollable table. tkinter's Treeview cannot be themed to match."""

    def __init__(self, master, columns: list[tuple[str, int]], height: int = 320):
        super().__init__(master, fg_color=theme.BG_PANEL, corner_radius=theme.RADIUS,
                         border_width=1, border_color=theme.BORDER)
        self.columns = columns

        header = ctk.CTkFrame(self, fg_color=theme.BG_SIDEBAR, corner_radius=0, height=32)
        header.pack(fill="x")
        header.pack_propagate(False)
        for title, width in columns:
            ctk.CTkLabel(header, text=title, font=theme.font(12, "bold"),
                         text_color=theme.FG_MUTED, width=width, anchor="w").pack(
                side="left", padx=(10, 0), pady=6)

        self.rows_frame = theme.scroll_frame(self, height=height)
        self.rows_frame.pack(fill="both", expand=True, padx=1, pady=1)
        self._row_widgets: list[ctk.CTkFrame] = []

    def clear(self) -> None:
        for widget in self._row_widgets:
            widget.destroy()
        self._row_widgets.clear()

    def add_row(self, values: list[str], colors: list | None = None,
                on_click: Callable | None = None) -> None:
        index = len(self._row_widgets)
        background = theme.BG_PANEL if index % 2 == 0 else theme.BG_HOVER
        row = ctk.CTkFrame(self.rows_frame, fg_color=background, corner_radius=0, height=28)
        row.pack(fill="x")
        row.pack_propagate(False)

        for position, (title, width) in enumerate(self.columns):
            text = values[position] if position < len(values) else ""
            color = colors[position] if colors and position < len(colors) and colors[position] \
                else theme.FG
            ctk.CTkLabel(row, text=str(text)[:200], font=theme.font(12), text_color=color,
                         width=width, anchor="w").pack(side="left", padx=(10, 0))

        if on_click:
            for widget in [row] + list(row.winfo_children()):
                widget.bind("<Button-1>", lambda e, cb=on_click: cb())
                widget.configure(cursor="hand2")
        self._row_widgets.append(row)

    def set_empty_message(self, message: str) -> None:
        self.clear()
        frame = ctk.CTkFrame(self.rows_frame, fg_color="transparent")
        frame.pack(fill="both", expand=True, pady=30)
        ctk.CTkLabel(frame, text=message, font=theme.font(13), text_color=theme.FG_MUTED).pack()
        self._row_widgets.append(frame)


# --- Section ----------------------------------------------------------------
class Section(ctk.CTkFrame):
    """A titled card that page content goes into via .body."""

    def __init__(self, master, title: str, description: str = ""):
        super().__init__(master, fg_color=theme.BG_PANEL, corner_radius=theme.RADIUS_CARD,
                         border_width=1, border_color=theme.BORDER)
        ctk.CTkLabel(self, text=title, font=theme.font(15, "bold"), text_color=theme.FG_BRIGHT,
                     anchor="w").pack(anchor="w", padx=18, pady=(16, 0))
        if description:
            desc = ctk.CTkLabel(self, text=description, font=theme.font(12),
                                text_color=theme.FG_MUTED, anchor="w", justify="left",
                                wraplength=760)
            desc.pack(anchor="w", padx=18, pady=(2, 0))
            theme.auto_wrap(desc, self, padding=48)
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=18, pady=(12, 16))


class FormRow(ctk.CTkFrame):
    """Label above an input, with an optional hint underneath."""

    def __init__(self, master, label: str, hint: str = ""):
        super().__init__(master, fg_color="transparent")
        ctk.CTkLabel(self, text=label, font=theme.font(12, "bold"), text_color=theme.FG,
                     anchor="w").pack(anchor="w")
        self.input_area = ctk.CTkFrame(self, fg_color="transparent")
        self.input_area.pack(fill="x", pady=(4, 0))
        if hint:
            ctk.CTkLabel(self, text=hint, font=theme.font(11), text_color=theme.FG_MUTED,
                         anchor="w", justify="left", wraplength=560).pack(anchor="w", pady=(3, 0))


# --- Confirm dialog ---------------------------------------------------------
class ConfirmDialog(ctk.CTkToplevel):
    def __init__(self, master, title: str, message: str, confirm_text: str = "Continue",
                 cancel_text: str = "Cancel", danger: bool = False):
        super().__init__(master)
        self.result = False
        self.title(title)
        self.configure(fg_color=theme.BG[1] if ctk.get_appearance_mode() == "Dark" else theme.BG[0])
        self.resizable(False, False)
        self.transient(master)

        wrapper = ctk.CTkFrame(self, fg_color="transparent")
        wrapper.pack(fill="both", expand=True, padx=24, pady=20)
        ctk.CTkLabel(wrapper, text=title, font=theme.font(16, "bold"),
                     text_color=theme.FG_BRIGHT, anchor="w").pack(anchor="w")
        ctk.CTkLabel(wrapper, text=message, font=theme.font(13), text_color=theme.FG,
                     wraplength=460, justify="left", anchor="w").pack(anchor="w", pady=(10, 18))

        buttons = ctk.CTkFrame(wrapper, fg_color="transparent")
        buttons.pack(fill="x")
        theme.secondary_button(buttons, cancel_text, self._cancel, width=110).pack(side="right")
        maker = theme.danger_button if danger else theme.primary_button
        maker(buttons, confirm_text, self._confirm, width=140).pack(side="right", padx=(0, 8))

        self.update_idletasks()
        self._centre(master)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)

    def _centre(self, master) -> None:
        width, height = self.winfo_width(), self.winfo_height()
        x = master.winfo_rootx() + (master.winfo_width() - width) // 2
        y = master.winfo_rooty() + (master.winfo_height() - height) // 3
        self.geometry(f"+{max(0, x)}+{max(0, y)}")

    def _confirm(self) -> None:
        self.result = True
        self.grab_release()
        self.destroy()

    def _cancel(self) -> None:
        self.result = False
        self.grab_release()
        self.destroy()

    @classmethod
    def ask(cls, master, title: str, message: str, confirm_text: str = "Continue",
            danger: bool = False) -> bool:
        dialog = cls(master, title, message, confirm_text, danger=danger)
        master.wait_window(dialog)
        return dialog.result


# --- Helpers ----------------------------------------------------------------
def copy_to_clipboard(widget, text: str) -> None:
    root = widget.winfo_toplevel()
    root.clipboard_clear()
    root.clipboard_append(text)
    root.update()


def open_url(url: str) -> None:
    webbrowser.open(url)


def set_text(textbox: ctk.CTkTextbox, text: str, readonly: bool = False) -> None:
    textbox.configure(state="normal")
    textbox.delete("1.0", "end")
    textbox.insert("1.0", text)
    if readonly:
        textbox.configure(state="disabled")


def get_text(textbox: ctk.CTkTextbox) -> str:
    return textbox.get("1.0", "end").rstrip("\n")
