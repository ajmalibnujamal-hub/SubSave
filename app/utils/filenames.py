"""Filename sanitising and Content-Disposition helpers (Unicode-safe, no path traversal)."""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import quote

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def sanitize_filename(name: object, fallback: str = "subtitles", max_len: int = 80) -> str:
    text = name if isinstance(name, str) else ""
    text = unicodedata.normalize("NFC", text)
    text = _ILLEGAL.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    text = text[:max_len].strip(" .")
    if not text or text.lower() in _RESERVED:
        return fallback
    return text


def content_disposition(filename: str) -> str:
    """Build an attachment header with an ASCII fallback plus an RFC 5987 UTF-8 filename."""
    ascii_name = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii")
    ascii_name = re.sub(r"[^A-Za-z0-9._ \-\[\]()]", "_", ascii_name).strip() or "subtitles"
    ext = filename.rsplit(".", 1)[1] if "." in filename else ""
    ext = re.sub(r"[^A-Za-z0-9]", "", ext)
    if ext and not ascii_name.lower().endswith("." + ext.lower()):
        ascii_name = f"{ascii_name}.{ext}"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}"
