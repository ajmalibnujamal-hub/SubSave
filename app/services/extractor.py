"""Safe yt-dlp runner: argument lists only, captured output, validated JSON, mapped errors."""
from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import Any

from app.config import settings
from app.utils.errors import AppError

log = logging.getLogger("subsave.extractor")
_slots = threading.BoundedSemaphore(settings.max_concurrent_ytdlp)


# ---- defensive accessors: never call .get() on something that might be None -------------
def as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def get_str(data: Any, key: str, default: str = "") -> str:
    value = as_dict(data).get(key)
    return value.strip() if isinstance(value, str) and value.strip() else default


def get_int(data: Any, key: str) -> int | None:
    value = as_dict(data).get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value >= 0:
        return int(value)
    return None


# ---- error mapping ----------------------------------------------------------------------
# (substrings to look for in lower-cased stderr, code, HTTP status, user message). Order matters.
_KNOWN_ERRORS: list[tuple[tuple[str, ...], str, int, str]] = [
    (("no module named yt_dlp", "no module named 'yt_dlp'"), "DEPENDENCY_MISSING", 503,
     "The subtitle engine (yt-dlp) is not installed on this server."),
    (("not a bot", "confirm you\u2019re not a bot", "confirm you're not a bot"), "BOT_CHECK", 503,
     "YouTube is asking this server to confirm it is not a bot, so it cannot read this video right now. Try again later or run SubSave from your own computer."),
    (("http error 429", "too many requests"), "RATE_LIMITED", 429,
     "YouTube is limiting requests from this server. Wait a few minutes and try again."),
    (("private video", "video is private"), "VIDEO_PRIVATE", 403,
     "This video is private. SubSave cannot access private videos."),
    (("confirm your age", "age-restricted", "inappropriate for some users"), "AGE_RESTRICTED", 403,
     "This video is age-restricted and requires a signed-in account. SubSave does not bypass age checks."),
    (("members-only", "join this channel"), "MEMBERS_ONLY", 403,
     "This video is for channel members only. SubSave cannot access it."),
    (("not available in your country", "blocked it in your country", "blocked it on copyright"), "GEO_BLOCKED", 403,
     "This video is not available from the server's region."),
    (("live event will begin", "premieres in", "this live event"), "VIDEO_NOT_READY", 409,
     "This is an upcoming live stream or premiere. Subtitles are not available yet."),
    (("playlist does not exist", "this playlist is private"), "PLAYLIST_NOT_FOUND", 404,
     "This playlist does not exist or is private."),
    (("video unavailable", "this video is unavailable", "this video is not available", "has been removed",
      "account associated with this video has been terminated"), "VIDEO_UNAVAILABLE", 404,
     "This video is unavailable. It may have been removed or made private."),
    (("unable to download webpage", "temporary failure in name resolution", "connection reset",
      "network is unreachable", "connection refused", "remote end closed", "timed out",
      "failed to resolve", "name or service not known", "transporterror"), "NETWORK_ERROR", 503,
     "The server could not reach YouTube. Try again in a moment."),
]


def match_known_error(stderr: str) -> AppError | None:
    text = (stderr or "").lower()
    for needles, code, status, message in _KNOWN_ERRORS:
        if any(n in text for n in needles):
            return AppError(code, message, status)
    return None


def classify_failure(stderr: str, default_code: str = "EXTRACTION_FAILED") -> AppError:
    return match_known_error(stderr) or AppError(
        default_code, "YouTube data could not be retrieved for this link. Try again later.", 503
    )


# ---- running yt-dlp ---------------------------------------------------------------------
@dataclass
class RunResult:
    returncode: int
    stdout: str
    stderr: str


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value if isinstance(value, str) else ""


def base_command() -> list[str]:
    cache_dir = settings.temp_dir / "ytdlp-cache"
    return [
        sys.executable, "-m", "yt_dlp",
        "--no-config", "--no-color", "--cache-dir", str(cache_dir),
        "--socket-timeout", "20", "--retries", "2", "--extractor-retries", "2",
    ]


def run_ytdlp(args: list[str], *, timeout: int, cwd: str | None = None) -> RunResult:
    """Run yt-dlp with an argument list (never a shell string) and capture both streams."""
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    cmd = [*base_command(), *args]
    with _slots:
        try:
            proc = subprocess.run(  # noqa: S603 - argument list, shell disabled
                cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=timeout, cwd=cwd, stdin=subprocess.DEVNULL, check=False,
            )
        except subprocess.TimeoutExpired:
            log.warning("yt-dlp timed out after %ss", timeout)
            raise AppError("TIMEOUT", "YouTube took too long to respond. Try again.", 504) from None
        except OSError as exc:
            log.error("cannot start yt-dlp: %s", exc)
            raise AppError("DEPENDENCY_MISSING", "The subtitle engine (yt-dlp) could not be started on this server.", 503) from None
    result = RunResult(int(getattr(proc, "returncode", 1)), _text(proc.stdout), _text(proc.stderr))
    if result.returncode != 0 or result.stderr:
        log.info("yt-dlp rc=%s stderr=%s", result.returncode, result.stderr.strip()[-1500:])
    return result


def parse_json_output(stdout: Any) -> dict:
    """Return the JSON object printed by yt-dlp, or raise AppError. Rejects null, lists and scalars."""
    if not isinstance(stdout, str) or not stdout.strip():
        raise AppError("EMPTY_OUTPUT", "YouTube returned no data for this link.", 503)
    text = stdout.strip()
    data: Any = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        for line in reversed(text.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    data = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
        else:
            raise AppError("INVALID_JSON", "YouTube returned data that could not be read.", 503) from None
    if not isinstance(data, dict):
        raise AppError("INVALID_JSON", "YouTube returned an unexpected response.", 503)
    return data


def extract_json(args: list[str], *, timeout: int) -> dict:
    result = run_ytdlp(args, timeout=timeout)
    if result.returncode != 0:
        raise classify_failure(result.stderr)
    try:
        return parse_json_output(result.stdout)
    except AppError as exc:
        known = match_known_error(result.stderr)
        raise known or exc
