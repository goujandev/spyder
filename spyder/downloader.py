"""yt-dlp glue: probing a URL for available quality presets, and downloading.

This module is deliberately Qt-free so it can be exercised from a plain script.
Callers pass in plain callables for progress/log reporting; the Qt layer in
worker.py adapts those to signals.
"""

from __future__ import annotations

import importlib.util
import re
from dataclasses import dataclass
from typing import Callable

import yt_dlp

from . import platforms
from .ffmpeg_tools import find_ffmpeg, missing_ffmpeg_message
from .platforms import Platform

try:  # yt-dlp exposes this from 2023.07 onwards; fall back for older releases.
    from yt_dlp.utils import DownloadCancelled
except ImportError:  # pragma: no cover - depends on installed yt-dlp
    class DownloadCancelled(Exception):
        pass


# A long dropdown defeats the point of simple presets, so cap the number of
# per-resolution entries; the highest ones are kept.
MAX_QUALITY_ENTRIES = 8

# Friendlier names for the resolutions people recognise. Anything else falls
# back to a plain "<height>p".
LADDER_LABELS = {
    2160: "2160p (4K)",
    1440: "1440p (2K)",
    1080: "1080p (Full HD)",
    720: "720p (HD)",
    480: "480p",
    360: "360p",
}

# yt-dlp's own label for the stamped copies TikTok serves alongside the clean
# ones. "!*=" is "does not contain"; the "?" keeps formats carrying no note at
# all, which is nearly all of them.
NO_WATERMARK = "[format_note!*=?watermark]"

IMPERSONATION_HINT = (
    "This site turns away anything that does not look like a real browser, and "
    "Spyder cannot pose as one right now. Running from source? Install the "
    "missing piece with:  pip install curl_cffi"
)

_impersonation: bool | None = None


class SpyderError(Exception):
    """An error worth showing to the user verbatim."""


@dataclass(frozen=True)
class Preset:
    """One entry in the quality dropdown."""

    label: str
    format_selector: str
    audio_only: bool = False


@dataclass(frozen=True)
class VideoInfo:
    title: str
    duration: str
    uploader: str
    presets: list
    platform: Platform = platforms.GENERIC


def _format_duration(seconds) -> str:
    if not seconds:
        return "unknown length"
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _friendly_error(exc: Exception) -> str:
    """Turn a yt-dlp exception into something a non-technical user can act on."""
    text = str(exc)
    # yt-dlp prefixes messages with "ERROR: " and may embed ANSI colour codes.
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    text = re.sub(r"^ERROR:\s*", "", text).strip()

    lowered = text.lower()
    if "unsupported url" in lowered or "is not a valid url" in lowered:
        return "That link is not a video URL Spyder recognises. Check it and try again."
    if "video unavailable" in lowered or "private video" in lowered:
        return "This video is unavailable - it may be private, deleted, or region locked."
    if "sign in" in lowered or "age-restricted" in lowered:
        return (
            "This video requires signing in (age-restricted or members-only), "
            "so it cannot be downloaded."
        )
    if any(t in lowered for t in ("urlopen error", "timed out", "connection",
                                  "network", "getaddrinfo", "temporary failure")):
        return "Network problem - check your internet connection and try again."
    if "http error 404" in lowered:
        return "That page could not be found (404). Double-check the link."
    if "http error 403" in lowered:
        return (
            "The site refused the download (403). This is usually temporary - "
            "wait a moment and try again."
        )
    if "no space left" in lowered or "not enough space" in lowered:
        return "The drive is out of space. Free some room or pick another folder."
    if "permission denied" in lowered or "access is denied" in lowered:
        return "Spyder could not write to that folder. Pick a different output folder."
    return text or "Something went wrong."


def impersonation_available() -> bool:
    """Whether yt-dlp can currently pose as a real browser.

    TikTok answers everything else with a bot challenge, so without this the
    site is effectively shut. yt-dlp gets the ability from curl_cffi, which the
    built exe bundles and a source checkout may not have.
    """
    global _impersonation
    if _impersonation is None:
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
                _impersonation = bool(ydl._get_available_impersonate_targets())
        except Exception:  # noqa: BLE001 - a private API; treat absence as absence
            _impersonation = importlib.util.find_spec("curl_cffi") is not None
    return _impersonation


