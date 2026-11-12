"""Video inspection: build a validated description of one video and its caption tracks."""
from __future__ import annotations

from app.config import settings
from app.models import VideoInfo
from app.services import extractor
from app.services.extractor import as_dict, as_list, get_int, get_str
from app.services.subtitles import choose_default_track, track_sort_key
from app.utils.errors import AppError
from app.utils.validators import is_valid_video_id

LANG_NAMES = {
    "en": "English", "ml": "Malayalam", "hi": "Hindi", "ar": "Arabic", "ta": "Tamil", "te": "Telugu",
    "kn": "Kannada", "bn": "Bengali", "mr": "Marathi", "gu": "Gujarati", "pa": "Punjabi", "ur": "Urdu",
    "es": "Spanish", "fr": "French", "de": "German", "pt": "Portuguese", "ru": "Russian", "ja": "Japanese",
    "ko": "Korean", "zh": "Chinese", "id": "Indonesian", "tr": "Turkish", "it": "Italian",
}


def format_duration(seconds: int | None) -> str:
    if seconds is None:
        return ""
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _track(code: str, formats: object, kind: str) -> dict:
    entries = [f for f in as_list(formats) if isinstance(f, dict)]
    name = next((get_str(f, "name") for f in entries if get_str(f, "name")), "")
    name = name or LANG_NAMES.get(code.split("-")[0].lower(), code)
    translated = kind == "auto" and any("tlang=" in get_str(f, "url") for f in entries)
    label = "Manual" if kind == "manual" else ("Auto-translated" if translated else "Auto-generated")
    return {"code": code, "name": name, "kind": kind, "translated": translated, "kind_label": label}


def build_tracks(info: dict) -> list[dict]:
    tracks: list[dict] = []
    for code, formats in as_dict(info.get("subtitles")).items():
        if isinstance(code, str) and code != "live_chat":
            tracks.append(_track(code, formats, "manual"))
    for code, formats in as_dict(info.get("automatic_captions")).items():
        if isinstance(code, str):
            tracks.append(_track(code, formats, "auto"))
    return sorted(tracks, key=track_sort_key)


def inspect_video(video_id: str) -> dict:
    if not is_valid_video_id(video_id):
        raise AppError("INVALID_VIDEO_ID", "Invalid YouTube video ID.", 400)
    info = extractor.extract_json(
        ["--dump-single-json", "--skip-download", "--no-playlist", "--ignore-no-formats-error",
         "--", f"https://www.youtube.com/watch?v={video_id}"],
        timeout=settings.timeout_inspect,
    )
    if info.get("_type") == "playlist" or not get_str(info, "id"):
        raise AppError("INVALID_JSON", "YouTube returned an unexpected response for this video.", 503)
    duration = get_int(info, "duration")
    tracks = build_tracks(info)
    model = VideoInfo(
        video_id=video_id,
        title=get_str(info, "title", "Untitled video"),
        channel=get_str(info, "channel") or get_str(info, "uploader", "Unknown channel"),
        duration=duration,
        duration_text=format_duration(duration),
        thumbnail=f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        url=f"https://www.youtube.com/watch?v={video_id}",
        is_live=bool(info.get("is_live")),
        tracks=tracks,
        default_track=choose_default_track(tracks),
    )
    return model.model_dump()
