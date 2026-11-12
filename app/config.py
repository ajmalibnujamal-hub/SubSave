"""Runtime configuration, read from environment variables with safe bounds."""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


def _int_env(name: str, default: int, low: int, high: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(low, min(high, value))


@dataclass
class Settings:
    app_name: str = "SubSave"
    version: str = "3.0.0"
    max_playlist_videos: int = field(default_factory=lambda: _int_env("MAX_PLAYLIST_VIDEOS", 300, 1, 300))
    max_zip_videos: int = field(default_factory=lambda: _int_env("MAX_ZIP_VIDEOS", 100, 1, 100))
    max_body_bytes: int = field(default_factory=lambda: _int_env("MAX_BODY_BYTES", 65536, 1024, 1048576))
    timeout_inspect: int = field(default_factory=lambda: _int_env("YTDLP_TIMEOUT_INSPECT", 60, 5, 300))
    timeout_playlist: int = field(default_factory=lambda: _int_env("YTDLP_TIMEOUT_PLAYLIST", 90, 5, 600))
    timeout_subtitle: int = field(default_factory=lambda: _int_env("YTDLP_TIMEOUT_SUBTITLE", 60, 5, 300))
    max_concurrent_ytdlp: int = field(default_factory=lambda: _int_env("MAX_CONCURRENT_YTDLP", 4, 1, 16))
    zip_workers: int = field(default_factory=lambda: _int_env("ZIP_WORKERS", 3, 1, 8))
    zip_time_budget: int = field(default_factory=lambda: _int_env("ZIP_TIME_BUDGET", 85, 10, 3600))
    log_level: str = field(default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO").upper())
    temp_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("TEMP_DIR") or Path(tempfile.gettempdir()) / "subsave")
    )
    static_dir: Path = field(default_factory=lambda: Path(os.environ.get("STATIC_DIR") or ROOT_DIR / "static"))


settings = Settings()
