"""Subtitle fetching, WebVTT parsing, clean-up and SRT/VTT/TXT conversion."""
from __future__ import annotations

import html
import logging
import os
import re
import tempfile
from dataclasses import dataclass

from app.config import settings
from app.services import extractor
from app.utils.errors import AppError
from app.utils.validators import is_valid_lang, is_valid_video_id

log = logging.getLogger("subsave.subtitles")

_TS = r"(?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3}"
_TIMING_RE = re.compile(rf"^\s*({_TS})\s*-->\s*({_TS})")
_TAG_RE = re.compile(r"<[^>]*>")
_AUTO_STYLE_RE = re.compile(r"<\d{2}:\d{2}:\d{2}\.\d{3}><c>")
MAX_VTT_BYTES = 10 * 1024 * 1024
MEDIA_TYPES = {"srt": "application/x-subrip", "vtt": "text/vtt", "txt": "text/plain"}


@dataclass
class Cue:
    start: int  # milliseconds
    end: int
    lines: list[str]


@dataclass
class SubtitleResult:
    video_id: str
    lang: str
    fmt: str
    content: str
    cue_count: int


def parse_timestamp(value: str) -> int:
    parts = value.replace(",", ".").split(":")
    seconds = parts[-1]
    whole, _, frac = seconds.partition(".")
    minutes = int(parts[-2])
    hours = int(parts[-3]) if len(parts) == 3 else 0
    millis = int((frac + "000")[:3]) if frac else 0
    return ((hours * 60 + minutes) * 60 + int(whole)) * 1000 + millis


def _clean_line(line: str) -> str:
    text = html.unescape(_TAG_RE.sub("", line)).replace("\u00a0", " ")
    return re.sub(r"[ \t]+", " ", text).strip()


def parse_vtt(text: str) -> list[Cue]:
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    cues: list[Cue] = []
    for block in re.split(r"\n{2,}", text):
        lines = block.split("\n")
        for i, line in enumerate(lines[:2]):
            match = _TIMING_RE.match(line)
            if match:
                body = [c for c in (_clean_line(x) for x in lines[i + 1:]) if c]
                if body:
                    cues.append(Cue(parse_timestamp(match.group(1)), parse_timestamp(match.group(2)), body))
                break
    return cues


def _dedupe_rolling(cues: list[Cue]) -> list[Cue]:
    """YouTube auto-captions repeat the previous line in every cue; keep each line once."""
    out: list[Cue] = []
    previous: list[str] = []
    for cue in cues:
        fresh = [line for line in cue.lines if line not in previous]
        previous = cue.lines
        if fresh:
            out.append(Cue(cue.start, cue.end, fresh))
    for current, nxt in zip(out, out[1:]):
        if current.end > nxt.start > current.start:
            current.end = nxt.start
    return out


def process_vtt(text: str) -> list[Cue]:
    cues = parse_vtt(text)
    if _AUTO_STYLE_RE.search(text) or _looks_rolling(cues):
        cues = _dedupe_rolling(cues)
    return cues


def _looks_rolling(cues: list[Cue]) -> bool:
    return any(len(b.lines) > 1 and b.lines[0] == a.lines[-1] for a, b in zip(cues, cues[1:]))


def format_time(ms: int, sep: str) -> str:
    ms = max(0, ms)
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, milli = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{milli:03d}"


def to_srt(cues: list[Cue]) -> str:
    blocks = [
        f"{i}\n{format_time(c.start, ',')} --> {format_time(c.end, ',')}\n" + "\n".join(c.lines)
        for i, c in enumerate(cues, 1)
    ]
    return "\n\n".join(blocks) + "\n"


def to_vtt(cues: list[Cue]) -> str:
    blocks = [f"{format_time(c.start, '.')} --> {format_time(c.end, '.')}\n" + "\n".join(c.lines) for c in cues]
    return "WEBVTT\n\n" + "\n\n".join(blocks) + "\n"


def to_txt(cues: list[Cue]) -> str:
    lines: list[str] = []
    for cue in cues:
        for line in cue.lines:
            if not lines or lines[-1] != line:
                lines.append(line)
    return "\n".join(lines) + "\n"


def convert(vtt_text: str, fmt: str) -> tuple[str, int]:
    cues = process_vtt(vtt_text)
    if not cues:
        raise AppError("SUBTITLE_EMPTY", "YouTube returned a subtitle file with no text.", 404)
    writer = {"srt": to_srt, "vtt": to_vtt, "txt": to_txt}.get(fmt)
    if writer is None:
        raise AppError("INVALID_FORMAT", "Format must be srt, vtt or txt.", 400)
    return writer(cues), len(cues)


