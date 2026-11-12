"""ZIP creation in memory (UTF-8 filenames, unique names, plain-text report)."""
from __future__ import annotations

import io
import zipfile


def unique_name(name: str, used: set[str]) -> str:
    if name not in used:
        used.add(name)
        return name
    stem, dot, ext = name.rpartition(".")
    n = 2
    while True:
        candidate = f"{stem} ({n}).{ext}" if dot else f"{name} ({n})"
        if candidate not in used:
            used.add(candidate)
            return candidate
        n += 1


def build_report(ok_count: int, failures: list[dict], lang: str, fmt: str) -> str:
    lines = ["SubSave download report", f"Language: {lang}   Format: {fmt.upper()}", f"Succeeded: {ok_count}", f"Failed: {len(failures)}", ""]
    for failure in failures:
        lines.append(f"- {failure.get('title', '')} [{failure.get('video_id', '')}]: {failure.get('message', '')}")
    return "\n".join(lines) + "\n"


def build_zip(files: list[tuple[str, str]], report: str) -> bytes:
    """files: (filename, text content). Returns the ZIP as bytes."""
    buffer = io.BytesIO()
    used: set[str] = {"_report.txt"}
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in files:
            archive.writestr(unique_name(name, used), text.encode("utf-8"))
        archive.writestr("_report.txt", report.encode("utf-8"))
    return buffer.getvalue()
