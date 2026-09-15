"""The Windows plumbing a window owes the user once it drops the OS frame.

Dropping the frame is a look decision, made in theme.py and ui.py. Everything
here is the bill that arrives with it: two things Windows did for free and
stops doing the moment the frame is gone.

Nothing in here is imported for its own sake - each function is a no-op off
Windows and a no-op if the call fails, so the app runs unchanged on a machine
that does not have, or does not know about, what it is asking for.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

WM_GETMINMAXINFO = 0x0024

# DwmSetWindowAttribute
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWCP_ROUND = 2

_MONITOR_DEFAULTTONEAREST = 2


class _MINMAXINFO(ctypes.Structure):
    _fields_ = [
        ("ptReserved", wintypes.POINT),
        ("ptMaxSize", wintypes.POINT),
        ("ptMaxPosition", wintypes.POINT),
        ("ptMinTrackSize", wintypes.POINT),
        ("ptMaxTrackSize", wintypes.POINT),
    ]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def round_corners(widget) -> None:
    """Ask Windows to round the corners of a frameless window.

    A window with no frame opts out of the rounding Windows 11 gives every
    other window, which leaves the one app on screen with hard corners against
    a desktop of soft ones. This asks for them back; builds that predate the
    attribute ignore it.
    """
    if os.name != "nt":
        return
    try:
        preference = ctypes.c_int(_DWMWCP_ROUND)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(int(widget.winId())),
            ctypes.c_int(_DWMWA_WINDOW_CORNER_PREFERENCE),
            ctypes.byref(preference),
            ctypes.sizeof(preference),
        )
    except Exception:  # noqa: BLE001 - cosmetic only, never worth failing over
        pass


def clamp_maximised(message) -> bool:
    """Keep a maximised frameless window out from under the taskbar.

    Windows sizes a maximised window to the whole monitor and relies on the
    frame to know better. Without one, "maximise" covers the taskbar and the
    bottom of the app is behind it - and because Aero Snap maximises too,
    dragging to the top of the screen does the same thing.

    Answering WM_GETMINMAXINFO with the monitor's *work* area fixes both at
    once, which is why it is done here rather than by overriding showMaximized:
    a snap never goes through showMaximized.

    Returns whether the message was handled.
    """
    if os.name != "nt":
        return False
    try:
        msg = wintypes.MSG.from_address(int(message))
        if msg.message != WM_GETMINMAXINFO:
            return False

        monitor = ctypes.windll.user32.MonitorFromWindow(
            wintypes.HWND(msg.hWnd), _MONITOR_DEFAULTTONEAREST
        )
        if not monitor:
            return False

        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if not ctypes.windll.user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return False

        work, screen = info.rcWork, info.rcMonitor
        bounds = _MINMAXINFO.from_address(int(msg.lParam))
        # Both are relative to the monitor's own origin, not the desktop's, so
        # a second monitor left of the first does not send the window to -2560.
        bounds.ptMaxPosition.x = work.left - screen.left
        bounds.ptMaxPosition.y = work.top - screen.top
        bounds.ptMaxSize.x = work.right - work.left
        bounds.ptMaxSize.y = work.bottom - work.top
        # Without the track size the user can still drag it larger than this.
        bounds.ptMaxTrackSize.x = bounds.ptMaxSize.x
        bounds.ptMaxTrackSize.y = bounds.ptMaxSize.y
        return True
    except Exception:  # noqa: BLE001 - a wrong guess here must not kill the app
        return False
