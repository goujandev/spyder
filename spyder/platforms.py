"""Which site a link points at, and what that follows for the download.

Detection is a hostname lookup, so it is instant and offline: the moment a link
lands in the URL field Spyder can name the site and pick its defaults without
touching the network. Everything that varies per site lives on the Platform
record rather than in branches elsewhere, so teaching Spyder a new one is an
entry in _HOSTS and nothing else.

Qt-free, like downloader.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Platform:
    """One site, and the download rules that follow from it."""

    key: str
    name: str

    # The wording of the top preset. Sites where "best" carries a caveat worth
    # spelling out - TikTok's missing watermark - override it.
    best_label: str = "Best available quality"

    # TikTok publishes every video twice: once clean, once stamped with a
    # drifting @handle. The stamped copy is sometimes the *higher* resolution,
    # so it has to be filtered out rather than merely outranked.
    drop_watermarked: bool = False

    # Sites that publish one finished file per quality, video and audio already
    # muxed together. Asking for separate streams there wins no quality and
    # risks pairing the video with a different audio track, so take the file.
    prefer_progressive: bool = False

    # Sites that serve a bot challenge to any client that does not look like a
    # real browser. yt-dlp can impersonate one, but only with curl_cffi
    # installed - see downloader.impersonation_available().
    needs_impersonation: bool = False

    @property
    def recognised(self) -> bool:
        """Whether Spyder can put a name to this link."""
        return bool(self.name)


# The fallback: no name, no special rules, and every default left alone. It is
# a singleton because detect() returning it is what "unrecognised" means.
GENERIC = Platform(key="", name="")

TIKTOK = Platform(
    key="tiktok",
    name="TikTok",
    best_label="Best quality, no watermark",
    drop_watermarked=True,
    prefer_progressive=True,
    needs_impersonation=True,
)

# Sites Spyder has no special rules for, listed only so it can name them. The
# generic path already downloads them correctly.
YOUTUBE = Platform(key="youtube", name="YouTube")
INSTAGRAM = Platform(key="instagram", name="Instagram")
TWITTER = Platform(key="twitter", name="X")
REDDIT = Platform(key="reddit", name="Reddit")
FACEBOOK = Platform(key="facebook", name="Facebook")
VIMEO = Platform(key="vimeo", name="Vimeo")
TWITCH = Platform(key="twitch", name="Twitch")
SOUNDCLOUD = Platform(key="soundcloud", name="SoundCloud")
DAILYMOTION = Platform(key="dailymotion", name="Dailymotion")

ALL = (
    TIKTOK,
    YOUTUBE,
    INSTAGRAM,
    TWITTER,
    REDDIT,
    FACEBOOK,
    VIMEO,
    TWITCH,
    SOUNDCLOUD,
    DAILYMOTION,
)

# Registrable domains, without "www." and without subdomains: the lookup walks
# a host inwards, so one entry covers vm.tiktok.com, m.tiktok.com and the rest.
_HOSTS = {
    "tiktok.com": TIKTOK,
    "tiktokv.com": TIKTOK,
    "youtube.com": YOUTUBE,
    "youtu.be": YOUTUBE,
    "youtube-nocookie.com": YOUTUBE,
    "instagram.com": INSTAGRAM,
    "instagr.am": INSTAGRAM,
    "twitter.com": TWITTER,
    "x.com": TWITTER,
    "t.co": TWITTER,
    "reddit.com": REDDIT,
    "redd.it": REDDIT,
    "facebook.com": FACEBOOK,
    "fb.watch": FACEBOOK,
    "vimeo.com": VIMEO,
    "twitch.tv": TWITCH,
    "soundcloud.com": SOUNDCLOUD,
    "dailymotion.com": DAILYMOTION,
    "dai.ly": DAILYMOTION,
}


def _hostname(url: str) -> str:
    url = url.strip()
    if not url:
        return ""
    # urlsplit only fills in the host when there is a scheme or a leading "//",
    # and this runs against a field the user is still typing into.
    if "//" not in url:
        url = "//" + url
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def detect(url: str) -> Platform:
    """Name the site behind a URL. Offline, and cheap enough for every keystroke."""
    host = _hostname(url)
    if not host:
        return GENERIC

    parts = host.split(".")
    # Walk the host inwards so vm.tiktok.com and www.tiktok.com both land on
    # tiktok.com, while tiktok.com.example.net - which is example.net - does not.
    for start in range(len(parts) - 1):
        found = _HOSTS.get(".".join(parts[start:]))
        if found is not None:
            return found
    return GENERIC


def from_extractor(name: str) -> Platform:
    """Name the site from the extractor yt-dlp actually used.

    The host table only knows the links people paste. This runs afterwards and
    catches the rest - shorteners, embeds, and the several hundred sites Spyder
    has no entry for but yt-dlp can still name.
    """
    key = re.sub(r"[^a-z0-9]", "", (name or "").lower())
    if not key:
        return GENERIC
    for platform in ALL:
        # "TikTok", "TikTokUser" and "TikTokLive" are all TikTok.
        if key.startswith(platform.key):
            return platform
    # Known by name only: generic rules, wearing the label yt-dlp gave it.
    return replace(GENERIC, name=name)


def looks_complete(url: str) -> bool:
    """Whether a URL is finished enough to be worth sending to yt-dlp.

    This gates the automatic fetch. A link typed by hand passes through a
    hundred invalid prefixes on its way to being valid, and each one that
    reached the network would be a wasted request and a spurious error.
    """
    url = url.strip()
    if not re.match(r"^https?://", url, re.IGNORECASE):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    # A bare domain is a home page, not a video, so something has to follow it.
    return "." in (parts.hostname or "") and bool(parts.path.strip("/") or parts.query)
