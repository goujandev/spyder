"""The Spyder main window.

The window draws its own frame. A title strip flush to the top carries the app
mark, what is being downloaded, and the three window controls; everything else
sits in one rounded canvas inset from the edges, on the dot texture. Nothing on
screen is drawn by the OS.

The window owns the widgets and the two workers; all blocking work lives in
worker.py, so every method here returns immediately.
"""

from __future__ import annotations

import html
import os
import subprocess
from pathlib import Path

from PyQt6.QtCore import QSettings, QSize, QStandardPaths, Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import APP_NAME, ORG_NAME, __version__, downloader, platforms, theme, updater, win32
from .ffmpeg_tools import find_ffmpeg
from .resources import WINDOW_ICON, WINDOW_LOGO, resource_path
from .widgets import (
    BlockDialog,
    BlockSelect,
    DotCanvas,
    EdgeResizer,
    ElidedLabel,
    IconButton,
    IconLabel,
    Omnibox,
    TitleBar,
    WindowControls,
    action_button,
    section_label,
)
from .worker import DownloadWorker, ProbeWorker, human_size
from .update_worker import UpdateWorker

IDLE_TITLE = "New download"
MARK_SIZE = 18
RESULT_HEIGHT = 40
TASKBAR_FLASH_MS = 3000

# How long a finished-looking link sits still before Spyder reads it by itself.
# Long enough that a link typed by hand settles first, short enough that a
# paste feels understood rather than processed.
AUTO_FETCH_MS = 500

# Log tags are a fixed-width first column; the colour carries the severity.
LOG_TAG_WIDTH = 7
LOG_TONES = {"warn": theme.BLOCKED, "error": theme.DANGER, "ok": theme.READY}


