"""Strict YouTube URL parsing. Only canonical URLs built from validated IDs ever reach yt-dlp."""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from app.utils.errors import AppError

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
PLAYLIST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,64}$")
LANG_RE = re.compile(r"^[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{2,8}){0,3}$")

ALLOWED_HOSTS = frozenset(
    {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "www.youtu.be"}
)
_VIDEO_PATH_PREFIXES = {"shorts", "live", "embed", "v"}
_CONTROL_OR_SPACE = re.compile(r"[\x00-\x20\x7f]")


@dataclass(frozen=True)
class ParsedUrl:
    kind: str  # "video" or "playlist"
    video_id: str | None
    playlist_id: str | None

    @property
    def canonical_url(self) -> str:
        if self.kind == "video" and self.video_id:
            return f"https://www.youtube.com/watch?v={self.video_id}"
        return f"https://www.youtube.com/playlist?list={self.playlist_id}"


def is_valid_video_id(value: object) -> bool:
    return isinstance(value, str) and bool(VIDEO_ID_RE.match(value))


def is_valid_lang(value: object) -> bool:
    return isinstance(value, str) and bool(LANG_RE.match(value))


def _invalid(message: str = "Paste a YouTube video or playlist link.") -> AppError:
    return AppError("INVALID_URL", message, 400)


def _check_playlist_id(playlist_id: str | None) -> str | None:
    """Return a usable playlist ID, None when unusable, or raise for known-unsupported lists."""
    if playlist_id in {"WL", "LL"}:
        raise AppError("PLAYLIST_PRIVATE", "Watch Later and Liked videos are private playlists. SubSave cannot open them.", 403)
    if not playlist_id or not PLAYLIST_ID_RE.match(playlist_id):
        return None
    if playlist_id.startswith("RD"):
        return None  # auto-generated Mix: dynamic and effectively endless
    return playlist_id


def parse_youtube_url(raw: object) -> ParsedUrl:
    if not isinstance(raw, str):
        raise _invalid()
    text = raw.strip()
    if not text or len(text) > 2048 or _CONTROL_OR_SPACE.search(text):
        raise _invalid()
    if "://" not in text:
        text = "https://" + text
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        raise _invalid() from None
    if parts.scheme not in ("http", "https") or parts.username or parts.password:
        raise _invalid()
    if port not in (None, 80, 443):
        raise _invalid()
    host = (parts.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise _invalid("Only youtube.com and youtu.be links are supported.")

    query = parse_qs(parts.query)
    segments = [s for s in parts.path.split("/") if s]
    video_id: str | None = None

    if host in ("youtu.be", "www.youtu.be"):
        video_id = segments[0] if segments else None
    elif segments and segments[0] == "watch":
        video_id = (query.get("v") or [None])[0]
    elif len(segments) >= 2 and segments[0] in _VIDEO_PATH_PREFIXES:
        video_id = segments[1]

    list_param = (query.get("list") or [None])[0]
    playlist_id = _check_playlist_id(list_param)

    if video_id is not None and is_valid_video_id(video_id):
        return ParsedUrl("video", video_id, playlist_id)
    if playlist_id and (segments[:1] == ["playlist"] or segments[:1] == ["watch"]):
        return ParsedUrl("playlist", None, playlist_id)
    if list_param and list_param.startswith("RD"):
        raise _invalid("YouTube Mix playlists are generated on the fly and are not supported. Paste a single video or a regular playlist.")
    raise _invalid("This link does not point to a YouTube video or playlist.")
