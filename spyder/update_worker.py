"""Background update checks and downloads, with cooperative cancellation."""

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from . import updater


class UpdateWorker(QThread):
    checked = pyqtSignal(object)
    downloaded = pyqtSignal(object)
    progress = pyqtSignal(int, int)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, cache_dir: Path, release: updater.Release | None = None, parent=None):
        super().__init__(parent)
        self.cache_dir = cache_dir
        self.release = release

    def run(self) -> None:
        try:
            if self.release is None:
                release = updater.check_for_update(cancel=self.isInterruptionRequested)
                self.checked.emit(release)
            else:
                update = updater.download_update(
                    self.release, self.cache_dir,
                    progress=self.progress.emit, cancel=self.isInterruptionRequested,
                )
                self.downloaded.emit(update)
        except updater.UpdateCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))
