"""FastAPI application: routing, error handling, security headers and static serving."""
from __future__ import annotations

import importlib.util
import logging
import mimetypes
import shutil
import time
from contextlib import asynccontextmanager
from importlib import metadata
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.models import DownloadRequest, InspectRequest, PlaylistRequest, ZipRequest
from app.services import archive, playlist, youtube
from app.services.subtitles import MEDIA_TYPES, fetch_subtitle
from app.utils.errors import AppError
from app.utils.filenames import content_disposition, sanitize_filename
from app.utils.validators import parse_youtube_url

logging.basicConfig(level=getattr(logging, settings.log_level, logging.INFO), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("subsave")
mimetypes.add_type("application/manifest+json", ".webmanifest")

CSP = (
    "default-src 'self'; img-src 'self' https://i.ytimg.com data:; "
    "style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
    "script-src 'self'; connect-src 'self'; manifest-src 'self'; worker-src 'self'; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


def clean_stale_temp_dirs(max_age_seconds: int = 3600) -> None:
    if not settings.temp_dir.is_dir():
        return
    cutoff = time.time() - max_age_seconds
    for path in settings.temp_dir.glob("subsave-*"):
        try:
            if path.is_dir() and path.stat().st_mtime < cutoff:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            continue


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    clean_stale_temp_dirs()
    log.info("SubSave %s started (temp dir: %s)", settings.version, settings.temp_dir)
    yield


app = FastAPI(title="SubSave", version=settings.version, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


def ok(data: Any) -> JSONResponse:
    return JSONResponse({"ok": True, "data": data})


def error_response(error: AppError) -> JSONResponse:
    return JSONResponse(error.to_payload(), status_code=error.status)


@app.middleware("http")
async def guard(request: Request, call_next):
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > settings.max_body_bytes:
        return error_response(AppError("REQUEST_TOO_LARGE", "The request is too large.", 413))
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = CSP
    path = request.url.path
    if path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    elif path in ("/sw.js", "/manifest.webmanifest", "/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.exception_handler(AppError)
async def _app_error(_: Request, exc: AppError):
    return error_response(exc)


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(p) for p in first.get("loc", ()) if p != "body") or "request"
    message = f"Invalid {field}: {str(first.get('msg', 'invalid value')).removeprefix('Value error, ')}"
    return error_response(AppError("INVALID_REQUEST", message[:300], 422))


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException):
    if request.url.path.startswith("/api/"):
        code = "NOT_FOUND" if exc.status_code == 404 else "METHOD_NOT_ALLOWED" if exc.status_code == 405 else "HTTP_ERROR"
        return error_response(AppError(code, "Unknown API endpoint or method.", exc.status_code))
    return Response("Not found" if exc.status_code == 404 else "Error", status_code=exc.status_code, media_type="text/plain")


@app.exception_handler(Exception)
async def _unexpected(request: Request, exc: Exception):
    log.error("unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
    return error_response(AppError("INTERNAL_ERROR", "Something went wrong on the server. Please try again.", 500))


# ---- API ----------------------------------------------------------------------------------
@app.get("/api/health")
def health():
    installed = importlib.util.find_spec("yt_dlp") is not None
    version = None
    if installed:
        try:
            version = metadata.version("yt-dlp")
        except metadata.PackageNotFoundError:
            version = None
    return ok({"status": "ok", "app": settings.app_name, "version": settings.version, "yt_dlp_installed": installed, "yt_dlp_version": version})


@app.post("/api/inspect")
def inspect(req: InspectRequest):
    parsed = parse_youtube_url(req.url)
    if parsed.kind == "playlist":
        return ok({"kind": "playlist", "playlist_id": parsed.playlist_id, "video": None})
    return ok({"kind": "video", "playlist_id": parsed.playlist_id, "video": youtube.inspect_video(parsed.video_id)})


@app.post("/api/playlist")
def playlist_endpoint(req: PlaylistRequest):
    parsed = parse_youtube_url(req.url)
    if not parsed.playlist_id:
        raise AppError("INVALID_URL", "This link does not contain a playlist.", 400)
    return ok(playlist.get_playlist(parsed.playlist_id))


@app.post("/api/download")
def download(req: DownloadRequest):
    result = fetch_subtitle(req.video_id, req.lang, req.kind, req.format)
    stem = sanitize_filename(req.title, fallback=req.video_id, max_len=80)
    filename = f"{stem} [{req.video_id}].{result.lang}.{result.fmt}"
    return Response(
        content=result.content.encode("utf-8"),
        media_type=f"{MEDIA_TYPES[result.fmt]}; charset=utf-8",
        headers={"Content-Disposition": content_disposition(filename), "Cache-Control": "no-store", "X-Subsave-Lang": result.lang},
    )


@app.post("/api/download-zip")
def download_zip(req: ZipRequest):
    successes, failures = playlist.collect_subtitles(req.items, req.lang, req.kind, req.format)
    if not successes:
        raise AppError("ZIP_ALL_FAILED", "No subtitles could be downloaded for the selected videos.", 422, {"failures": failures})
    files = [(playlist.entry_filename(i, c), c.result.content) for i, c in enumerate(successes, 1)]
    data = archive.build_zip(files, archive.build_report(len(successes), failures, req.lang, req.format))
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": content_disposition(f"SubSave {req.lang} {req.format}.zip"),
            "Cache-Control": "no-store",
            "X-Subsave-Succeeded": str(len(successes)),
            "X-Subsave-Failed": str(len(failures)),
            "X-Subsave-Failed-Ids": ",".join(f["video_id"] for f in failures),
        },
    )


if settings.static_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(settings.static_dir), html=True), name="static")
