import subprocess

import pytest

from app.services import extractor
from app.services.extractor import as_dict, get_int, get_str, parse_json_output
from app.utils.errors import AppError


def test_parse_valid_json():
    assert parse_json_output('{"id": "x"}\n') == {"id": "x"}


@pytest.mark.parametrize("payload", ["", "   \n", None, b"{}"])
def test_parse_empty_output(payload):
    with pytest.raises(AppError) as exc:
        parse_json_output(payload)
    assert exc.value.code == "EMPTY_OUTPUT"


@pytest.mark.parametrize("payload", ["{not json", "<html>blocked</html>", "[1, 2]", '"text"', "42", "null", "true"])
def test_parse_invalid_or_non_object_json(payload):
    with pytest.raises(AppError) as exc:
        parse_json_output(payload)
    assert exc.value.code == "INVALID_JSON"


def test_parse_json_with_noise_before():
    assert parse_json_output('WARNING: something\n{"id": "x"}') == {"id": "x"}


def test_safe_accessors_handle_none():
    assert as_dict(None) == {} and as_dict([1]) == {}
    assert get_str(None, "a") == "" and get_str({"a": None}, "a", "d") == "d"
    assert get_int({"a": "5"}, "a") is None and get_int({"a": True}, "a") is None and get_int({"a": 7.9}, "a") == 7


def test_run_uses_argument_list_and_captures(fake_ytdlp):
    calls = fake_ytdlp(lambda cmd: (0, '{"id":"abc"}', "WARNING: x"))
    result = extractor.run_ytdlp(["--version"], timeout=5)
    assert result.stdout == '{"id":"abc"}' and result.stderr == "WARNING: x"
    assert calls[0][1:3] == ["-m", "yt_dlp"]


def test_timeout_maps_to_504(fake_ytdlp):
    fake_ytdlp(lambda cmd: subprocess.TimeoutExpired(cmd, 5))
    with pytest.raises(AppError) as exc:
        extractor.run_ytdlp(["x"], timeout=5)
    assert exc.value.code == "TIMEOUT" and exc.value.status == 504


def test_missing_python_maps_to_dependency_error(fake_ytdlp):
    fake_ytdlp(lambda cmd: FileNotFoundError("no python"))
    with pytest.raises(AppError) as exc:
        extractor.run_ytdlp(["x"], timeout=5)
    assert exc.value.code == "DEPENDENCY_MISSING"


@pytest.mark.parametrize("stderr,code", [
    ("ERROR: [youtube] x: Sign in to confirm you\u2019re not a bot", "BOT_CHECK"),
    ("ERROR: [youtube] x: Private video. Sign in if you've been granted access", "VIDEO_PRIVATE"),
    ("ERROR: Sign in to confirm your age. This video may be inappropriate for some users", "AGE_RESTRICTED"),
    ("ERROR: HTTP Error 429: Too Many Requests", "RATE_LIMITED"),
    ("ERROR: Video unavailable", "VIDEO_UNAVAILABLE"),
    ("ERROR: The playlist does not exist.", "PLAYLIST_NOT_FOUND"),
    ("ERROR: Unable to download webpage: timed out", "NETWORK_ERROR"),
    ("/usr/bin/python: No module named yt_dlp", "DEPENDENCY_MISSING"),
    ("some brand new unknown failure with /srv/app/secret/path.py", "EXTRACTION_FAILED"),
])
def test_ytdlp_errors_are_mapped_and_sanitised(fake_ytdlp, stderr, code):
    fake_ytdlp(lambda cmd: (1, "", stderr))
    with pytest.raises(AppError) as exc:
        extractor.extract_json(["--dump-single-json"], timeout=5)
    assert exc.value.code == code
    assert "/srv/" not in exc.value.message and "Traceback" not in exc.value.message


def test_exit_zero_with_empty_stdout(fake_ytdlp):
    fake_ytdlp(lambda cmd: (0, "", ""))
    with pytest.raises(AppError) as exc:
        extractor.extract_json(["x"], timeout=5)
    assert exc.value.code == "EMPTY_OUTPUT"


def test_exit_zero_with_null(fake_ytdlp):
    fake_ytdlp(lambda cmd: (0, "null\n", ""))
    with pytest.raises(AppError) as exc:
        extractor.extract_json(["x"], timeout=5)
    assert exc.value.code == "INVALID_JSON"
