#!/usr/bin/env python3
"""CineBox — self-hosted film library (search / watch / download).

Zero third-party dependencies: Python 3.10+ standard library only, ffmpeg optional
(used for HLS ladders and the software-decode rendition).

    python app.py            # listens on 0.0.0.0:8426
"""
from __future__ import annotations

import json
import os
import re
import sys
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from cinelib import api_admin, api_auth, api_catalog, api_live_http, api_media, auth, httpkit, media  # noqa: E402
from cinelib.store import Store  # noqa: E402

WEB_DIR = os.path.join(ROOT, "web")
DATA_DIR = os.path.join(ROOT, "data")
MEDIA_DIR = os.path.join(ROOT, "media")
PORT = int(os.environ.get("PRIVATECINEMA_PORT")
           or os.environ.get("CINEBOX_PORT", "8426"))
HOST = (os.environ.get("PRIVATECINEMA_HOST")
        or os.environ.get("CINEBOX_HOST", "0.0.0.0"))
VERSION = "1.0.0"

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(MEDIA_DIR, exist_ok=True)
os.makedirs(os.path.join(MEDIA_DIR, "assets"), exist_ok=True)

STORE = Store(os.path.join(DATA_DIR, "db.json"))
auth.ensure_admin(STORE)
api_media.configure(MEDIA_DIR)
STORE.settings["_port"] = PORT
STARTED = __import__("time").time()


def api_health(ctx):
    ctx.json({"ok": True, "version": VERSION, "ffmpeg": media.available(),
              "uptime": int(__import__("time").time() - STARTED),
              "movies": len(STORE.data["movies"]), "user": bool(ctx.user)})


def R(method: str, pattern: str, handler, role: str | None = None):
    return (method, re.compile("^" + pattern + "$"), handler, role)


