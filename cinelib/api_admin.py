"""Admin routes: users, site settings, movie library, uploads, providers."""
from __future__ import annotations

import os
import shutil
import time

from . import api_live, auth, catalog, maccms, media, net, providers
from .store import new_id, now_ts


ALLOWED_SETTINGS = {
    "siteName", "tagline", "announcement", "allowSignup", "allowGuestSearch",
    "proxyUrl", "proxyEnabled", "tmdbKey", "omdbKey", "defaultDecoding",
    "downloadExtrasDefault", "maxUploadMb", "maintenance", "themeAccent",
    "transcodeEnabled", "hlsHeights", "hlsCrf", "hlsPreset", "softCrf", "softMaxMinutes",
    "gpuTranscodeEnabled", "gpuDevice", "gpuAutoFallback",
}
EXTRAS = {"poster", "backdrop", "nfo", "json", "subs", "readme", "checksums", "m3u"}
DECODING = {"auto", "hw", "sw"}


def _admin(ctx) -> bool:
    if not ctx.user or ctx.user.get("role") != "admin":
        ctx.error("需要管理员权限", 403, "forbidden")
        return False
    return True


# ---------------------------------------------------------------- api sources
def h_sources(ctx):
    if not _admin(ctx):
        return
    items = ctx.store.data.get("sources", [])
    ctx.json({"ok": True, "items": items, "kinds": api_live.KINDS,
              "playableKinds": sorted(api_live.PLAYABLE_KINDS)})


def h_source_add(ctx):
    if not _admin(ctx):
        return
    body = ctx.body_json()
    kind = body.get("kind") or "maccms"
    name = (body.get("name") or "").strip()
    endpoint = (body.get("endpoint") or "").strip()
    if kind == "maccms":
        if not endpoint.startswith("http"):
            return ctx.error("资源接口地址必须以 http(s):// 开头", 400, "bad_endpoint")
        if not name:
            return ctx.error("请填写片源名称", 400, "bad_name")
        # 同地址不重复添加
        if any((s.get("endpoint") or "").rstrip("/") == endpoint.rstrip("/")
               for s in ctx.store.data.get("sources", [])):
            return ctx.error("该接口已存在", 409, "duplicate")
    if kind not in api_live.KINDS:
        return ctx.error("不支持的片源类型", 400, "bad_kind")
    entry = api_live.add_source(ctx.store, name or api_live.KINDS[kind], kind, endpoint,
                                show=bool(body.get("show", True)))
    ctx.store.audit(ctx.user["username"], "source_add", f"{entry['name']} {kind}")
    ctx.json({"ok": True, "source": entry})


def h_source_update(ctx):
    if not _admin(ctx):
        return
    sid = ctx.params["id"]
    body = ctx.body_json()
    def apply(db):
        for s in db.get("sources", []):
            if s["id"] != sid:
                continue
            for key in ("name", "endpoint", "note"):
                if key in body and isinstance(body[key], str):
                    s[key] = body[key].strip()[:200]
            for key in ("enabled", "show"):
                if key in body:
                    s[key] = bool(body[key])
            return dict(s)
        return None
    result = ctx.store.tx(apply)
    if result is None:
        return ctx.error("片源不存在", 404, "not_found")
    ctx.store.audit(ctx.user["username"], "source_update", result.get("name") or sid)
    ctx.json({"ok": True, "source": result})


def h_source_delete(ctx):
    if not _admin(ctx):
        return
    sid = ctx.params["id"]
    target = next((s for s in ctx.store.data.get("sources", []) if s["id"] == sid), None)
    if not target:
        return ctx.error("片源不存在", 404, "not_found")
    if target.get("builtin"):
        return ctx.error("内置片源不能删除，可改为「停用」", 400, "builtin")
    def apply(db):
        db["sources"] = [s for s in db.get("sources", []) if s["id"] != sid]
    ctx.store.tx(apply)
    ctx.store.audit(ctx.user["username"], "source_delete", target.get("name") or sid)
    ctx.json({"ok": True})