def app_icon() -> QIcon:
    """The Spyder mark, from the built icon or the source logo beside it."""
    for name in (WINDOW_ICON, WINDOW_LOGO):
        path = resource_path(name)
        if path:
            return QIcon(path)
    return QIcon()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.setMinimumSize(660, 620)
        self.resize(760, 680)

        # An OS frame above a carefully made app looks like a web page in a
        # picture frame. Dropping it means owing the user drag, double-click to
        # maximise and edge resize; TitleBar and EdgeResizer give those back.
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)

        self._settings = QSettings(ORG_NAME, APP_NAME)
        self._probe_worker: ProbeWorker | None = None
        self._download_worker: DownloadWorker | None = None
        self._update_worker: UpdateWorker | None = None
        self._update_outcome: tuple | None = None
        self._close_after_update = False
        self._presets: list = []
        self._output_presets: list = []
        self._video_presets: list = []
        self._probing_url = ""
        self._probed_url = ""
        self._corners_done = False
        self._auto_probe = False
        self._impersonation_warned = False

        # Pasting a link is the whole gesture; making the user press Fetch
        # afterwards asks again for a decision they have already made.
        self._auto_fetch = QTimer(self)
        self._auto_fetch.setSingleShot(True)
        self._auto_fetch.setInterval(AUTO_FETCH_MS)
        self._auto_fetch.timeout.connect(self.on_auto_fetch)

        self._build_ui()
        EdgeResizer(self)
        self._restore_output_dir()
        self._check_ffmpeg()
        self._update_buttons()

    # ---------------------------------------------------------------- layout

    def _build_ui(self) -> None:
        shell = QWidget()
        shell.setObjectName("shell")
        stack = QVBoxLayout(shell)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(0)
        stack.addWidget(self._build_head())

        # The strip stays flush because the close button has to reach the
        # corner. The canvas does not, because nothing in it does.
        body = QWidget()
        body.setObjectName("shell")
        inset = QVBoxLayout(body)
        inset.setContentsMargins(
            theme.CANVAS_INSET, 0, theme.CANVAS_INSET, theme.CANVAS_INSET
        )
        inset.addWidget(self._build_canvas())
        stack.addWidget(body, 1)

        self.setCentralWidget(shell)

    def _build_head(self) -> QWidget:
        """The title strip: what this is, what it is doing, and the controls."""
        head = TitleBar()
        head.doubleClicked.connect(self._toggle_maximised)

        row = QHBoxLayout(head)
        row.setContentsMargins(13, 0, 0, 0)
        row.setSpacing(9)

        mark = QLabel()
        mark.setObjectName("headMark")
        path = resource_path(WINDOW_LOGO) or resource_path(WINDOW_ICON)
        if path:
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                mark.setPixmap(
                    pixmap.scaled(
                        QSize(MARK_SIZE, MARK_SIZE),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        row.addWidget(mark)

        name = QLabel(APP_NAME)
        name.setObjectName("headTitle")
        name.setFont(theme.title_font())
        row.addWidget(name)

        # What is being downloaded, in the one place always on screen.
        self.head_sub = ElidedLabel("headSub")
        row.addWidget(self.head_sub, 1)

        row.addWidget(WindowControls(self))
        self._head = head
        return head

    def _build_canvas(self) -> QWidget:
        canvas = DotCanvas()
        column = QVBoxLayout(canvas)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self._build_toolbar())
        column.addWidget(self._build_page(), 1)
        self._canvas = canvas
        return canvas

    def _build_toolbar(self) -> QWidget:
        toolbar = QWidget()
        toolbar.setObjectName("toolbar")
        column = QVBoxLayout(toolbar)
        column.setContentsMargins(16, 16, 16, 0)
        column.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.omnibox = Omnibox("Paste a video or audio link")
        self.url_edit = self.omnibox.edit
        self.url_edit.returnPressed.connect(self.on_fetch)
        self.url_edit.textChanged.connect(self.on_url_changed)
        self.fetch_button = action_button("Fetch")
        self.fetch_button.setMinimumWidth(96)
        self.fetch_button.setFixedHeight(theme.ROW_HEIGHT + 8)
        self.fetch_button.clicked.connect(self.on_fetch)
        row.addWidget(self.omnibox, 1)
        row.addWidget(self.fetch_button)
        column.addLayout(row)

        self.source_help = QLabel(
            "Video links: YouTube, TikTok, Reddit, Pinterest and more.\n"
            "Single posts or pins; no photos, galleries, boards or playlists."
        )
        self.source_help.setObjectName("detailText")
        self.source_help.setWordWrap(True)
        self.source_help.setToolTip(
            "Examples: reddit.com/r/.../comments/... or pinterest.com/pin/...\n"
            "redd.it and pin.it links must resolve to a supported single video.\n"
            "Whole accounts are not supported. Availability depends on the source."
        )
        column.addWidget(self.source_help)

        # Length and uploader, once a link has been read. Hidden until then:
        # an empty row would be a label for something that does not exist.
        self.media_title = ElidedLabel("mediaTitle")
        self.media_title.setVisible(False)
        column.addWidget(self.media_title)
        self.detail_label = ElidedLabel("detailText")
        self.detail_label.setObjectName("detailText")
        self.detail_label.setVisible(False)
        column.addWidget(self.detail_label)

        self._toolbar = toolbar
        return toolbar

    def _build_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("page")
        column = QVBoxLayout(page)
        column.setContentsMargins(16, 16, 16, 16)
        column.setSpacing(0)

        choices = QHBoxLayout()
        choices.setSpacing(12)
        output_column = QVBoxLayout()
        output_column.setSpacing(7)
        output_column.addWidget(section_label("Output"))
        self.output_select = BlockSelect("Fetch a link first")
        self.output_select.currentIndexChanged.connect(self.on_output_changed)
        output_column.addWidget(self.output_select)
        quality_column = QVBoxLayout()
        quality_column.setSpacing(7)
        quality_column.addWidget(section_label("Video quality"))
        self.quality_select = BlockSelect("Not applicable")
        quality_column.addWidget(self.quality_select)
        choices.addLayout(output_column, 1)
        choices.addLayout(quality_column, 1)
        column.addLayout(choices)
        column.addSpacing(8)
        self.selection_help = QLabel("Paste a link above to discover available video and audio outputs.")
        self.selection_help.setObjectName("detailText")
        self.selection_help.setWordWrap(True)
        column.addWidget(self.selection_help)

        column.addSpacing(16)
        column.addWidget(section_label("Save to"))
        column.addSpacing(7)
        folder_row = QHBoxLayout()
        folder_row.setSpacing(8)
        self.folder_edit = QLineEdit()
        self.folder_edit.setObjectName("field")
        self.folder_edit.setReadOnly(True)
        self.folder_edit.setFixedHeight(theme.ROW_HEIGHT)
        self.browse_button = IconButton("folder", "Choose a folder")
        self.browse_button.clicked.connect(self.on_browse)
        self.open_folder_button = IconButton("external", "Open the folder")
        self.open_folder_button.clicked.connect(self.on_open_folder)
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(self.browse_button)
        folder_row.addWidget(self.open_folder_button)
        column.addLayout(folder_row)

        column.addSpacing(18)
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.download_button = action_button("Download", "primary")
        self.download_button.clicked.connect(self.on_download)
        self.cancel_button = action_button("Cancel", "danger")
        self.cancel_button.clicked.connect(self.on_cancel)
        action_row.addWidget(self.download_button)
        action_row.addWidget(self.cancel_button)
        action_row.addStretch(1)
        column.addLayout(action_row)

        column.addSpacing(16)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(6)
        # The numbers live in the status line below, in monospace.
        self.progress_bar.setTextVisible(False)
        column.addWidget(self.progress_bar)
        column.addWidget(self._build_result())

        column.addSpacing(10)
        self.status_label = QLabel("ready")
        self.status_label.setObjectName("status")
        self.status_label.setWordWrap(True)
        column.addWidget(self.status_label)

        column.addSpacing(16)
        column.addWidget(section_label("Log"))
        column.addSpacing(7)
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("log")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(500)
        self.log_view.setFrameShape(QFrame.Shape.NoFrame)
        column.addWidget(self.log_view, 1)

        column.addSpacing(10)
        update_row = QHBoxLayout()
        version_label = QLabel(f"Spyder {__version__}")
        version_label.setObjectName("detailText")
        update_row.addWidget(version_label)
        update_row.addStretch(1)
        self.update_button = action_button("Check for updates")
        self.update_button.clicked.connect(self.on_check_updates)
        update_row.addWidget(self.update_button)
        column.addLayout(update_row)

        self._page = page
        return page

    def _build_result(self) -> QWidget:
        """The finished file. Hidden until there is one, and it replaces the bar."""
        result = QFrame()
        result.setObjectName("result")
        result.setFixedHeight(RESULT_HEIGHT)
        result.setVisible(False)

        row = QHBoxLayout(result)
        row.setContentsMargins(0, 0, 6, 0)
        row.setSpacing(0)
        row.addWidget(IconLabel("check", "resultIcon", colour=theme.READY))

        self.result_name = ElidedLabel("resultName")
        row.addWidget(self.result_name, 1)

        self.result_size = QLabel("")
        self.result_size.setObjectName("resultSize")
        row.addWidget(self.result_size)

        self.reveal_button = QPushButton("Show in folder")
        self.reveal_button.setObjectName("reveal")
        self.reveal_button.setFixedHeight(26)
        self.reveal_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reveal_button.clicked.connect(self.on_reveal)
        row.addWidget(self.reveal_button)

        self._result = result
        self._result_path = ""
        return result

    def _show_result(self, path: str) -> None:
        self._result_path = path
        self.result_name.set_full_text(os.path.basename(path))
        try:
            self.result_size.setText(human_size(os.path.getsize(path)))
        except OSError:
            self.result_size.setText("")
        self.progress_bar.setVisible(False)
        self._result.setVisible(True)

    def _clear_result(self) -> None:
        """Back to the in-flight view: the bar returns, the finished file goes."""
        self._result_path = ""
        self._result.setVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)

    def _toggle_maximised(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().showEvent(event)
        if not self._corners_done:
            self._corners_done = True
            win32.round_corners(self)

    def nativeEvent(self, event_type, message):  # noqa: N802 - Qt naming
        """Answer the one Windows message a frameless window has to answer.

        Maximising or snapping would otherwise run the window under the
        taskbar; win32.clamp_maximised decides how big "maximised" is.

        Everything else is declined with (False, 0), which is what the base
        class does. It is spelled out rather than delegated because calling
        QWidget.nativeEvent through super() crashes PyQt6 outright.
        """
        if event_type == b"windows_generic_MSG" and win32.clamp_maximised(message):
            return True, 0
        return False, 0

    # ------------------------------------------------------------- utilities

    def log(self, message: str, tag: str = "log") -> None:
        """Append one line: a fixed-width tag, then the fact."""
        colour = LOG_TONES.get(tag, theme.MUTED)
        # Escaped first, then the tag's padding is made non-breaking so the
        # column survives HTML whitespace collapsing.
        padded = html.escape(tag[:LOG_TAG_WIDTH].ljust(LOG_TAG_WIDTH))
        padded = padded.replace(" ", "&#160;")
        self.log_view.appendHtml(
            f'<span style="color:{colour};">{padded}</span>'
            f'<span style="color:{theme.TEXT};">{html.escape(message)}</span>'
        )

    def set_status(self, message: str) -> None:
        self.status_label.setText(message)

    def set_head_title(self, title: str) -> None:
        """What is being downloaded, beside the app name in the title strip."""
        self.head_sub.set_full_text("" if title == IDLE_TITLE else f"\u00b7  {title}")

    def _dialog(
        self,
        tone: str,
        heading: str,
        message: str,
        buttons: list[tuple[str, str]],
        escape_index: int = 0,
    ) -> int:
        """A modal panel over the page. Blocks until a button is pressed."""
        dialog = BlockDialog(self._canvas, tone, heading, message, buttons, escape_index)
        result = dialog.exec()
        # Worker signals can land while the dialog holds a nested event loop,
        # so re-derive every enabled state once it closes.
        self._update_buttons()
        return result

    def _notice(self, tone: str, heading: str, message: str) -> None:
        self._dialog(tone, heading, message, [("Dismiss", "")])

    def _busy(self) -> bool:
        return (
            self._download_worker is not None
            or self._probe_worker is not None
            or self._update_worker is not None
        )

    def _update_buttons(self) -> None:
        downloading = self._download_worker is not None
        probing = self._probe_worker is not None
        busy = self._busy()

        self.omnibox.setEnabled(not busy)
        self.fetch_button.setEnabled(not busy and bool(self.url_edit.text().strip()))
        self.output_select.setEnabled(not busy and bool(self._output_presets))
        selected = self._selected_preset()
        self.quality_select.setEnabled(not busy and selected is not None and not selected.audio_only)
        if busy:
            self.output_select.close_popup()
            self.quality_select.close_popup()
        self.browse_button.setEnabled(not downloading)
        self.download_button.setEnabled(
            not busy and selected is not None and bool(self.folder_edit.text())
        )
        updating = self._update_worker is not None
        self.cancel_button.setEnabled(downloading or updating)
        self.update_button.setEnabled(not busy)
        self.update_button.setText(
            ("Checking..." if self._update_worker.release is None else "Downloading update...")
            if updating else "Check for updates"
        )
        self.open_folder_button.setEnabled(bool(self.folder_edit.text()))
        self.fetch_button.setText("Fetching" if probing else "Fetch")

    def _restore_output_dir(self) -> None:
        saved = self._settings.value("output_dir", "", type=str)
        if saved and os.path.isdir(saved):
            self._set_output_dir(saved)
            return
        downloads = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DownloadLocation
        )
        if downloads and os.path.isdir(downloads):
            self._set_output_dir(downloads)

    def _set_output_dir(self, path: str) -> None:
        # Qt hands back forward slashes; a path is technical text and should
        # read the way Windows writes it.
        self.folder_edit.setText(os.path.normpath(path))
        # Long paths otherwise show their tail; the drive matters more.
        self.folder_edit.setCursorPosition(0)

    def _check_ffmpeg(self) -> None:
        if find_ffmpeg():
            return
        self.log("ffmpeg not found - merging and audio conversion will fail", "warn")

    def _check_impersonation(self, platform) -> None:
        """Warn once when a link needs something this build cannot do.

        Said before the fetch rather than after it fails, so the reason
        arrives ahead of the error it would otherwise have to explain. The
        first answer costs ~100ms, which is why it is asked here and not on
        every keystroke.
        """
        if self._impersonation_warned or not platform.needs_impersonation:
            return
        if downloader.impersonation_available():
            return
        self._impersonation_warned = True
        self.log(downloader.IMPERSONATION_HINT, "warn")

    # --------------------------------------------------------------- updates

    def on_check_updates(self) -> None:
        if self._busy():
            return
        self._auto_fetch.stop()
        self.log("checking GitHub releases", "update")
        self.set_status("checking for updates")
        self._start_update_worker()

    def _start_update_worker(self, release: updater.Release | None = None) -> None:
        cache = Path(QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.CacheLocation
        )) / "updates"
        worker = UpdateWorker(cache, release, self)
        self._update_outcome = None
        worker.checked.connect(lambda result: self._record_update("checked", result))
        worker.downloaded.connect(lambda result: self._record_update("downloaded", result))
        worker.failed.connect(lambda message: self._record_update("failed", message))
        worker.cancelled.connect(lambda: self._record_update("cancelled", None))
        worker.progress.connect(self.on_update_progress)
        worker.finished.connect(self.on_update_finished)
        self._update_worker = worker
        worker.start()
        self._update_buttons()

    def _record_update(self, kind: str, result) -> None:
        # Present results only after finished: no worker is destroyed or left
        # running while setup replaces files or a modal panel starts a new job.
        self._update_outcome = (kind, result)

    def on_update_progress(self, done: int, total: int) -> None:
        percent = int(done * 100 / total)
        self.progress_bar.setValue(percent)
        self.set_status(f"update {percent}%  {human_size(done)} / {human_size(total)}")

    def on_update_finished(self) -> None:
        worker = self._update_worker
        self._update_worker = None
        if worker is not None:
            worker.deleteLater()
        outcome = self._update_outcome
        self._update_outcome = None
        self._update_buttons()
        if self._close_after_update:
            self.close()
            return
        if outcome is None:
            return
        kind, result = outcome
        if kind == "cancelled":
            self.progress_bar.setValue(0)
            self.set_status("update cancelled")
            self.log("update cancelled", "cancel")
        elif kind == "failed":
            self.progress_bar.setValue(0)
            self.set_status("update failed")
            self.log(result, "error")
            self._notice("warning", "update", result)
        elif kind == "checked":
            self._present_update(result)
        elif kind == "downloaded":
            self._install_update(result)

    def _present_update(self, release: updater.Release | None) -> None:
        if release is None:
            self.set_status("up to date")
            self.log(f"Spyder {__version__} is up to date", "ok")
            self._notice("info", "up to date", f"You are using Spyder {__version__}, the latest stable version.")
            return
        self.set_status(f"Spyder {release.version} available")
        self.log(f"Spyder {release.version} available", "update")
        if updater.installation_directory() is None:
            answer = self._dialog(
                "ask", "update available",
                f"Spyder {release.version} is available. In-app installation requires an "
                "installed Windows copy of Spyder. Download and run the setup file from GitHub.",
                [("Later", ""), ("Open release", "primary")],
            )
            if answer == 1:
                QDesktopServices.openUrl(QUrl(updater.RELEASES_URL))
            return
        answer = self._dialog(
            "ask", "update available",
            f"Update Spyder {__version__} to {release.version}? The download is "
            f"{human_size(release.size)}. Spyder will close after the download, "
            "install the update, and restart. Your settings and downloads will be kept.",
            [("Later", ""), ("Update and restart", "primary")],
        )
        if answer != 1:
            return
        self._clear_result()
        self.set_status("downloading update")
        self._start_update_worker(release)

    def _install_update(self, update: updater.PreparedUpdate) -> None:
        try:
            updater.launch_installer(update)
        except updater.UpdateError as exc:
            self.set_status("installer could not start")
            self.log(str(exc), "error")
            self._notice("danger", "update", str(exc))
            return
        self.log("installer started; restarting Spyder", "update")
        self.close()

    # -------------------------------------------------------------- handlers

    def on_url_changed(self) -> None:
        url = self.url_edit.text().strip()
        stale = url != self._probed_url
        # Any edit invalidates the fetched quality list.
        if stale:
            self._presets = []
            self._output_presets = []
            self._video_presets = []
            self.output_select.clear()
            self.quality_select.clear()
            self.media_title.setVisible(False)
            self.selection_help.setText("Paste a link above to discover available video and audio outputs.")
            self.detail_label.setVisible(False)
            self.set_head_title(IDLE_TITLE)
            self._clear_result()

        # Free and offline, so the platform is named on every keystroke:
        # the link is recognised as it lands, not after a round trip.
        self.omnibox.set_platform(platforms.detect(url).name)

        self._auto_fetch.stop()
        if stale and platforms.looks_complete(url):
            self._auto_fetch.start()

        self._update_buttons()

    def on_browse(self) -> None:
        start = self.folder_edit.text() or ""
        chosen = QFileDialog.getExistingDirectory(self, "Choose a folder to save into", start)
        if chosen:
            self._set_output_dir(chosen)
            self._settings.setValue("output_dir", chosen)
            self._update_buttons()

    def on_open_folder(self) -> None:
        folder = self.folder_edit.text()
        if folder and os.path.isdir(folder):
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def on_fetch(self) -> None:
        self._start_probe(auto=False)

    def on_auto_fetch(self) -> None:
        """The debounce timer fired. Checked again, because it fires late."""
        if self.url_edit.text().strip() != self._probed_url:
            self._start_probe(auto=True)

    def _start_probe(self, auto: bool) -> None:
        if self._busy():
            return
        url = self.url_edit.text().strip()
        if not url:
            return

        self._auto_fetch.stop()
        self._auto_probe = auto
        self.progress_bar.setValue(0)
        self.set_status("reading link")
        self.log(url, "read")
        self._check_impersonation(platforms.detect(url))

        self._probing_url = url
        self._probe_worker = ProbeWorker(url, self)
        self._probe_worker.succeeded.connect(self.on_probe_ok)
        self._probe_worker.failed.connect(self.on_probe_failed)
        self._probe_worker.finished.connect(self.on_probe_finished)
        self._probe_worker.start()
        self._update_buttons()

    def on_probe_ok(self, info) -> None:
        if self._probing_url and self._probing_url != self.url_edit.text().strip():
            return
        self._presets = list(info.presets)
        self._probed_url = self.url_edit.text().strip()

        self._video_presets = [p for p in self._presets if not p.audio_only]
        self._output_presets = ([self._video_presets[0]] if self._video_presets else []) + [
            p for p in self._presets if p.audio_only
        ]
        self.output_select.set_items([
            "Video" if not p.audio_only else p.label for p in self._output_presets
        ])
        self.on_output_changed()

        # The extractor that answered knows the site better than its
        # hostname did, so the badge is settled here rather than left a guess.
        self.omnibox.set_platform(info.platform.name)

        # The title names the tab, the way a page title does.
        self.set_head_title(info.title)
        self.media_title.set_full_text(info.title)
        self.media_title.setVisible(True)
        detail = info.duration
        if info.uploader:
            detail = f"{detail}  ·  {info.uploader}"
        self.detail_label.set_full_text(detail)
        self.detail_label.setVisible(True)

        self.set_status("ready to download")
        self.log(f"{len(self._output_presets)} output types available", "ok")
        if info.platform.drop_watermarked:
            self.log("watermarked copies skipped", "ok")

    def on_probe_failed(self, message: str) -> None:
        self.set_status("link unreadable")
        self.log(message, "error")
        # Nobody asked for the automatic read, so nobody should have to
        # dismiss a box when it fails. A half-typed link is the usual cause;
        # the log says what happened and Fetch is still there to press.
        if not self._auto_probe:
            self._notice("warning", "link", message)

    def on_probe_finished(self) -> None:
        self._probe_worker = None
        self._probing_url = ""
        self._update_buttons()

    def _selected_preset(self):
        index = self.output_select.current_index()
        if not 0 <= index < len(self._output_presets):
            return None
        preset = self._output_presets[index]
        if preset.audio_only:
            return preset
        quality = self.quality_select.current_index()
        return self._video_presets[quality] if 0 <= quality < len(self._video_presets) else None

    def on_output_changed(self, _index=0) -> None:
        index = self.output_select.current_index()
        if not 0 <= index < len(self._output_presets):
            return
        preset = self._output_presets[index]
        if preset.audio_only:
            self.quality_select.clear()
            help_text = {
                "mp3": "MP3: widely compatible; targets 320 kbps when converting.",
                "m4a": "M4A: copies compatible AAC audio; otherwise converts at 256 kbps.",
                "wav": "WAV: uncompressed, larger files. Cannot restore lost source quality.",
            }
            self.selection_help.setText(help_text[preset.audio_codec])
        else:
            self.quality_select.set_items([p.label for p in self._video_presets])
            self.selection_help.setText("Choose a video quality. File type depends on the source; merges prefer MP4.")
        self._update_buttons()

    def on_download(self) -> None:
        if self._busy():
            return

        preset = self._selected_preset()
        if preset is None or self.url_edit.text().strip() != self._probed_url:
            return

        folder = self.folder_edit.text()
        if not folder or not os.path.isdir(folder):
            self._notice("warning", "no folder", "Choose a folder to save into first.")
            return

        url = self._probed_url or self.url_edit.text().strip()

        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self._clear_result()
        self.set_status("starting")
        self.log(preset.label, "get")

        self._download_worker = DownloadWorker(url, preset, folder, self)
        self._download_worker.progress.connect(self.on_progress)
        self._download_worker.log.connect(self.on_worker_log)
        self._download_worker.succeeded.connect(self.on_download_ok)
        self._download_worker.failed.connect(self.on_download_failed)
        self._download_worker.cancelled.connect(self.on_download_cancelled)
        self._download_worker.finished.connect(self.on_download_finished)
        self._download_worker.start()
        self._update_buttons()

    def on_worker_log(self, message: str) -> None:
        self.log(message, "ffmpeg")

    def on_progress(self, percent: int, detail: str) -> None:
        if percent < 0:
            # Size unknown - show a busy indicator rather than a fake number.
            self.progress_bar.setRange(0, 0)
            self.set_status(detail)
            return
        if self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(percent)
        self.set_status(f"{percent:>3}%  {detail}")

    def on_download_ok(self, path: str) -> None:
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.set_status("done")
        if path and os.path.isfile(path):
            self._show_result(path)
            self.log(path, "save")
        else:
            self.log("finished, but the saved file could not be located", "warn")

        # The window is usually in the background by the time a download ends,
        # so flash the taskbar. Qt makes this a no-op when it is already active.
        if not self.isActiveWindow():
            app = QApplication.instance()
            if app is not None:
                app.alert(self, TASKBAR_FLASH_MS)

    def on_reveal(self) -> None:
        """Open the folder with the finished file selected."""
        path = self._result_path
        if not path or not os.path.isfile(path):
            return self.on_open_folder()
        if os.name == "nt":
            # Only explorer can select a file; QDesktopServices cannot. The
            # command line is built by hand because explorer wants the quotes
            # around the path alone - /select,"C:\dir\file" - while passing a
            # list quotes the whole argument and silently opens the wrong
            # folder for any name containing a space.
            # It also exits non-zero on success, so the result is not checked.
            subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')
            return None
        return self.on_open_folder()

    def on_download_failed(self, message: str) -> None:
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self._clear_result()
        self.set_status("failed")
        self.log(message, "error")
        self._notice("danger", "download failed", message)

    def on_download_cancelled(self) -> None:
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self._clear_result()
        self.set_status("cancelled")
        self.log("partial files removed", "cancel")

    def on_download_finished(self) -> None:
        self._download_worker = None
        self._update_buttons()

    def on_cancel(self) -> None:
        if self._update_worker is not None:
            self._update_worker.requestInterruption()
            self.set_status("cancelling update")
            self.cancel_button.setEnabled(False)
            return
        if self._download_worker is None:
            return
        self.set_status("cancelling")
        self.cancel_button.setEnabled(False)
        self._download_worker.cancel()

    # ---------------------------------------------------------------- closing

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._auto_fetch.stop()
        if self._update_worker is not None:
            # A network read may take up to its timeout. Keep the event loop
            # alive until the thread finishes instead of destroying a live QThread.
            self._close_after_update = True
            self._update_worker.requestInterruption()
            self.set_status("cancelling update before closing")
            event.ignore()
            return
        if self._download_worker is not None:
            answer = self._dialog(
                "ask",
                "download running",
                "A download is still running. Cancel it and quit?",
                [("Keep downloading", "primary"), ("Quit", "danger")],
                escape_index=0,
            )
            if answer != 1:
                event.ignore()
                return
            self._download_worker.cancel()
            self._download_worker.wait(5000)

        if self._probe_worker is not None:
            self._probe_worker.wait(2000)

        event.accept()
