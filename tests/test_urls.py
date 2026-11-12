import pytest

from app.utils.errors import AppError
from app.utils.filenames import content_disposition, sanitize_filename
from app.utils.validators import parse_youtube_url

VID = "dQw4w9WgXcQ"
PL = "PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"


@pytest.mark.parametrize("url", [
    f"https://www.youtube.com/watch?v={VID}",
    f"https://youtube.com/watch?v={VID}&t=42s",
    f"https://m.youtube.com/watch?v={VID}",
    f"https://youtu.be/{VID}",
    f"https://youtu.be/{VID}?si=abc",
    f"https://www.youtube.com/shorts/{VID}",
    f"https://www.youtube.com/live/{VID}",
    f"https://www.youtube.com/embed/{VID}",
    f"www.youtube.com/watch?v={VID}",
    f"  https://music.youtube.com/watch?v={VID}  ",
])
def test_video_urls(url):
    parsed = parse_youtube_url(url)
    assert parsed.kind == "video" and parsed.video_id == VID
    assert parsed.canonical_url == f"https://www.youtube.com/watch?v={VID}"


def test_playlist_url():
    parsed = parse_youtube_url(f"https://www.youtube.com/playlist?list={PL}")
    assert parsed.kind == "playlist" and parsed.playlist_id == PL and parsed.video_id is None
    assert parsed.canonical_url.endswith(PL)


def test_video_inside_playlist_is_video_with_playlist_id():
    parsed = parse_youtube_url(f"https://www.youtube.com/watch?v={VID}&list={PL}")
    assert parsed.kind == "video" and parsed.playlist_id == PL


def test_watch_with_only_list_is_playlist():
    assert parse_youtube_url(f"https://www.youtube.com/watch?list={PL}").kind == "playlist"


def test_mix_playlist_ignored_for_video():
    parsed = parse_youtube_url(f"https://www.youtube.com/watch?v={VID}&list=RDdQw4w9WgXcQ")
    assert parsed.kind == "video" and parsed.playlist_id is None


def test_mix_only_rejected():
    with pytest.raises(AppError) as exc:
        parse_youtube_url("https://www.youtube.com/playlist?list=RDdQw4w9WgXcQ")
    assert exc.value.code == "INVALID_URL"


def test_watch_later_private():
    with pytest.raises(AppError) as exc:
        parse_youtube_url("https://www.youtube.com/playlist?list=WL")
    assert exc.value.code == "PLAYLIST_PRIVATE"


@pytest.mark.parametrize("url", [
    "", "   ", None, 123, "not a url", "https://example.com/watch?v=dQw4w9WgXcQ",
    "https://youtube.com.evil.com/watch?v=dQw4w9WgXcQ", "https://evil.com/?u=youtube.com",
    "https://user@www.youtube.com/watch?v=dQw4w9WgXcQ", "https://www.youtube.com:8080/watch?v=dQw4w9WgXcQ",
    "http://localhost/watch?v=dQw4w9WgXcQ", "http://127.0.0.1/", "http://169.254.169.254/latest/meta-data",
    "file:///etc/passwd", "javascript:alert(1)", "ftp://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://www.youtube.com/watch?v=short", "https://www.youtube.com/watch?v=dQw4w9WgXcQ%20--exec",
    "https://www.youtube.com/watch?v=dQw4w9WgXc;", "https://www.youtube.com/", "https://www.youtube.com/@channel",
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ\nhttps://evil.com", "https://" + "a" * 3000 + ".com",
])
def test_rejected_urls(url):
    with pytest.raises(AppError) as exc:
        parse_youtube_url(url)
    assert exc.value.code == "INVALID_URL"


def test_sanitize_filename():
    assert sanitize_filename("../../etc/passwd") == "etc passwd"
    assert sanitize_filename('a<b>c:d"e/f\\g|h?i*j') == "a b c d e f g h i j"
    assert sanitize_filename("CON") == "subtitles"
    assert sanitize_filename(None, fallback="x") == "x"
    assert sanitize_filename("  ..  ") == "subtitles"
    assert len(sanitize_filename("x" * 500)) <= 80
    assert sanitize_filename("മലയാളം വീഡിയോ") == "മലയാളം വീഡിയോ"


def test_content_disposition_unicode():
    header = content_disposition("മലയാളം [abc].ml.srt")
    assert header.startswith("attachment;")
    assert "filename*=UTF-8''%E0%B4%AE" in header
    header.encode("ascii")  # header must be pure ASCII
