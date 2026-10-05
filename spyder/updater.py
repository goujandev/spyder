"""GitHub release updates. Network and file work stays outside the UI thread."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from . import __version__

REPOSITORY = "goujandev/spyder"
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"
LATEST_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
TIMEOUT = 20
MAX_INSTALLER_SIZE = 1024 * 1024 * 1024


class UpdateError(Exception):
    """An update problem safe to display to the user."""


class UpdateCancelled(Exception):
    """The user cancelled a check or download."""


@dataclass(frozen=True)
class Release:
    version: str
    tag: str
    filename: str
    url: str
    size: int
    sha256: str | None
    checksum_url: str | None


@dataclass(frozen=True)
class PreparedUpdate:
    release: Release
    path: Path
    sha256: str


def version_tuple(version: str) -> tuple[int, int, int]:
    """Stable release tags are vMAJOR.MINOR.PATCH; compare them numerically."""
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        raise UpdateError(f"Unsupported release version: {version!r}. Expected vMAJOR.MINOR.PATCH.")
    return tuple(int(part) for part in match.groups())


def _check_cancel(cancel: Callable[[], bool]) -> None:
    if cancel():
        raise UpdateCancelled()


def _open(url: str):
    request = Request(url, headers={
        "User-Agent": f"Spyder/{__version__}",
        "Accept": "application/vnd.github+json" if url == LATEST_URL else "application/octet-stream",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    response = urlopen(request, timeout=TIMEOUT)
    if urlparse(response.geturl()).scheme != "https":
        response.close()
        raise UpdateError("GitHub redirected the update to an insecure connection.")
    return response


def _read(url: str, limit: int, cancel: Callable[[], bool]) -> bytes:
    _check_cancel(cancel)
    with _open(url) as response:
        chunks = []
        size = 0
        while True:
            _check_cancel(cancel)
            chunk = response.read(min(65536, limit + 1 - size))
            if not chunk:
                return b"".join(chunks)
            size += len(chunk)
            if size > limit:
                raise UpdateError("GitHub returned an unexpectedly large response.")
            chunks.append(chunk)


def _network_error(exc: Exception) -> UpdateError:
    if isinstance(exc, HTTPError):
        if exc.code in (403, 429):
            return UpdateError("GitHub refused the request or its rate limit was reached. Try again later.")
        return UpdateError(f"GitHub returned HTTP {exc.code}. Try again later.")
    return UpdateError(f"Could not reach GitHub. Check your connection and try again. ({exc})")


def check_for_update(
    current_version: str = __version__,
    cancel: Callable[[], bool] = lambda: False,
) -> Release | None:
    """Return a newer stable release, or None when the installed version is current."""
    try:
        payload = _read(LATEST_URL, 2 * 1024 * 1024, cancel)
    except HTTPError as exc:
        if exc.code == 404:
            raise UpdateError("No public GitHub release is available yet.") from exc
        raise _network_error(exc) from exc
    except (URLError, OSError) as exc:
        raise _network_error(exc) from exc

    try:
        data = json.loads(payload)
        if not isinstance(data, dict):
            raise ValueError("expected a release object")
        if data.get("draft") or data.get("prerelease"):
            return None
        tag = data["tag_name"]
        if not isinstance(tag, str):
            raise ValueError("invalid tag")
        latest = version_tuple(tag)
        if latest <= version_tuple(current_version):
            return None
        version = tag.removeprefix("v")
        filename = f"Spyder-Setup-{version}.exe"
        assets = data["assets"]
        if not isinstance(assets, list) or not all(isinstance(asset, dict) for asset in assets):
            raise ValueError("invalid release assets")
        installer = next((asset for asset in assets if asset.get("name") == filename), None)
        if installer is None:
            raise UpdateError(
                f"Version {version} has no Windows installer attached. "
                "The publisher must upload the setup file before this release can be installed."
            )
        base = f"https://github.com/{REPOSITORY}/releases/download/{quote(tag, safe='')}/"
        url = base + filename
        if installer.get("browser_download_url") != url or installer.get("state") != "uploaded":
            raise UpdateError("The release installer has an unexpected download address or is not ready.")
        size = installer["size"]
        if type(size) is not int or not 0 < size <= MAX_INSTALLER_SIZE:
            raise UpdateError("The release installer has an invalid file size.")
        digest = installer.get("digest")
        sha256 = None
        if digest is not None:
            if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
                raise UpdateError("GitHub returned an invalid installer checksum.")
            sha256 = digest.split(":", 1)[1].lower()
        checksum_name = filename + ".sha256"
        checksum = next((asset for asset in assets if asset.get("name") == checksum_name), None)
        checksum_url = None
        if checksum is not None:
            checksum_url = base + checksum_name
            if checksum.get("browser_download_url") != checksum_url or checksum.get("state") != "uploaded":
                raise UpdateError("The release checksum has an unexpected download address or is not ready.")
        if sha256 is None and checksum_url is None:
            raise UpdateError("The release has no SHA-256 checksum. The update cannot be verified.")
        return Release(version, tag, filename, url, size, sha256, checksum_url)
    except (KeyError, TypeError, ValueError) as exc:
        raise UpdateError("GitHub returned incomplete or invalid release information.") from exc


def cleanup_cache(cache_dir: Path) -> None:
    """Remove our own old staging directories, never a currently running installer."""
    if not cache_dir.is_dir():
        return
    cutoff = time.time() - 7 * 24 * 60 * 60
    for child in cache_dir.glob("Spyder-update-*"):
        try:
            if child.is_dir() and not child.is_symlink() and child.stat().st_mtime < cutoff:
                shutil.rmtree(child)
        except OSError:
            pass


def download_update(
    release: Release,
    cache_dir: Path,
    progress: Callable[[int, int], None] = lambda done, total: None,
    cancel: Callable[[], bool] = lambda: False,
) -> PreparedUpdate:
    """Stage a complete, size-checked and SHA-256-verified installer."""
    _check_cancel(cancel)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cleanup_cache(cache_dir)
    staging = Path(tempfile.mkdtemp(prefix="Spyder-update-", dir=cache_dir))
    part = staging / (release.filename + ".part")
    target = staging / release.filename
    try:
        expected = release.sha256
        if expected is None:
            if release.checksum_url is None:
                raise UpdateError("The installer checksum is missing.")
            checksum = _read(release.checksum_url, 4096, cancel).decode("ascii").strip()
            fields = checksum.split()
            if (
                len(fields) != 2
                or not re.fullmatch(r"[0-9a-fA-F]{64}", fields[0])
                or fields[1].lstrip("*") != release.filename
            ):
                raise UpdateError("The release checksum file is invalid.")
            expected = fields[0].lower()
        digest = hashlib.sha256()
        downloaded = 0
        with _open(release.url) as response, part.open("wb") as output:
            while True:
                _check_cancel(cancel)
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                downloaded += len(chunk)
                if downloaded > release.size:
                    raise UpdateError("The installer is larger than the file published on GitHub.")
                output.write(chunk)
                digest.update(chunk)
                progress(downloaded, release.size)
        _check_cancel(cancel)
        if downloaded != release.size:
            raise UpdateError("The installer download was incomplete. Try again.")
        actual = digest.hexdigest()
        if actual != expected:
            raise UpdateError("The installer checksum did not match. Nothing was installed; try again.")
        part.replace(target)
        return PreparedUpdate(release, target, actual)
    except (URLError, OSError) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdateError(f"Could not download the update: {exc}") from exc
    except UnicodeError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdateError("The release checksum file is invalid.") from exc
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def installation_directory() -> Path | None:
    """Only upgrade installed, frozen Windows builds; source/portable runs stay intact."""
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return None
    directory = Path(sys.executable).resolve().parent
    marker = directory / "installed.ini"
    try:
        installed = marker.read_text(encoding="utf-8").strip() == "[installation]\nproduct=Spyder"
    except OSError:
        return None
    if installed and (directory / "unins000.exe").is_file():
        return directory
    return None


def launch_installer(update: PreparedUpdate) -> None:
    """Launch setup first; the UI quits only if process creation succeeds.

    Setup waits for this PID to exit, then checks the app mutex before touching
    files. Its progress/errors remain visible, and it restarts Spyder on success.
    """
    directory = installation_directory()
    if directory is None:
        raise UpdateError("Install Spyder using the setup file before using in-app updates.")
    try:
        with update.path.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != update.sha256:
                raise UpdateError("The downloaded installer changed. Check for updates again.")
        subprocess.Popen([
            str(update.path),
            "/SP-", "/SILENT", "/NORESTART", "/NOCLOSEAPPLICATIONS",
            "/UPDATE=1", f"/PARENTPID={os.getpid()}",
            f"/DIR={directory}", f"/LOG={update.path.parent / 'setup.log'}",
        ], cwd=str(update.path.parent))
    except OSError as exc:
        raise UpdateError(f"Could not start the installer. Spyder is still running. ({exc})") from exc
