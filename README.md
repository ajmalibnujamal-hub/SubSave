# SubSave 3.0 – Subtitle Studio

*Every word. Within reach.*

SubSave downloads the subtitles that YouTube already provides for a video or a playlist, as **SRT, VTT or TXT**, one file at a time or as a **ZIP** (up to 100 videos per ZIP, playlists up to 300 videos).

- Backend: Python 3.11+, FastAPI, Uvicorn, yt-dlp, Pydantic
- Frontend: HTML, CSS, vanilla JavaScript, installable PWA
- Deployment: GitHub, Docker, Render Blueprint

**Honesty rules built into the app:** SubSave never writes subtitles itself and never claims a translation exists. It lists the tracks YouTube reports (manual, auto-generated, auto-translated) and downloads only those. It does not log in, use cookies, or bypass private, age-restricted or members-only videos.

---

## 1. Project layout

```
subsave/
├── app/
│   ├── main.py            FastAPI app, routes, error handlers, security headers
│   ├── config.py          Settings from environment variables
│   ├── models.py          Pydantic request/response models
│   ├── services/
│   │   ├── extractor.py   Runs yt-dlp safely, validates JSON, maps errors
│   │   ├── youtube.py     Video inspection and caption-track listing
│   │   ├── subtitles.py   Fetching, VTT parsing, SRT/VTT/TXT conversion
│   │   ├── playlist.py    Playlist listing and bulk collection
│   │   └── archive.py     ZIP creation
│   └── utils/
│       ├── validators.py  YouTube URL validation (SSRF protection)
│       ├── filenames.py   Filename sanitising, Content-Disposition
│       └── errors.py      AppError
├── static/                index.html, style.css, app.js, sw.js, manifest.webmanifest, icons
├── tests/                 Mocked tests (no live YouTube)
├── scripts/make_icons.py  Regenerates the PNG icons
├── requirements.txt       Runtime dependencies
├── requirements-dev.txt   Runtime + test dependencies
├── Dockerfile
├── render.yaml
└── README.md
```

## 2. Run locally on Windows (PowerShell)