def h_source_test(ctx):
    if not _admin(ctx):
        return
    body = ctx.body_json()
    kind = body.get("kind") or "maccms"
    endpoint = (body.get("endpoint") or "").strip()
    keyword = (body.get("keyword") or "流浪地球").strip()
    started = time.time()
    try:
        if kind == "maccms":
            if not endpoint.startswith("http"):
                return ctx.error("请先填写接口地址", 400, "bad_endpoint")
            result = maccms.test(endpoint, keyword)
            ctx.json({"ok": True, "count": result["count"], "ms": round((time.time()-started)*1000),
                      "sample": result.get("sample"), "files": result.get("files"),
                      "play": result.get("play")})
        else:
            items = providers.search(kind, keyword, ctx.settings)
            ctx.json({"ok": True, "count": len(items), "ms": round((time.time()-started)*1000),
                      "sample": (items[0].get("title") if items else None)})
    except Exception as exc:  # noqa: BLE001
        ctx.error(f"测试失败：{exc}", 502, "provider_failed")


# -------------------------------------------------------------------- stats
def h_stats(ctx):
    if not _admin(ctx):
        return
    db = ctx.store.data
    movies = db["movies"]
    files = [f for m in movies for f in (m.get("files") or [])]
    local_bytes = 0
    media_dir = os.path.dirname(os.path.abspath(ctx.settings.get("_db_path", ".")))
    for m in movies:
        for f in m.get("files") or []:
            w = (f.get("watch") or {})
            if w.get("type") in ("local", "hls"):
                pass
    ctx.json({
        "ok": True,
        "counts": {
            "movies": len(movies),
            "published": sum(1 for m in movies if m.get("status", "published") == "published"),
            "files": len(files),
            "users": len(db["users"]),
            "playlists": sum(len(v) for v in db.get("playlists", {}).values()),
            "history": sum(len(v) for v in db.get("history", {}).values()),
            "downloads": db["stats"].get("downloads", 0),
            "plays": db["stats"].get("plays", 0),
            "searches": db["stats"].get("searches", 0),
        },
        "storage": {
            "remoteBytes": sum(int(f.get("sizeBytes") or 0) for f in files
                               if (f.get("watch") or {}).get("type") == "remote"),
            "localBytes": sum(int(f.get("sizeBytes") or 0) for f in files
                              if (f.get("watch") or {}).get("type") in ("local", "hls")),
        },
        "top": [{"id": m["id"], "title": m.get("title"), "views": m.get("views") or 0}
                for m in sorted(movies, key=lambda x: -(x.get("views") or 0))[:6]],
        "audit": db.get("audit", [])[:12],
        "ffmpeg": media.available(),
        "server": {"python": "3.12", "port": ctx.settings.get("_port", 8426)},
    })


# -------------------------------------------------------------------- users
def h_users(ctx):
    if not _admin(ctx):
        return
    out = []
    for u in ctx.store.data["users"]:
        out.append({
            "id": u["id"], "username": u.get("username"),
            "displayName": u.get("displayName"), "role": u.get("role"),
            "status": u.get("status", "active"), "createdAt": u.get("createdAt"),
            "lastLoginAt": u.get("lastLoginAt"),
        })
    ctx.json({"ok": True, "items": out})


def h_user_create(ctx):
    if not _admin(ctx):
        return
    body = ctx.body_json()
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    role = "admin" if body.get("role") == "admin" else "user"
    if len(username) < 3 or len(password) < 6:
        return ctx.error("账号至少 3 位、密码至少 6 位", 400, "bad_request")
    if ctx.store.find_user(username=username):
        return ctx.error("账号已存在", 409, "exists")
    salt, digest = auth.hash_password(password)
    user = {"id": new_id("u"), "username": username,
            "displayName": (body.get("displayName") or username)[:24],
            "role": role, "status": "active", "salt": salt, "hash": digest,
            "createdAt": now_ts(), "lastLoginAt": None}
    ctx.store.tx(lambda db: db["users"].append(user))
    ctx.store.audit(ctx.user["username"], "user_create", username)
    ctx.json({"ok": True, "id": user["id"]})


