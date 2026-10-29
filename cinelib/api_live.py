"""Live federated search over configurable sources (registry in db["sources"]).

Built-in kinds map to the public APIs in providers.py; the `maccms` kind talks to
any 苹果CMS/MacCMS V10 resource endpoint the admin adds.
"""
from __future__ import annotations

import concurrent.futures
import time
import urllib.parse

from . import maccms, net, providers
from .source_defaults import DEFAULT_SOURCES
from .store import new_id, now_ts

SEARCH_TTL = 300
ITEM_TTL = 1800
MAX_PER_SOURCE = 10

BUILTIN_KINDS = {"archive", "itunes", "tvmaze", "wiki", "tmdb"}
KINDS = {
    "archive": "Internet Archive",
    "itunes": "iTunes",
    "tvmaze": "TVMaze",
    "wiki": "Wikipedia",
    "tmdb": "TMDB",
    "maccms": "MacCMS 资源接口",
}
PLAYABLE_KINDS = {"archive", "itunes", "maccms"}


# ------------------------------------------------------------------ registry
def default_sources() -> list[dict]:
    return [dict(x) for x in DEFAULT_SOURCES]


def registry(store) -> list[dict]:
    return store.data.setdefault("sources", [])


def visible(store) -> list[dict]:
    return [s for s in registry(store) if s.get("enabled", True) and s.get("show", True)]


def resolve(store, source_id: str) -> dict | None:
    for s in registry(store):
        if s.get("id") == source_id:
            return s
    return None


def public_sources(store) -> list[dict]:
    return [{
        "id": s["id"], "name": s.get("name") or s["id"], "kind": s.get("kind"),
        "playable": s.get("kind") in PLAYABLE_KINDS,
        "note": s.get("note") or "",
    } for s in visible(store)]


def add_source(store, name: str, kind: str, endpoint: str = "", show: bool = True) -> dict:
    kind = kind if kind in KINDS else "maccms"
    entry = {
        "id": new_id("src"),
        "name": (name or KINDS.get(kind, kind)).strip()[:40],
        "kind": kind,
        "endpoint": (endpoint or "").strip(),
        "enabled": True,
        "show": bool(show),
        "builtin": False,
        "note": KINDS.get(kind, kind),
    }
    store.tx(lambda db: db.setdefault("sources", []).append(entry))
    return entry


# --------------------------------------------------------------------- cache
def _cache_get(store, key: str, ttl: int):
    entry = (store.data.get("providerCache") or {}).get(key)
    if entry and now_ts() - entry.get("at", 0) < ttl:
        return entry.get("data")
    return None


def _cache_put(store, key: str, data) -> None:
    def apply(db):
        cache = db.setdefault("providerCache", {})
        cache[key] = {"at": now_ts(), "data": data}
        if len(cache) > 500:
            for k in sorted(cache, key=lambda k: cache[k].get("at", 0))[:160]:
                cache.pop(k, None)
    store.tx(apply)


def _fingerprint(settings: dict) -> str:
    import hashlib
    raw = f"{settings.get('proxyEnabled')}|{settings.get('proxyUrl')}|{bool(settings.get('tmdbKey'))}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]


# ---------------------------------------------------------------------- cards
def _norm_title(title: str) -> str:
    """Normalise a title so the same film from different sources groups together."""
    text = (title or "").lower()
    drop = set(" \t\n-_·,，。!！?？:：;；\"'“”‘’、()（）[]【】《》")
    return "".join(ch for ch in text if ch not in drop)


def _card(src: dict, cand: dict) -> dict:
    files = []
    for raw in (cand.get("files") or [])[:80]:
        url = raw.get("url") or ""
        if not url.startswith("http"):
            continue
        files.append({
            "quality": raw.get("quality") or "SD",
            "label": raw.get("label") or raw.get("quality") or "原画",
            "kind": raw.get("kind") or ("hls" if ".m3u8" in url.lower() else "mp4"),
            "height": raw.get("height"),
            "width": raw.get("width"),
            "sizeBytes": raw.get("sizeBytes"),
            "sizeLabel": net.human_bytes(raw.get("sizeBytes")),
            "url": url,
            "playUrl": "/api/proxy?u=" + urllib.parse.quote(url, safe=""),
        })
    kind = src.get("kind") or ""
    return {
        "key": f"{src['id']}:{cand.get('uid')}",
        "provider": src["id"],
        "providerName": src.get("name") or src["id"],
        "providerKind": kind,
        "uid": str(cand.get("uid") or ""),
        "title": cand.get("title") or "未命名",
        "originalTitle": cand.get("originalTitle") or "",
        "year": cand.get("year"),
        "poster": cand.get("poster") or "",
        "backdrop": cand.get("backdrop") or cand.get("poster") or "",
        "synopsis": (cand.get("synopsis") or "")[:1500],
        "genres": cand.get("genres") or [],
        "rating": cand.get("rating"),
        "runtime": cand.get("runtime"),
        "kind": cand.get("type") or "movie",
        "license": cand.get("license") or "",
        "sourceUrl": cand.get("sourceUrl") or "",
        "remark": cand.get("remark") or "",
        "files": files,
        "needsDetail": bool(cand.get("needsDetail")) or (kind == "archive" and not files),
        "playable": bool(files),
        "canPlay": kind in PLAYABLE_KINDS,
    }