# ---- track selection ----------------------------------------------------------------------
_PRIORITY = ["en", "ml", "hi", "ar", "ta", "te", "kn"]


def track_sort_key(track: dict) -> tuple:
    base = track["code"].split("-")[0].lower()
    rank = _PRIORITY.index(base) if base in _PRIORITY else len(_PRIORITY)
    return (rank, track["name"].lower(), 0 if track["kind"] == "manual" else 1, track["code"])


def choose_default_track(tracks: list[dict]) -> dict | None:
    """English first: manual English, then original auto English, then any English, then the first useful track."""
    def english(t: dict) -> bool:
        return t["code"].lower() == "en" or t["code"].lower().startswith("en-")

    manual_en = [t for t in tracks if t["kind"] == "manual" and english(t)]
    if manual_en:
        pick = sorted(manual_en, key=lambda t: (t["code"] != "en", t["code"]))[0]
        return {"code": pick["code"], "kind": "manual", "reason": "English captions provided by the uploader"}
    auto_en = [t for t in tracks if t["kind"] == "auto" and english(t)]
    if auto_en:
        pick = sorted(auto_en, key=lambda t: (not t["code"].lower().endswith("-orig"), t["translated"], t["code"]))[0]
        reason = "Original English captions generated by YouTube" if not pick["translated"] else "English translation offered by YouTube"
        return {"code": pick["code"], "kind": "auto", "reason": reason}
    manual = [t for t in tracks if t["kind"] == "manual"]
    if manual:
        return {"code": manual[0]["code"], "kind": "manual", "reason": "No English captions; first available uploader captions"}
    originals = [t for t in tracks if t["kind"] == "auto" and not t["translated"]]
    if originals:
        return {"code": originals[0]["code"], "kind": "auto", "reason": "No English captions; original captions generated by YouTube"}
    return None


# ---- fetching -----------------------------------------------------------------------------
def lang_candidates(lang: str) -> list[str]:
    return ["en", "en-US", "en-GB", "en-orig"] if lang.lower() == "en" else [lang]


def fetch_subtitle(video_id: str, lang: str, kind: str, fmt: str, *, timeout: int | None = None) -> SubtitleResult:
    if not is_valid_video_id(video_id):
        raise AppError("INVALID_VIDEO_ID", "Invalid YouTube video ID.", 400)
    if not is_valid_lang(lang):
        raise AppError("INVALID_LANGUAGE", "Invalid language code.", 400)
    if kind not in ("manual", "auto", "best") or fmt not in MEDIA_TYPES:
        raise AppError("INVALID_REQUEST", "Invalid kind or format.", 400)
    candidates = lang_candidates(lang)
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="subsave-", dir=settings.temp_dir) as tmp:
        args = [
            "--skip-download", "--no-playlist", "--ignore-no-formats-error",
            "--sub-format", "vtt", "--sub-langs", ",".join(candidates),
            "-o", os.path.join(tmp, "%(id)s.%(ext)s"),
        ]
        if kind in ("manual", "best"):
            args.append("--write-subs")
        if kind in ("auto", "best"):
            args.append("--write-auto-subs")
        args += ["--", f"https://www.youtube.com/watch?v={video_id}"]

        result = extractor.run_ytdlp(args, timeout=timeout or settings.timeout_subtitle, cwd=tmp)
        found = None
        for candidate in candidates:
            path = os.path.join(tmp, f"{video_id}.{candidate}.vtt")
            if os.path.isfile(path):
                found = (candidate, path)
                break
        if found is None:
            known = extractor.match_known_error(result.stderr)
            if known:
                raise known
            if result.returncode != 0:
                raise extractor.classify_failure(result.stderr)
            raise AppError(
                "SUBTITLES_UNAVAILABLE",
                f"YouTube does not offer '{lang}' subtitles for this video. SubSave never creates subtitles that YouTube does not provide.",
                404,
            )
        used_lang, path = found
        if os.path.getsize(path) > MAX_VTT_BYTES:
            raise AppError("SUBTITLE_TOO_LARGE", "The subtitle file is unexpectedly large.", 413)
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            raw = handle.read()
    content, count = convert(raw, fmt)
    return SubtitleResult(video_id, used_lang, fmt, content, count)