def h_user_update(ctx):
    if not _admin(ctx):
        return
    uid = ctx.params["id"]
    body = ctx.body_json()
    target = ctx.store.user_by_id(uid)
    if not target:
        return ctx.error("用户不存在", 404, "not_found")
    if uid == ctx.user["id"] and body.get("role") == "user":
        return ctx.error("不能降级当前登录的管理员", 400, "self_demote")
    def apply(db):
        u = next(x for x in db["users"] if x["id"] == uid)
        if body.get("displayName"):
            u["displayName"] = str(body["displayName"])[:24]
        if body.get("role") in ("user", "admin"):
            u["role"] = body["role"]
        if body.get("status") in ("active", "disabled"):
            u["status"] = body["status"]
        if body.get("password"):
            if len(body["password"]) < 6:
                raise ValueError("密码至少 6 位")
            salt, digest = auth.hash_password(body["password"])
            u["salt"], u["hash"] = salt, digest
            for tok, sess in list(db.get("sessions", {}).items()):
                if sess.get("userId") == uid:
                    db["sessions"].pop(tok, None)
    try:
        ctx.store.tx(apply)
    except ValueError as exc:
        return ctx.error(str(exc), 400, "bad_request")
    ctx.store.audit(ctx.user["username"], "user_update", str(uid))
    ctx.json({"ok": True})


def h_user_delete(ctx):
    if not _admin(ctx):
        return
    uid = ctx.params["id"]
    if uid == ctx.user["id"]:
        return ctx.error("不能删除当前登录账号", 400, "self_delete")
    target = ctx.store.user_by_id(uid)
    if not target:
        return ctx.error("用户不存在", 404, "not_found")
    admins = [u for u in ctx.store.data["users"] if u.get("role") == "admin"]
    if target.get("role") == "admin" and len(admins) <= 1:
        return ctx.error("必须保留至少一个管理员", 400, "last_admin")
    def apply(db):
        db["users"] = [u for u in db["users"] if u["id"] != uid]
        db.get("playlists", {}).pop(uid, None)
        db.get("history", {}).pop(uid, None)
        db.get("downloads", {}).pop(uid, None)
        for tok, sess in list(db.get("sessions", {}).items()):
            if sess.get("userId") == uid:
                db["sessions"].pop(tok, None)
    ctx.store.tx(apply)
    ctx.store.audit(ctx.user["username"], "user_delete", target.get("username") or uid)
    ctx.json({"ok": True})


# ----------------------------------------------------------------- settings
def h_settings_get(ctx):
    if not _admin(ctx):
        return
    s = {k: v for k, v in ctx.store.settings.items() if k in ALLOWED_SETTINGS}
    s["tmdbKey"] = "••••" + (s.get("tmdbKey") or "")[-4:] if s.get("tmdbKey") else ""
    s["omdbKey"] = "••••" + (s.get("omdbKey") or "")[-4:] if s.get("omdbKey") else ""
    ctx.json({"ok": True, "settings": s, "providers": providers.PROVIDERS,
              "ffmpeg": media.available()})


def h_settings_put(ctx):
    if not _admin(ctx):
        return
    body = ctx.body_json()
    def apply(db):
        for k, v in body.items():
            if k not in ALLOWED_SETTINGS:
                continue
            if k in ("tmdbKey", "omdbKey") and isinstance(v, str) and v.startswith("••••"):
                continue
            db["settings"][k] = v
        return {k: v for k, v in db["settings"].items() if k in ALLOWED_SETTINGS}
    result = ctx.store.tx(apply)
    ctx.store.audit(ctx.user["username"], "settings_update", ",".join(body.keys())[:200])
    ctx.json({"ok": True, "settings": result})


# ------------------------------------------------------------------- movies
def h_movies(ctx):
    if not _admin(ctx):
        return
    items = []
    for m in sorted(ctx.store.data["movies"], key=lambda x: -(x.get("createdAt") or 0)):
        items.append({
            "id": m["id"], "title": m.get("title"), "year": m.get("year"),
            "status": m.get("status", "published"), "featured": bool(m.get("featured")),
            "genres": m.get("genres") or [], "rating": m.get("rating"),
            "views": m.get("views") or 0, "files": len(m.get("files") or []),
            "poster": catalog.normalize_img(m.get("poster")),
            "source": (m.get("source") or {}).get("provider") or "local",
            "createdAt": m.get("createdAt"),
            "sizes": [f.get("quality") for f in (m.get("files") or [])],
        })
    ctx.json({"ok": True, "items": items})


