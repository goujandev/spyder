"""Offscreen output selection regressions."""
import os
import unittest
from unittest.mock import Mock, patch
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
from spyder import downloader as d, theme
from spyder.ui import MainWindow


class OutputUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        theme.apply(cls.app)

    def setUp(self):
        with patch.object(MainWindow, "_check_ffmpeg"), patch.object(MainWindow, "_restore_output_dir"):
            self.w = MainWindow()
        self.w.folder_edit.setText(os.getcwd())
        self.w.url_edit.setText("https://example.com/media")
        self.w._auto_fetch.stop()

    def tearDown(self):
        self.w._probe_worker = self.w._download_worker = self.w._update_worker = None
        self.w.close()
        self.w.deleteLater()
        self.app.processEvents()

    def load(self, audio_only=False):
        info = d.VideoInfo("A long media title " * 8, "3:24", "Uploader " * 12,
            d.build_presets({"formats": [{"vcodec": "none" if audio_only else "h264", "acodec": "aac", "height": 1080}]}))
        self.w.on_probe_ok(info)

    def test_output_switch_and_worker_selection(self):
        self.load()
        self.assertTrue(self.w.quality_select.isEnabled())
        for index, codec in enumerate(("mp3", "m4a", "wav"), 1):
            self.w.output_select._choose(index)
            self.assertFalse(self.w.quality_select.isEnabled())
            self.assertEqual(self.w._selected_preset().audio_codec, codec)
            with patch("spyder.ui.DownloadWorker") as worker:
                self.w.on_download()
                self.assertEqual(worker.call_args.args[1].audio_codec, codec)
                self.w.on_download_finished()
        self.w.output_select._choose(0)
        self.assertTrue(self.w.quality_select.isEnabled())
        self.assertFalse(self.w._selected_preset().audio_only)

    def test_audio_only(self):
        self.load(True)
        self.assertEqual(self.w.output_select.count(), 3)
        self.assertTrue(self.w.download_button.isEnabled())
        self.assertFalse(self.w.quality_select.isEnabled())
        self.assertTrue(self.w._selected_preset().audio_only)

    def test_stale_link_and_late_probe(self):
        self.load()
        self.w._probing_url = self.w._probed_url
        self.w.url_edit.setText("https://example.com/other")
        self.assertTrue(self.w._auto_fetch.isActive())
        self.w._auto_fetch.stop()
        self.load()
        self.assertEqual(self.w.output_select.count(), 0)
        self.assertFalse(self.w.download_button.isEnabled())
        self.assertTrue(self.w.media_title.isHidden())
        with patch("spyder.ui.DownloadWorker") as worker:
            self.w.on_download()
        worker.assert_not_called()

    def test_busy_controls_and_popup(self):
        self.load()
        for attr in ("_probe_worker", "_download_worker", "_update_worker"):
            with self.subTest(worker=attr):
                self.w.output_select.open_popup()
                setattr(self.w, attr, Mock(release=None))
                self.w._update_buttons()
                for control in (self.w.output_select, self.w.quality_select, self.w.download_button, self.w.update_button):
                    self.assertFalse(control.isEnabled())
                self.assertIsNone(self.w.output_select._popup)
                setattr(self.w, attr, None)
                self.w._update_buttons()
                self.assertTrue(self.w.output_select.isEnabled())

    def test_source_help_and_pinterest_video_only(self):
        from spyder import platforms
        self.assertIn("Reddit, Pinterest", self.w.source_help.text())
        self.assertIn("no photos, galleries", self.w.source_help.text())
        self.w.url_edit.setText("https://pin.it/example")
        self.w._auto_fetch.stop()
        presets = d.build_presets({"formats": [{"url": "https://example.com/pin.mp4",
            "ext": "mp4", "height": 720, "width": 1280}]}, platforms.PINTEREST)
        self.w.on_probe_ok(d.VideoInfo("Video pin", "0:57", "", presets, platforms.PINTEREST))
        self.assertEqual(self.w.output_select.count(), 1)
        self.assertFalse(self.w._selected_preset().audio_only)
        self.assertTrue(self.w.download_button.isEnabled())

    def test_default_and_minimum_geometry(self):
        self.load()
        self.w.show()
        for size in ((760, 680), (660, 620)):
            self.w.resize(*size)
            self.app.processEvents()
            self.assertEqual((self.w.width(), self.w.height()), size)
            self.assertGreater(self.w.log_view.height(), 40)
            for widget in (self.w.output_select, self.w.quality_select, self.w.update_button, self.w.source_help):
                self.assertTrue(self.w.rect().contains(widget.mapTo(self.w, widget.rect().bottomRight())))
