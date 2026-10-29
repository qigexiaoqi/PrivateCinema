"""Media routes: playback stream, download bundles, image/media proxy, subtitles."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.parse
import zlib

from . import httpkit, media, net
from .catalog import normalize_img
from .store import now_ts

MEDIA_DIR = ""

SOFT_DIR = "soft"
IMG_CACHE = "assets/imgcache"

# hosts discovered from live sources / playlists (persisted in db["liveHosts"])
_DYNAMIC_HOSTS: set[str] = set()


def configure(media_dir: str) -> None:
    global MEDIA_DIR
    MEDIA_DIR = os.path.abspath(media_dir)
    os.makedirs(os.path.join(MEDIA_DIR, SOFT_DIR), exist_ok=True)
    os.makedirs(os.path.join(MEDIA_DIR, IMG_CACHE), exist_ok=True)


def _local_path(rel: str) -> str:
    return net.safe_join(MEDIA_DIR, *rel.replace("\\", "/").split("/"))


def _need_login(ctx, what="该功能"):
    if not ctx.user:
        ctx.error(f"{what}需要登录后使用", 401, "login_required")
        return False
    return True


def _find(ctx, mid, fid):
    movie = ctx.store.movie(mid)
    if not movie:
        ctx.error("影片不存在", 404, "not_found")
        return None, None
    f = next((x for x in movie.get("files") or [] if x.get("id") == fid), None)
    if not f:
        ctx.error("该清晰度不存在", 404, "not_found")
        return None, None
    return movie, f


# ------------------------------------------------------------------ helpers
def _upstream_open(url: str, settings: dict, range_header: str | None = None,
                   method: str = "GET"):
    last_error = None
    for proxy in net.proxy_candidates(settings):
        try:
            headers = {"Range": range_header} if range_header else {}
            return net.open_url(url, headers=headers, timeout=45, proxy=proxy, method=method)
        except Exception as exc:  # noqa: BLE001 - report the last failure
            last_error = exc
            continue
    raise IOError(str(last_error))


def all_allowed_hosts(ctx) -> set[str]:
    hosts = set(ctx.store.data.get("liveHosts") or [])
    hosts |= _DYNAMIC_HOSTS
    return hosts


def remember_hosts(ctx, urls) -> None:
    """Allow proxying hosts that a live source actually handed us."""
    known = all_allowed_hosts(ctx)
    new = []
    for u in urls:
        host = urllib.parse.urlparse(u or "").hostname
        if host and host not in known and host not in new:
            new.append(host)
    if not new:
        return
    _DYNAMIC_HOSTS.update(new)

    def apply(db):
        lst = db.setdefault("liveHosts", [])
        for host in new:
            if host not in lst:
                lst.append(host)
        if len(lst) > 400:
            del lst[:-400]
    ctx.store.tx(apply)


def _is_playlist(url: str, ctype: str = "") -> bool:
    path = urllib.parse.urlparse(url).path.lower()
    return path.endswith(".m3u8") or "mpegurl" in (ctype or "").lower()


def _proxy_hls(ctx, url: str) -> None:
    """Fetch an HLS playlist and rewrite every URI through this proxy.

    Relative variant/segment/key URIs would otherwise resolve against
    /api/proxy and 404, so they are absolutised and re-encoded here.
    """
    try:
        resp = _upstream_open(url, ctx.settings)
        raw = resp.read(4 * 1024 * 1024)
        resp.close()
    except Exception as exc:  # noqa: BLE001
        return ctx.error(f"HLS 拉取失败：{exc}", 502, "upstream_failed")
    text = raw.decode("utf-8", "replace")
    hosts = [url]
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append(line)
            continue
        if stripped.startswith("#"):
            def repl(match):
                absolute = urllib.parse.urljoin(url, match.group(2))
                hosts.append(absolute)
                return f'{match.group(1)}{"/api/proxy?u=" + urllib.parse.quote(absolute, safe="")}{match.group(3)}'
            lines.append(re.sub(r'(URI=")([^"]+)(")', repl, line))
            continue
        absolute = urllib.parse.urljoin(url, stripped)
        hosts.append(absolute)
        lines.append("/api/proxy?u=" + urllib.parse.quote(absolute, safe=""))
    remember_hosts(ctx, hosts)
    body = ("\n".join(lines) + "\n").encode("utf-8")
    ctx.send(200, body, "application/vnd.apple.mpegurl",
             {"Cache-Control": "no-store", "Access-Control-Allow-Origin": "*"})


def serve_hls_as_mp4(ctx, url: str, filename: str) -> None:
    """Remux an upstream HLS stream into a downloadable fragmented MP4.

    Tries a direct connection first (resource CDNs are usually local/fast and
    some of them break inside the HTTP proxy), then retries through the proxy.
    """
    import queue
    import subprocess
    import threading

    if not media.available():
        return ctx.error("服务器未安装 ffmpeg，无法把 HLS 转封装为 MP4", 503, "no_ffmpeg")

    base_env = os.environ.copy()
    base_env.pop("HTTP_PROXY", None)
    base_env.pop("HTTPS_PROXY", None)
    base_env.pop("http_proxy", None)
    base_env.pop("https_proxy", None)
    attempts = [base_env]
    if ctx.settings.get("proxyEnabled") and ctx.settings.get("proxyUrl"):
        proxied = dict(base_env)
        proxied["HTTP_PROXY"] = ctx.settings["proxyUrl"]
        proxied["HTTPS_PROXY"] = ctx.settings["proxyUrl"]
        attempts.append(proxied)

    args = [
        media.FFMPEG, "-hide_banner", "-loglevel", "error",
        "-user_agent", net.UA, "-i", url,
        "-c", "copy", "-bsf:a", "aac_adtstoasc",
        "-movflags", "frag_keyframe+empty_moov+default_base_moof",
        "-f", "mp4", "pipe:1",
    ]

    proc = None
    chunks: "queue.Queue[bytes | None]" = queue.Queue(maxsize=96)
    first = None
    for env in attempts:
        try:
            proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    env=env,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            return ctx.error(f"ffmpeg 启动失败：{exc}", 500, "ffmpeg_failed")

        chunks = queue.Queue(maxsize=96)

        def pump(proc=proc, chunks=chunks):
            try:
                while True:
                    buf = proc.stdout.read(65536)
                    if not buf:
                        break
                    chunks.put(buf)
            except Exception:
                pass
            finally:
                chunks.put(None)

        threading.Thread(target=pump, daemon=True).start()
        try:
            first = chunks.get(timeout=18)
        except queue.Empty:
            first = None
        if first:
            break
        try:
            proc.kill()
        except Exception:
            pass
        proc = None

    if not first or proc is None:
        return ctx.error("该 HLS 线路无法转封装（源站拒绝或分片失效），可改用 m3u8 下载或在播放器观看",
                         502, "remux_failed")

    h = ctx.handler
    h.send_response(200)
    h.send_header("Content-Type", "video/mp4")
    h.send_header("Content-Disposition", httpkit.content_disposition(filename))
    h.send_header("Cache-Control", "no-store")
    h.send_header("Connection", "close")
    h.end_headers()
    ctx._sent = True
    try:
        h.wfile.write(first)
        while True:
            buf = chunks.get()
            if buf is None:
                break
            h.wfile.write(buf)
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
        pass
    finally:
        try:
            proc.kill()
        except Exception:
            pass


def _proxy_stream(ctx, url: str, download_name: str | None = None) -> None:
    if not net.host_allowed(urllib.parse.urlparse(url).hostname or "", all_allowed_hosts(ctx)):
        return ctx.error("该源域名不在白名单内", 403, "host_not_allowed")
    if not download_name and _is_playlist(url):
        return _proxy_hls(ctx, url)
    range_header = ctx.handler.headers.get("Range")
    try:
        resp = _upstream_open(url, ctx.settings, range_header)
    except Exception as exc:  # noqa: BLE001
        return ctx.error(f"源站连接失败：{exc}", 502, "upstream_failed")
    try:
        status = getattr(resp, "status", 200) or 200
        headers = resp.headers
        length = headers.get("Content-Length")
        ctype = headers.get("Content-Type") or "video/mp4"
        h = ctx.handler
        h.send_response(status if status in (200, 206) else 200)
        h.send_header("Content-Type", ctype)
        if length:
            h.send_header("Content-Length", length)
        else:
            h.send_header("Connection", "close")
        h.send_header("Accept-Ranges", "bytes")
        if headers.get("Content-Range"):
            h.send_header("Content-Range", headers["Content-Range"])
        h.send_header("Cache-Control", "public, max-age=3600")
        if download_name:
            h.send_header("Content-Disposition", httpkit.content_disposition(download_name))
        h.end_headers()
        if ctx.method == "HEAD":
            ctx._sent = True
            return
        while True:
            chunk = resp.read(262144)
            if not chunk:
                break
            h.wfile.write(chunk)
        ctx._sent = True
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
        ctx._sent = True
    finally:
        try:
            resp.close()
        except Exception:
            pass


def _note_play(ctx, movie: dict, f: dict) -> None:
    def apply(db):
        m = next((x for x in db["movies"] if x["id"] == movie["id"]), None)
        if m:
            m["views"] = int(m.get("views") or 0) + 1
        db["stats"]["plays"] = int(db["stats"].get("plays", 0)) + 1
    ctx.store.tx(apply)


# ------------------------------------------------------------------- stream
def h_stream(ctx):
    if not _need_login(ctx, "在线观看"):
        return
    movie, f = _find(ctx, ctx.params["mid"], ctx.params["fid"])
    if not movie:
        return
    watch = f.get("watch") or {}
    kind, value = watch.get("type"), watch.get("value")
    if not kind or not value:
        return ctx.error("该清晰度未配置在线观看源", 404, "no_source")
    decoding = (ctx.query.get("decoding") or ["auto"])[0]
    _note_play(ctx, movie, f)

    if kind == "remote":
        return _proxy_stream(ctx, value)

    if kind == "hls":
        rel = value
        if decoding == "sw":
            alt = f"{SOFT_DIR}/{movie['id']}/{f['id']}.mp4"
            if os.path.isfile(_local_path(alt)):
                return ctx.serve_path(_local_path(alt), cache="public, max-age=600")
        # Redirect so relative segment URIs resolve under /media/
        ctx.send(302, b"", headers={"Location": f"/media/{rel}", "Cache-Control": "no-store"})
        return

    path = _local_path(value)
    if not os.path.isfile(path):
        return ctx.error("媒体文件缺失，请在后台重新扫描", 410, "missing_file")
    if decoding == "sw":
        soft_rel = f"{SOFT_DIR}/{movie['id']}/{f['id']}.mp4"
        soft_path = _local_path(soft_rel)
        if not os.path.isfile(soft_path) and media.available() and \
                ctx.settings.get("transcodeEnabled", True):
            size = os.path.getsize(path)
            try:
                max_min = int(ctx.settings.get("softMaxMinutes") or 30)
                soft_crf = int(ctx.settings.get("softCrf") or 26)
            except (TypeError, ValueError):
                max_min, soft_crf = 30, 26
            if size <= 2 * 1024 * 1024 * 1024:
                media.make_soft_rendition(path, soft_path, max_seconds=max_min * 60,
                                          crf=soft_crf)
        if os.path.isfile(soft_path):
            return ctx.serve_path(soft_path, cache="public, max-age=600")
    return ctx.serve_path(path, cache="public, max-age=600")


# ----------------------------------------------------------------- download
def _sanitize(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', " ", name or "")
    return re.sub(r"\s{2,}", " ", name).strip()[:120] or "cinema"


def _ext_of(url: str, fallback: str = "jpg") -> str:
    ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower().lstrip(".")
    return ext if ext in ("jpg", "jpeg", "png", "webp") else fallback


def _nfo(movie: dict, f: dict) -> str:
    def esc(v):
        return (str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    genres = "".join(f"  <genre>{esc(g)}</genre>\n" for g in movie.get("genres") or [])
    actors = "".join(f"  <actor><name>{esc(a)}</name></actor>\n" for a in movie.get("cast") or [])
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<movie>\n'
        f"  <title>{esc(movie.get('title'))}</title>\n"
        f"  <originaltitle>{esc(movie.get('originalTitle'))}</originaltitle>\n"
        f"  <year>{esc(movie.get('year'))}</year>\n"
        f"  <rating>{esc(movie.get('rating') or '')}</rating>\n"
        f"  <runtime>{esc(movie.get('runtime') or '')}</runtime>\n"
        f"  <plot>{esc(movie.get('synopsis'))}</plot>\n"
        f"{genres}{actors}"
        f"  <director>{esc(movie.get('director'))}</director>\n"
        f'  <fileinfo><streamdetails><video><codec>{esc(f.get("codec"))}</codec>'
        f"<width>{esc(f.get('width') or '')}</width><height>{esc(f.get('height') or '')}</height>"
        f"</video><audio><codec>{esc(f.get('audio') or 'aac')}</codec></audio>"
        f"</streamdetails></fileinfo>\n"
        f"  <quality>{esc(f.get('quality'))}</quality>\n"
        f"  <source>CineBox</source>\n"
        "</movie>\n"
    )


def _readme(ctx, movie: dict, f: dict, extras: list[str]) -> str:
    lines = [
        f"{movie.get('title')} ({movie.get('year') or '----'})",
        "=" * 60,
        f"原始片名 : {movie.get('originalTitle') or '—'}",
        f"类型     : {' / '.join(movie.get('genres') or []) or '—'}",
        f"评分     : {movie.get('rating') or '—'}",
        f"片长     : {movie.get('runtime') or '—'} 分钟",
        f"导演     : {movie.get('director') or '—'}",
        f"主演     : {', '.join(movie.get('cast') or []) or '—'}",
        "",
        "剧情简介",
        "-" * 60,
        (movie.get("synopsis") or "—").strip(),
        "",
        "本文件",
        "-" * 60,
        f"清晰度   : {f.get('label') or f.get('quality')}",
        f"编码     : {f.get('codec') or 'h264'} / {f.get('width') or '?'}x{f.get('height') or '?'}",
        f"大小     : {net.human_bytes(f.get('sizeBytes'))}",
        f"来源     : {f.get('sourceLabel') or '—'}",
        f"版权说明 : {(movie.get('source') or {}).get('license') or '见源站'}",
        f"源站链接 : {(movie.get('source') or {}).get('url') or '—'}",
        "",
        f"打包包含 : {', '.join(extras) if extras else '仅正片'}",
        f"生成时间 : {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"站点     : {ctx.settings.get('siteName')}",
        "",
    ]
    return "\n".join(lines)


def _download_extras(ctx, movie: dict, f: dict, extras: list[str]) -> list[tuple[str, bytes]]:
    folder = _sanitize(f"{movie.get('title')} ({movie.get('year') or ''})")
    base = os.path.splitext(_sanitize(f"{movie.get('title')} ({movie.get('year') or ''}) - "
                                      f"{f.get('label') or f.get('quality')}"))[0]
    out: list[tuple[str, bytes]] = []

    def grab_image(url: str, name: str):
        if not url:
            return
        target = url
        if url.startswith("/api/img"):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            target = (q.get("u") or [""])[0]
        if not target.startswith("http"):
            return
        try:
            data = net.fetch_bytes(target, settings=ctx.settings, timeout=25, limit=20 * 1024 * 1024)
            if data:
                out.append((f"{folder}/{name}.{_ext_of(target)}", data))
        except Exception:
            pass

    if "poster" in extras:
        grab_image(movie.get("poster") or "", "poster")
    if "backdrop" in extras:
        grab_image(movie.get("backdrop") or movie.get("poster") or "", "backdrop")
    if "nfo" in extras:
        out.append((f"{folder}/{base}.nfo", _nfo(movie, f).encode("utf-8")))
    if "json" in extras:
        payload = {"exportedAt": now_ts(), "site": ctx.settings.get("siteName"),
                   "movie": {k: v for k, v in movie.items()},
                   "file": {k: v for k, v in f.items()}}
        out.append((f"{folder}/metadata.json",
                    json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")))
    if "subs" in extras:
        for s in movie.get("subtitles") or []:
            try:
                if (s.get("url") or "").startswith("http"):
                    raw = net.fetch_bytes(s["url"], settings=ctx.settings, timeout=25)
                else:
                    raw = open(_local_path(s.get("value") or ""), "rb").read()
                out.append((f"{folder}/subtitles/{s.get('lang') or 'und'}.srt", raw))
            except Exception:
                continue
    if "readme" in extras:
        out.append((f"{folder}/readme.txt", _readme(ctx, movie, f, extras).encode("utf-8")))
    if "checksums" in extras:
        lines = [f"{net.human_bytes(f.get('sizeBytes'))}\t{f.get('quality')}\t{f.get('id')}",
                 f"source\t{f.get('watch', {}).get('value') or ''}",
                 f"generated\t{time.strftime('%Y-%m-%d %H:%M:%S')}"]
        out.append((f"{folder}/checksums.txt", "\n".join(lines).encode("utf-8")))
    if "m3u" in extras:
        lines = ["#EXTM3U"]
        for x in movie.get("files") or []:
            w = x.get("watch") or {}
            if not w.get("type"):
                continue
            lines.append(f"#EXTINF:-1,{movie.get('title')} - {x.get('quality')}")
            lines.append(w.get("value") or "")
        out.append((f"{folder}/playlist.m3u", "\n".join(lines).encode("utf-8")))
    return out


def _zip_overhead(name: str, size: int) -> int:
    name_len = len(name.replace("\\", "/").encode("utf-8"))
    zip64 = size >= 0xFFFFFFFF
    return (30 + name_len + (20 if zip64 else 0) + (24 if zip64 else 16)
            + 46 + name_len + (20 if zip64 else 0))


def _pack_entry(name: str, data: bytes):
    """Precompute CRC + deflate payload so the archive length is exact."""
    crc = zlib.crc32(data) & 0xFFFFFFFF
    compressor = zlib.compressobj(6, zlib.DEFLATED, -15)
    packed = compressor.compress(data) + compressor.flush()
    method = 8
    if len(packed) >= len(data):
        packed, method = data, 0
    size = 30 + len(name.encode("utf-8")) + len(packed) + 46 + len(name.encode("utf-8"))
    return {"name": name, "crc": crc, "method": method, "packed": packed,
            "usize": len(data), "size": size}


def h_download(ctx):
    if not _need_login(ctx, "下载"):
        return
    movie, f = _find(ctx, ctx.params["mid"], ctx.params["fid"])
    if not movie:
        return
    dl = f.get("download") or {}
    if not dl.get("enabled", True) or not dl.get("type"):
        return ctx.error("该清晰度未开放下载", 403, "download_disabled")
    extras_raw = (ctx.query.get("extras") or [""])[0]
    extras = [e for e in extras_raw.split(",") if e.strip()]
    allowed = {"poster", "backdrop", "nfo", "json", "subs", "readme", "checksums", "m3u"}
    extras = [e for e in extras if e in allowed]
    kind, value = dl.get("type"), dl.get("value")
    base = _sanitize(f"{movie.get('title')} ({movie.get('year') or ''}) - "
                     f"{f.get('label') or f.get('quality')}")

    # ---- no extras: plain attachment stream (fastest path)
    if not extras:
        _record_download(ctx, movie, f, [], f.get("sizeBytes"))
        if kind == "remote":
            return _proxy_stream(ctx, value, download_name=f"{base}.mp4")
        path = _local_path(value)
        if not os.path.isfile(path):
            return ctx.error("媒体文件缺失", 410, "missing_file")
        return ctx.serve_path(path, download_name=f"{base}.mp4", ctype="video/mp4",
                              cache="no-store")

    extras_entries = _download_extras(ctx, movie, f, extras)
    if not extras_entries:
        extras_entries = [(f"{base}/readme.txt",
                           _readme(ctx, movie, f, []).encode("utf-8"))]

    video_name = f"{base}/{base}.mp4"
    if kind == "remote":
        size = f.get("sizeBytes") or net.probe_size(value, settings=ctx.settings)
        if not size:
            return ctx.error("无法获取源文件大小，请改用“仅正片直下”", 502, "unknown_size")
        opener = None
    else:
        path = _local_path(value)
        if not os.path.isfile(path):
            return ctx.error("媒体文件缺失", 410, "missing_file")
        size = os.path.getsize(path)
        opener = path

    total = 0
    prepared = []
    for name, data in extras_entries:
        entry = _pack_entry(name, data)
        prepared.append(entry)
        total += entry["size"]
    total += size + _zip_overhead(video_name, size) + 22
    zip_name = f"{base} [{len(extras)}项元数据].zip"

    h = ctx.handler
    h.send_response(200)
    h.send_header("Content-Type", "application/zip")
    h.send_header("Content-Length", str(total))
    h.send_header("Content-Disposition", httpkit.content_disposition(zip_name))
    h.send_header("Cache-Control", "no-store")
    h.end_headers()
    ctx._sent = True

    from .zipstream import ZipStream
    zs = ZipStream(h.wfile)
    for entry in prepared:
        zs.add_precompressed(entry["name"], entry["crc"], entry["method"],
                             entry["packed"], entry["usize"])
    if opener:
        def chunks():
            with open(opener, "rb") as fh:
                while True:
                    buf = fh.read(524288)
                    if not buf:
                        break
                    yield buf
        zs.add_stream(video_name, size, chunks())
    else:
        resp = _upstream_open(value, ctx.settings)
        try:
            def chunks():
                remaining = size
                while remaining > 0:
                    buf = resp.read(min(524288, remaining))
                    if not buf:
                        break
                    remaining -= len(buf)
                    yield buf
            zs.add_stream(video_name, size, chunks())
        finally:
            try:
                resp.close()
            except Exception:
                pass
    try:
        zs.close()
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
        pass
    _record_download(ctx, movie, f, extras, size)


def _record_download(ctx, movie, f, extras, size):
    entry = {"movieId": movie["id"], "fileId": f.get("id"), "quality": f.get("quality"),
             "extras": extras, "sizeBytes": size, "at": now_ts()}
    def apply(db):
        rows = db.setdefault("downloads", {}).setdefault(ctx.user["id"], [])
        rows.insert(0, entry)
        del rows[40:]
        db["stats"]["downloads"] = int(db["stats"].get("downloads", 0)) + 1
    ctx.store.tx(apply)


# -------------------------------------------------------------- media proxy
def h_proxy(ctx):
    if not _need_login(ctx, "媒体代理"):
        return
    url = (ctx.query.get("u") or [""])[0]
    if not url.startswith("http"):
        return ctx.error("缺少地址", 400, "bad_request")
    dl = (ctx.query.get("dl") or [""])[0]
    _proxy_stream(ctx, url, download_name=dl or None)


def h_img(ctx):
    """Public image proxy with a small on-disk cache (posters in search results)."""
    url = (ctx.query.get("u") or [""])[0]
    if not url.startswith("http"):
        return ctx.error("缺少地址", 400, "bad_request")
    host = urllib.parse.urlparse(url).hostname or ""
    if not net.host_allowed(host, all_allowed_hosts(ctx)):
        return ctx.error("域名不在白名单", 403, "host_not_allowed")
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
    ext = _ext_of(url, "jpg")
    cache_path = os.path.join(MEDIA_DIR, IMG_CACHE, f"{digest}.{ext}")
    if os.path.isfile(cache_path) and time.time() - os.path.getmtime(cache_path) < 86400 * 30:
        return ctx.serve_path(cache_path, ctype=httpkit.ctype_for(cache_path),
                              cache="public, max-age=86400")
    try:
        data = net.fetch_bytes(url, settings=ctx.settings, timeout=25, limit=16 * 1024 * 1024)
    except Exception as exc:  # noqa: BLE001
        return ctx.error(f"图片拉取失败：{exc}", 502, "upstream_failed")
    try:
        with open(cache_path, "wb") as fh:
            fh.write(data)
    except OSError:
        pass
    ctx.send(200, data, httpkit.ctype_for(cache_path), {"Cache-Control": "public, max-age=86400"})


# ---------------------------------------------------------------- subtitles
def h_subtitle(ctx):
    if not _need_login(ctx, "字幕"):
        return
    movie = ctx.store.movie(ctx.params["mid"])
    if not movie:
        return ctx.error("影片不存在", 404, "not_found")
    sub = next((s for s in movie.get("subtitles") or [] if s.get("id") == ctx.params["sid"]), None)
    if not sub:
        return ctx.error("字幕不存在", 404, "not_found")
    url = sub.get("url") or ""
    if url.startswith("http"):
        try:
            raw = net.fetch_bytes(url, settings=ctx.settings, timeout=25)
        except Exception as exc:  # noqa: BLE001
            return ctx.error(f"字幕拉取失败：{exc}", 502, "upstream_failed")
    else:
        path = _local_path(sub.get("value") or "")
        if not os.path.isfile(path):
            return ctx.error("字幕文件缺失", 404, "not_found")
        raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-8", "gbk", "big5"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", "replace")
    ctx.send(200, text.encode("utf-8"), "text/plain; charset=utf-8")