def h_movie_get(ctx):
    """Raw movie document for the editor (includes source URLs)."""
    if not _admin(ctx):
        return
    movie = ctx.store.movie(ctx.params["id"])
    if not movie:
        return ctx.error("影片不存在", 404, "not_found")
    ctx.json({"ok": True, "movie": movie})


def _clean_movie(body: dict, existing: dict | None = None) -> dict:
    base = dict(existing or {})
    fields = ["title", "originalTitle", "synopsis", "poster", "backdrop", "director",
              "country", "language", "status", "license"]
    for f in fields:
        if f in body:
            base[f] = (body[f] or "").strip() if isinstance(body[f], str) else body[f]
    if "year" in body:
        try:
            base["year"] = int(body["year"]) if body["year"] else None
        except (TypeError, ValueError):
            base["year"] = None
    if "rating" in body:
        try:
            base["rating"] = float(body["rating"]) if body["rating"] not in (None, "") else None
        except (TypeError, ValueError):
            base["rating"] = None
    if "runtime" in body:
        try:
            base["runtime"] = int(body["runtime"]) if body["runtime"] else None
        except (TypeError, ValueError):
            base["runtime"] = None
    if "featured" in body:
        base["featured"] = bool(body["featured"])
    for key in ("genres", "tags", "cast"):
        if key in body:
            val = body[key]
            if isinstance(val, str):
                val = [x.strip() for x in val.replace("，", ",").split(",") if x.strip()]
            base[key] = list(val or [])[:24]
    if "status" in body and body["status"] not in ("published", "draft"):
        base["status"] = "published"
    base.setdefault("status", "published")
    base.setdefault("title", "未命名影片")
    return base


def h_movie_create(ctx):
    if not _admin(ctx):
        return
    body = ctx.body_json()
    movie = _clean_movie(body)
    movie.update({"id": new_id("m"), "createdAt": now_ts(), "updatedAt": now_ts(),
                  "views": 0, "files": [], "subtitles": [], "cast": movie.get("cast") or [],
                  "genres": movie.get("genres") or [], "tags": movie.get("tags") or [],
                  "source": movie.get("source") or {"provider": "local", "uid": "",
                                                    "license": "", "url": ""}})
    if body.get("files"):
        for raw in body["files"]:
            f = _clean_file(raw, movie["id"])
            if f:
                movie["files"].append(f)
    ctx.store.tx(lambda db: db["movies"].append(movie))
    ctx.store.audit(ctx.user["username"], "movie_create", movie["title"])
    ctx.json({"ok": True, "id": movie["id"]})


def _clean_file(raw: dict, movie_id: str) -> dict | None:
    if not isinstance(raw, dict):
        return None
    watch_type = raw.get("watchType") or (raw.get("watch") or {}).get("type") or "remote"
    watch_value = raw.get("watchValue") or (raw.get("watch") or {}).get("value") or ""
    if not watch_value:
        return None
    dl_enabled = raw.get("downloadEnabled", True)
    dl_type = raw.get("downloadType") or (raw.get("download") or {}).get("type") or watch_type
    dl_value = raw.get("downloadValue") or (raw.get("download") or {}).get("value") or watch_value
    height = raw.get("height")
    try:
        height = int(height) if height else None
    except (TypeError, ValueError):
        height = None
    quality = raw.get("quality") or providers.quality_for_height(height)
    return {
        "id": raw.get("id") or new_id("f"),
        "quality": quality,
        "label": raw.get("label") or f"{str(quality).upper()} · 原画",
        "width": raw.get("width"), "height": height,
        "codec": raw.get("codec") or "h264",
        "sizeBytes": int(raw["sizeBytes"]) if str(raw.get("sizeBytes") or "").isdigit() else None,
        "sourceLabel": raw.get("sourceLabel") or ("本地片源" if watch_type == "local" else "远端片源"),
        "watch": {"type": watch_type, "value": watch_value},
        "download": {"enabled": bool(dl_enabled), "type": dl_type if dl_enabled else None,
                     "value": dl_value if dl_enabled else None},
    }