ROUTES = [
    R("GET", r"/api/health", api_health),
    # auth
    R("POST", r"/api/auth/login", api_auth.h_login),
    R("POST", r"/api/auth/logout", api_auth.h_logout),
    R("POST", r"/api/auth/register", api_auth.h_register),
    R("GET", r"/api/auth/me", api_auth.h_me),
    R("PATCH", r"/api/me", api_auth.h_update_me, "user"),
    R("POST", r"/api/me/password", api_auth.h_change_password, "user"),
    # catalog
    R("GET", r"/api/search", api_catalog.h_search),
    R("GET", r"/api/suggest", api_catalog.h_suggest),
    R("GET", r"/api/live/search", api_live_http.h_live_search),
    R("GET", r"/api/live/sources", api_live_http.h_live_sources),
    R("GET", r"/api/live/item", api_live_http.h_live_item),
    R("GET", r"/api/live/group", api_live_http.h_live_group),
    R("GET", r"/api/live/download", api_live_http.h_live_download, "user"),
    R("GET", r"/api/home", api_catalog.h_home),
    R("GET", r"/api/movies/(?P<id>[\w-]+)", api_catalog.h_movie, "user"),
    # playlists / history / downloads
    R("GET", r"/api/playlists", api_catalog.h_playlists, "user"),
    R("POST", r"/api/playlists", api_catalog.h_playlist_create, "user"),
    R("PATCH", r"/api/playlists/(?P<id>[\w-]+)", api_catalog.h_playlist_update, "user"),
    R("DELETE", r"/api/playlists/(?P<id>[\w-]+)", api_catalog.h_playlist_delete, "user"),
    R("GET", r"/api/history", api_catalog.h_history_get, "user"),
    R("POST", r"/api/history", api_catalog.h_history_post, "user"),
    R("DELETE", r"/api/history(?:/(?P<id>[\w-]+))?", api_catalog.h_history_clear, "user"),
    R("GET", r"/api/downloads", api_catalog.h_downloads_get, "user"),
    # media
    R("GET", r"/api/stream/(?P<mid>[\w-]+)/(?P<fid>[\w-]+)", api_media.h_stream, "user"),
    R("GET", r"/api/download/(?P<mid>[\w-]+)/(?P<fid>[\w-]+)", api_media.h_download, "user"),
    R("GET", r"/api/proxy", api_media.h_proxy),
    R("GET", r"/api/img", api_media.h_img),
    R("GET", r"/api/subtitles/(?P<mid>[\w-]+)/(?P<sid>[\w-]+)", api_media.h_subtitle, "user"),
    # admin
    R("GET", r"/api/admin/stats", api_admin.h_stats, "admin"),
    R("GET", r"/api/admin/users", api_admin.h_users, "admin"),
    R("POST", r"/api/admin/users", api_admin.h_user_create, "admin"),
    R("PATCH", r"/api/admin/users/(?P<id>[\w-]+)", api_admin.h_user_update, "admin"),
    R("DELETE", r"/api/admin/users/(?P<id>[\w-]+)", api_admin.h_user_delete, "admin"),
    R("GET", r"/api/admin/settings", api_admin.h_settings_get, "admin"),
    R("PUT", r"/api/admin/settings", api_admin.h_settings_put, "admin"),
    R("GET", r"/api/admin/movies", api_admin.h_movies, "admin"),
    R("GET", r"/api/admin/movies/(?P<id>[\w-]+)", api_admin.h_movie_get, "admin"),
    R("POST", r"/api/admin/movies", api_admin.h_movie_create, "admin"),
    R("PATCH", r"/api/admin/movies/(?P<id>[\w-]+)", api_admin.h_movie_update, "admin"),
    R("DELETE", r"/api/admin/movies/(?P<id>[\w-]+)", api_admin.h_movie_delete, "admin"),
    R("POST", r"/api/admin/movies/(?P<id>[\w-]+)/hls", api_admin.h_build_hls, "admin"),
    R("DELETE", r"/api/admin/movies/(?P<mid>[\w-]+)/files/(?P<fid>[\w-]+)",
      api_admin.h_file_delete, "admin"),
    R("PUT", r"/api/admin/upload", api_admin.h_movie_upload, "admin"),
    R("POST", r"/api/admin/rescan", api_admin.h_rescan, "admin"),
    R("GET", r"/api/admin/transcode/probe", api_admin.h_transcode_probe, "admin"),
    R("GET", r"/api/admin/sources", api_admin.h_sources, "admin"),
    R("POST", r"/api/admin/sources", api_admin.h_source_add, "admin"),
    R("POST", r"/api/admin/sources/test", api_admin.h_source_test, "admin"),
    R("PATCH", r"/api/admin/sources/(?P<id>[\w-]+)", api_admin.h_source_update, "admin"),
    R("DELETE", r"/api/admin/sources/(?P<id>[\w-]+)", api_admin.h_source_delete, "admin"),
    R("GET", r"/api/admin/providers", api_admin.h_providers, "admin"),
    R("POST", r"/api/admin/providers/search", api_admin.h_provider_search, "admin"),
    R("POST", r"/api/admin/providers/test", api_admin.h_test_provider, "admin"),
    R("POST", r"/api/admin/import", api_admin.h_import, "admin"),
    R("POST", r"/api/admin/movies/(?P<id>[\w-]+)/enrich", api_admin.h_enrich, "admin"),
]

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_EXEMPT = {"/api/auth/login", "/api/auth/register"}


