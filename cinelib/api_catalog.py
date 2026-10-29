"""Catalog routes: search, home rails, movie detail, playlists, history."""
from __future__ import annotations

import time

from . import catalog
from .store import now_ts, new_id


def _gate(ctx, what: str = "该功能") -> bool:
    if not ctx.user:
        ctx.error(f"{what}需要登录后使用", 401, "login_required")
        return False
    return True


# ------------------------------------------------------------------- search
def h_search(ctx):
    if not ctx.settings.get("allowGuestSearch", True) and not ctx.user:
        return ctx.error("搜索功能已对本访客关闭", 403, "guest_disabled")
    q = (ctx.query.get("q") or [""])[0].strip()
    genre = (ctx.query.get("genre") or [""])[0].strip()
    year = (ctx.query.get("year") or [""])[0].strip()
    quality = (ctx.query.get("quality") or [""])[0].strip()
    sort = (ctx.query.get("sort") or ["relevance"])[0]
    try:
        page = max(1, int((ctx.query.get("page") or ["1"])[0]))
    except ValueError:
        page = 1
    started = time.time()
    movies = ctx.store.published()
    rows, total = catalog.search_movies(movies, q, genre, year, quality, sort, page, 24)
    ctx.store.tx(lambda d: d["stats"].__setitem__("searches", d["stats"].get("searches", 0) + 1))
    ctx.json({
        "ok": True,
        "items": [catalog.movie_card(m) for m in rows],
        "total": total,
        "page": page,
        "pageSize": 24,
        "genres": catalog.all_genres(movies),
        "years": sorted({m.get("year") for m in movies if m.get("year")}, reverse=True)[:20],
        "authenticated": bool(ctx.user),
        "took": round((time.time() - started) * 1000, 1),
        "guestMode": not bool(ctx.user),
    })


def h_suggest(ctx):
    q = (ctx.query.get("q") or [""])[0].strip().lower()
    if len(q) < 1:
        return ctx.json({"ok": True, "items": []})
    out = []
    for m in ctx.store.published():
        hay = f"{m.get('title','')} {m.get('originalTitle','')}".lower()
        if q in hay:
            out.append({"id": m["id"], "title": m.get("title"), "year": m.get("year"),
                        "poster": catalog.normalize_img(m.get("poster")),
                        "genres": (m.get("genres") or [])[:2]})
        if len(out) >= 8:
            break
    ctx.json({"ok": True, "items": out})


# --------------------------------------------------------------------- home
def h_home(ctx):
    # 游客也返回同一套首页数据，仅去掉用户私有内容（继续观看 / 片单）
    movies = ctx.store.published()
    cards = {m["id"]: catalog.movie_card(m) for m in movies}
    history = (ctx.store.data.get("history", {}).get(ctx.user["id"], [])[:8]
               if ctx.user else [])
    cont = []
    for h in history:
        card = cards.get(h.get("movieId"))
        if not card:
            continue
        d = dict(card)
        d.update({"fileId": h.get("fileId"), "position": h.get("position") or 0,
                  "duration": h.get("duration") or 0, "quality": h.get("quality"),
                  "progress": round((h.get("position") or 0) / max(1, h.get("duration") or 1) * 100, 1),
                  "at": h.get("at")})
        cont.append(d)
    featured = [catalog.movie_card(m) for m in movies if m.get("featured")][:8]
    trending = sorted(movies, key=lambda m: -(m.get("views") or 0))[:12]
    recent = sorted(movies, key=lambda m: -(m.get("createdAt") or 0))[:12]
    top = sorted(movies, key=lambda m: -(m.get("rating") or 0))[:12]
    playlists = (ctx.store.data.get("playlists", {}).get(ctx.user["id"], [])
                 if ctx.user else [])
    ctx.json({
        "ok": True,
        "featured": featured,
        "continue": cont,
        "trending": [catalog.movie_card(m) for m in trending],
        "recent": [catalog.movie_card(m) for m in recent],
        "topRated": [catalog.movie_card(m) for m in top],
        "genres": catalog.all_genres(movies),
        "counts": {"movies": len(movies), "playlists": len(playlists),
                   "watchMinutes": sum(int((h.get("position") or 0) / 60) for h in history)},
        "announcement": ctx.settings.get("announcement"),
    })


# ------------------------------------------------------------------- detail
def h_movie(ctx):
    if not _gate(ctx, "影片详情"):
        return
    mid = ctx.params["id"]
    m = ctx.store.movie(mid)
    if not m:
        return ctx.error("影片不存在", 404, "not_found")
    detail = catalog.movie_detail(m)
    genres = set(m.get("genres") or [])
    related = [catalog.movie_card(x) for x in ctx.store.published()
               if x["id"] != mid and genres & set(x.get("genres") or [])][:8]
    if len(related) < 4:
        related += [catalog.movie_card(x) for x in ctx.store.published()
                    if x["id"] != mid][: 8 - len(related)]
    hist = next((h for h in ctx.store.data.get("history", {}).get(ctx.user["id"], [])
                 if h.get("movieId") == mid), None)
    playlists = (ctx.store.data.get("playlists", {}).get(ctx.user["id"], [])
                 if ctx.user else [])
    ctx.json({
        "ok": True,
        "movie": detail,
        "related": related,
        "resume": hist,
        "playlists": [{"id": p["id"], "name": p["name"],
                       "has": any(i.get("movieId") == mid for i in p.get("items", []))}
                      for p in playlists],
        "server": {"defaultDecoding": ctx.settings.get("defaultDecoding", "auto")},
    })


