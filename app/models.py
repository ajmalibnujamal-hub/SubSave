"""Pydantic request and response models."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import settings
from app.utils.validators import is_valid_lang, is_valid_video_id

Kind = Literal["manual", "auto", "best"]
Fmt = Literal["srt", "vtt", "txt"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class InspectRequest(_Strict):
    url: str = Field(min_length=1, max_length=2048)


class PlaylistRequest(InspectRequest):
    pass


class _SubtitleChoice(_Strict):
    lang: str = "en"
    kind: Kind = "best"
    format: Fmt = "srt"

    @field_validator("lang")
    @classmethod
    def _lang(cls, value: str) -> str:
        if not is_valid_lang(value):
            raise ValueError("lang must be a language code such as en, ml or zh-Hans")
        return value


class DownloadRequest(_SubtitleChoice):
    video_id: str
    title: str | None = Field(default=None, max_length=300)

    @field_validator("video_id")
    @classmethod
    def _video_id(cls, value: str) -> str:
        if not is_valid_video_id(value):
            raise ValueError("video_id must be an 11-character YouTube video ID")
        return value


class ZipItem(_Strict):
    video_id: str
    title: str | None = Field(default=None, max_length=300)

    @field_validator("video_id")
    @classmethod
    def _video_id(cls, value: str) -> str:
        if not is_valid_video_id(value):
            raise ValueError("video_id must be an 11-character YouTube video ID")
        return value


class ZipRequest(_SubtitleChoice):
    items: list[ZipItem] = Field(min_length=1, max_length=settings.max_zip_videos)


class Track(BaseModel):
    code: str
    name: str
    kind: Literal["manual", "auto"]
    translated: bool = False
    kind_label: str


class DefaultTrack(BaseModel):
    code: str
    kind: Literal["manual", "auto"]
    reason: str


class VideoInfo(BaseModel):
    video_id: str
    title: str
    channel: str
    duration: int | None = None
    duration_text: str = ""
    thumbnail: str
    url: str
    is_live: bool = False
    tracks: list[Track]
    default_track: DefaultTrack | None = None


class PlaylistVideo(BaseModel):
    video_id: str
    title: str
    channel: str = ""
    duration: int | None = None
    duration_text: str = ""
    index: int


class PlaylistInfo(BaseModel):
    playlist_id: str
    title: str
    channel: str = ""
    videos: list[PlaylistVideo]
    skipped: int = 0
    truncated: bool = False
    limit: int