def h_movie_update(ctx):
    if not _admin(ctx):
        return
    mid = ctx.params["id"]
    body = ctx.body_json()
    movie = ctx.store.movie(mid)
    if not movie:
        return ctx.error("影片不存在", 404, "not_found")
    def apply(db):
        m = next(x for x in db["movies"] if x["id"] == mid)
        cleaned = _clean_movie(body, m)
        for k, v in cleaned.items():
            m[k] = v
        if "files" in body and isinstance(body["files"], list):
            m["files"] = [f for f in (_clean_file(r, mid) for r in body["files"]) if f]
        if "subtitles" in body and isinstance(body["subtitles"], list):
            m["subtitles"] = [{"id": s.get("id") or new_id("s"), "lang": s.get("lang") or "und",
                               "label": s.get("label") or s.get("lang") or "字幕",
                               "url": s.get("url") or "", "value": s.get("value") or ""}
                              for s in body["subtitles"]]
        m["updatedAt"] = now_ts()
    ctx.store.tx(apply)
    ctx.store.audit(ctx.user["username"], "movie_update", movie.get("title") or mid)
    ctx.json({"ok": True})


def h_movie_delete(ctx):
    if not _admin(ctx):
        return
    mid = ctx.params["id"]
    title = (ctx.store.movie(mid) or {}).get("title", mid)
    def apply(db):
        db["movies"] = [m for m in db["movies"] if m["id"] != mid]
        for uid, rows in db.get("history", {}).items():
            db["history"][uid] = [r for r in rows if r.get("movieId") != mid]
        for uid, pls in db.get("playlists", {}).items():
            for p in pls:
                p["items"] = [i for i in p.get("items", []) if i.get("movieId") != mid]
    ctx.store.tx(apply)
    ctx.store.audit(ctx.user["username"], "movie_delete", title)
    ctx.json({"ok": True})


def h_movie_upload(ctx):
    """Raw PUT body: streamed straight to disk, then probed with ffprobe."""
    if not _admin(ctx):
        return
    mid = (ctx.query.get("movieId") or [""])[0]
    movie = ctx.store.movie(mid)
    if not movie:
        return ctx.error("请先创建影片", 404, "not_found")
    length = int(ctx.handler.headers.get("Content-Length") or 0)
    if length <= 0:
        return ctx.error("空文件", 400, "empty")
    max_bytes = int(ctx.settings.get("maxUploadMb") or 4096) * 1024 * 1024
    if length > max_bytes:
        return ctx.error(f"文件超过 {ctx.settings.get('maxUploadMb')} MB 限制", 413, "too_large")
    quality = (ctx.query.get("quality") or ["1080p"])[0]
    label = (ctx.query.get("label") or [""])[0] or f"{quality.upper()} · 本地片源"
    fid = new_id("f")
    rel_dir = f"local/{mid}"
    abs_dir = os.path.join(_media_root(), *rel_dir.split("/"))
    os.makedirs(abs_dir, exist_ok=True)
    ext = os.path.splitext((ctx.query.get("filename") or ["movie.mp4"])[0])[1] or ".mp4"
    if ext.lower() not in (".mp4", ".m4v", ".webm", ".mkv", ".mov"):
        ext = ".mp4"
    target = os.path.join(abs_dir, fid + ext)
    remaining = length
    try:
        with open(target, "wb") as fh:
            while remaining > 0:
                chunk = ctx.handler.rfile.read(min(1048576, remaining))
                if not chunk:
                    break
                fh.write(chunk)
                remaining -= len(chunk)
    except OSError as exc:
        return ctx.error(f"写入失败：{exc}", 500, "write_failed")
    info = media.probe(target)
    entry = {
        "id": fid, "quality": quality, "label": label,
        "width": info.get("width"), "height": info.get("height"),
        "codec": info.get("codec") or "h264", "fps": info.get("fps"),
        "duration": info.get("duration"), "sizeBytes": os.path.getsize(target),
        "sourceLabel": (ctx.query.get("sourceLabel") or ["本地片源"])[0],
        "watch": {"type": "local", "value": f"{rel_dir}/{fid}{ext}"},
        "download": {"enabled": True, "type": "local", "value": f"{rel_dir}/{fid}{ext}"},
    }
    def apply(db):
        m = next(x for x in db["movies"] if x["id"] == mid)
        m["files"] = [f for f in m.get("files", []) if f.get("quality") != quality]
        m["files"].append(entry)
        m["updatedAt"] = now_ts()
    ctx.store.tx(apply)
    ctx.store.audit(ctx.user["username"], "upload", f"{movie.get('title')} {quality}")
    ctx.json({"ok": True, "file": catalog.public_file(entry)})


