"""Proxy-aware HTTP helpers used for upstream film metadata and media.

Every outbound call tries the configured proxy first and silently falls back to
a direct connection, so the same build works behind the 127.0.0.1:7897 tunnel
and on a plain server.
"""
from __future__ import annotations

import base64
import io
import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CineBox/1.0"

# Hosts that may be fetched through the media/image proxy.  Anything else is
# rejected so the proxy can never be turned into an open relay.
ALLOWED_HOSTS = {
    "archive.org", "www.archive.org", "ia.us.archive.org", "ia801.us.archive.org",
    "ia802.us.archive.org", "ia803.us.archive.org", "ia804.us.archive.org",
    "ia805.us.archive.org", "ia806.us.archive.org", "ia807.us.archive.org",
    "is1-ssl.mzstatic.com", "is2-ssl.mzstatic.com", "is3-ssl.mzstatic.com",
    "is4-ssl.mzstatic.com", "is5-ssl.mzstatic.com", "mzstatic.com",
    "image.tmdb.org", "m.media-amazon.com", "ia.media-imdb.com",
    "static.tvmaze.com", "media.themoviedb.org", "upload.wikimedia.org",
    "dn720308.us.archive.org", "dn790007.us.archive.org",
}
ALLOWED_SUFFIXES = (".archive.org", ".mzstatic.com", ".themoviedb.org",
                    ".tvmaze.com", ".itunes.apple.com", ".apple.com")


def host_allowed(host: str, extra: set[str] | None = None) -> bool:
    host = (host or "").lower().split(":")[0]
    if not host:
        return False
    if extra and host in extra:
        return True
    if host in ALLOWED_HOSTS:
        return True
    return any(host.endswith(suffix) for suffix in ALLOWED_SUFFIXES)


def proxy_candidates(settings: dict | None) -> list[str | None]:
    """Ordered proxy list: configured proxy first, then a direct attempt."""
    out: list[str | None] = []
    if settings and settings.get("proxyEnabled") and settings.get("proxyUrl"):
        out.append(settings["proxyUrl"].strip())
    out.append(None)
    return out


def _opener(proxy: str | None):
    if proxy:
        handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
    else:
        handler = urllib.request.ProxyHandler({})
    return urllib.request.build_opener(handler)


def open_url(url: str, *, headers: dict | None = None, timeout: float = 20,
             proxy: str | None = None, method: str = "GET", data: bytes | None = None):
    hdrs = {"User-Agent": UA, "Accept": "*/*"}
    if headers:
        hdrs.update({k: v for k, v in headers.items() if v is not None})
    req = urllib.request.Request(url, headers=hdrs, method=method, data=data)
    return _opener(proxy).open(req, timeout=timeout)


def request(url: str, *, settings: dict | None = None, headers: dict | None = None,
            timeout: float = 20, method: str = "GET", data: bytes | None = None,
            attempts: int = 12):
    """Return (status, headers, body) trying proxy then direct."""
    errors = []
    for proxy in proxy_candidates(settings):
        for _ in range(attempts):
            try:
                with open_url(url, headers=headers, timeout=timeout, proxy=proxy,
                              method=method, data=data) as resp:
                    return resp.status, dict(resp.headers), resp.read()
            except urllib.error.HTTPError as exc:
                body = b""
                try:
                    body = exc.read()
                except Exception:
                    pass
                if exc.code in (301, 302, 303, 307, 308):
                    loc = exc.headers.get("Location")
                    if loc:
                        return request(urllib.parse.urljoin(url, loc), settings=settings,
                                       headers=headers, timeout=timeout, method=method,
                                       data=data, attempts=attempts)
                return exc.code, dict(exc.headers or {}), body
            except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
                errors.append(f"{proxy or 'direct'}: {exc}")
                break  # try next candidate immediately
    raise IOError("upstream failed: " + "; ".join(errors[-3:]))


def fetch_json(url: str, *, settings: dict | None = None, timeout: float = 20) -> dict:
    status, _headers, body = request(url, settings=settings, timeout=timeout,
                                     headers={"Accept": "application/json"})
    if status >= 400:
        raise IOError(f"HTTP {status} for {url}")
    return json.loads(body.decode("utf-8", "replace"))


def fetch_bytes(url: str, *, settings: dict | None = None, timeout: float = 30,
                limit: int = 12 * 1024 * 1024) -> bytes:
    status, headers, body = request(url, settings=settings, timeout=timeout)
    if status >= 400:
        raise IOError(f"HTTP {status}")
    return body[:limit]


def probe_size(url: str, *, settings: dict | None = None) -> int | None:
    try:
        status, headers, _ = request(url, settings=settings, method="HEAD", timeout=12)
        length = headers.get("Content-Length") or headers.get("content-length")
        return int(length) if length else None
    except Exception:
        return None


def b64url_encode(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def b64url_decode(text: str) -> str:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad).decode("utf-8")


def proxied(url: str) -> str:
    """Rewrite an upstream media/image URL through our own proxy endpoint."""
    return "/api/proxy?u=" + urllib.parse.quote(url, safe="") if _needs_proxy(url) else url


def _needs_proxy(url: str) -> bool:
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return host not in ("localhost", "127.0.0.1")


def safe_join(root: str, *parts) -> str:
    target = os.path.abspath(os.path.join(root, *parts))
    root_abs = os.path.abspath(root)
    if not target.startswith(root_abs + os.sep) and target != root_abs:
        raise ValueError("path escapes root")
    return target


def human_bytes(n: int | None) -> str:
    if not n:
        return "—"
    units = ["B", "KB", "MB", "GB", "TB"]
    val = float(n)
    for unit in units:
        if val < 1024 or unit == units[-1]:
            return f"{val:.0f} {unit}" if unit == "B" else f"{val:.1f} {unit}"
        val /= 1024
    return f"{n} B"
