"""Tiny HTTP toolkit: cookies, query parsing, JSON replies, Range file serving."""
from __future__ import annotations

import json
import mimetypes
import os
import re
import urllib.parse

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".webm": "video/webm",
    ".m3u8": "application/vnd.apple.mpegurl",
    ".ts": "video/mp2t",
    ".vtt": "text/vtt; charset=utf-8",
    ".srt": "application/x-subrip",
    ".nfo": "application/xml",
    ".txt": "text/plain; charset=utf-8",
}
mimetypes.add_type("application/vnd.apple.mpegurl", ".m3u8")


def ctype_for(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return MIME.get(ext) or mimetypes.guess_type(path)[0] or "application/octet-stream"


def parse_cookies(header: str | None) -> dict:
    out = {}
    for part in (header or "").split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = urllib.parse.unquote(v.strip())
    return out


def parse_range(header: str | None, size: int):
    """Return (start, end) inclusive, or None when unsatisfiable/absent."""
    if not header:
        return None
    m = re.match(r"bytes=(\d*)-(\d*)$", header.strip())
    if not m:
        return None
    start_s, end_s = m.group(1), m.group(2)
    if start_s == "" and end_s == "":
        return None
    if start_s == "":
        length = int(end_s)
        if length <= 0:
            return None
        start = max(0, size - length)
        end = size - 1
    else:
        start = int(start_s)
        end = int(end_s) if end_s else size - 1
    if start > end or start >= size:
        return ("-1", "-1")
    return (start, min(end, size - 1))


class Ctx:
    def __init__(self, handler, method: str, path: str, query: dict, body: bytes,
                 user: dict | None, params: dict, store, settings: dict, client_ip: str):
        self.handler = handler
        self.method = method
        self.path = path
        self.query = query
        self.body = body
        self.user = user
        self.params = params
        self.store = store
        self.settings = settings
        self.client_ip = client_ip
        self._sent = False
        self.extra_headers: list[tuple[str, str]] = []

    # ------------------------------------------------------------- replies
    def send(self, status: int, body: bytes = b"", ctype: str = "text/plain; charset=utf-8",
             headers: dict | None = None) -> None:
        if self._sent:
            return
        h = self.handler
        h.send_response(status)
        h.send_header("Content-Type", ctype)
        h.send_header("Content-Length", str(len(body)))
        h.send_header("X-Content-Type-Options", "nosniff")
        h.send_header("Referrer-Policy", "same-origin")
        for k, v in self.extra_headers:
            h.send_header(k, v)
        for k, v in (headers or {}).items():
            h.send_header(k, v)
        h.end_headers()
        if self.method != "HEAD" and body:
            try:
                h.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass
        self._sent = True

    def json(self, data, status: int = 200, headers: dict | None = None) -> None:
        raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send(status, raw, "application/json; charset=utf-8",
                  headers={"Cache-Control": "no-store", **(headers or {})})

    def error(self, message: str, status: int = 400, code: str = "error") -> None:
        self.json({"ok": False, "error": message, "code": code}, status=status)

    # --------------------------------------------------------- file stream
    def serve_path(self, path: str, *, download_name: str | None = None,
                   ctype: str | None = None, cache: str = "public, max-age=3600") -> None:
        if not os.path.isfile(path):
            self.error("文件不存在", 404, "not_found")
            return
        size = os.path.getsize(path)
        ctype = ctype or ctype_for(path)
        rng = parse_range(self.handler.headers.get("Range"), size)
        if rng == ("-1", "-1"):
            self.send(416, b"", ctype, {"Content-Range": f"bytes */{size}"})
            return
        start, end = (0, size - 1) if not rng else rng
        length = end - start + 1
        status = 206 if rng else 200
        h = self.handler
        h.send_response(status)
        h.send_header("Content-Type", ctype)
        h.send_header("Content-Length", str(length))
        h.send_header("Accept-Ranges", "bytes")
        if rng:
            h.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        h.send_header("Cache-Control", cache)
        if download_name:
            h.send_header("Content-Disposition", content_disposition(download_name))
        h.end_headers()
        if self.method == "HEAD":
            self._sent = True
            return
        remaining = length
        try:
            with open(path, "rb") as fh:
                fh.seek(start)
                while remaining > 0:
                    chunk = fh.read(min(262144, remaining))
                    if not chunk:
                        break
                    h.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        self._sent = True


def content_disposition(name: str) -> str:
    ascii_name = name.encode("ascii", "replace").decode("ascii").replace('"', "'")
    quoted = urllib.parse.quote(name, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quoted}"
