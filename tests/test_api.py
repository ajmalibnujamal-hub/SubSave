import io
import json
import subprocess
import zipfile

from tests.conftest import MALAYALAM_VTT, SIMPLE_VTT, VIDEO_JSON, write_subtitle_file

VID = "dQw4w9WgXcQ"
PLAYLIST_JSON = {
    "title": "My Playlist", "channel": "Chan", "playlist_count": 4,
    "entries": [
        {"id": "aaaaaaaaaaa", "title": "One", "duration": 61, "channel": "Chan"},
        None,
        {"id": "bbbbbbbbbbb", "title": "[Private video]"},
        {"id": "ccccccccccc", "title": "മൂന്ന്", "duration": 3700, "uploader": "Up"},
        {"id": "aaaaaaaaaaa", "title": "One again"},
        {"id": "bad", "title": "Bad id"},
    ],
}


def err(resp):
    body = resp.json()
    assert body["ok"] is False
    return body["error"]["code"]


def test_inspect_video(client, fake_ytdlp):
    calls = fake_ytdlp(lambda cmd: (0, json.dumps(VIDEO_JSON), ""))
    r = client.post("/api/inspect", json={"url": f"https://youtu.be/{VID}"})
    assert r.status_code == 200
    data = r.json()["data"]
    video = data["video"]
    assert data["kind"] == "video" and video["video_id"] == VID and video["duration_text"] == "3:32"
    assert video["thumbnail"] == f"https://i.ytimg.com/vi/{VID}/hqdefault.jpg"
    codes = [(t["code"], t["kind"], t["kind_label"]) for t in video["tracks"]]
    assert codes[0] == ("en", "manual", "Manual")
    assert ("en-orig", "auto", "Auto-generated") in codes and ("ml", "auto", "Auto-translated") in codes
    assert all(c[0] != "live_chat" for c in codes)
    assert video["default_track"]["code"] == "en" and video["default_track"]["kind"] == "manual"
    assert calls[0][-1] == f"https://www.youtube.com/watch?v={VID}"
    assert "--ignore-errors" not in calls[0] and "-i" not in calls[0]


def test_inspect_playlist_url_does_not_call_ytdlp(client, fake_ytdlp):
    calls = fake_ytdlp(lambda cmd: (1, "", "should not run"))
    r = client.post("/api/inspect", json={"url": "https://www.youtube.com/playlist?list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"})
    assert r.json()["data"]["kind"] == "playlist" and calls == []


def test_inspect_rejects_non_youtube(client, fake_ytdlp):
    calls = fake_ytdlp(lambda cmd: (0, "{}", ""))
    r = client.post("/api/inspect", json={"url": "http://169.254.169.254/latest"})
    assert r.status_code == 400 and err(r) == "INVALID_URL" and calls == []


def test_inspect_null_json_from_ytdlp(client, fake_ytdlp):
    fake_ytdlp(lambda cmd: (0, "null", ""))
    r = client.post("/api/inspect", json={"url": f"https://youtu.be/{VID}"})
    assert r.status_code == 503 and err(r) == "INVALID_JSON"


def test_inspect_handles_none_fields(client, fake_ytdlp):
    fake_ytdlp(lambda cmd: (0, json.dumps({"id": VID, "title": None, "channel": None, "uploader": None, "subtitles": None, "automatic_captions": None, "duration": None}), ""))
    r = client.post("/api/inspect", json={"url": f"https://youtu.be/{VID}"})
    video = r.json()["data"]["video"]
    assert r.status_code == 200 and video["tracks"] == [] and video["default_track"] is None and video["title"] == "Untitled video"


def test_inspect_timeout_and_errors(client, fake_ytdlp):
    fake_ytdlp(lambda cmd: subprocess.TimeoutExpired(cmd, 5))
    r = client.post("/api/inspect", json={"url": f"https://youtu.be/{VID}"})
    assert r.status_code == 504 and err(r) == "TIMEOUT"
    fake_ytdlp(lambda cmd: (1, "", "ERROR: Private video"))
    r = client.post("/api/inspect", json={"url": f"https://youtu.be/{VID}"})
    assert r.status_code == 403 and err(r) == "VIDEO_PRIVATE"


