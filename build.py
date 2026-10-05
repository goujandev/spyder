"""Build the installed Windows app, setup executable, and SHA-256 checksum."""

from __future__ import annotations

import argparse
import hashlib
import io
import struct
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

from spyder import __version__
from spyder.updater import version_tuple

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


def run_pyinstaller(no_ffmpeg: bool = False) -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is not installed. Run:")
        print("    pip install -r requirements-dev.txt")
        return 1

    command = [sys.executable, "-m", "PyInstaller", "Spyder.spec", "--noconfirm"]
    print("Running:", " ".join(command))
    env = os.environ.copy()
    if no_ffmpeg:
        env["SPYDER_NO_FFMPEG"] = "1"
    else:
        env.pop("SPYDER_NO_FFMPEG", None)
    return subprocess.call(command, cwd=str(ROOT), env=env)



def find_iscc(explicit: str | None = None) -> Path | None:
    candidates = [
        explicit, os.environ.get("ISCC"), shutil.which("ISCC"),
        str(ROOT / ".tools" / "innosetup" / "ISCC.exe"),
        str(Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe"),
        str(Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Inno Setup 6" / "ISCC.exe"),
    ]
    if explicit:
        return Path(explicit).resolve() if Path(explicit).is_file() else None
    return next((Path(item).resolve() for item in candidates if item and Path(item).is_file()), None)


def build_installer(iscc: Path) -> int:
    command = [str(iscc), f"/DAppVersion={__version__}", str(ROOT / "installer" / "Spyder.iss")]
    print("Running:", " ".join(command), flush=True)
    code = subprocess.call(command, cwd=str(ROOT))
    if code:
        return code
    installer = ROOT / "dist" / f"Spyder-Setup-{__version__}.exe"
    if not installer.is_file():
        print(f"Installer compiler did not produce {installer}")
        return 1
    with installer.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    checksum = installer.with_suffix(".exe.sha256")
    checksum.write_text(f"{digest}  {installer.name}\n", encoding="ascii")
    print(f"Built {installer} ({installer.stat().st_size / (1024 * 1024):.0f} MB)")
    print(f"Wrote {checksum}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Spyder Windows installer.")
    parser.add_argument("--clean", action="store_true", help="remove build/ and dist/ before building")
    parser.add_argument("--no-ffmpeg", action="store_true", help="exclude ffmpeg (requires a separate installation)")
    parser.add_argument("--app-only", action="store_true", help="build dist/Spyder/ without creating an installer")
    parser.add_argument("--iscc", metavar="PATH", help="path to the Inno Setup 6 compiler (6.3 or newer)")
    args = parser.parse_args()
    if os.name != "nt" or struct.calcsize("P") != 8:
        print("The Windows installer must be built using 64-bit Python on Windows.")
        return 1
    version_tuple(__version__)
    iscc = None if args.app_only else find_iscc(args.iscc)
    if not args.app_only and iscc is None:
        print("Inno Setup 6.3+ is required to build the installer.")
        print("Install it from https://jrsoftware.org/isdl.php, or pass --iscc PATH.")
        print("Use --app-only to build just the application folder.")
        return 1
    if not NOTICES.is_file() or not (ROOT / "LICENSE").is_file():
        print("LICENSE and THIRD-PARTY-NOTICES.txt are required.")
        return 1

    if args.clean:
        for folder in ("build", "dist"):
            path = (ROOT / folder).resolve()
            if path.parent != ROOT:
                raise RuntimeError(f"Refusing to clean outside the project: {path}")
            if path.exists():
                print(f"Removing {path}")
                shutil.rmtree(path)

    if not build_icons():
        return 1
    if not args.no_ffmpeg and not fetch_ffmpeg():
        return 1
    code = run_pyinstaller(args.no_ffmpeg)
    if code:
        return code
    app_dir = ROOT / "dist" / "Spyder"
    if not (app_dir / "Spyder.exe").is_file():
        print("PyInstaller did not produce dist/Spyder/Spyder.exe.")
        return 1
    shutil.copyfile(NOTICES, ROOT / "dist" / NOTICES.name)
    for notice in (NOTICES, ROOT / "LICENSE"):
        shutil.copyfile(notice, app_dir / notice.name)
    print(f"Built application: {app_dir}")
    return 0 if args.app_only else build_installer(iscc)


if __name__ == "__main__":
    raise SystemExit(main())