class App(BaseHTTPRequestHandler):
    server_version = "PrivateCinema/" + VERSION
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------- plumbing
    def log_message(self, fmt, *args):  # quieter, timestamped
        sys.stdout.write("[%s] %s %s\n" % (
            __import__("time").strftime("%H:%M:%S"), self.address_string(), fmt % args))

    def _read_body(self, limit: int = 4 * 1024 * 1024) -> bytes:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return b""
        if length <= 0:
            return b""
        if length > limit:
            return b""
        return self.rfile.read(length)

    def _dispatch(self, method: str):
        parsed = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(parsed.path)
        query = urllib.parse.parse_qs(parsed.query)
        try:
            # ---------- static + SPA
            if not path.startswith("/api/"):
                if self._static(path):
                    return
                if method in ("GET", "HEAD"):
                    return self._serve_spa(path)
                return self._plain(405, "Method Not Allowed")

            cookies = httpkit.parse_cookies(self.headers.get("Cookie"))
            token = cookies.get(auth.SESSION_COOKIE)
            user = auth.session_user(STORE, token)
            body = b""
            if method in MUTATING and path != "/api/admin/upload":
                body = self._read_body()
            ip = self.headers.get("X-Forwarded-For", "").split(",")[0].strip() or \
                self.client_address[0]
            ctx = httpkit.Ctx(self, method, path, query, body, user, {}, STORE,
                              STORE.settings, ip)
            ctx.cookies = cookies
            ctx.body_json = lambda: _json_body(ctx)
            ctx.media_root = MEDIA_DIR

            route = None
            method_mismatch = False
            for r_method, r_pat, r_handler, r_role in ROUTES:
                m = r_pat.match(path)
                if not m:
                    continue
                if r_method != method:
                    method_mismatch = True
                    continue
                route = (m, r_handler, r_role)
                break
            if not route:
                if method_mismatch:
                    return ctx.error("方法不允许", 405, "method_not_allowed")
                return ctx.error("接口不存在", 404, "not_found")
            m, handler, role = route
            if role == "user" and not user:
                return ctx.error("请先登录", 401, "login_required")
            if role == "admin" and (not user or user.get("role") != "admin"):
                return ctx.error("需要管理员权限", 403, "forbidden")
            if method in MUTATING and user and path not in CSRF_EXEMPT:
                sent = self.headers.get("X-CSRF") or ""
                if not sent or sent != cookies.get(auth.CSRF_COOKIE):
                    return ctx.error("会话校验失败，请刷新页面", 403, "csrf")
            ctx.params = {k: v for k, v in m.groupdict().items() if v is not None}
            handler(ctx)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            try:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                payload = json.dumps({"ok": False, "error": "服务器内部错误"},
                                     ensure_ascii=False).encode()
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except Exception:
                pass

    # -------------------------------------------------------------- helpers
    def _plain(self, code: int, text: str):
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path: str) -> bool:
        if path.startswith("/media/"):
            return self._media(path)
        if path.startswith("/static/"):
            rel = path[len("/static/"):]
            target = os.path.abspath(os.path.join(WEB_DIR, "static", *rel.split("/")))
            if not target.startswith(os.path.abspath(os.path.join(WEB_DIR, "static"))):
                self._plain(403, "forbidden")
                return True
            if os.path.isfile(target):
                ctx = self._ctx_for_static()
                # local self-hosted app: always revalidate so a code update is
                # picked up on the next refresh (no stale CSS/JS after patches)
                ctx.serve_path(target, cache="no-cache")
                return True
            return False
        return False

    def _media(self, path: str):
        rel = path[len("/media/"):]
        parts = rel.split("/")
        if not parts or not parts[0]:
            self._plain(404, "not found")
            return True
        target = os.path.abspath(os.path.join(MEDIA_DIR, *parts))
        if not target.startswith(os.path.abspath(MEDIA_DIR)):
            self._plain(403, "forbidden")
            return True
        if not os.path.isfile(target):
            self._plain(404, "not found")
            return True
        public = parts[0] in ("assets",)
        if not public:
            cookies = httpkit.parse_cookies(self.headers.get("Cookie"))
            user = auth.session_user(STORE, cookies.get(auth.SESSION_COOKIE))
            if not user:
                self._plain(401, "login required")
                return True
        ctx = self._ctx_for_static()
        ctype = httpkit.ctype_for(target)
        cache = "public, max-age=86400" if public else "private, max-age=300"
        if path.endswith(".m3u8"):
            cache = "no-store"
        ctx.serve_path(target, ctype=ctype, cache=cache)
        return True

    def _ctx_for_static(self):
        cookies = httpkit.parse_cookies(self.headers.get("Cookie"))
        user = auth.session_user(STORE, cookies.get(auth.SESSION_COOKIE))
        ctx = httpkit.Ctx(self, self.command, self.path, {}, b"", user, {}, STORE,
                          STORE.settings, self.client_address[0])
        ctx.cookies = cookies
        return ctx

    def _serve_spa(self, path: str):
        index = os.path.join(WEB_DIR, "index.html")
        if not os.path.isfile(index):
            self._plain(500, "web/index.html missing")
            return
        with open(index, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob: data:; "
            "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self' blob:; "
            "font-src 'self' data:; object-src 'none'; base-uri 'self'",
        )
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    # --------------------------------------------------------------- verbs
    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("HEAD")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Allow", "GET, HEAD, POST, PUT, PATCH, DELETE, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()