def h_file_delete(ctx):
    if not _admin(ctx):
        return
    mid, fid = ctx.params["mid"], ctx.params["fid"]
    removed = {}
    def apply(db):
        m = next((x for x in db["movies"] if x["id"] == mid), None)
        if not m:
            return
        keep = []
        for f in m.get("files", []):
            if f.get("id") == fid:
                removed.update(f)
            else:
                keep.append(f)
        m["files"] = keep
    ctx.store.tx(apply)
    if removed.get("watch", {}).get("type") == "local":
        try:
            path = _local_path(removed["watch"]["value"])
            if os.path.isfile(path):
                os.remove(path)
        except (OSError, ValueError):
            pass
    ctx.json({"ok": True})


def h_build_hls(ctx):
    if not _admin(ctx):
        return
    if not media.available():
        return ctx.error("服务器未安装 ffmpeg", 503, "no_ffmpeg")
    mid = ctx.params["id"]
    body = ctx.body_json()
    fid = body.get("fileId")
    movie = ctx.store.movie(mid)
    if not movie:
        return ctx.error("影片不存在", 404, "not_found")
    f = next((x for x in movie.get("files", []) if x.get("id") == fid), None)
    if not f or (f.get("watch") or {}).get("type") != "local":
        return ctx.error("请选择本地片源再生成 HLS", 400, "not_local")
    src = _local_path(f["watch"]["value"])
    outdir = os.path.join(_media_root(), "hls", mid, fid)
    raw_heights = str(ctx.settings.get("hlsHeights") or "1080,720,480").replace("，", ",")
    heights = tuple(int(x) for x in raw_heights.split(",") if x.strip().isdigit()) or (1080, 720, 480)
    try:
        crf = int(ctx.settings.get("hlsCrf") or 23)
    except (TypeError, ValueError):
        crf = 23
    preset = str(ctx.settings.get("hlsPreset") or "veryfast")
    if preset not in ("ultrafast", "veryfast", "fast", "medium", "slow"):
        preset = "veryfast"
    gpu = None
    if ctx.settings.get("gpuTranscodeEnabled"):
        options = media.gpu_options()
        wanted = str(ctx.settings.get("gpuDevice") or "auto")
        chosen = None
        if wanted == "auto":
            chosen = options[0] if options else None
        else:
            chosen = next((o for o in options if o["id"] == wanted or o["encoder"] == wanted), None)
        if chosen:
            gpu = {"encoder": chosen["encoder"], "id": chosen["id"],
                   "fallback": bool(ctx.settings.get("gpuAutoFallback", True))}
    result = media.build_hls(src, outdir, heights=heights, crf=crf, preset=preset, gpu=gpu)
    if not result.get("ok"):
        return ctx.error("转码失败，请检查 ffmpeg", 500, "transcode_failed")
    def apply(db):
        m = next(x for x in db["movies"] if x["id"] == mid)
        for x in m["files"]:
            if x["id"] == fid:
                x["watch"] = {"type": "hls", "value": f"hls/{mid}/{fid}/master.m3u8"}
                x["hlsVariants"] = result["variants"]
    ctx.store.tx(apply)
    ctx.store.audit(ctx.user["username"], "build_hls", f"{movie.get('title')} {f.get('quality')}")
    ctx.json({"ok": True, "variants": result["variants"]})


