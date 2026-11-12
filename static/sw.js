/* SubSave service worker: caches the app shell only. API responses are never cached. */
const CACHE = "subsave-shell-v1";
const SHELL = ["/", "/index.html", "/style.css", "/app.js", "/manifest.webmanifest", "/icon.svg", "/icon-192.png", "/icon-512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

function offlineJson() {
  return new Response(
    JSON.stringify({ ok: false, error: { code: "OFFLINE", message: "You are offline. Reading and processing subtitles needs an internet connection." } }),
    { status: 503, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } }
  );
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;           // fonts, thumbnails: browser handles them
  if (url.pathname.startsWith("/api/")) {                    // never cache or intercept private downloads
    if (request.method !== "GET" && request.method !== "POST") return;
    event.respondWith(fetch(request).catch(offlineJson));
    return;
  }
  if (request.method !== "GET") return;
  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(() => caches.match("/index.html")));
    return;
  }
  event.respondWith(
    caches.match(request).then((cached) => {
      const refresh = fetch(request).then((response) => {
        if (response && response.ok) {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(request, copy));
        }
        return response;
      }).catch(() => cached);
      return cached || refresh;
    })
  );
});