# --------------------------------------------------------------------- search
def _search_one(src: dict, query: str, settings: dict) -> list[dict]:
    kind = src.get("kind")
    label = src.get("name") or src["id"]
    try:
        if kind == "maccms":
            rows = maccms.search(src, query, settings)
        elif kind in BUILTIN_KINDS:
            rows = providers.search(kind, query, settings)
        else:
            rows = []
    except Exception as exc:  # noqa: BLE001
        return [{"__error": f"{label}: {exc}"}]
    out = []
    for cand in (rows or [])[:MAX_PER_SOURCE]:
        if not cand.get("title"):
            continue
        out.append(_card(src, cand))
    return out


def search(store, query: str, sources: list[str] | None, settings: dict) -> dict:
    query = (query or "").strip()
    if not query:
        return {"ok": True, "items": [], "errors": [], "sources": [], "cached": False}

    enabled = visible(store)
    if sources:
        allowed = set(sources)
        picked = [s for s in registry(store) if s["id"] in allowed and s.get("enabled", True)]
    else:
        picked = enabled

    cache_key = (f"q|{_fingerprint(settings)}|{query.lower()}|"
                 f"{','.join(sorted(s['id'] for s in picked))}")
    cached = _cache_get(store, cache_key, SEARCH_TTL)
    if cached:
        return {**cached, "cached": True, "took": 0}

    started = time.time()
    items: list[dict] = []
    errors: list[str] = []
    counts: dict[str, int] = {}

    if picked:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(10, len(picked))) as pool:
            futures = {pool.submit(_search_one, s, query, settings): s for s in picked}
            for fut in concurrent.futures.as_completed(futures, timeout=60):
                src = futures[fut]
                try:
                    rows = fut.result()
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{src.get('name', src['id'])}: {exc}")
                    continue
                got = 0
                for row in rows:
                    if "__error" in row:
                        errors.append(row["__error"])
                        continue
                    items.append(row)
                    got += 1
                counts[src["id"]] = got

    order = {s["id"]: i for i, s in enumerate(picked)}
    needle = query.lower()

    def rank(card):
        title = (card.get("title") or "").lower()
        return (
            0 if needle in title else 1,          # exact-ish title matches first
            0 if card.get("canPlay") else 1,       # playable sources before metadata-only
            order.get(card.get("provider"), 99),   # keep the admin's source order
            -(card.get("year") or 0),
        )
    items.sort(key=rank)

    groups_map: dict[tuple, dict] = {}
    for card in items:
        key = (_norm_title(card.get("title")), card.get("year") or "")
        group = groups_map.get(key)
        if not group:
            group = {
                "title": card.get("title"),
                "year": card.get("year"),
                "poster": card.get("poster") or "",
                "backdrop": card.get("backdrop") or "",
                "rating": card.get("rating"),
                "genres": card.get("genres") or [],
                "synopsis": card.get("synopsis") or "",
                "sources": [],
                "files": 0,
                "qualities": [],
                "canPlay": False,
                "_rank": rank(card),
            }
            groups_map[key] = group
        if any(x["provider"] == card["provider"] and x["uid"] == card["uid"]
               for x in group["sources"]):
            continue
        group["sources"].append({
            "provider": card["provider"],
            "providerName": card.get("providerName") or card["provider"],
            "uid": card["uid"],
            "files": len(card.get("files") or []),
            "canPlay": bool(card.get("canPlay")),
        })
        group["files"] += len(card.get("files") or [])
        for f in card.get("files") or []:
            q = f.get("quality")
            if q and q not in group["qualities"]:
                group["qualities"].append(q)
        group["canPlay"] = group["canPlay"] or bool(card.get("canPlay"))
        if not group["poster"] and card.get("poster"):
            group["poster"] = card["poster"]
        if len(card.get("synopsis") or "") > len(group["synopsis"] or ""):
            group["synopsis"] = card["synopsis"]
    groups = sorted(groups_map.values(), key=lambda g: g["_rank"])
    for g in groups:
        g.pop("_rank", None)
        g["qualities"] = g.get("qualities", [])[:6]

    payload = {
        "ok": True,
        "query": query,
        "items": items,
        "groups": groups,
        "errors": errors,
        "counts": counts,
        "sources": [{"id": s["id"], "name": s.get("name") or s["id"], "kind": s.get("kind"),
                     "count": counts.get(s["id"], 0),
                     "playable": s.get("kind") in PLAYABLE_KINDS} for s in picked],
        "took": round((time.time() - started) * 1000, 1),
    }
    _cache_put(store, cache_key, payload)
    return {**payload, "cached": False}