def test_error_never_leaks_internals(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret /srv/app/path")
    monkeypatch.setattr("app.main.youtube.inspect_video", boom)
    r = client.post("/api/inspect", json={"url": f"https://youtu.be/{VID}"})
    assert r.status_code == 500 and err(r) == "INTERNAL_ERROR"
    assert "secret" not in r.text and "/srv/" not in r.text and "Traceback" not in r.text


def test_validation_errors_are_json(client):
    assert err(client.post("/api/inspect", json={})) == "INVALID_REQUEST"
    assert err(client.post("/api/inspect", json={"url": "x", "extra": 1})) == "INVALID_REQUEST"
    assert client.post("/api/inspect", content="not json", headers={"content-type": "application/json"}).status_code == 422
    r = client.post("/api/download", json={"video_id": "../etc/passwd", "lang": "en"})
    assert r.status_code == 422 and err(r) == "INVALID_REQUEST"
    assert err(client.post("/api/download", json={"video_id": VID, "lang": "en", "format": "exe"})) == "INVALID_REQUEST"
    assert err(client.post("/api/download", json={"video_id": VID, "lang": "en; rm -rf /"})) == "INVALID_REQUEST"


def test_request_size_limit(client):
    r = client.post("/api/inspect", content="x" * 70000, headers={"content-type": "application/json"})
    assert r.status_code == 413 and err(r) == "REQUEST_TOO_LARGE"


def test_playlist_processing(client, fake_ytdlp):
    calls = fake_ytdlp(lambda cmd: (0, json.dumps(PLAYLIST_JSON), ""))
    r = client.post("/api/playlist", json={"url": "https://www.youtube.com/playlist?list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"})
    data = r.json()["data"]
    assert r.status_code == 200 and [v["video_id"] for v in data["videos"]] == ["aaaaaaaaaaa", "ccccccccccc"]
    assert data["videos"][1]["title"] == "മൂന്ന്" and data["videos"][1]["duration_text"] == "1:01:40"
    assert data["skipped"] == 3 and data["limit"] == 300 and data["truncated"] is False
    assert "--flat-playlist" in calls[0] and "300" in calls[0]


def test_playlist_limit_300(client, fake_ytdlp):
    entries = [{"id": f"{i:011d}", "title": f"v{i}"} for i in range(500)]
    fake_ytdlp(lambda cmd: (0, json.dumps({"title": "Big", "entries": entries, "playlist_count": 500}), ""))
    data = client.post("/api/playlist", json={"url": "https://www.youtube.com/playlist?list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"}).json()["data"]
    assert len(data["videos"]) == 300 and data["truncated"] is True


def test_empty_playlist(client, fake_ytdlp):
    for payload in ({"title": "x", "entries": []}, {"title": "x", "entries": None}, {"title": "x"}, {"entries": [None, {"id": "bbbbbbbbbbb", "title": "[Deleted video]"}]}):
        fake_ytdlp(lambda cmd, p=payload: (0, json.dumps(p), ""))
        r = client.post("/api/playlist", json={"url": "https://www.youtube.com/playlist?list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"})
        assert r.status_code == 404 and err(r) == "EMPTY_PLAYLIST"


def test_playlist_requires_playlist_link(client):
    assert err(client.post("/api/playlist", json={"url": f"https://youtu.be/{VID}"})) == "INVALID_URL"


def test_download_srt_malayalam(client, fake_ytdlp):
    fake_ytdlp(lambda cmd: (write_subtitle_file(cmd, "ml", MALAYALAM_VTT) or (0, "", "")))
    r = client.post("/api/download", json={"video_id": VID, "lang": "ml", "kind": "auto", "format": "srt", "title": "മലയാളം/../title"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-subrip") and r.headers["cache-control"] == "no-store"
    from urllib.parse import unquote
    header = r.headers["content-disposition"]
    filename = unquote(header.split("filename*=UTF-8''")[1])
    assert filename.endswith("[dQw4w9WgXcQ].ml.srt") and "/" not in filename and "\\" not in filename
    assert "നമസ്കാരം" in r.content.decode("utf-8") and "00:00:00,500 --> 00:00:02,000" in r.text


def test_download_unavailable_language(client, fake_ytdlp):
    fake_ytdlp(lambda cmd: (0, "", "WARNING: There are no subtitles for the requested languages"))
    r = client.post("/api/download", json={"video_id": VID, "lang": "kn"})
    assert r.status_code == 404 and err(r) == "SUBTITLES_UNAVAILABLE"


def _zip_handler(fail_ids):
    def handler(cmd):
        vid = cmd[-1].split("v=")[-1]
        if vid in fail_ids:
            return (0, "", "WARNING: There are no subtitles for the requested languages")
        write_subtitle_file(cmd, "en", SIMPLE_VTT)
        return (0, "", "")
    return handler


def test_zip_partial_success(client, fake_ytdlp):
    fake_ytdlp(_zip_handler({"bbbbbbbbbbb"}))
    items = [{"video_id": "aaaaaaaaaaa", "title": "A/title"}, {"video_id": "bbbbbbbbbbb", "title": "B"}, {"video_id": "ccccccccccc"}, {"video_id": "aaaaaaaaaaa"}]
    r = client.post("/api/download-zip", json={"items": items, "lang": "en", "format": "vtt"})
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert r.headers["x-subsave-succeeded"] == "2" and r.headers["x-subsave-failed"] == "1" and r.headers["x-subsave-failed-ids"] == "bbbbbbbbbbb"
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        assert z.testzip() is None
        names = z.namelist()
        assert len(names) == 3 and "_report.txt" in names
        assert any(n.startswith("001 - A title [aaaaaaaaaaa].en.vtt") for n in names)
        assert all("/" not in n and ".." not in n for n in names)
        assert "SubSave download report" in z.read("_report.txt").decode()
        assert z.read(names[0]).decode().startswith("WEBVTT")


def test_zip_all_failed(client, fake_ytdlp):
    fake_ytdlp(_zip_handler({"aaaaaaaaaaa", "bbbbbbbbbbb"}))
    r = client.post("/api/download-zip", json={"items": [{"video_id": "aaaaaaaaaaa"}, {"video_id": "bbbbbbbbbbb"}], "lang": "en"})
    assert r.status_code == 422 and err(r) == "ZIP_ALL_FAILED"
    assert len(r.json()["error"]["details"]["failures"]) == 2


def test_zip_limits(client):
    too_many = [{"video_id": f"{i:011d}"} for i in range(101)]
    assert err(client.post("/api/download-zip", json={"items": too_many})) == "INVALID_REQUEST"
    assert err(client.post("/api/download-zip", json={"items": []})) == "INVALID_REQUEST"
    assert err(client.post("/api/download-zip", json={"items": [{"video_id": "nope"}]})) == "INVALID_REQUEST"


def test_zip_100_items_accepted(client, fake_ytdlp):
    fake_ytdlp(_zip_handler(set()))
    items = [{"video_id": f"{i:011d}", "title": f"t{i}"} for i in range(100)]
    r = client.post("/api/download-zip", json={"items": items, "lang": "en", "format": "txt"})
    assert r.status_code == 200 and r.headers["x-subsave-succeeded"] == "100"


def test_zip_time_budget(client, fake_ytdlp, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "zip_time_budget", 1)
    fake_ytdlp(_zip_handler(set()))
    r = client.post("/api/download-zip", json={"items": [{"video_id": "aaaaaaaaaaa"}], "lang": "en"})
    assert r.status_code == 422 and r.json()["error"]["details"]["failures"][0]["code"] == "TIME_BUDGET"
