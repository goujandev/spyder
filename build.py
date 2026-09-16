"""One-command build: fetch ffmpeg if needed, then run PyInstaller.

    python build.py

The result is dist/Spyder.exe - a single self-contained file. The first run
downloads a static ffmpeg build (~30 MB zipped) into vendor/ so it can be
bundled; later builds reuse it.

Flags:
    --no-ffmpeg   skip the ffmpeg download and build without it (smaller exe,
                  but the user must supply ffmpeg themselves)
    --clean       remove build/ and dist/ first
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / "vendor"
FFMPEG_EXE = VENDOR / "ffmpeg.exe"

NOTICES = ROOT / "THIRD-PARTY-NOTICES.txt"
SOURCE_LOGO = ROOT / "logo.png"
SOURCE_ICON = ROOT / "logo.ico"
ASSETS = ROOT / "assets"
ICON_ICO = ASSETS / "Spyder.ico"
ICON_PNG = ASSETS / "icon.png"

# Sizes Windows picks between for the taskbar, Explorer and Alt-Tab.
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]

# Gyan.dev "essentials" build - the standard static Windows ffmpeg.
FFMPEG_ZIP_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


def build_icons() -> bool:
    """Render logo.png into the .ico the exe needs and the .png the window uses.

    Regenerated whenever logo.png is newer, so replacing the logo and rebuilding
    is all it takes to change the icon.
    """
    if not SOURCE_LOGO.is_file():
        print(f"No {SOURCE_LOGO.name} found - building without a custom icon.")
        return True

    # Preserve the authored small pixel-art sizes; regenerate from PNG only
    # when there is no explicit source ICO.
    authored_icon = SOURCE_ICON.is_file()
    source_mtime = max(
        SOURCE_LOGO.stat().st_mtime,
        SOURCE_ICON.stat().st_mtime if authored_icon else 0,
        Path(__file__).stat().st_mtime,
    )
    fresh = (
        ICON_ICO.is_file()
        and ICON_PNG.is_file()
        and min(ICON_ICO.stat().st_mtime, ICON_PNG.stat().st_mtime) >= source_mtime
    )
    if fresh:
        print(f"Icons already up to date: {ICON_ICO}")
        return True

    if authored_icon:
        ASSETS.mkdir(exist_ok=True)
        shutil.copyfile(SOURCE_ICON, ICON_ICO)
        shutil.copyfile(SOURCE_LOGO, ICON_PNG)
        print(f"Copied authored icons to {ASSETS}")
        return True

    try:
        from PIL import Image
    except ImportError:
        print("Pillow is needed to build the icon. Run:")
        print("    pip install -r requirements-dev.txt")
        return False

    ASSETS.mkdir(exist_ok=True)
    with Image.open(SOURCE_LOGO) as image:
        image = image.convert("RGBA")
        image.save(ICON_ICO, format="ICO", sizes=[(s, s) for s in ICO_SIZES])
        image.resize((256, 256), Image.Resampling.LANCZOS).save(ICON_PNG, format="PNG")

    print(f"Generated {ICON_ICO} and {ICON_PNG} from {SOURCE_LOGO.name}")
    return True


def fetch_ffmpeg() -> bool:
    if FFMPEG_EXE.is_file():
        print(f"ffmpeg already present: {FFMPEG_EXE}")
        return True

    VENDOR.mkdir(exist_ok=True)
    print(f"Downloading ffmpeg from {FFMPEG_ZIP_URL}")
    print("(about 30 MB - this happens once)")

    try:
        request = Request(FFMPEG_ZIP_URL, headers={"User-Agent": "Spyder-build"})
        with urlopen(request, timeout=120) as response:
            payload = response.read()
    except Exception as exc:  # noqa: BLE001
        print(f"Download failed: {exc}")
        print("Download ffmpeg manually and place ffmpeg.exe in the vendor/ folder,")
        print("or re-run with --no-ffmpeg.")
        return False

    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            member = next(
                (n for n in archive.namelist() if n.endswith("bin/ffmpeg.exe")), None
            )
            if member is None:
                print("Could not find ffmpeg.exe inside the downloaded archive.")
                return False
            with archive.open(member) as source, open(FFMPEG_EXE, "wb") as target:
                shutil.copyfileobj(source, target)
    except zipfile.BadZipFile:
        print("The downloaded file was not a valid zip archive.")
        return False

    size_mb = FFMPEG_EXE.stat().st_size / (1024 * 1024)
    print(f"Extracted ffmpeg.exe ({size_mb:.0f} MB) to {FFMPEG_EXE}")
    return True


def run_pyinstaller() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is not installed. Run:")
        print("    pip install -r requirements-dev.txt")
        return 1

    command = [sys.executable, "-m", "PyInstaller", "Spyder.spec", "--noconfirm"]
    print("Running:", " ".join(command))
    return subprocess.call(command, cwd=str(ROOT))


def main() -> int:
    args = set(sys.argv[1:])

    if "--clean" in args:
        for folder in ("build", "dist"):
            path = ROOT / folder
            if path.exists():
                print(f"Removing {path}")
                shutil.rmtree(path, ignore_errors=True)

    if not build_icons():
        return 1

    if "--no-ffmpeg" not in args:
        if not fetch_ffmpeg():
            return 1

    code = run_pyinstaller()
    if code == 0:
        exe = ROOT / "dist" / "Spyder.exe"
        if exe.is_file():
            size_mb = exe.stat().st_size / (1024 * 1024)
            print(f"\nBuilt {exe} ({size_mb:.0f} MB)")
        # The notices ship inside the exe as well, but a release attaches this
        # copy: the GPL ffmpeg bundled in there has to travel with its licence,
        # and a step you have to remember is a step that gets forgotten.
        if NOTICES.is_file():
            shutil.copyfile(NOTICES, ROOT / "dist" / NOTICES.name)
            print(f"Copied {NOTICES.name} to dist/")
        else:
            print(f"WARNING: {NOTICES.name} is missing - do not publish without it.")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
