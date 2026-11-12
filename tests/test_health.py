def test_health_ok(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "ok"
    assert "yt_dlp_installed" in body["data"]


def test_health_headers(client):
    r = client.get("/api/health")
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in r.headers["content-security-policy"]


def test_unknown_api_route_is_json(client):
    r = client.get("/api/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


def test_static_files_served(client):
    assert "SubSave" in client.get("/").text
    manifest = client.get("/manifest.webmanifest")
    assert manifest.status_code == 200
    assert "manifest+json" in manifest.headers["content-type"]
    sw = client.get("/sw.js")
    assert sw.status_code == 200 and sw.headers["cache-control"] == "no-cache"