def _json_body(ctx) -> dict:
    if not ctx.body:
        return {}
    try:
        data = json.loads(ctx.body.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}


class CineServer(ThreadingHTTPServer):
    daemon_threads = True
    # Windows SO_REUSEADDR lets two processes bind the same port (connections
    # then land on either one), so only reuse addresses on POSIX.
    allow_reuse_address = os.name != "nt"

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


def _already_running(port: int) -> bool:
    """True when a CINEBOX instance already answers on this port."""
    import socket
    import urllib.request

    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.8):
            pass
    except OSError:
        return False
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1.8) as resp:
            return resp.status == 200
    except Exception:
        return False


def _open_browser_later(port: int) -> None:
    """Optionally open the local UI after boot (CINEBOX_OPEN=1, set by start.bat)."""
    if str(os.environ.get("CINEBOX_OPEN", "")).lower() not in ("1", "true", "yes", "on"):
        return
    import threading
    import time
    import webbrowser

    def run():
        time.sleep(1.4)
        try:
            webbrowser.open(f"http://127.0.0.1:{port}")
        except Exception:
            pass

    threading.Thread(target=run, daemon=True).start()


def _port_in_use(exc: OSError) -> bool:
    return getattr(exc, "winerror", None) == 10048 or getattr(exc, "errno", None) in (48, 98, 10048)


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if _already_running(PORT):
        print("=" * 66)
        print(f"  CINEBOX 已经在运行： http://127.0.0.1:{PORT}")
        print("  无需重复启动。若窗口已关，服务仍在后台继续工作。")
        print(f"  想换端口启动： set PRIVATECINEMA_PORT=8430 && python app.py")
        print("=" * 66)
        _open_browser_later(PORT)
        return 2
    try:
        server = CineServer((HOST, PORT), App)
    except OSError as exc:
        if _port_in_use(exc):
            print("=" * 66)
            print(f"  端口 {PORT} 已被占用。")
            print(f"  如果 PrivateCinema 已经在运行，直接打开： http://127.0.0.1:{PORT}")
            print(f"  想换端口启动： set PRIVATECINEMA_PORT=8430 && python app.py")
            print("=" * 66)
            _open_browser_later(PORT)
            return 2
        raise
    server.daemon_threads = True
    print("=" * 66)
    print(f"  PrivateCinema {VERSION}  ·  私人影院 / 在线观看 / 下载管理")
    print(f"  本机访问   http://127.0.0.1:{PORT}")
    print(f"  局域网     http://<本机IP>:{PORT}")
    print(f"  数据库     {os.path.join(DATA_DIR, 'db.json')}")
    print(f"  媒体目录   {MEDIA_DIR}")
    print(f"  ffmpeg     {'可用' if media.available() else '未检测到（HLS/软解转码不可用）'}")
    print("=" * 66)
    _open_browser_later(PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[exit] 正在关闭 PrivateCinema…")
    finally:
        server.server_close()


if __name__ == "__main__":
    sys.exit(main() or 0)