def _is_watermarked(fmt: dict) -> bool:
    return "watermark" in (fmt.get("format_note") or "").lower()


def _selector(platform: Platform, height: int = 0, audio_only: bool = False) -> str:
    """Compose the yt-dlp format selector for one preset on one platform."""
    clean = NO_WATERMARK if platform.drop_watermarked else ""
    limit = f"[height<={height}]" if height else ""

    if audio_only:
        # A site with no audio-only stream still has audio inside its video.
        return f"ba{clean}/b{clean}"

    parts = f"bv*{clean}{limit}+ba{clean}"  # video and audio fetched separately
    whole = f"b{clean}{limit}"              # one file with both already in it

    if platform.prefer_progressive:
        return f"{whole}/{parts}"

    ladder = f"{parts}/{whole}"
    if height:
        # Last resort for a source whose only format is taller than the rung
        # asked for: better the wrong size than nothing.
        return f"{ladder}/wv*{clean}+ba{clean}/w{clean}"
    return ladder


def _quality_ladder(formats: list) -> dict:
    """Map each video height the source offers to the name people give it.

    Portrait video is named by its short side - a 1080x1920 TikTok is a "1080p"
    video, not a "1920p" one - so the label comes from the narrower dimension
    while the key stays height, the field a format filter can actually test.
    """
    named = {}
    for fmt in formats:
        if fmt.get("vcodec") in (None, "none"):
            continue
        height = fmt.get("height")
        if not height:
            continue
        width = fmt.get("width")
        side = min(height, width) if width else height
        named[height] = LADDER_LABELS.get(side, f"{side}p")

    ladder = {}
    for height in sorted(named, reverse=True):
        label = named[height]
        # Two heights can share a name - 1080x1920 and 1080x1080 are both
        # "1080p" - and the taller one, reached first, is the better stream.
        if label not in ladder.values():
            ladder[height] = label
    return ladder


def build_presets(info: dict, platform: Platform = platforms.GENERIC) -> list:
    """Work out which simple presets this URL can actually deliver."""
    formats = info.get("formats") or []
    if platform.drop_watermarked:
        # Dropped here as well as in the selector, so a watermarked-only height
        # never appears in the dropdown as a rung that cannot be delivered.
        formats = [f for f in formats if not _is_watermarked(f)]

    # One entry per quality the source genuinely offers. Deriving the list from
    # the real formats rather than a fixed ladder avoids offering two rungs
    # that would download the same stream.
    ladder = _quality_ladder(formats)
    has_audio = any(f.get("acodec") not in (None, "none") for f in formats)

    presets = []

    if ladder:
        presets.append(Preset(platform.best_label, _selector(platform)))
        # A source with one quality needs no ladder underneath "best": both
        # rows would fetch the same file.
        if len(ladder) > 1:
            for height, label in list(ladder.items())[:MAX_QUALITY_ENTRIES]:
                presets.append(Preset(label, _selector(platform, height=height)))

    if has_audio:
        presets.append(
            Preset(
                "Audio only (MP3, 320 kbps)",
                _selector(platform, audio_only=True),
                audio_only=True,
            )
        )

    if not presets:
        if platform.drop_watermarked and (info.get("formats") or []):
            raise SpyderError(
                "Every copy of this video carries a watermark, so there is "
                "nothing clean for Spyder to download."
            )
        raise SpyderError("No downloadable video or audio was found at that link.")

    return presets


