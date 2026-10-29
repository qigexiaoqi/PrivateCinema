"""Admin CRUD smoke test (movies / users / settings / providers)."""
import http.cookiejar
import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8426"
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
CSRF = {"v": ""}


def call(path, method="GET", body=None, raw=False):
    h = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    if method != "GET" and CSRF["v"]:
        h["X-CSRF"] = CSRF["v"]
    req = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    try:
        with opener.open(req, timeout=90) as r:
            payload = r.read()
            return r.status, json.loads(payload or b"{}") if not raw else payload
    except urllib.error.HTTPError as e:
        payload = e.read()
        try:
            return e.code, json.loads(payload or b"{}")
        except Exception:
            return e.code, {"raw": payload[:200]}


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    st, d = call("/api/auth/login", "POST", {"username": "admin", "password": "admin"})
    CSRF["v"] = d.get("csrf", "")
    print("login", st)

    st, d = call("/api/admin/movies", "POST", {
        "title": "测试影片 Test Fixture", "originalTitle": "Test Fixture", "year": 2021,
        "genres": "测试, 剧情", "rating": 6.5, "runtime": 90, "director": "测试导演",
        "cast": "演员甲, 演员乙", "synopsis": "这是一条用于自检的测试记录。",
        "status": "draft", "featured": False,
        "files": [{"quality": "720p", "label": "720P · 测试源", "watchType": "remote",
                   "watchValue": "https://archive.org/download/his_girl_friday/his_girl_friday_512kb.mp4",
                   "downloadEnabled": True}],
    })
    print("movie create", st, d)
    mid = d.get("id")

    st, m = call(f"/api/movies/{mid}")
    print("movie detail", st, m.get("movie", {}).get("title"), "files", len(m.get("movie", {}).get("files") or []))

    st, d = call(f"/api/admin/movies/{mid}", "PATCH", {"title": "测试影片 改名", "featured": True})
    print("movie patch", st, d)

    st, d = call("/api/admin/users", "POST", {"username": "tester01", "password": "tester123", "role": "user"})
    print("user create", st, d)
    st, users = call("/api/admin/users")
    tid = next((u["id"] for u in users["items"] if u["username"] == "tester01"), None)
    st, d = call(f"/api/admin/users/{tid}", "PATCH", {"status": "disabled", "password": "newpass123"})
    print("user patch", st, d)
    st, d = call(f"/api/admin/users/{tid}", "DELETE")
    print("user delete", st, d)

    st, s = call("/api/admin/settings")
    print("settings get", st, s["settings"]["siteName"], "proxy", s["settings"]["proxyUrl"])
    st, d = call("/api/admin/settings", "PUT", {"siteName": "CINEBOX", "defaultDecoding": "auto",
                                                "downloadExtrasDefault": ["poster", "nfo", "json", "readme"]})
    print("settings put", st, d.get("ok"))

    st, d = call("/api/admin/providers/test", "POST", {"provider": "archive", "q": "chaplin"})
    print("archive test", st, d.get("count"), "ms", d.get("ms"))
    st, d = call("/api/admin/providers/test", "POST", {"provider": "wiki", "q": "盗梦空间"})
    print("wiki test", st, d.get("count"), "ms", d.get("ms"))
    st, d = call("/api/admin/providers/search", "POST", {"provider": "archive", "q": "nosferatu"})
    print("archive search", st, len(d.get("items") or []),
          (d.get("items") or [{}])[0].get("title") if d.get("items") else "")

    st, d = call(f"/api/admin/movies/{mid}", "DELETE")
    print("movie delete", st, d)

    st, d = call("/api/admin/rescan", "POST")
    print("rescan", st, d.get("updated"), "ffmpeg", d.get("ffmpeg"))

    # guest cannot reach admin
    jar.clear()
    st, d = call("/api/admin/movies")
    print("guest admin", st, d.get("code"))


if __name__ == "__main__":
    main()
