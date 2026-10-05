# Spyder

A video and audio downloader for YouTube, TikTok, Reddit, Pinterest and other
sources supported by yt-dlp.

Paste a link → it works out where the link is from and reads it → pick an
output and video quality → pick a folder → Download.

Licensed under [GPL-3.0](LICENSE).

## What it does

- Paste a video or audio URL and fetch the outputs that link actually offers
- Recognises the site as you paste — the name appears in the URL bar
  immediately, and the link is read without you pressing anything
- **TikTok downloads have no watermark**, at the highest quality the post has
- Separate **Output** and **Video quality** controls: best available video or
  per-resolution quality, plus **MP3**, **M4A**, and **WAV** audio.
  Choices follow source capabilities, including audio-only links; video quality
  is disabled for audio. MP3 targets 320 kbps on conversion; M4A copies compatible
  AAC audio or converts at 256 kbps. WAV is uncompressed and larger, but cannot
  restore quality lost in the source. Video merges prefer MP4; the source and
  selected streams determine the actual file type.
- Native folder picker, remembers the last folder you used
- Live progress bar with size, speed and ETA
- Status/log panel showing each stage (reading link, downloading, merging with
  ffmpeg, done)
- Cancel button that stops cleanly and deletes the half-written files
- Friendly messages for bad links, dead videos, network drops and missing ffmpeg

Deliberately **not** in v1: playlists, subtitles, trimming.

## Platforms

Spyder uses [yt-dlp extractors](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md)
for individual video and audio links. Extractor coverage does not guarantee a
download: availability, sign-in requirements, regional restrictions and site
changes can prevent access.

**Reddit and Pinterest video:** paste a single Reddit video post
(`reddit.com/r/.../comments/...`) or video pin (`pinterest.com/pin/...`).
Pinterest's supported regional domains are recognised too. `redd.it` and `pin.it`
shortlinks are recognised and passed to yt-dlp for redirect resolution; the badge
alone does not verify that the destination can be downloaded.

Photos, galleries, boards, whole accounts and playlists are not supported.
Collection results are rejected instead of silently selecting their first entry.
Pinterest story pins with multiple pages are also rejected. Video choices follow
the formats returned by the source; audio extraction is offered only when audio
is identified. A Pinterest MP4 with unknown audio metadata can still be downloaded
as video, with any embedded audio preserved.

The moment a link lands in the URL bar its site is named there — no network
call, it is a hostname lookup — and half a second later Spyder reads the link by
itself. The **Fetch** button still works; it just rarely needs pressing.

**TikTok** is the one site with its own rules:

- TikTok serves every video twice, once clean and once stamped with a drifting
  @handle. Spyder filters the stamped copies out entirely, so the watermark-free
  version is not a setting to find — it is the only thing offered.
- The top preset reads **Best quality, no watermark** and is already selected.
- Because TikTok publishes each quality as one finished file, Spyder takes it
  whole instead of downloading video and audio separately and merging them.
- `vm.tiktok.com` and `vt.tiktok.com` short links work; they are resolved on
  the way through.

Vertical video is named the way people name it. A 1080×1920 TikTok or Short is
listed as **1080p**, not 1920p.

### TikTok needs one extra piece

