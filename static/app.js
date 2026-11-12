"use strict";
(function () {
  var MAX_ZIP = 100;
  var COMMON_LANGS = [
    ["en", "English"], ["ml", "Malayalam"], ["hi", "Hindi"], ["ar", "Arabic"], ["ta", "Tamil"],
    ["te", "Telugu"], ["kn", "Kannada"], ["bn", "Bengali"], ["mr", "Marathi"], ["ur", "Urdu"],
    ["es", "Spanish"], ["fr", "French"], ["de", "German"], ["other", "Other code…"]
  ];
  var LANG_RE = /^[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{2,8}){0,3}$/;

  var $ = function (id) { return document.getElementById(id); };
  var state = { video: null, videoUrl: "", playlist: null, selected: new Set(), busy: false };

  function el(tag, props, children) {
    var node = document.createElement(tag);
    Object.keys(props || {}).forEach(function (key) {
      if (key === "text") node.textContent = props[key];
      else if (key === "class") node.className = props[key];
      else node.setAttribute(key, props[key]);
    });
    (children || []).forEach(function (child) { node.appendChild(child); });
    return node;
  }

  function ApiError(code, message, details) {
    this.code = code; this.message = message; this.details = details || null;
  }

  /* ---------- messages ---------- */
  function showMessage(text, kind) {
    var box = $("message");
    box.textContent = text;
    box.className = "message" + (kind ? " is-" + kind : "");
    box.hidden = !text;
  }
  function setBusy(button, busy) {
    button.classList.toggle("is-busy", busy);
    button.disabled = busy;
  }

  /* ---------- network ---------- */
  function request(path, body, timeoutMs) {
    if (!navigator.onLine) {
      return Promise.reject(new ApiError("OFFLINE", "You are offline. Reading and processing subtitles needs an internet connection."));
    }
    var controller = new AbortController();
    var timer = setTimeout(function () { controller.abort(); }, timeoutMs || 120000);
    return fetch(path, {
      method: "POST", cache: "no-store", signal: controller.signal,
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
    }).catch(function (err) {
      if (err && err.name === "AbortError") throw new ApiError("TIMEOUT", "The request took too long. Try again, or select fewer videos.");
      throw new ApiError("NETWORK", "Could not reach the SubSave server. Check your connection and try again.");
    }).then(function (res) { clearTimeout(timer); return res; }, function (err) { clearTimeout(timer); throw err; });
  }
  function readError(res) {
    return res.json().then(function (data) {
      if (data && data.error && typeof data.error.message === "string") {
        return new ApiError(String(data.error.code || "ERROR"), data.error.message, data.error.details);
      }
      return new ApiError("HTTP_" + res.status, "The server sent an unexpected response (" + res.status + ").");
    }, function () { return new ApiError("HTTP_" + res.status, "The server sent an unexpected response (" + res.status + ")."); });
  }
  function postJson(path, body, timeoutMs) {
    return request(path, body, timeoutMs).then(function (res) {
      if (!res.ok) return readError(res).then(function (e) { throw e; });
      return res.json().then(function (data) {
        if (!data || data.ok !== true || typeof data.data !== "object" || data.data === null) throw new ApiError("BAD_RESPONSE", "The server sent data in an unexpected format.");
        return data.data;
      }, function () { throw new ApiError("BAD_RESPONSE", "The server sent data in an unexpected format."); });
    });
  }
  function postFile(path, body, timeoutMs) {
    return request(path, body, timeoutMs).then(function (res) {
      if (!res.ok) return readError(res).then(function (e) { throw e; });
      return res.blob().then(function (blob) { return { blob: blob, res: res }; });
    });
  }
  function filenameFrom(res, fallback) {
    var header = res.headers.get("Content-Disposition") || "";
    var star = /filename\*=UTF-8''([^;]+)/i.exec(header);
    if (star) { try { return decodeURIComponent(star[1]); } catch (e) { /* fall through */ } }
    var plain = /filename="([^"]+)"/i.exec(header);
    return plain ? plain[1] : fallback;
  }
  function saveBlob(blob, filename) {
    var url = URL.createObjectURL(blob);
    var link = el("a", { href: url, download: filename });
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
  }
  function errText(err) { return err instanceof ApiError ? err.message : "Something unexpected happened. Please try again."; }

  /* ---------- analyze ---------- */
  function resetPanels() {
    $("videoPanel").hidden = true; $("playlistPanel").hidden = true; $("zipResult").hidden = true;
    state.video = null; state.playlist = null; state.selected.clear();
  }
  function analyze(event) {
    event.preventDefault();
    var url = $("urlInput").value.trim();
    if (!url) { showMessage("Paste a YouTube video or playlist link first.", "error"); return; }
    var btn = $("analyzeBtn");
    setBusy(btn, true); showMessage("Reading the link…");
    resetPanels();
    postJson("/api/inspect", { url: url }, 90000).then(function (data) {
      state.videoUrl = url;
      if (data.kind === "playlist") { showMessage("Playlist found. Loading its videos…"); return loadPlaylist(url); }
      showMessage("", "");
      renderVideo(data.video, data.playlist_id);
    }).catch(function (err) { showMessage(errText(err), "error"); })
      .then(function () { setBusy(btn, false); });
  }

  /* ---------- single video ---------- */
  function trackValue(t) { return t.kind + "|" + t.code; }
  function renderVideo(video, playlistId) {
    state.video = video;
    var thumb = $("videoThumb");
    thumb.src = /^https:\/\/i\.ytimg\.com\//.test(video.thumbnail) ? video.thumbnail : "";
    thumb.alt = "Thumbnail for " + video.title;
    $("videoTitle").textContent = video.title;
    $("videoChannel").textContent = video.channel;
    $("videoFacts").textContent = [video.duration_text, "ID " + video.video_id].filter(Boolean).join("  |  ");

    var counts = { Manual: 0, "Auto-generated": 0, "Auto-translated": 0 };
    video.tracks.forEach(function (t) { counts[t.kind_label] = (counts[t.kind_label] || 0) + 1; });
    var hasTracks = video.tracks.length > 0;
    $("trackControls").hidden = !hasTracks;
    $("noTracks").hidden = hasTracks;
    $("trackSummary").textContent = hasTracks
      ? counts.Manual + " manual, " + counts["Auto-generated"] + " auto-generated, " + counts["Auto-translated"] + " auto-translated"
      : "";

    var select = $("trackSelect");
    select.textContent = "";
    ["Manual", "Auto-generated", "Auto-translated"].forEach(function (label) {
      var group = el("optgroup", { label: label + " captions" });
      video.tracks.filter(function (t) { return t.kind_label === label; }).forEach(function (t) {
        group.appendChild(el("option", { value: trackValue(t), text: t.name + " (" + t.code + ")" }));
      });
      if (group.children.length) select.appendChild(group);
    });
    if (video.default_track) select.value = video.default_track.kind + "|" + video.default_track.code;
    updateTrackHint();

    $("loadPlaylistBtn").hidden = !playlistId;
    $("videoPanel").hidden = false;
    $("videoPanel").scrollIntoView({ behavior: "smooth", block: "start" });
  }
  function selectedTrack() {
    var parts = $("trackSelect").value.split("|");
    return state.video ? state.video.tracks.filter(function (t) { return t.kind === parts[0] && t.code === parts[1]; })[0] : null;
  }
  function updateTrackHint() {
    var track = selectedTrack(), hint = $("trackHint");
    var text = "";
    if (track && track.kind_label === "Auto-translated") text = "Translated by YouTube from the video’s original captions. Quality varies.";
    else if (track && track.kind === "auto") text = "Generated automatically by YouTube. It can contain mistakes.";
    else if (state.video && state.video.default_track && track && track.code === state.video.default_track.code) text = state.video.default_track.reason + ".";
    hint.textContent = text; hint.hidden = !text;
  }
  function chosenFormat() { var r = document.querySelector('input[name="vfmt"]:checked'); return r ? r.value : "srt"; }
  function downloadVideo() {
    var track = selectedTrack();
    if (!track || !state.video) return;
    var btn = $("videoDownloadBtn");
    setBusy(btn, true); showMessage("Fetching " + track.name + " subtitles from YouTube…");
    postFile("/api/download", { video_id: state.video.video_id, lang: track.code, kind: track.kind, format: chosenFormat(), title: state.video.title }, 120000)
      .then(function (r) {
        saveBlob(r.blob, filenameFrom(r.res, state.video.video_id + "." + track.code + "." + chosenFormat()));
        showMessage("Subtitles downloaded.", "success");
      }).catch(function (err) { showMessage(errText(err), "error"); })
      .then(function () { setBusy(btn, false); });
  }

  /* ---------- playlist ---------- */
  function loadPlaylist(url) {
    return postJson("/api/playlist", { url: url }, 150000).then(function (data) {
      showMessage("", "");
      renderPlaylist(data);
    });
  }
  function playlistLang() {
    var value = $("plLang").value;
    if (value !== "other") return value;
    var typed = $("plOther").value.trim();
    return LANG_RE.test(typed) ? typed : "";
  }
  function renderPlaylist(data) {
    state.playlist = data; state.selected.clear();
    $("playlistTitle").textContent = data.title;
    $("playlistFacts").textContent = [data.channel, data.videos.length + " videos"].filter(Boolean).join("  |  ");
    var notes = [];
    if (data.truncated) notes.push("Showing the first " + data.limit + " videos of this playlist.");
    if (data.skipped) notes.push(data.skipped + " unavailable or private " + (data.skipped === 1 ? "entry was" : "entries were") + " skipped.");
    $("playlistNote").textContent = notes.join(" "); $("playlistNote").hidden = !notes.length;

    var select = $("plLang");
    if (!select.children.length) {
      COMMON_LANGS.forEach(function (l) { select.appendChild(el("option", { value: l[0], text: l[1] })); });
    }
    var list = $("playlistList");
    list.textContent = "";
    data.videos.forEach(function (v) {
      var checkbox = el("input", { type: "checkbox", "aria-label": "Select " + v.title, "data-id": v.video_id });
      var status = el("p", { class: "vstatus", "data-status": v.video_id, "aria-live": "polite" });
      var info = el("div", {}, [
        el("p", { class: "vtitle", text: v.title }),
        el("p", { class: "vmeta", text: [v.index + ".", v.channel, v.duration_text].filter(Boolean).join("  ") }),
        status
      ]);
      var dl = el("button", { class: "btn btn-ghost", type: "button", "data-dl": v.video_id, text: "Download" });
      list.appendChild(el("li", { class: "vitem", "data-row": v.video_id }, [checkbox, info, dl]));
    });
    updateSelection();
    $("videoPanel").hidden = !state.video;
    $("playlistPanel").hidden = false;
    $("playlistPanel").scrollIntoView({ behavior: "smooth", block: "start" });
  }
  function updateSelection() {
    var count = state.selected.size;
    $("selectedCount").textContent = count + " selected" + (count >= MAX_ZIP ? " (maximum)" : "");
    $("zipBtn").disabled = count === 0 || state.busy;
    document.querySelectorAll("#playlistList .vitem").forEach(function (row) {
      var id = row.getAttribute("data-row"), on = state.selected.has(id);
      row.classList.toggle("is-selected", on);
      row.querySelector('input[type="checkbox"]').checked = on;
    });
  }
  function selectAll() {
    state.selected.clear();
    state.playlist.videos.slice(0, MAX_ZIP).forEach(function (v) { state.selected.add(v.video_id); });
    updateSelection();
    if (state.playlist.videos.length > MAX_ZIP) showMessage("Selected the first " + MAX_ZIP + " videos. A ZIP holds up to " + MAX_ZIP + ".", "");
  }
  function rowStatus(id, text, kind) {
    var node = document.querySelector('[data-status="' + id + '"]');
    if (node) { node.textContent = text; node.className = "vstatus" + (kind ? " is-" + kind : ""); }
  }
  function titleOf(id) {
    var v = state.playlist.videos.filter(function (x) { return x.video_id === id; })[0];
    return v ? v.title : id;
  }
  function downloadOne(id, button) {
    var lang = playlistLang();
    if (!lang) { showMessage("Choose a language, or enter a valid language code such as mr or zh-Hans.", "error"); return; }
    var fmt = $("plFormat").value;
    setBusy(button, true); rowStatus(id, "Fetching…", "");
    postFile("/api/download", { video_id: id, lang: lang, kind: "best", format: fmt, title: titleOf(id) }, 120000)
      .then(function (r) { saveBlob(r.blob, filenameFrom(r.res, id + "." + lang + "." + fmt)); rowStatus(id, "Downloaded", "ok"); })
      .catch(function (err) { rowStatus(id, errText(err), "fail"); })
      .then(function () { setBusy(button, false); });
  }

  var timerId = null;
  function downloadZip() {
    var lang = playlistLang();
    if (!lang) { showMessage("Choose a language, or enter a valid language code such as mr or zh-Hans.", "error"); return; }
    var ids = state.playlist.videos.filter(function (v) { return state.selected.has(v.video_id); }).map(function (v) { return v.video_id; });
    if (!ids.length) return;
    var fmt = $("plFormat").value;
    var items = ids.map(function (id) { return { video_id: id, title: titleOf(id) }; });
    state.busy = true; updateSelection(); setBusy($("zipBtn"), true);
    $("zipResult").hidden = true;
    ids.forEach(function (id) { rowStatus(id, "Queued", ""); });
    var started = Date.now();
    $("progressWrap").hidden = false;
    var tick = function () { $("progressText").textContent = "Preparing " + ids.length + " subtitle file" + (ids.length === 1 ? "" : "s") + "… " + Math.round((Date.now() - started) / 1000) + " s. YouTube is contacted once per video, so this can take a minute."; };
    tick(); timerId = setInterval(tick, 1000);

    postFile("/api/download-zip", { items: items, lang: lang, kind: "best", format: fmt }, 15 * 60 * 1000).then(function (r) {
      var failed = (r.res.headers.get("X-Subsave-Failed-Ids") || "").split(",").filter(Boolean);
      var okCount = parseInt(r.res.headers.get("X-Subsave-Succeeded") || "0", 10);
      ids.forEach(function (id) { rowStatus(id, failed.indexOf(id) === -1 ? "In ZIP" : "Failed", failed.indexOf(id) === -1 ? "ok" : "fail"); });
      saveBlob(r.blob, filenameFrom(r.res, "SubSave " + lang + " " + fmt + ".zip"));
      showZipResult(okCount, failed.map(function (id) { return { video_id: id, message: "No " + lang + " subtitles, or YouTube refused the request. See _report.txt in the ZIP." }; }));
    }).catch(function (err) {
      var failures = err instanceof ApiError && err.details && Array.isArray(err.details.failures) ? err.details.failures : [];
      failures.forEach(function (f) { rowStatus(f.video_id, "Failed", "fail"); });
      showZipResult(0, failures, errText(err));
    }).then(function () {
      clearInterval(timerId); $("progressWrap").hidden = true;
      state.busy = false; setBusy($("zipBtn"), false); updateSelection();
    });
  }
  function showZipResult(okCount, failures, errorMessage) {
    var box = $("zipResult");
    box.textContent = "";
    if (errorMessage) box.appendChild(el("p", { text: errorMessage }));
    else box.appendChild(el("p", {}, [el("strong", { text: okCount + " succeeded" }), document.createTextNode(", " + failures.length + " failed. The ZIP also contains a _report.txt.")]));
    if (failures.length) {
      var ul = el("ul");
      failures.slice(0, 50).forEach(function (f) { ul.appendChild(el("li", { text: titleOf(f.video_id) + (f.message ? ": " + f.message : "") })); });
      box.appendChild(ul);
    }
    box.hidden = false;
  }

  /* ---------- connectivity & PWA ---------- */
  function updateNetwork() {
    var online = navigator.onLine;
    $("netStatus").hidden = online; $("offlineNote").hidden = online;
  }
  var deferredPrompt = null;
  function setupInstall() {
    var standalone = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
    if (standalone) return;
    $("installBtn").hidden = false;
    window.addEventListener("beforeinstallprompt", function (e) { e.preventDefault(); deferredPrompt = e; });
    window.addEventListener("appinstalled", function () { $("installBtn").hidden = true; deferredPrompt = null; showMessage("SubSave is installed.", "success"); });
    $("installBtn").addEventListener("click", function () {
      if (deferredPrompt) {
        deferredPrompt.prompt();
        deferredPrompt.userChoice.then(function () { deferredPrompt = null; });
      } else {
        showMessage("To install: open your browser menu and choose Install app or Add to Home screen.", "");
      }
    });
  }
  function registerWorker() {
    if ("serviceWorker" in navigator && (location.protocol === "https:" || location.hostname === "localhost" || location.hostname === "127.0.0.1")) {
      window.addEventListener("load", function () { navigator.serviceWorker.register("/sw.js").catch(function () { /* app still works online */ }); });
    }
  }

  /* ---------- wiring ---------- */
  $("analyzeForm").addEventListener("submit", analyze);
  $("trackSelect").addEventListener("change", updateTrackHint);
  $("videoDownloadBtn").addEventListener("click", downloadVideo);
  $("loadPlaylistBtn").addEventListener("click", function () {
    var btn = $("loadPlaylistBtn"); setBusy(btn, true);
    loadPlaylist(state.videoUrl).catch(function (err) { showMessage(errText(err), "error"); }).then(function () { setBusy(btn, false); });
  });
  $("plLang").addEventListener("change", function () { $("plOtherWrap").hidden = $("plLang").value !== "other"; });
  $("selectAllBtn").addEventListener("click", selectAll);
  $("deselectAllBtn").addEventListener("click", function () { state.selected.clear(); updateSelection(); });
  $("zipBtn").addEventListener("click", downloadZip);
  $("playlistList").addEventListener("change", function (event) {
    var box = event.target;
    if (!box || box.type !== "checkbox") return;
    var id = box.getAttribute("data-id");
    if (box.checked) {
      if (state.selected.size >= MAX_ZIP) { box.checked = false; showMessage("A ZIP can hold up to " + MAX_ZIP + " videos.", ""); return; }
      state.selected.add(id);
    } else { state.selected.delete(id); }
    updateSelection();
  });
  $("playlistList").addEventListener("click", function (event) {
    var button = event.target.closest ? event.target.closest("[data-dl]") : null;
    if (button) downloadOne(button.getAttribute("data-dl"), button);
  });
  window.addEventListener("online", updateNetwork);
  window.addEventListener("offline", updateNetwork);
  updateNetwork(); setupInstall(); registerWorker();
})();
