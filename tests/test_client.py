"""End-to-end smoke test for CineBox (stdlib only)."""
import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile

BASE = "http://127.0.0.1:8426"
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
CSRF = {"v": ""}


def call(path, method="GET", body=None, headers=None, raw=False):
    h = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    if method != "GET" and CSRF["v"]:
        h["X-CSRF"] = CSRF["v"]
    h.update(headers or {})
    req = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    try:
        with opener.open(req, timeout=60) as r:
            payload = r.read()
            if raw:
                return r.status, dict(r.headers), payload
            return r.status, dict(r.headers), json.loads(payload or b"{}")
    except urllib.error.HTTPError as e:
        payload = e.read()
        if raw:
            return e.code, dict(e.headers or {}), payload
        try:
            return e.code, dict(e.headers or {}), json.loads(payload or b"{}")
        except Exception:
            return e.code, dict(e.headers or {}), {"raw": payload[:200]}


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    st, _, data = call("/api/health")
    print("health", st, data)

    st, _, data = call("/api/search?q=chaplin")
    print("guest search", st, "total=", data.get("total"), "guestMode=", data.get("guestMode"))

    st, _, data = call("/api/home")
    print("guest home", st, data.get("code"))

    st, _, data = call("/api/auth/login", "POST", {"username": "admin", "password": "admin"})
    print("login", st, data.get("user", {}).get("role"))
    CSRF["v"] = data.get("csrf", "")

    st, _, data = call("/api/home")
    print("home", st, "movies=", data["counts"]["movies"], "featured=", len(data.get("featured") or []),
          "continue=", len(data.get("continue") or []))

    mid = (data.get("featured") or data.get("recent"))[0]["id"]
    st, _, detail = call(f"/api/movies/{mid}")
    m = detail["movie"]
    print("detail", st, m["title"], "watch=", len(m["watchQualities"]), "dl=", len(m["downloadQualities"]),
          "extras=", len(m["downloadExtras"]), "subs=", len(m["subtitles"]))

    f = m["watchQualities"][0]
    st, hdrs, body = call(f"/api/stream/{mid}/{f['id']}", headers={"Range": "bytes=0-2047"}, raw=True)
    print("stream", st, "len=", len(body), "ctype=", hdrs.get("Content-Type"), "range=", hdrs.get("Content-Range"))

    st, _, pl = call("/api/playlists", "POST", {"name": "测试片单"})
    print("playlist create", st, pl.get("playlist", {}).get("name"))
    pid = pl["playlist"]["id"]
    st, _, pl2 = call(f"/api/playlists/{pid}", "PATCH", {"addMovieId": mid})
    print("playlist add", st)
    st, _, hist = call("/api/history", "POST", {"movieId": mid, "fileId": f["id"],
                                                "position": 12.5, "duration": 42, "quality": f["quality"]})
    print("history post", st)
    st, _, hl = call("/api/history")
    print("history list", st, len(hl["items"]), "progress=", hl["items"][0]["progress"])

    dl = m["downloadQualities"][0]
    st, hdrs, body = call(f"/api/download/{mid}/{dl['id']}?extras=poster,nfo,json,readme,checksums,m3u",
                          raw=True)
    print("download zip", st, "bytes=", len(body), "type=", hdrs.get("Content-Type"))
    with open("test_dl.zip", "wb") as fh:
        fh.write(body)
    with zipfile.ZipFile("test_dl.zip") as zf:
        bad = zf.testzip()
        print("zip entries", zf.namelist(), "crc_ok=", bad is None)

    st, hdrs, body = call(f"/api/download/{mid}/{dl['id']}", raw=True)
    print("download direct", st, "bytes=", len(body), "disp=", hdrs.get("Content-Disposition"))

    st, _, adm = call("/api/admin/stats")
    print("admin stats", st, adm["counts"])
    st, _, users = call("/api/admin/users")
    print("admin users", st, [u["username"] for u in users["items"]])
    st, _, prov = call("/api/admin/providers/test", "POST", {"provider": "itunes", "q": "inception"})
    print("provider test", st, prov.get("count"), prov.get("ms"))

    st, hdrs, body = call("/api/subtitles/%s/%s" % (mid, m["subtitles"][0]["id"]), raw=True) if m["subtitles"] else (0, {}, b"")
    print("subtitle", st, len(body))

    st, _, up = call("/api/suggest?q=" + urllib.parse.quote("霓"))
    print("suggest", st, len(up["items"]))

    # guest access to protected route
    jar.clear()
    st, _, g = call("/api/home")
    print("after logout home", st, g.get("code"))


if __name__ == "__main__":
    main()
