"""QThread wrappers around the blocking yt-dlp calls in downloader.py.

Nothing here touches widgets; everything comes back to the UI as signals, which
Qt delivers on the main thread.
"""

from __future__ import annotations

import os
import threading

from PyQt6.QtCore import QThread, pyqtSignal

from . import downloader
from .downloader import DownloadCancelled, SpyderError, Preset, VideoInfo


def human_size(num_bytes) -> str:
    """Bytes as a short human string. Shared with the UI, which shows file sizes."""
    if not num_bytes:
        return "?"
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TB"


def _human_eta(seconds) -> str:
    if seconds is None:
        return "--:--"
    seconds = int(seconds)
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


class ProbeWorker(QThread):
    """Fetches title + available quality presets for a URL."""

    succeeded = pyqtSignal(object)  # VideoInfo
    failed = pyqtSignal(str)

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self._url = url

    def run(self) -> None:
        try:
            info: VideoInfo = downloader.probe(self._url)
        except SpyderError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - a crash here must not kill the app
            self.failed.emit(f"Unexpected problem while reading that link: {exc}")
        else:
            self.succeeded.emit(info)


class DownloadWorker(QThread):
    """Runs one download, reporting progress as it goes."""

    # percent (0-100 or -1 when unknown), human-readable detail line
    progress = pyqtSignal(int, str)
    log = pyqtSignal(str)
    succeeded = pyqtSignal(str)  # final file path
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, url: str, preset: Preset, output_dir: str, parent=None):
        super().__init__(parent)
        self._url = url
        self._preset = preset
        self._output_dir = output_dir
        self._cancel = threading.Event()
        self._partials: set[str] = set()

    def cancel(self) -> None:
        """Ask the download to stop. Safe to call from the UI thread."""
        self._cancel.set()

    def _is_cancelled(self) -> bool:
        return self._cancel.is_set()

    def _on_progress(self, status: dict) -> None:
        for key in ("tmpfilename", "filename"):
            path = status.get(key)
            if path:
                self._partials.add(path)

        state = status.get("status")
        if state == "finished":
            self.progress.emit(100, "stream complete")
            return
        if state != "downloading":
            return

        downloaded = status.get("downloaded_bytes") or 0
        total = status.get("total_bytes") or status.get("total_bytes_estimate")
        speed = status.get("speed")
        eta = status.get("eta")

        speed_text = f"{human_size(speed)}/s" if speed else "-- MB/s"

        # Read on one monospace status line, so the parts are separated rather
        # than described.
        if total:
            percent = int(downloaded * 100 / total)
            percent = max(0, min(100, percent))
            detail = (
                f"{human_size(downloaded)} / {human_size(total)}  ·  "
                f"{speed_text}  ·  {_human_eta(eta)} left"
            )
        else:
            percent = -1
            detail = f"{human_size(downloaded)}  ·  {speed_text}"

        self.progress.emit(percent, detail)

    def _cleanup_partials(self) -> None:
        """Remove half-written files so a cancelled download leaves no litter."""
        for path in list(self._partials):
            for candidate in (path, path + ".part"):
                try:
                    if candidate and os.path.isfile(candidate):
                        os.remove(candidate)
                except OSError:
                    # A file still held open by ffmpeg is not worth failing over.
                    pass

    def run(self) -> None:
        try:
            path = downloader.download(
                self._url,
                self._preset,
                self._output_dir,
                on_progress=self._on_progress,
                on_log=self.log.emit,
                is_cancelled=self._is_cancelled,
            )
        except DownloadCancelled:
            self._cleanup_partials()
            self.cancelled.emit()
        except SpyderError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"Unexpected problem during download: {exc}")
        else:
            self.succeeded.emit(path)