def h_rescan(ctx):
    if not _admin(ctx):
        return
    """Re-probe every local file so sizes/quality stay accurate."""
    updated = 0
    def apply(db):
        nonlocal updated
        for m in db["movies"]:
            for f in m.get("files", []):
                w = f.get("watch") or {}
                if w.get("type") != "local":
                    continue
                try:
                    path = _local_path(w["value"])
                except ValueError:
                    continue
                if not os.path.isfile(path):
                    continue
                info = media.probe(path)
                if info:
                    f.update({k: info[k] for k in ("width", "height", "codec", "fps",
                                                   "duration", "sizeBytes") if info.get(k)})
                    updated += 1
    ctx.store.tx(apply)
    ctx.json({"ok": True, "updated": updated, "ffmpeg": media.available()})


# ------------------------------------------------------------------ imports
def h_providers(ctx):
    if not _admin(ctx):
        return
    ctx.json({"ok": True, "items": providers.PROVIDERS,
              "configured": {"tmdb": bool(ctx.settings.get("tmdbKey")),
                             "omdb": bool(ctx.settings.get("omdbKey")),
                             "proxy": ctx.settings.get("proxyEnabled") and
                                      bool(ctx.settings.get("proxyUrl"))}})


def h_provider_search(ctx):
    if not _admin(ctx):
        return
    body = ctx.body_json()
    provider = body.get("provider") or "archive"
    q = body.get("q") or ""
    try:
        items = providers.search(provider, q, ctx.settings)
    except Exception as exc:  # noqa: BLE001
        return ctx.error(f"{provider} 检索失败：{exc}", 502, "provider_failed")
    ctx.json({"ok": True, "items": items, "provider": provider})


def h_import(ctx):
    if not _admin(ctx):
        return
    body = ctx.body_json()
    provider = body.get("provider") or "archive"
    uid = body.get("uid") or ""
    if not uid:
        return ctx.error("缺少条目 ID", 400, "bad_request")
    try:
        if provider == "archive":
            cand = providers.archive_item(uid, ctx.settings)
        elif provider == "tmdb":
            meta = providers.tmdb_detail(uid, ctx.settings)
            cand = {"provider": "tmdb", "uid": uid, **meta, "files": [], "type": "movie",
                    "license": "TMDB 元数据", "sourceUrl": f"https://www.themoviedb.org/movie/{uid}"}
        elif provider == "itunes":
            cand = body.get("candidate") or {}
        else:
            cand = body.get("candidate") or {}
    except Exception as exc:  # noqa: BLE001
        return ctx.error(f"导入失败：{exc}", 502, "provider_failed")
    if not cand.get("title"):
        return ctx.error("候选数据不完整", 400, "bad_candidate")
    if ctx.store.find_user(title="") is None:
        pass
    dup = next((m for m in ctx.store.data["movies"]
                if (m.get("source") or {}).get("uid") == uid
                and (m.get("source") or {}).get("provider") == provider), None)
    if dup:
        return ctx.error("该条目已存在片库中", 409, "duplicate")
    movie = {
        "id": new_id("m"),
        "title": cand.get("title"), "originalTitle": cand.get("originalTitle") or "",
        "year": cand.get("year"), "genres": cand.get("genres") or [],
        "tags": [], "rating": cand.get("rating"), "runtime": cand.get("runtime"),
        "country": cand.get("country") or "", "language": cand.get("language") or "",
        "director": cand.get("director") or "", "cast": cand.get("cast") or [],
        "synopsis": cand.get("synopsis") or "",
        "poster": cand.get("poster") or "", "backdrop": cand.get("backdrop") or "",
        "featured": False, "status": "published", "views": 0,
        "source": {"provider": provider, "uid": uid,
                   "license": cand.get("license") or "", "url": cand.get("sourceUrl") or ""},
        "files": [], "subtitles": [], "createdAt": now_ts(), "updatedAt": now_ts(),
    }
    for raw in cand.get("files") or []:
        movie["files"].append({
            "id": new_id("f"),
            "quality": raw.get("quality") or providers.quality_for_height(raw.get("height")),
            "label": raw.get("label") or "远端片源",
            "width": raw.get("width"), "height": raw.get("height"),
            "codec": raw.get("codec") or "h264",
            "sizeBytes": raw.get("sizeBytes"),
            "sourceLabel": "Internet Archive" if provider == "archive" else provider,
            "watch": {"type": "remote", "value": raw.get("url")},
            "download": {"enabled": True, "type": "remote", "value": raw.get("url")},
        })
    ctx.store.tx(lambda db: db["movies"].append(movie))
    ctx.store.audit(ctx.user["username"], "movie_import", f"{provider}:{uid}")
    ctx.json({"ok": True, "id": movie["id"], "files": len(movie["files"])})