# ---------------------------------------------------------------- playlists
def h_playlists(ctx):
    if not _gate(ctx, "播放列表"):
        return
    items = ctx.store.data.get("playlists", {}).get(ctx.user["id"], [])
    cards = {m["id"]: catalog.movie_card(m) for m in ctx.store.data["movies"]}
    out = []
    for p in items:
        movies = [cards[i["movieId"]] for i in p.get("items", []) if i.get("movieId") in cards]
        out.append({"id": p["id"], "name": p["name"], "createdAt": p.get("createdAt"),
                    "count": len(movies), "movies": movies})
    ctx.json({"ok": True, "items": out})


def _playlist_or_404(ctx, pid):
    for p in ctx.store.data.get("playlists", {}).get(ctx.user["id"], []):
        if p["id"] == pid:
            return p
    return None


def h_playlist_create(ctx):
    if not _gate(ctx, "播放列表"):
        return
    body = ctx.body_json()
    name = (body.get("name") or "我的片单").strip()[:40]
    entry = {"id": new_id("pl"), "name": name, "createdAt": now_ts(), "items": []}
    if body.get("movieId"):
        entry["items"].append({"movieId": body["movieId"], "addedAt": now_ts()})
    def apply(db):
        db.setdefault("playlists", {}).setdefault(ctx.user["id"], []).append(entry)
    ctx.store.tx(apply)
    ctx.json({"ok": True, "playlist": entry})


def h_playlist_update(ctx):
    if not _gate(ctx, "播放列表"):
        return
    pid = ctx.params["id"]
    body = ctx.body_json()
    def apply(db):
        for p in db.get("playlists", {}).get(ctx.user["id"], []):
            if p["id"] != pid:
                continue
            if body.get("name"):
                p["name"] = str(body["name"]).strip()[:40] or p["name"]
            if body.get("addMovieId"):
                if not any(i["movieId"] == body["addMovieId"] for i in p["items"]):
                    p["items"].append({"movieId": body["addMovieId"], "addedAt": now_ts()})
            if body.get("removeMovieId"):
                p["items"] = [i for i in p["items"] if i["movieId"] != body["removeMovieId"]]
            return dict(p)
        return None
    result = ctx.store.tx(apply)
    if result is None:
        return ctx.error("片单不存在", 404, "not_found")
    ctx.json({"ok": True, "playlist": result})


def h_playlist_delete(ctx):
    if not _gate(ctx, "播放列表"):
        return
    pid = ctx.params["id"]
    def apply(db):
        lists = db.get("playlists", {}).get(ctx.user["id"], [])
        db["playlists"][ctx.user["id"]] = [p for p in lists if p["id"] != pid]
    ctx.store.tx(apply)
    ctx.json({"ok": True})


# ------------------------------------------------------------------ history
def h_history_get(ctx):
    if not _gate(ctx, "最近播放"):
        return
    rows = ctx.store.data.get("history", {}).get(ctx.user["id"], [])
    cards = {m["id"]: catalog.movie_card(m) for m in ctx.store.data["movies"]}
    out = []
    for h in rows:
        card = cards.get(h.get("movieId"))
        if not card:
            continue
        d = dict(card)
        d.update({"fileId": h.get("fileId"), "position": h.get("position") or 0,
                  "duration": h.get("duration") or 0, "quality": h.get("quality"),
                  "progress": round((h.get("position") or 0) / max(1, h.get("duration") or 1) * 100, 1),
                  "at": h.get("at")})
        out.append(d)
    ctx.json({"ok": True, "items": out})


def h_history_post(ctx):
    if not _gate(ctx, "最近播放"):
        return
    body = ctx.body_json()
    mid = body.get("movieId")
    if not mid:
        return ctx.error("缺少影片", 400, "bad_request")
    entry = {"movieId": mid, "fileId": body.get("fileId"),
             "position": float(body.get("position") or 0),
             "duration": float(body.get("duration") or 0),
             "quality": body.get("quality"), "at": now_ts()}
    def apply(db):
        rows = db.setdefault("history", {}).setdefault(ctx.user["id"], [])
        rows[:] = [r for r in rows if r.get("movieId") != mid]
        rows.insert(0, entry)
        del rows[60:]
    ctx.store.tx(apply)
    ctx.json({"ok": True})


def h_history_clear(ctx):
    if not _gate(ctx, "最近播放"):
        return
    mid = ctx.params.get("id")
    def apply(db):
        rows = db.setdefault("history", {}).setdefault(ctx.user["id"], [])
        if mid:
            rows[:] = [r for r in rows if r.get("movieId") != mid]
        else:
            rows.clear()
    ctx.store.tx(apply)
    ctx.json({"ok": True})


# ---------------------------------------------------------------- downloads
def h_downloads_get(ctx):
    if not _gate(ctx, "下载记录"):
        return
    rows = ctx.store.data.get("downloads", {}).get(ctx.user["id"], [])
    cards = {m["id"]: catalog.movie_card(m) for m in ctx.store.data["movies"]}
    out = []
    for d in rows:
        card = cards.get(d.get("movieId"))
        if not card:
            continue
        item = dict(card)
        item.update({"fileId": d.get("fileId"), "quality": d.get("quality"),
                     "extras": d.get("extras") or [], "at": d.get("at"),
                     "sizeBytes": d.get("sizeBytes")})
        out.append(item)
    ctx.json({"ok": True, "items": out, "extrasCatalog": catalog.download_extras()})
