# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Spyder.

Produces a single windowed Spyder.exe in dist/, with ffmpeg.exe bundled inside
when vendor/ffmpeg.exe exists (build.py fetches it for you).

    pyinstaller Spyder.spec --noconfirm
"""

import os

from PyInstaller.utils.hooks import collect_submodules

# SPECPATH is injected by PyInstaller and is the directory holding this spec;
# it is reliable regardless of the working directory the build was started from.
spec_dir = os.path.abspath(SPECPATH)  # noqa: F821

binaries = []
datas = []
hiddenimports = [
    # yt-dlp resolves extractors lazily; PyInstaller cannot see them.
    "yt_dlp.extractor.lazy_extractors",
]

# Required: the bundled ffmpeg is GPL, so its notice must ship with the exe.
notices = os.path.join(spec_dir, "THIRD-PARTY-NOTICES.txt")
if os.path.isfile(notices):
    datas.append((notices, "."))
    print(f"Bundling licence notices: {notices}")
else:
    raise SystemExit(
        f"THIRD-PARTY-NOTICES.txt is missing from {spec_dir}. "
        "It must ship with the GPL ffmpeg binary; refusing to build without it."
    )

# App icon: the multi-size .ico is used by the exe, window and taskbar.
# build.py preserves the authored logo.ico and also exports a PNG.
icon_ico = os.path.join(spec_dir, "assets", "Spyder.ico")
icon_png = os.path.join(spec_dir, "assets", "icon.png")
exe_icon = icon_ico if os.path.isfile(icon_ico) else None
if exe_icon is not None:
    datas.append((icon_ico, "assets"))
if os.path.isfile(icon_png):
    datas.append((icon_png, "assets"))
if exe_icon is None:
    print("WARNING: assets/Spyder.ico not found - the exe will use the default icon.")

# curl_cffi is what lets yt-dlp impersonate a browser, which TikTok requires of
# anything that wants to read it. PyInstaller ships no hook for the package, and
# two of its pieces are invisible to the dependency graph: the submodules, which
# yt-dlp reaches only through its own indirection, and the libcurl-impersonate
# DLL, which the wheel puts in a sibling "curl_cffi.libs" directory that no
# import statement mentions.
try:
    import curl_cffi
except ImportError:
    print(
        "WARNING: curl_cffi not installed - the exe will not be able to read "
        "TikTok. Install it with: pip install -r requirements.txt"
    )
else:
    hiddenimports += collect_submodules("curl_cffi")
    # curl_cffi/__init__.py hands this exact directory to os.add_dll_directory
    # before loading its extension, so the DLL has to keep that name beside the
    # package rather than land at the bundle root with everything else.
    site_packages = os.path.dirname(os.path.dirname(curl_cffi.__file__))
    libs_dir = os.path.join(site_packages, "curl_cffi.libs")
    found = []
    if os.path.isdir(libs_dir):
        found = [name for name in os.listdir(libs_dir) if name.lower().endswith(".dll")]
        binaries += [
            (os.path.join(libs_dir, name), "curl_cffi.libs") for name in found
        ]
    if found:
        print(f"Bundling curl_cffi impersonation libraries: {', '.join(found)}")
    else:
        # Not fatal: on some platforms the wheel links the library statically.
        print(f"Note: no separate curl_cffi DLLs found beside {libs_dir}")

ffmpeg_exe = os.path.join(spec_dir, "vendor", "ffmpeg.exe")
if os.path.isfile(ffmpeg_exe):
    # Land it at the root of the extraction dir, where ffmpeg_tools looks first.
    binaries.append((ffmpeg_exe, "."))
else:
    print("WARNING: vendor/ffmpeg.exe not found - building without bundled ffmpeg.")

a = Analysis(
    ["run_spyder.py"],
    pathex=[spec_dir],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Trim the parts of Qt Spyder never touches.
        "PyQt6.QtQml",
        "PyQt6.QtQuick",
        "PyQt6.QtQuick3D",
        "PyQt6.QtWebEngineCore",
        "PyQt6.QtWebEngineWidgets",
        "PyQt6.QtMultimedia",
        "PyQt6.Qt3DCore",
        "PyQt6.QtCharts",
        "PyQt6.QtDataVisualization",
        "tkinter",
        "test",
        "unittest",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Spyder",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # windowed app - no console flashes
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=exe_icon,
)