def h_enrich(ctx):
    if not _admin(ctx):
        return
    mid = ctx.params["id"]
    body = ctx.body_json()
    provider = body.get("provider") or "itunes"
    movie = ctx.store.movie(mid)
    if not movie:
        return ctx.error("影片不存在", 404, "not_found")
    try:
        if provider == "tmdb":
            if body.get("uid"):
                meta = providers.tmdb_detail(body["uid"], ctx.settings)
            else:
                results = providers.tmdb_search(movie.get("title") or "", ctx.settings)
                if not results:
                    return ctx.error("TMDB 未匹配到影片", 404, "no_match")
                meta = providers.tmdb_detail(results[0]["uid"], ctx.settings)
        elif provider == "omdb":
            meta = providers.omdb_lookup(movie.get("title") or "", movie.get("year"), ctx.settings)
        elif provider == "itunes":
            results = providers.itunes_search(movie.get("title") or "", ctx.settings)
            if not results:
                return ctx.error("iTunes 未匹配到影片", 404, "no_match")
            meta = results[0]
        elif provider == "archive":
            results = providers.archive_search(movie.get("title") or "", ctx.settings)
            if not results:
                return ctx.error("Archive 未匹配到影片", 404, "no_match")
            meta = providers.archive_item(results[0]["uid"], ctx.settings)
        elif provider == "wiki":
            meta = providers.wikipedia_summary(movie.get("title") or "", ctx.settings)
            if not meta:
                results = providers.wikipedia_search(movie.get("title") or "", ctx.settings)
                if not results:
                    return ctx.error("维基百科未匹配到条目", 404, "no_match")
                meta = results[0]
        else:
            return ctx.error("不支持的供应商", 400, "bad_provider")
    except Exception as exc:  # noqa: BLE001
        return ctx.error(f"补全失败：{exc}", 502, "provider_failed")
    def apply(db):
        m = next(x for x in db["movies"] if x["id"] == mid)
        for k in ("title", "originalTitle", "year", "poster", "backdrop", "synopsis",
                  "genres", "rating", "runtime", "director", "cast"):
            if meta.get(k) and not body.get("overwrite") is False:
                m[k] = meta[k]
        m["updatedAt"] = now_ts()
    ctx.store.tx(apply)
    ctx.store.audit(ctx.user["username"], "movie_enrich", f"{movie.get('title')} <- {provider}")
    ctx.json({"ok": True, "updated": {k: v for k, v in meta.items() if v}})


def h_test_provider(ctx):
    if not _admin(ctx):
        return
    body = ctx.body_json()
    provider = body.get("provider") or "archive"
    q = body.get("q") or "chaplin"
    started = time.time()
    try:
        items = providers.search(provider, q, ctx.settings)
        ctx.json({"ok": True, "count": len(items), "ms": round((time.time() - started) * 1000),
                  "sample": items[:2]})
    except Exception as exc:  # noqa: BLE001
        ctx.error(f"连接失败：{exc}", 502, "provider_failed")


def _media_root() -> str:
    from .api_media import MEDIA_DIR
    return MEDIA_DIR


def _local_path(rel: str) -> str:
    from .api_media import _local_path as lp
    return lp(rel)

def h_transcode_probe(ctx):
    if not _admin(ctx):
        return
    ctx.json({
        "ok": True,
        "ffmpeg": media.available(),
        "gpus": media.gpu_options(force=True),
        "settings": {k: ctx.settings.get(k) for k in
                     ("transcodeEnabled", "gpuTranscodeEnabled", "gpuDevice",
                      "gpuAutoFallback", "hlsHeights", "hlsCrf", "hlsPreset",
                      "softCrf", "softMaxMinutes")},
    })
