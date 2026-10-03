"""Keep the pigeon on the Windows taskbar button.

The first launch after the computer starts is the slow one: Python, Qt and
their libraries all come off a cold disk while antivirus scans each of them.
Explorer asks a new window for its icon with a short time limit, and while the
app is still busy building its first page that request can go unanswered. The
taskbar button then shows a blank icon and never asks again.

Two things close that gap. The pigeon is stored on the window class, which
Explorer reads directly without waiting on the app, and the window icon is sent
again once start-up has settled, which makes Explorer redraw the button.
"""
from __future__ import annotations

import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QWidget

from app import config

GCLP_HICON = -14
GCLP_HICONSM = -34
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
SM_CXICON = 11
SM_CXSMICON = 49

# Loaded once and kept for the life of the process; the class icon points at them
_loaded: list[int] = []


def _is_windows() -> bool:
    return sys.platform == "win32" and QGuiApplication.platformName() == "windows"


def _load_icons() -> list[int]:
    if _loaded:
        return _loaded
    import ctypes
    from ctypes import wintypes

    path = config.resource_path("assets/icon.ico")
    if not path.exists():
        return []
    user32 = ctypes.windll.user32
    user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                                  ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.LoadImageW.restype = wintypes.HANDLE
    for metric in (SM_CXICON, SM_CXSMICON):
        size = user32.GetSystemMetrics(metric)
        handle = user32.LoadImageW(None, str(path), IMAGE_ICON, size, size, LR_LOADFROMFILE)
        if not handle:
            return []
        _loaded.append(handle)
    return _loaded


def _set_class_icon(window: QWidget) -> None:
    import ctypes
    from ctypes import wintypes

    icons = _load_icons()
    if len(icons) != 2:
        return
    user32 = ctypes.windll.user32
    user32.SetClassLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    user32.SetClassLongPtrW.restype = ctypes.c_void_p
    hwnd = int(window.winId())
    user32.SetClassLongPtrW(hwnd, GCLP_HICON, icons[0])
    user32.SetClassLongPtrW(hwnd, GCLP_HICONSM, icons[1])


def _resend_icon(window: QWidget) -> None:
    from PyQt6 import sip

    if sip.isdeleted(window):
        return
    handle = window.windowHandle()
    if handle is not None and not window.windowIcon().isNull():
        # QWindow.setIcon always hands the icon to Windows again, even unchanged
        handle.setIcon(window.windowIcon())


def keep_icon(window: QWidget) -> None:
    """Call once, when the main window is first shown."""
    if not _is_windows():
        return
    try:
        _set_class_icon(window)
    except (AttributeError, OSError, ValueError):
        pass  # cosmetic; never stop the app opening over an icon
    # Once now, and again after the first page and the status bar have loaded
    for delay in (0, 1500, 6000):
        QTimer.singleShot(delay, lambda: _resend_icon(window))