# ----------------------------------------------------------------------- item
def item(store, provider: str, uid: str, settings: dict) -> dict:
    src = resolve(store, provider)
    if not src:
        raise ValueError("未知片源")
    uid = (uid or "").strip()
    if not uid:
        raise ValueError("缺少条目 ID")
    cache_key = f"item|{_fingerprint(settings)}|{provider}|{uid}"
    cached = _cache_get(store, cache_key, ITEM_TTL)
    if cached:
        return cached

    kind = src.get("kind")
    if kind == "archive":
        cand = providers.archive_item(uid, settings)
    elif kind == "itunes":
        cand = _itunes_lookup(uid, settings)
    elif kind == "tvmaze":
        d = net.fetch_json(f"https://api.tvmaze.com/shows/{urllib.parse.quote(uid)}",
                           settings=settings, timeout=20)
        img = (d.get("image") or {}).get("original") or (d.get("image") or {}).get("medium") or ""
        cand = {"uid": uid, "title": d.get("name") or "",
                "year": providers._year(d.get("premiered")), "poster": img,
                "synopsis": providers._strip_html(d.get("summary")),
                "genres": d.get("genres") or [],
                "rating": (d.get("rating") or {}).get("average"),
                "runtime": d.get("averageRuntime") or d.get("runtime"),
                "type": "series", "files": [], "license": "TVmaze 元数据 (CC BY-SA)",
                "sourceUrl": d.get("url") or ""}
    elif kind == "wiki":
        cand = providers.wikipedia_summary(uid, settings)
        if not cand:
            raise IOError("维基条目不存在")
    elif kind == "tmdb":
        cand = providers.tmdb_detail(uid, settings)
        cand.update({"files": [], "type": "movie", "license": "TMDB 元数据"})
    elif kind == "maccms":
        cand = maccms.item(src, uid, settings)
    else:
        raise ValueError("不支持的片源类型")

    card = _card(src, cand)
    card["needsDetail"] = False
    _cache_put(store, cache_key, card)
    return card


def _itunes_lookup(uid: str, settings: dict) -> dict:
    url = ("https://itunes.apple.com/lookup?id=" + urllib.parse.quote(uid) +
           "&entity=movie&country=US")
    data = net.fetch_json(url, settings=settings, timeout=20)
    rows = data.get("results") or []
    if not rows:
        raise IOError("iTunes 条目不存在")
    r = rows[0]
    art = (r.get("artworkUrl100") or "").replace("100x100bb", "600x900bb")
    files = []
    if r.get("previewUrl"):
        files.append({"quality": "预告", "label": "官方预告片 · MP4", "height": 360,
                      "width": 640, "sizeBytes": None, "url": r["previewUrl"],
                      "kind": "mp4"})
    return {
        "provider": "itunes", "uid": uid,
        "title": r.get("trackName") or "",
        "originalTitle": r.get("trackCensoredName") or "",
        "year": providers._year(r.get("releaseDate")),
        "poster": art, "backdrop": art,
        "synopsis": providers._strip_html(r.get("longDescription") or r.get("shortDescription")),
        "genres": [r.get("primaryGenreName")] if r.get("primaryGenreName") else [],
        "rating": None,
        "runtime": int(round((r.get("trackTimeMillis") or 0) / 60000)) or None,
        "type": "movie", "files": files,
        "license": "Apple iTunes 元数据", "sourceUrl": r.get("trackViewUrl") or "",
    }

def group_items(store, refs: list[str], settings: dict) -> dict:
    """Combine several (provider|uid) references into one playable page."""
    picked: list[dict] = []
    errors: list[str] = []
    for ref in refs[:12]:
        if "|" not in ref:
            continue
        provider, uid = ref.split("|", 1)
        try:
            item_data = item(store, provider, uid, settings)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{provider}: {exc}")
            continue
        picked.append(item_data)
    if not picked:
        raise IOError("没有可用的播放源")

    def longest(field):
        return max((p.get(field) or "" for p in picked), key=len, default="")

    base = picked[0]
    return {
        "title": base.get("title") or "",
        "originalTitle": base.get("originalTitle") or "",
        "year": base.get("year"),
        "poster": next((p["poster"] for p in picked if p.get("poster")), ""),
        "backdrop": next((p["backdrop"] for p in picked if p.get("backdrop")), ""),
        "rating": next((p["rating"] for p in picked if p.get("rating")), None),
        "genres": next((p["genres"] for p in picked if p.get("genres")), []),
        "synopsis": longest("synopsis"),
        "remark": base.get("remark") or "",
        "sources": [{
            "provider": p["provider"],
            "providerName": p.get("providerName") or p["provider"],
            "providerKind": p.get("providerKind"),
            "uid": p["uid"],
            "files": p.get("files") or [],
            "license": p.get("license") or "",
            "sourceUrl": p.get("sourceUrl") or "",
        } for p in picked],
        "errors": errors,
    }
