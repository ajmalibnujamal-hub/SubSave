import io
import zipfile

import pytest

from app.services import archive, subtitles
from app.services.subtitles import choose_default_track, convert, fetch_subtitle, parse_timestamp
from app.utils.errors import AppError
from tests.conftest import AUTO_ROLLING_VTT, MALAYALAM_VTT, SIMPLE_VTT, write_subtitle_file


def test_parse_timestamp():
    assert parse_timestamp("00:00:01.000") == 1000
    assert parse_timestamp("01:02:03,450") == 3_723_450
    assert parse_timestamp("02:03.5") == 123_500


def test_vtt_to_srt():
    srt, count = convert(SIMPLE_VTT, "srt")
    assert count == 2
    assert srt.startswith("1\n00:00:01,000 --> 00:00:03,500\nHello & welcome\n\n2\n00:00:04,000 --> 00:00:06,000\nSecond line\nwith two rows\n")


def test_vtt_roundtrip_and_txt():
    vtt, _ = convert(SIMPLE_VTT, "vtt")
    assert vtt.startswith("WEBVTT\n\n00:00:01.000 --> 00:00:03.500\nHello & welcome")
    txt, _ = convert(SIMPLE_VTT, "txt")
    assert txt == "Hello & welcome\nSecond line\nwith two rows\n"


def test_malayalam_unicode_preserved_in_all_formats():
    for fmt in ("srt", "vtt", "txt"):
        out, count = convert(MALAYALAM_VTT, fmt)
        assert count == 2 and "നമസ്കാരം, സ്വാഗതം" in out and "ഇതൊരു പരീക്ഷണമാണ്" in out
        out.encode("utf-8")
    srt, _ = convert(MALAYALAM_VTT, "srt")
    assert "00:00:00,500 --> 00:00:02,000" in srt and "00:00:02,500 --> 00:00:04,000" in srt


def test_auto_caption_rolling_duplicates_removed():
    txt, _ = convert(AUTO_ROLLING_VTT, "txt")
    assert txt == "Hello there\nhow are you\n"
    srt, count = convert(AUTO_ROLLING_VTT, "srt")
    assert count == 2
    assert "00:00:02,000" in srt and "<c>" not in srt


def test_manual_repeated_lines_are_kept():
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nNo.\n\n00:00:03.000 --> 00:00:04.000\nNo.\n"
    _, count = convert(vtt, "srt")
    assert count == 2


@pytest.mark.parametrize("text", ["", "WEBVTT\n\n", "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n<c></c>\n"])
def test_empty_subtitles_raise(text):
    with pytest.raises(AppError) as exc:
        convert(text, "srt")
    assert exc.value.code == "SUBTITLE_EMPTY"


def test_invalid_format():
    with pytest.raises(AppError):
        convert(SIMPLE_VTT, "docx")


def test_default_track_english_first():
    t = lambda code, kind, translated=False: {"code": code, "name": code, "kind": kind, "translated": translated}  # noqa: E731
    assert choose_default_track([t("ml", "manual"), t("en", "manual")])["code"] == "en"
    assert choose_default_track([t("en", "auto", True), t("en-orig", "auto")])["code"] == "en-orig"
    assert choose_default_track([t("ml", "auto", True), t("hi", "manual")])["code"] == "hi"
    assert choose_default_track([t("ml", "auto", True)]) is None
    assert choose_default_track([]) is None


def test_fetch_subtitle_success(fake_ytdlp):
    calls = fake_ytdlp(lambda cmd: (write_subtitle_file(cmd, "ml", MALAYALAM_VTT) or (0, "", "")))
    result = fetch_subtitle("dQw4w9WgXcQ", "ml", "best", "srt")
    assert result.lang == "ml" and result.cue_count == 2 and "നമസ്കാരം" in result.content
    cmd = calls[0]
    assert "--write-subs" in cmd and "--write-auto-subs" in cmd and cmd[-2:] == ["--", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"]


def test_fetch_manual_only_flag(fake_ytdlp):
    calls = fake_ytdlp(lambda cmd: (write_subtitle_file(cmd, "en", SIMPLE_VTT) or (0, "", "")))
    fetch_subtitle("dQw4w9WgXcQ", "en", "manual", "txt")
    assert "--write-subs" in calls[0] and "--write-auto-subs" not in calls[0]


def test_english_falls_back_to_orig_track(fake_ytdlp):
    fake_ytdlp(lambda cmd: (write_subtitle_file(cmd, "en-orig", AUTO_ROLLING_VTT) or (0, "", "")))
    assert fetch_subtitle("dQw4w9WgXcQ", "en", "best", "txt").lang == "en-orig"


def test_missing_track_never_fabricated(fake_ytdlp):
    fake_ytdlp(lambda cmd: (0, "", "WARNING: There are no subtitles for the requested languages"))
    with pytest.raises(AppError) as exc:
        fetch_subtitle("dQw4w9WgXcQ", "ml", "best", "srt")
    assert exc.value.code == "SUBTITLES_UNAVAILABLE" and exc.value.status == 404


def test_rate_limited_subtitle_fetch(fake_ytdlp):
    fake_ytdlp(lambda cmd: (0, "", "WARNING: Unable to download video subtitles for 'en': HTTP Error 429: Too Many Requests"))
    with pytest.raises(AppError) as exc:
        fetch_subtitle("dQw4w9WgXcQ", "en", "best", "srt")
    assert exc.value.code == "RATE_LIMITED"


def test_fetch_validates_inputs():
    for args in [("bad", "en", "best", "srt"), ("dQw4w9WgXcQ", "en;rm", "best", "srt"), ("dQw4w9WgXcQ", "en", "x", "srt"), ("dQw4w9WgXcQ", "en", "best", "pdf")]:
        with pytest.raises(AppError):
            fetch_subtitle(*args)


def test_temp_files_cleaned(fake_ytdlp):
    from app.config import settings
    fake_ytdlp(lambda cmd: (write_subtitle_file(cmd, "en", SIMPLE_VTT) or (0, "", "")))
    fetch_subtitle("dQw4w9WgXcQ", "en", "best", "srt")
    assert list(settings.temp_dir.glob("subsave-*")) == []


def test_zip_generation_and_unicode_names():
    data = archive.build_zip(
        [("001 - മലയാളം [a].ml.srt", "1\nടെസ്റ്റ്\n"), ("001 - മലയാളം [a].ml.srt", "dup")],
        archive.build_report(2, [{"title": "T", "video_id": "x", "message": "m"}], "ml", "srt"),
    )
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert z.testzip() is None
        names = z.namelist()
        assert len(set(names)) == 3 and "_report.txt" in names and "001 - മലയാളം [a].ml (2).srt" in names
        assert z.read("001 - മലയാളം [a].ml.srt").decode("utf-8") == "1\nടെസ്റ്റ്\n"
        assert "Failed: 1" in z.read("_report.txt").decode()
