"""Update protocol tests use mocked GitHub responses and temporary staging."""
import hashlib
import io
import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from spyder import updater


PAYLOAD = b"MZtest installer"
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()


def metadata(version="2.2.0"):
    name = f"Spyder-Setup-{version}.exe"
    base = f"https://github.com/{updater.REPOSITORY}/releases/download/v{version}/"
    return {
        "tag_name": f"v{version}", "draft": False, "prerelease": False,
        "assets": [{
            "name": name, "browser_download_url": base + name,
            "state": "uploaded", "size": len(PAYLOAD), "digest": "sha256:" + DIGEST,
        }, {
            "name": name + ".sha256", "browser_download_url": base + name + ".sha256",
            "state": "uploaded",
        }],
    }


def release():
    with patch.object(updater, "_read", return_value=json.dumps(metadata()).encode()):
        return updater.check_for_update("2.1.0")


class ReleaseTests(unittest.TestCase):
    def check(self, data, current="2.1.0"):
        with patch.object(updater, "_read", return_value=json.dumps(data).encode()):
            return updater.check_for_update(current)

    def test_numeric_version_order(self):
        self.assertGreater(updater.version_tuple("v2.10.0"), updater.version_tuple("2.9.9"))
        for invalid in ("../x", "v2.0", "v2.0.0-beta", "2.0.0/evil"):
            with self.subTest(invalid=invalid), self.assertRaises(updater.UpdateError):
                updater.version_tuple(invalid)

    def test_newer_release(self):
        result = self.check(metadata())
        self.assertEqual(result.version, "2.2.0")
        self.assertEqual(result.sha256, DIGEST)

    def test_current_or_older_release(self):
        for version in ("2.1.0", "2.0.0"):
            self.assertIsNone(self.check(metadata(version)))

    def test_drafts_and_prereleases_ignored(self):
        for flag in ("draft", "prerelease"):
            data = metadata()
            data[flag] = True
            self.assertIsNone(self.check(data))

    def test_missing_installer(self):
        data = metadata()
        data["assets"] = []
        with self.assertRaisesRegex(updater.UpdateError, "no Windows installer"):
            self.check(data)

    def test_wrong_url_rejected(self):
        data = metadata()
        data["assets"][0]["browser_download_url"] = "https://example.com/setup.exe"
        with self.assertRaisesRegex(updater.UpdateError, "unexpected download"):
            self.check(data)

    def test_invalid_asset_sizes_rejected(self):
        for size in (0, -1, True, "10", updater.MAX_INSTALLER_SIZE + 1):
            data = metadata()
            data["assets"][0]["size"] = size
            with self.subTest(size=size), self.assertRaises(updater.UpdateError):
                self.check(data)

    def test_checksum_required(self):
        data = metadata()
        data["assets"] = data["assets"][:1]
        data["assets"][0].pop("digest")
        with self.assertRaisesRegex(updater.UpdateError, "no SHA-256"):
            self.check(data)

    def test_checksum_sidecar_fallback(self):
        data = metadata()
        data["assets"][0]["digest"] = None
        result = self.check(data)
        self.assertIsNone(result.sha256)
        self.assertTrue(result.checksum_url.endswith(".exe.sha256"))

    def test_malformed_response(self):
        for data in ([], {}, {"tag_name": 4}, {"tag_name": "v2.2.0", "assets": [None]}):
            with self.subTest(data=data), self.assertRaises(updater.UpdateError):
                self.check(data)

    def test_network_errors_are_readable(self):
        for code, message in ((404, "No public"), (403, "rate limit"), (500, "HTTP 500")):
            with patch.object(updater, "_read", side_effect=HTTPError("url", code, "", {}, None)):
                with self.assertRaisesRegex(updater.UpdateError, message):
                    updater.check_for_update()
        with patch.object(updater, "_read", side_effect=URLError("offline")):
            with self.assertRaisesRegex(updater.UpdateError, "connection"):
                updater.check_for_update()


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cache = Path(self.temp.name)
        self.release = release()

    def tearDown(self):
        self.temp.cleanup()

    def download(self, payload=PAYLOAD, release_override=None, **kwargs):
        with patch.object(updater, "_open", return_value=io.BytesIO(payload)):
            return updater.download_update(release_override or self.release, self.cache, **kwargs)

    def test_verified_download_and_progress(self):
        progress = []
        result = self.download(progress=lambda done, total: progress.append((done, total)))
        self.assertEqual(result.path.read_bytes(), PAYLOAD)
        self.assertEqual(result.sha256, DIGEST)
        self.assertEqual(progress[-1], (len(PAYLOAD), len(PAYLOAD)))
        self.assertFalse(result.path.with_suffix(".exe.part").exists())

    def test_size_and_checksum_failures_clean_staging(self):
        for payload in (b"short", PAYLOAD + b"x", b"x" * len(PAYLOAD)):
            with self.subTest(payload=payload), self.assertRaises(updater.UpdateError):
                self.download(payload)
            self.assertEqual(list(self.cache.iterdir()), [])

    def test_cancellation_cleans_partial_file(self):
        interrupted = []
        with self.assertRaises(updater.UpdateCancelled):
            self.download(progress=lambda *_: interrupted.append(True), cancel=lambda: bool(interrupted))
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_cancellation_before_network(self):
        with patch.object(updater, "_open") as opened, self.assertRaises(updater.UpdateCancelled):
            updater.download_update(self.release, self.cache, cancel=lambda: True)
        opened.assert_not_called()

    def test_sidecar_verification(self):
        sidecar = f"{DIGEST}  {self.release.filename}\n".encode()
        with patch.object(updater, "_read", return_value=sidecar):
            result = self.download(release_override=replace(self.release, sha256=None))
        self.assertEqual(result.path.read_bytes(), PAYLOAD)

    def test_wrong_sidecar_filename_rejected(self):
        with patch.object(updater, "_read", return_value=f"{DIGEST}  different.exe".encode()):
            with self.assertRaisesRegex(updater.UpdateError, "checksum file"):
                self.download(release_override=replace(self.release, sha256=None))
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_source_run_is_not_an_installation(self):
        with patch.object(updater.sys, "frozen", False, create=True):
            self.assertIsNone(updater.installation_directory())

    def test_installed_directory_requires_marker_and_uninstaller(self):
        exe = self.cache / "Spyder.exe"
        exe.touch()
        with patch.object(updater.sys, "frozen", True, create=True), patch.object(updater.sys, "executable", str(exe)):
            self.assertIsNone(updater.installation_directory())
            (self.cache / "installed.ini").write_text("[installation]\nproduct=Spyder\n")
            self.assertIsNone(updater.installation_directory())
            (self.cache / "unins000.exe").touch()
            self.assertEqual(updater.installation_directory(), self.cache.resolve())

    def test_installer_handoff_uses_argument_list(self):
        result = self.download()
        directory = self.cache / "installed app"
        with patch.object(updater, "installation_directory", return_value=directory), patch.object(updater.subprocess, "Popen") as popen:
            updater.launch_installer(result)
        args = popen.call_args.args[0]
        self.assertIn(f"/DIR={directory}", args)
        self.assertIn(f"/PARENTPID={os.getpid()}", args)
        self.assertIn("/NORESTART", args)
        self.assertIn("/NOCLOSEAPPLICATIONS", args)
        self.assertIn("/UPDATE=1", args)
        self.assertNotIn("shell", popen.call_args.kwargs)

    def test_installer_not_started_if_staged_file_changed(self):
        result = self.download()
        result.path.write_bytes(b"tampered")
        with patch.object(updater, "installation_directory", return_value=self.cache), patch.object(updater.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(updater.UpdateError, "changed"):
                updater.launch_installer(result)
        popen.assert_not_called()

    def test_installer_launch_failure_is_readable(self):
        result = self.download()
        with patch.object(updater, "installation_directory", return_value=self.cache), patch.object(updater.subprocess, "Popen", side_effect=OSError("blocked")):
            with self.assertRaisesRegex(updater.UpdateError, "still running"):
                updater.launch_installer(result)


if __name__ == "__main__":
    unittest.main()
