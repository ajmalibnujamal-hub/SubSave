import os
import subprocess
import tempfile

import pytest

os.environ.setdefault("TEMP_DIR", tempfile.mkdtemp(prefix="subsave-tests-"))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def fake_ytdlp(monkeypatch):
    """Replace subprocess.run inside the extractor. handler(args) -> (returncode, stdout, stderr)."""
    calls = []

    def install(handler):
        def fake_run(cmd, **kwargs):
            assert isinstance(cmd, list), "yt-dlp must be invoked with an argument list"
            assert not kwargs.get("shell"), "shell must never be enabled"
            calls.append(cmd)
            result = handler(cmd)
            if isinstance(result, BaseException):
                raise result
            rc, out, err = result
            return subprocess.CompletedProcess(cmd, rc, out, err)

        monkeypatch.setattr("app.services.extractor.subprocess.run", fake_run)
        return calls

    return install


def write_subtitle_file(cmd, lang, text):
    """Emulate yt-dlp writing <id>.<lang>.vtt to the -o template directory."""
    template = cmd[cmd.index("-o") + 1]
    folder = os.path.dirname(template)
    video_id = cmd[-1].split("v=")[-1]
    with open(os.path.join(folder, f"{video_id}.{lang}.vtt"), "w", encoding="utf-8") as handle:
        handle.write(text)


SIMPLE_VTT = """WEBVTT
Kind: captions
Language: en

00:00:01.000 --> 00:00:03.500
Hello &amp; welcome

2
00:00:04.000 --> 00:00:06.000
<i>Second</i> line
with two rows
"""

MALAYALAM_VTT = """WEBVTT

00:00:00.500 --> 00:00:02.000
നമസ്കാരം, സ്വാഗതം

00:00:02.500 --> 00:00:04.000
ഇതൊരു പരീക്ഷണമാണ്
"""

AUTO_ROLLING_VTT = """WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:02.000 align:start position:0%
<00:00:00.000><c>Hello</c><00:00:00.500><c> there</c>

00:00:02.000 --> 00:00:02.010 align:start position:0%
Hello there

00:00:02.010 --> 00:00:04.000 align:start position:0%
Hello there
<00:00:02.500><c>how</c><00:00:03.000><c> are</c><00:00:03.500><c> you</c>

00:00:04.000 --> 00:00:04.010 align:start position:0%
how are you
"""

VIDEO_JSON = {
    "id": "dQw4w9WgXcQ",
    "title": "Test Video മലയാളം",
    "channel": "Test Channel",
    "duration": 212,
    "subtitles": {"en": [{"ext": "vtt", "name": "English", "url": "https://x/y?lang=en"}], "live_chat": [{"ext": "json"}]},
    "automatic_captions": {
        "ml": [{"ext": "vtt", "name": "Malayalam", "url": "https://x/y?lang=en&tlang=ml"}],
        "en-orig": [{"ext": "vtt", "name": "English (Original)", "url": "https://x/y?lang=en"}],
    },
}
