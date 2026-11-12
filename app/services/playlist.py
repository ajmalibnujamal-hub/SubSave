"""Playlist listing and bulk subtitle collection."""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from app.config import settings
from app.models import PlaylistInfo, ZipItem
from app.services import extractor
from app.services.extractor import as_dict, as_list, get_int, get_str
from app.services.subtitles import SubtitleResult, fetch_subtitle
from app.services.youtube import format_duration
from app.utils.errors import AppError
from app.utils.filenames import sanitize_filename
from app.utils.validators import is_valid_video_id

log = logging.getLogger("subsave.playlist")
_UNAVAILABLE_TITLES = ("[private video]", "[deleted video]")


def get_playlist(playlist_id: str) -> dict:
    limit = settings.max_playlist_videos
    info = extractor.extract_json(
        ["--flat-playlist", "--dump-single-json", "--skip-download", "--yes-playlist",
         "--playlist-end", str(limit), "--", f"https://www.youtube.com/playlist?list={playlist_id}"],
        timeout=settings.timeout_playlist,
    )
    entries = as_list(info.get("entries"))
    playlist_channel = get_str(info, "channel") or get_str(info, "uploader")
    videos: list[dict] = []
    seen: set[str] = set()
    skipped = 0
    for entry in entries:
        data = as_dict(entry)
        vid = data.get("id")
        title = get_str(data, "title")
        if not is_valid_video_id(vid) or title.lower() in _UNAVAILABLE_TITLES:
            skipped += 1
            continue
        if vid in seen:
            continue
        seen.add(vid)
        duration = get_int(data, "duration")
        videos.append({
            "video_id": vid,
            "title": title or "Untitled video",
            "channel": get_str(data, "channel") or get_str(data, "uploader") or playlist_channel,
            "duration": duration,
            "duration_text": format_duration(duration),
            "index": len(videos) + 1,
        })
        if len(videos) >= limit:
            break
    if not videos:
        raise AppError("EMPTY_PLAYLIST", "This playlist has no videos SubSave can read. It may be empty or private.", 404)
    declared = get_int(info, "playlist_count")
    truncated = len(videos) >= limit and (declared is None or declared > limit or len(entries) > limit)
    return PlaylistInfo(
        playlist_id=playlist_id,
        title=get_str(info, "title", "Untitled playlist"),
        channel=playlist_channel,
        videos=videos,
        skipped=skipped,
        truncated=truncated,
        limit=limit,
    ).model_dump()


@dataclass
class Collected:
    item: ZipItem
    result: SubtitleResult


def collect_subtitles(items: list[ZipItem], lang: str, kind: str, fmt: str) -> tuple[list[Collected], list[dict]]:
    """Fetch many subtitles with bounded concurrency and a total time budget. Never raises per-item."""
    unique: list[ZipItem] = []
    seen: set[str] = set()
    for item in items:
        if item.video_id not in seen:
            seen.add(item.video_id)
            unique.append(item)
    deadline = time.monotonic() + settings.zip_time_budget

    def work(item: ZipItem) -> SubtitleResult:
        remaining = deadline - time.monotonic()
        if remaining < 5:
            raise AppError("TIME_BUDGET", "Skipped because the time limit for this ZIP was reached. Select fewer videos.", 503)
        return fetch_subtitle(item.video_id, lang, kind, fmt, timeout=int(min(settings.timeout_subtitle, remaining)))

    with ThreadPoolExecutor(max_workers=settings.zip_workers) as pool:
        futures = [(item, pool.submit(work, item)) for item in unique]

    successes: list[Collected] = []
    failures: list[dict] = []
    for item, future in futures:
        try:
            successes.append(Collected(item, future.result()))
        except AppError as exc:
            failures.append({"video_id": item.video_id, "title": item.title or item.video_id, "code": exc.code, "message": exc.message})
        except Exception:  # noqa: BLE001 - never leak internals; log and report generically
            log.exception("unexpected failure collecting %s", item.video_id)
            failures.append({"video_id": item.video_id, "title": item.title or item.video_id, "code": "INTERNAL_ERROR", "message": "Unexpected error while processing this video."})
    return successes, failures


def entry_filename(position: int, collected: Collected) -> str:
    stem = sanitize_filename(collected.item.title, fallback=collected.item.video_id, max_len=70)
    return f"{position:03d} - {stem} [{collected.item.video_id}].{collected.result.lang}.{collected.result.fmt}"
