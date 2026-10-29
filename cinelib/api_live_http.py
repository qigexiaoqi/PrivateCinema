"""HTTP handlers for live federated search (registered in app.py)."""
from __future__ import annotations

import urllib.parse

from . import api_live, api_media, net


def h_live_sources(ctx):
    """Public: the sources that currently appear on the search page."""
    ctx.json({"ok": True, "sources": api_live.public_sources(ctx.store)})


def h_live_search(ctx):
    if not ctx.settings.get("allowGuestSearch", True) and not ctx.user:
        return ctx.error("搜索功能已对本访客关闭", 403, "guest_disabled")
    q = (ctx.query.get("q") or [""])[0].strip()
    raw = (ctx.query.get("sources") or [""])[0]
    sources = [s.strip() for s in raw.split(",") if s.strip()] or None
    try:
        data = api_live.search(ctx.store, q, sources, ctx.settings)
    except Exception as exc:  # noqa: BLE001
        return ctx.error(f"在线片源检索失败：{exc}", 502, "provider_failed")
    urls = []
    for it in data.get("items", []):
        if it.get("poster"):
            urls.append(it["poster"])
        urls.extend(f.get("url") for f in (it.get("files") or []))
    if urls:
        api_media.remember_hosts(ctx, urls)
    data["authenticated"] = bool(ctx.user)
    ctx.json(data)


def h_live_item(ctx):
    provider = (ctx.query.get("provider") or [""])[0]
    uid = (ctx.query.get("uid") or [""])[0]
    try:
        item = api_live.item(ctx.store, provider, uid, ctx.settings)
    except ValueError as exc:
        return ctx.error(str(exc), 400, "bad_request")
    except Exception as exc:  # noqa: BLE001
        return ctx.error(f"片源详情获取失败：{exc}", 502, "provider_failed")
    urls = [item.get("poster") or "", item.get("backdrop") or ""]
    urls.extend(f.get("url") for f in (item.get("files") or []))
    api_media.remember_hosts(ctx, urls)
    item["authenticated"] = bool(ctx.user)
    ctx.json({"ok": True, "item": item})


def h_live_download(ctx):
    """Stream one upstream file to the visitor's machine (no server-side copy)."""
    if not ctx.user:
        return ctx.error("下载需要登录后使用", 401, "login_required")
    provider = (ctx.query.get("provider") or [""])[0]
    uid = (ctx.query.get("uid") or [""])[0]
    try:
        idx = int((ctx.query.get("file") or ["0"])[0])
    except ValueError:
        idx = 0
    try:
        item = api_live.item(ctx.store, provider, uid, ctx.settings)
    except Exception as exc:  # noqa: BLE001
        return ctx.error(f"片源详情获取失败：{exc}", 502, "provider_failed")
    files = item.get("files") or []
    if not files:
        return ctx.error("该片源没有可下载文件", 404, "no_file")
    f = files[idx] if 0 <= idx < len(files) else files[0]
    url = f.get("url")
    host = urllib.parse.urlparse(url or "").hostname or ""
    if not host:
        return ctx.error("该地址无效", 400, "bad_url")
    # a direct download may be the first thing a visitor does: learn the CDN host
    api_media.remember_hosts(ctx, [url])
    if not net.host_allowed(host, api_media.all_allowed_hosts(ctx)):
        return ctx.error("该源域名不在白名单内", 403, "host_not_allowed")

    kind = f.get("kind") or ("hls" if ".m3u8" in (url or "").lower() else "mp4")
    safe_title = "".join(ch for ch in (item.get("title") or "video")
                         if ch not in '\\/:*?"<>|')[:80]
    base = f"{safe_title} ({item.get('year') or ''}) - {f.get('quality')}".replace(" ()", "")
    if kind == "embed":
        return ctx.error("该条目只有网页播放页（share 页），没有可直接下载的视频文件；"
                         "请换一个 m3u8/MP4 线路，或在播放器里播放", 415, "embed_only")
    ext = "m3u8" if kind == "hls" else "mp4"
    fmt = (ctx.query.get("format") or ["mp4"])[0].lower()
    ctx.store.audit(ctx.user["username"], "live_download", f"{provider}:{uid} {f.get('quality')}")
    if kind == "hls" and fmt != "m3u8":
        # give the visitor a real file: remux the HLS stream to fragmented MP4
        return api_media.serve_hls_as_mp4(ctx, url, f"{base}.mp4")
    return api_media._proxy_stream(ctx, url, download_name=f"{base}.{ext}")

def h_live_group(ctx):
    raw = (ctx.query.get("ids") or [""])[0]
    refs = [r.strip() for r in raw.split(",") if r.strip()]
    if not refs:
        return ctx.error("缺少播放源", 400, "bad_request")
    try:
        group = api_live.group_items(ctx.store, refs, ctx.settings)
    except Exception as exc:  # noqa: BLE001
        return ctx.error(f"聚合播放源失败：{exc}", 502, "provider_failed")
    urls = [group.get("poster") or "", group.get("backdrop") or ""]
    for src in group.get("sources", []):
        urls.extend(f.get("url") for f in src.get("files") or [])
    api_media.remember_hosts(ctx, urls)
    ctx.json({"ok": True, "group": group, "authenticated": bool(ctx.user)})
