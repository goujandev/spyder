"""Locating the ffmpeg binary.

Spyder ships ffmpeg.exe inside the frozen executable, but it also works from a
source checkout or against a system install, so the lookup tries several places
before giving up.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

FFMPEG_DOWNLOAD_PAGE = "https://www.gyan.dev/ffmpeg/builds/"

_BINARY = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"


def _candidate_dirs() -> list[Path]:
    dirs: list[Path] = []

    # 1. Unpacked alongside the PyInstaller bundle (--add-binary target).
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(Path(meipass))

    # 2. Next to the running .exe / script, so a user can drop ffmpeg.exe in.
    if getattr(sys, "frozen", False):
        dirs.append(Path(sys.executable).parent)
    else:
        project_root = Path(__file__).resolve().parent.parent
        dirs.append(project_root)
        dirs.append(project_root / "vendor")

    return dirs


def find_ffmpeg() -> str | None:
    """Return an absolute path to ffmpeg, or None if it cannot be found."""
    for directory in _candidate_dirs():
        candidate = directory / _BINARY
        if candidate.is_file():
            return str(candidate)

    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path

    return None


def missing_ffmpeg_message() -> str:
    return (
        "ffmpeg was not found, so Spyder cannot merge video and audio or "
        "convert to MP3.\n\n"
        "This build was expected to include ffmpeg. If you unzipped Spyder, "
        "make sure ffmpeg.exe sits in the same folder as Spyder.exe, or "
        f"install ffmpeg from {FFMPEG_DOWNLOAD_PAGE} and add it to your PATH."
    )
