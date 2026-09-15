"""Spyder entry point."""

from __future__ import annotations

import os
import subprocess
import sys


def _silence_child_console_windows() -> None:
    """Stop ffmpeg from flashing a console window on Windows.

    The frozen build is windowed, so any child process yt-dlp launches would
    otherwise pop up its own console. Injecting CREATE_NO_WINDOW into every
    Popen call is the reliable way to suppress that regardless of how yt-dlp
    spawns ffmpeg.
    """
    if os.name != "nt":
        return

    create_no_window = 0x08000000
    original_popen = subprocess.Popen

    class _QuietPopen(original_popen):  # type: ignore[misc, valid-type]
        def __init__(self, *args, **kwargs):
            kwargs["creationflags"] = kwargs.get("creationflags", 0) | create_no_window
            super().__init__(*args, **kwargs)

    subprocess.Popen = _QuietPopen  # type: ignore[assignment]


def _set_windows_app_id() -> None:
    """Give Windows an explicit app identity.

    Without this the taskbar groups the app under the host interpreter and shows
    its icon instead of ours, which is very visible when running from source.
    """
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Spyder.App")
    except Exception:  # noqa: BLE001 - cosmetic only, never worth failing over
        pass


def main() -> int:
    _silence_child_console_windows()
    _set_windows_app_id()

    # Imported after the patch above so yt-dlp picks up the patched Popen.
    from PyQt6.QtWidgets import QApplication

    from . import APP_NAME, ORG_NAME, theme
    from .ui import MainWindow, app_icon

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setWindowIcon(app_icon())
    # Fonts, palette and style sheet, before any widget is built.
    theme.apply(app)

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