TikTok turns away any client that does not look like a real browser, so yt-dlp
has to impersonate one. That ability comes from
[curl_cffi](https://github.com/lexiforest/curl_cffi), which `requirements.txt`
pulls in via yt-dlp's `curl-cffi` extra and which is bundled inside the built
exe. Without it TikTok fails before it starts; Spyder notices a TikTok link it
cannot read and says so in the log rather than letting the fetch fail
unexplained.

## Installing and updating

Download **Spyder-Setup-2.2.0.exe** (or the newer setup file) from
[GitHub Releases](https://github.com/goujandev/spyder/releases), then run it.
Setup installs to `%LOCALAPPDATA%\Programs\Spyder` for your Windows account,
creates a Start Menu shortcut, and optionally creates a desktop shortcut.
Python, Qt, yt-dlp, curl_cffi and ffmpeg are included. No administrator access is
needed. Uninstall through Windows **Settings > Apps > Installed apps**.

In Spyder, click **Check for updates** beside the version number. If a newer
stable GitHub release is available, choose **Update and restart**. The installer
downloads in the background with progress and cancellation, is checked against
its SHA-256 checksum and published file size, then upgrades the existing
installation and relaunches Spyder. Your chosen download folder and saved videos
are preserved. Checks happen only when requested; new commits alone do not
trigger updates.

You can also start a check with `Spyder.exe --check-for-updates` (or `--update`).
Source runs and uninstalled application folders can check for releases and open
the download page, but only installed Windows copies can install updates in-app.
Existing portable versions must install the setup file once to get this feature.

The installer is unsigned, so Windows may show a SmartScreen warning on first
installation. Code signing is required to remove that warning reliably.

## Running from source

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run_spyder.py
```

From source, ffmpeg is not bundled. Spyder looks for it in this order:

1. Inside the bundle (frozen builds only)
2. Next to `Spyder.exe`, or in the project root / `vendor/` when run from source
3. Anywhere on your `PATH`

So either drop an `ffmpeg.exe` into `vendor/` (running `python build.py` once
fetches it for you), or install ffmpeg system-wide:

```bash
winget install Gyan.FFmpeg
```

Without ffmpeg the app still starts and warns you in the log; downloads that
need merging or audio conversion will fail with a clear message.

## Building the Windows installer

Use 64-bit Python 3.12+ on Windows and install
[Inno Setup 6.3 or newer](https://jrsoftware.org/isdl.php), then:

```bash
pip install -r requirements-dev.txt
python build.py
```

`build.py` fetches ffmpeg into `vendor/`, builds an application directory with
PyInstaller, compiles the Inno Setup installer, and writes its SHA-256 file:

```text
dist/Spyder/Spyder.exe
dist/Spyder-Setup-2.2.0.exe
dist/Spyder-Setup-2.2.0.exe.sha256
dist/THIRD-PARTY-NOTICES.txt
```

Distribute the setup file. The application directory is an intermediate build;
its contents are installed together, so the application no longer unpacks a
single-file bundle each time it starts.

| Flag | Effect |
| --- | --- |
| `--clean` | delete `build/` and `dist/` first |
| `--no-ffmpeg` | exclude ffmpeg; users must install it separately |
| `--app-only` | build just the application directory |
| `--iscc PATH` | specify the Inno Setup compiler path |

The compiler is found through `--iscc`, the `ISCC` environment variable, `PATH`,
or the usual Inno Setup installation directories. It also recognises a local
portable compiler at `.tools/innosetup/ISCC.exe`.

To build the application directory directly: `pyinstaller Spyder.spec --noconfirm`.
To run update tests: `python -m unittest discover -s tests -v`.

### Notes on the build

- The exe is windowed (`console=False`). `spyder/main.py` patches
  `subprocess.Popen` with `CREATE_NO_WINDOW` so ffmpeg does not flash a console.
- `yt_dlp.extractor.lazy_extractors` is listed as a hidden import — yt-dlp loads
  extractors dynamically and PyInstaller cannot see them.
- curl_cffi needs the same treatment and then some. PyInstaller ships no hook
  for it, so the spec collects its submodules by hand and copies the
  `libcurl-impersonate-*.dll` out of the `curl_cffi.libs` directory the wheel
  puts beside the package. That directory name matters: `curl_cffi/__init__.py`
  passes it to `os.add_dll_directory` before loading its extension, so the DLL
  has to keep it rather than land at the bundle root like everything else.
  Building without curl_cffi installed prints a warning and produces an exe
  that cannot read TikTok.
- The pixel-art icon comes from `logo.ico`, with dedicated 16, 24, 32, 48,
  64, 128 and 256px images for the exe, window and taskbar. `logo.png` is the
  large preview and `logo.aseprite` is the editable source. Replace both
  `logo.ico` and `logo.png` and rebuild to change it. Without `logo.ico`, the
  build generates icon sizes from `logo.png` instead.
- Unused Qt modules (QML, Quick, WebEngine, Multimedia, …) are excluded to keep
  the exe smaller.
- The app uses a PyInstaller directory build inside the installer. Signing the
  setup file and app executable establishes a verified publisher.

## Releasing

1. Bump `__version__` in `spyder/__init__.py` to a new `MAJOR.MINOR.PATCH` version.
2. Commit and push the changes, including `.github/workflows/release.yml`.
3. Tag that commit with the same version and push the tag, for example:
   `git tag v2.2.0` then `git push origin v2.2.0`.
4. The GitHub Actions workflow checks the version, runs tests, builds the Windows
   installer, and publishes a release with the setup file, checksum and notices.

Manual workflow runs build downloadable artifacts without publishing a release.
For a manual release, run `python build.py` and attach the matching
**Spyder-Setup-VERSION.exe**, **Spyder-Setup-VERSION.exe.sha256** and
**THIRD-PARTY-NOTICES.txt** to a stable GitHub release tagged `vVERSION`.

The updater uses the public repository `goujandev/spyder` and GitHub's latest
stable release endpoint. Drafts and prereleases are excluded. Release asset
names and tag/version matching are part of the update contract: do not rename
setup or checksum files. A missing installer or checksum produces an actionable
error; an incomplete or corrupt download is never installed.

Keep the installer `AppId` and `AppMutex` stable across releases. Setup waits
for the updating process to exit and blocks replacement while another copy of
Spyder is running. It shows installation failures and does not reboot Windows.
The staged installer and `setup.log` are kept in the app's update cache for
troubleshooting; staging directories older than seven days are cleaned on the
next update download.

## License

Spyder is licensed under the **GNU General Public License v3.0** - see
[LICENSE](LICENSE).

It has to be. Spyder links PyQt6, which is GPLv3, so any distributed build must
also be GPLv3 and ship its source. Publishing this repository satisfies that.

To relicense Spyder under something permissive you would need to drop PyQt6 -
porting `ui.py` and `worker.py` to **PySide6** (LGPLv3) is mostly import
renames, since neither uses PyQt-specific APIs - or buy a Riverbank commercial
PyQt licence.

### Bundled components

`THIRD-PARTY-NOTICES.txt` ships inside the exe and next to it. It covers:

| Component | License |
| --- | --- |
| FFmpeg (gyan.dev essentials build) | GPLv3+ |
| PyQt6 / Qt6 | GPLv3 / LGPLv3 |
| yt-dlp | The Unlicense |
| curl_cffi + libcurl-impersonate | MIT (bundles libcurl, BoringSSL, nghttp2) |
| Python | PSF License v2 |

FFmpeg is run as a separate process, so only its own binary is covered by its
license.

### A note on use

Spyder is a front-end for yt-dlp; it does not host, bypass, or decrypt
anything. Downloading may still breach a site's terms of service or copyright
law depending on the content and your country. That is on the person using it.

Removing a watermark does not remove the credit it stood for. A TikTok saved
through Spyder is still someone's work, and reposting it as your own is the
thing the watermark existed to prevent.

## Project layout

```
run_spyder.py        launcher / PyInstaller entry point
spyder/
  main.py            app bootstrap, Windows console suppression
  ui.py              MainWindow — widgets and signal wiring only
  theme.py           palette, the three type roles, the global stylesheet
  widgets.py         the blocky pieces Qt does not provide
  worker.py          QThread wrappers: ProbeWorker, DownloadWorker
  updater.py         GitHub checks, verified download, installer handoff
  update_worker.py   cancellable background update operations
  downloader.py      yt-dlp logic (Qt-free), presets, error translation
  platforms.py       which site a link is from, and what that changes
  icons.py           the line-art icon set, drawn with QPainter
  win32.py           what a frameless window owes Windows
  ffmpeg_tools.py    finding ffmpeg
  resources.py       finding bundled assets (icons)
logo.png             large source logo / preview
logo.ico             authored Windows icon sizes
logo.aseprite        editable pixel-art source
assets/              generated Spyder.ico + icon.png (gitignored)
Spyder.spec          PyInstaller spec
build.py             fetch ffmpeg + build app and installer in one command
installer/           Inno Setup script and installation marker
.github/workflows/   Windows build and GitHub release publishing
tests/               updater and UI regression tests
vendor/              ffmpeg.exe lands here (gitignored)
```

## The look

The design language is [kitty](https://github.com/goujandev/kitty)'s, ported to
Qt: neutral dark, rounded, and drawn entirely by the app.

**Nothing on screen is drawn by the OS.** Spyder has no title bar, because an
OS frame above a carefully made app looks like a web page in a picture frame.
A strip flush to the top carries the mark, what is downloading, and the three
window controls; everything else sits in one rounded canvas inset from the
edges, on a 4px dot texture.

Dropping the frame means owing the user everything it gave them, and that debt
is paid rather than ignored:

| What the frame did | Who does it now |
| --- | --- |
| Drag to move, with Aero Snap | `TitleBar`, via `startSystemMove` |
| Double-click to maximise | `TitleBar.doubleClicked` |
| Edge and corner resize | `EdgeResizer`, via `startSystemResize` |
| Keeping a maximised window off the taskbar | `win32.clamp_maximised` |
| Rounded outer corners | `win32.round_corners` |

**No blue in the greys.** A tint that reads as merely "cool" on one panel
becomes a colour cast across a window full of them, so the neutrals are true
neutrals and the only hue is the accent (`#2b948b`), spent on state: a focused
field, the chosen row, the primary button, the recognised platform.

**Four radii, not a value per element.** Every rounded thing picks one of
`R_XS`/`R_SM`/`R_MD`/`R_LG`, so two controls of the same weight cannot disagree
about how round they are.

Three consequences show up in the code. Every colour and font decision lives in
`theme.py` as one style sheet, so no widget carries its own styling. Because the
style allows no floating system windows, `widgets.py` reimplements the two
things Qt would otherwise float: the quality dropdown (`BlockSelect`, a menu
built from our own rows) and message boxes (`BlockDialog`, a panel washed over
the page). The folder picker stays native — that one is the OS's job.

Icons are drawn, not fetched. `icons.py` strokes each one on its own square
viewbox, the way kitty draws its SVGs, so they are identical on every machine
and take the app's line weight. The icon fonts this replaced — Segoe Fluent on
Windows 11, Segoe MDL2 on 10, neither anywhere else — needed a text fallback
for a case that could not be tested.

Type is Segoe UI Variable Text for the interface and Cascadia Mono for
everything technical: links, paths, sizes, speeds and the log.

## Why the modules split this way

`downloader.py` knows nothing about Qt and
`ui.py` never blocks. Every slow call — reading a link, downloading — happens on
a `QThread` and reports back through signals, so the window stays responsive.

`platforms.py` is the same idea applied to per-site behaviour. Rather than
scattering `if tiktok:` through the downloader and the window, each site is one
frozen `Platform` record carrying what it changes — the wording of the top
preset, whether watermarked formats are dropped, whether to prefer one finished
file over a merge. The two modules that care read those fields; adding a site is
an entry in a table. It is Qt-free and network-free, which is what lets the
window name a link on every keystroke without lagging.
