"""Qt regressions for update results, cancellation, and safe thread teardown."""
import os
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from spyder import updater
from spyder.ui import MainWindow


class UpdateUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        with patch.object(MainWindow, "_check_ffmpeg"):
            self.window = MainWindow()
        self.window._notice = Mock()
        self.window._dialog = Mock(return_value=0)

    def tearDown(self):
        if self.window._update_worker is not None:
            self.window._update_worker.requestInterruption()
            self.wait_finished()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def wait_finished(self):
        deadline = time.monotonic() + 5
        while self.window._update_worker is not None and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertIsNone(self.window._update_worker)

    def test_up_to_date_result_waits_for_thread_completion(self):
        with patch.object(updater, "check_for_update", return_value=None):
            self.window.on_check_updates()
            self.assertFalse(self.window.update_button.isEnabled())
            self.wait_finished()
        self.assertEqual(self.window.status_label.text(), "up to date")
        self.assertTrue(self.window.update_button.isEnabled())
        self.window._notice.assert_called_once()

    def test_network_failure_keeps_app_usable(self):
        with patch.object(updater, "check_for_update", side_effect=updater.UpdateError("offline")):
            self.window.on_check_updates()
            self.wait_finished()
        self.assertTrue(self.window.update_button.isEnabled())
        self.assertEqual(self.window.status_label.text(), "update failed")

    def test_busy_download_blocks_update_check(self):
        self.window._download_worker = Mock()
        with patch.object(updater, "check_for_update") as check:
            self.window.on_check_updates()
        check.assert_not_called()
        self.window._download_worker = None

    def test_cancel_during_check(self):
        entered = threading.Event()
        def check(**kwargs):
            entered.set()
            while not kwargs["cancel"]():
                time.sleep(0.005)
            raise updater.UpdateCancelled()
        with patch.object(updater, "check_for_update", side_effect=check):
            self.window.on_check_updates()
            self.assertTrue(entered.wait(1))
            self.window.on_cancel()
            self.wait_finished()
        self.assertEqual(self.window.status_label.text(), "update cancelled")
        self.assertTrue(self.window.update_button.isEnabled())

    def test_close_cancels_worker_without_destroying_running_thread(self):
        entered = threading.Event()
        def check(**kwargs):
            entered.set()
            while not kwargs["cancel"]():
                time.sleep(0.005)
            raise updater.UpdateCancelled()
        with patch.object(updater, "check_for_update", side_effect=check):
            self.window.show()
            self.window.on_check_updates()
            self.assertTrue(entered.wait(1))
            self.window.close()
            self.assertTrue(self.window._close_after_update)
            self.wait_finished()
            self.app.processEvents()
        self.assertFalse(self.window.isVisible())

    def test_update_starts_after_accepted_prompt(self):
        release = updater.Release("2.2.0", "v2.2.0", "setup.exe", "https://github.com/test", 10, "0" * 64, None)
        self.window._dialog.return_value = 1
        with patch.object(updater, "installation_directory", return_value=Path("installed")), patch.object(self.window, "_start_update_worker") as start:
            self.window._present_update(release)
        start.assert_called_once_with(release)

    def test_launch_failure_does_not_close_app(self):
        self.window.show()
        with patch.object(updater, "launch_installer", side_effect=updater.UpdateError("blocked")):
            self.window._install_update(Mock())
        self.assertTrue(self.window.isVisible())
        self.assertTrue(self.window.update_button.isEnabled())
        self.window._notice.assert_called_once()

    def test_successful_launch_closes_app(self):
        with patch.object(updater, "launch_installer") as launch, patch.object(self.window, "close") as close:
            self.window._install_update(Mock())
        launch.assert_called_once()
        close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