Install [Python 3.11 or newer](https://www.python.org/downloads/) (tick **Add python.exe to PATH**) and [Git](https://git-scm.com/download/win). Then, in PowerShell:

```powershell
cd C:\path\to\subsave
python -m venv .venv
# If activation is blocked, run this once for the current window only:
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
```

Run the automated tests (they use mocked YouTube data and need no internet):

```powershell
python -m pytest -q
```

Start the app:

```powershell
python -m uvicorn app.main:app --reload --port 8000
```

Open <http://localhost:8000>. Check the API: `Invoke-RestMethod http://localhost:8000/api/health`.

**Live check (needs internet):** paste a public video that has captions, press **Analyze**, and download an SRT. Also try a public playlist and a ZIP of two or three videos. Live extraction depends on YouTube, so see *Known limitations* if it fails.

**Test on an Android phone on the same Wi-Fi:** run with `--host 0.0.0.0`, then open `http://<your-PC-IP>:8000`. Service workers and the install prompt need HTTPS, so test installation on the Render URL (section 4).

**Node syntax check (optional):** `node --check static\app.js; node --check static\sw.js`

## 3. Upload to GitHub

1. Create an empty repository on github.com (for example `subsave`). Do not add a README there.
2. In PowerShell, inside the project folder:

```powershell
git init
git add .
git commit -m "SubSave 3.0"
git branch -M main
git remote add origin https://github.com/<your-username>/subsave.git
git push -u origin main
```

If Git asks for a password, use a [personal access token](https://github.com/settings/tokens) or sign in through Git Credential Manager.

## 4. Deploy on Render

1. Sign in at <https://dashboard.render.com> and connect your GitHub account.
2. Choose **New +**, then **Blueprint**, and select the `subsave` repository.
3. Render reads `render.yaml`. Confirm the service **subsave** and click **Apply**.
4. Wait for the Docker build (first build takes several minutes). When it shows **Live**, open the URL, usually `https://subsave-xxxx.onrender.com`.
5. Check `https://<your-service>.onrender.com/api/health`. It should return `"status": "ok"`.
6. On Android Chrome open the URL, then use **Install app** in the page or Chrome menu, **Install app**.

Notes:

- `healthCheckPath: /api/health` is configured in `render.yaml`. The container listens on the `PORT` that Render provides.
- The free plan sleeps after inactivity and the first request afterwards is slow. Temporary files live in `/tmp/subsave` and are deleted after every request; leftovers older than one hour are removed at startup.
- Render sends every push to `main` to a new deploy (`autoDeploy: true`).

## 5. API

All responses are JSON: `{"ok": true, "data": ...}` or `{"ok": false, "error": {"code": "...", "message": "...", "details": {...}}}`. Downloads return the file itself on success.

| Endpoint | Body | Result |
|---|---|---|
| `GET /api/health` | none | Status, version, whether yt-dlp is installed |
| `POST /api/inspect` | `{"url": "..."}` | `kind` is `video` or `playlist`. For a video: title, channel, duration, thumbnail, ID, caption tracks, default track |
| `POST /api/playlist` | `{"url": "..."}` | Up to 300 videos (`video_id`, `title`, `channel`, `duration`), skipped count, truncation flag |
| `POST /api/download` | `{"video_id", "lang", "kind", "format", "title"?}` | Subtitle file (`srt`, `vtt` or `txt`) |
| `POST /api/download-zip` | `{"items": [{"video_id", "title"?}], "lang", "kind", "format"}` (1 to 100 items) | ZIP. Headers `X-Subsave-Succeeded`, `X-Subsave-Failed`, `X-Subsave-Failed-Ids`; `_report.txt` inside |

`kind` is `manual`, `auto` or `best` (uploader captions first, then automatic ones). `format` is `srt`, `vtt` or `txt`. `lang` is a code such as `en`, `ml`, `hi`, `ar`, `ta`, `te`, `kn` or `zh-Hans`. For `en`, SubSave accepts `en`, `en-US`, `en-GB` or `en-orig`.

Common error codes: `INVALID_URL`, `INVALID_REQUEST`, `VIDEO_PRIVATE`, `AGE_RESTRICTED`, `VIDEO_UNAVAILABLE`, `SUBTITLES_UNAVAILABLE`, `EMPTY_PLAYLIST`, `BOT_CHECK`, `RATE_LIMITED`, `TIMEOUT` (504), `INVALID_JSON`, `EMPTY_OUTPUT`, `ZIP_ALL_FAILED`, `INTERNAL_ERROR`. Stack traces and server paths are logged on the server only.

### Configuration (environment variables)

`MAX_PLAYLIST_VIDEOS` (300), `MAX_ZIP_VIDEOS` (100), `YTDLP_TIMEOUT_INSPECT` (60 s), `YTDLP_TIMEOUT_PLAYLIST` (90 s), `YTDLP_TIMEOUT_SUBTITLE` (60 s), `MAX_CONCURRENT_YTDLP` (4), `ZIP_WORKERS` (3), `ZIP_TIME_BUDGET` (85 s), `MAX_BODY_BYTES` (65536), `TEMP_DIR`, `STATIC_DIR`, `LOG_LEVEL`.

## 6. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `BOT_CHECK`: "YouTube is asking this server to confirm it is not a bot" | YouTube often blocks cloud and datacenter IP addresses. Run SubSave on your own PC (home internet usually works). SubSave does not bypass this. |
| `RATE_LIMITED` | Too many requests. Wait several minutes, select fewer videos per ZIP. |
| `SUBTITLES_UNAVAILABLE` | YouTube offers no track for that language on that video. Pick another language from the list. |
| `EXTRACTION_FAILED`, `NETWORK_ERROR` after it worked before | YouTube changed. Update yt-dlp (section 7). |
| `DEPENDENCY_MISSING` | yt-dlp is not installed in the active environment. Run `pip install -r requirements.txt`. |
| ZIP finishes with many failures labelled `TIME_BUDGET` | The request hit `ZIP_TIME_BUDGET`. Select fewer videos (30 to 50) or raise the limit. |
| PowerShell: "running scripts is disabled" | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` |
| "Install app" does nothing | Installation needs HTTPS (the Render URL) and a supported browser. Use the browser menu: Install app or Add to Home screen. |
| Page shows old design after an update | Close and reopen the app, or clear site data. The service worker refreshes cached files in the background. |
| Render deploy is slow or sleeping | Normal on the free plan. |

## 7. Updating dependencies

YouTube changes often, and an outdated yt-dlp is the most common cause of failures.

```powershell
pip install --upgrade yt-dlp
pip install --upgrade -r requirements.txt
python -m pytest -q
```

On Render: push to GitHub for an automatic deploy, or choose **Manual Deploy**, then **Clear build cache & deploy** so Docker reinstalls the newest yt-dlp. For full reproducibility you can pin an exact version in `requirements.txt` (for example `yt-dlp[default]==<version>`).

## 8. Known limitations

- **Live YouTube extraction was not tested while this project was built.** The build environment could not be verified against YouTube; all automated tests use mocked yt-dlp output. Use the live check in section 2 to confirm it works for you.
- Cloud hosting (including Render) may be blocked by YouTube's bot checks (`BOT_CHECK`). SubSave reports this honestly and does not work around it.
- Auto-translations exist only when YouTube lists them for that video. Translated and auto-generated text can be wrong.
- For `en`, SubSave picks the first available of `en`, `en-US`, `en-GB`, `en-orig`. It cannot tell from the file alone whether `en` was uploader-written or automatic when both kinds exist; the single-video screen uses the exact track you select.
- ZIP progress is indeterminate (a timer, not a percentage). The server reports successes and failures when the ZIP is ready.
- Live streams, premieres, Mix playlists, Watch Later and Liked videos are not supported.
- Private, age-restricted, members-only and region-blocked videos are not accessible.
- The Docker image was not built in the environment where this project was written; the first Render build is its first real run.
- Offline mode covers the app shell only. Subtitle processing always needs an internet connection and private downloads are never cached.
- Please respect creators' rights, copyright law and YouTube's Terms of Service.