def probe(url: str) -> VideoInfo:
    """Fetch metadata and available presets. Blocking - call from a worker."""
    url = url.strip()
    if not url:
        raise SpyderError("Paste a video link first.")
    if not re.match(r"^https?://", url, re.IGNORECASE):
        raise SpyderError(
            "That does not look like a link. It should start with http:// or https://."
        )

    # Free, offline, and right often enough to shape the request before it is
    # made; the extractor that answers gets the final say below.
    platform = platforms.detect(url)

    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:  # noqa: BLE001 - never let the worker die unexplained
        message = _friendly_error(exc)
        # The site's rejection is real but its wording explains nothing; the
        # reason Spyder was turned away is the missing impersonation.
        if platform.needs_impersonation and not impersonation_available():
            message = IMPERSONATION_HINT
        raise SpyderError(message) from exc

    if info is None:
        raise SpyderError("Nothing could be read from that link.")

    # A playlist URL still resolves. v1 handles single videos only, so take the
    # first entry; the UI tells the user that is what happened.
    if info.get("_type") == "playlist":
        entries = [e for e in (info.get("entries") or []) if e]
        if not entries:
            raise SpyderError("That link is a playlist with no playable videos.")
        info = entries[0]

    # The extractor that answered knows what the site is, which beats a guess
    # from the hostname - shorteners and embeds only reveal themselves here.
    resolved = platforms.from_extractor(info.get("extractor_key") or "")
    if not resolved.recognised:
        resolved = platform

    return VideoInfo(
        title=info.get("title") or "Untitled",
        duration=_format_duration(info.get("duration")),
        # The platform is named on its own now, so falling back to the
        # extractor here would print it twice.
        uploader=info.get("uploader") or "",
        presets=build_presets(info, resolved),
        platform=resolved,
    )


def download(
    url: str,
    preset: Preset,
    output_dir: str,
    on_progress: Callable[[dict], None],
    on_log: Callable[[str], None],
    is_cancelled: Callable[[], bool],
) -> str:
    """Download the URL into output_dir and return the final file path.

    Blocking - call from a worker thread.
    """
    ffmpeg_path = find_ffmpeg()
    if ffmpeg_path is None:
        raise SpyderError(missing_ffmpeg_message())

    finished = {"path": ""}

    def hook(status: dict) -> None:
        if is_cancelled():
            raise DownloadCancelled("Cancelled by user.")
        on_progress(status)
        if status.get("status") == "finished":
            finished["path"] = status.get("filename", "") or finished["path"]

    # yt-dlp starts a postprocessor once per stream, so a merge or an audio
    # extraction can announce itself several times for one download. The user
    # only needs to be told the stage began.
    announced: set[str] = set()

    def postprocessor_hook(status: dict) -> None:
        if is_cancelled():
            raise DownloadCancelled("Cancelled by user.")
        name = status.get("postprocessor", "")
        if status.get("status") == "started" and name not in announced:
            announced.add(name)
            if name == "Merger":
                on_log("merging video and audio")
            elif name in ("FFmpegExtractAudio", "ExtractAudio"):
                on_log("converting to mp3")
        elif status.get("status") == "finished":
            info = status.get("info_dict") or {}
            path = info.get("filepath") or info.get("_filename")
            if path:
                finished["path"] = path

    opts = {
        "outtmpl": {"default": output_dir.rstrip("/\\") + "/%(title)s.%(ext)s"},
        "format": preset.format_selector,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "ffmpeg_location": ffmpeg_path,
        "progress_hooks": [hook],
        "postprocessor_hooks": [postprocessor_hook],
        "windowsfilenames": True,
        "retries": 3,
        "fragment_retries": 3,
    }

    if preset.audio_only:
        opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "320",
            }
        ]
    else:
        opts["merge_output_format"] = "mp4"

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except DownloadCancelled:
        raise
    except Exception as exc:  # noqa: BLE001
        # A cancel raised inside a hook can surface wrapped in DownloadError.
        if is_cancelled():
            raise DownloadCancelled("Cancelled by user.") from exc
        raise SpyderError(_friendly_error(exc)) from exc

    if isinstance(info, dict):
        requested = info.get("requested_downloads") or []
        path = info.get("filepath") or (requested[0].get("filepath") if requested else None)
        if path:
            finished["path"] = path

    return finished["path"]
