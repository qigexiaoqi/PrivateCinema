"""Catalog helpers: search, filters, and API serialisation."""
from __future__ import annotations

import re
import urllib.parse

from .providers import QUALITY_RANK
from .net import human_bytes


def normalize_img(url: str | None) -> str:
    if not url:
        return ""
    url = url.strip()
    if url.startswith("/") or url.startswith("data:") or url.startswith("blob:"):
        return url
    if not url.startswith("http"):
        return ""
    return "/api/img?u=" + urllib.parse.quote(url, safe="")


def _rank(quality: str) -> int:
    return QUALITY_RANK.get(quality, 5)


def sorted_files(files: list[dict]) -> list[dict]:
    return sorted(files or [], key=lambda f: (-_rank(f.get("quality", "")),
                                              -(f.get("sizeBytes") or 0)))


def public_file(f: dict) -> dict:
    watch = f.get("watch") or {}
    dl = f.get("download") or {}
    data = {
        "id": f.get("id"),
        "quality": f.get("quality") or "SD",
        "label": f.get("label") or f.get("quality") or "原画",
        "width": f.get("width"),
        "height": f.get("height"),
        "codec": f.get("codec") or "h264",
        "container": f.get("container") or "mp4",
        "fps": f.get("fps"),
        "sizeBytes": f.get("sizeBytes"),
        "sizeLabel": human_bytes(f.get("sizeBytes")),
        "sourceLabel": f.get("sourceLabel") or ("本地片源" if watch.get("type") == "local" else "远端片源"),
        "watchType": watch.get("type"),
        "downloadType": dl.get("type"),
        "watchAvailable": bool(watch.get("type")),
        "downloadAvailable": bool(dl.get("enabled", True) and dl.get("type")),
        "duration": f.get("duration"),
        "hlsVariants": f.get("hlsVariants") or [],
    }
    if watch.get("type") == "hls":
        data["hlsUrl"] = "/media/" + str(watch.get("value") or "").lstrip("/")
    return data


def movie_card(m: dict, show_private: bool = False) -> dict:
    files = sorted_files(m.get("files") or [])
    qualities = [f["quality"] for f in files if (f.get("watch") or {}).get("type")]
    dl_qualities = [f["quality"] for f in files if (f.get("download") or {}).get("enabled", True)
                    and (f.get("download") or {}).get("type")]
    card = {
        "id": m.get("id"),
        "title": m.get("title") or "未命名",
        "originalTitle": m.get("originalTitle") or "",
        "year": m.get("year"),
        "genres": m.get("genres") or [],
        "rating": m.get("rating"),
        "runtime": m.get("runtime"),
        "poster": normalize_img(m.get("poster")),
        "backdrop": normalize_img(m.get("backdrop") or m.get("poster")),
        "synopsis": (m.get("synopsis") or "")[:320],
        "director": m.get("director") or "",
        "qualities": qualities[:6],
        "downloadQualities": dl_qualities[:6],
        "views": m.get("views") or 0,
        "featured": bool(m.get("featured")),
        "status": m.get("status", "published"),
        "sourceName": ((m.get("source") or {}).get("provider") or "local"),
    }
    if show_private:
        card["status"] = m.get("status", "published")
    return card


def movie_detail(m: dict) -> dict:
    files = sorted_files(m.get("files") or [])
    watch_qualities = [f for f in files if (f.get("watch") or {}).get("type")]
    dl_qualities = [f for f in files if (f.get("download") or {}).get("enabled", True)
                    and (f.get("download") or {}).get("type")]
    data = movie_card(m)
    data.update({
        "synopsis": m.get("synopsis") or "",
        "backdrop": normalize_img(m.get("backdrop") or m.get("poster")),
        "cast": m.get("cast") or [],
        "director": m.get("director") or "",
        "country": m.get("country") or "",
        "language": m.get("language") or "",
        "tags": m.get("tags") or [],
        "license": (m.get("source") or {}).get("license") or "",
        "sourceUrl": (m.get("source") or {}).get("url") or "",
        "files": [public_file(f) for f in files],
        "watchQualities": [public_file(f) for f in watch_qualities],
        "downloadQualities": [public_file(f) for f in dl_qualities],
        "subtitles": [{"id": s.get("id"), "lang": s.get("lang"),
                       "label": s.get("label"), "url": f"/api/subtitles/{m['id']}/{s.get('id')}"}
                      for s in (m.get("subtitles") or [])],
        "downloadExtras": download_extras(),
        "createdAt": m.get("createdAt"),
    })
    return data


def download_extras() -> list[dict]:
    """Selectable metadata payloads for a download bundle."""
    return [
        {"id": "poster", "label": "电影海报", "detail": "poster.jpg · 高清封面", "size": "~1 MB"},
        {"id": "backdrop", "label": "背景剧照", "detail": "backdrop.jpg · 横向大图", "size": "~2 MB"},
        {"id": "nfo", "label": "Kodi NFO", "detail": "影片刮削信息（XML）", "size": "~6 KB"},
        {"id": "json", "label": "元数据 JSON", "detail": "完整字段 + 文件清单", "size": "~4 KB"},
        {"id": "subs", "label": "内嵌字幕文件", "detail": "片库中全部字幕 (.srt)", "size": "~60 KB"},
        {"id": "readme", "label": "简介与版权", "detail": "readme.txt · 来源说明", "size": "~3 KB"},
        {"id": "checksums", "label": "校验清单", "detail": "checksums.txt · 大小/来源", "size": "~1 KB"},
        {"id": "m3u", "label": "播放列表", "detail": "playlist.m3u · 本片全部清晰度", "size": "~1 KB"},
    ]


def movie_matches(m: dict, q: str, genre: str = "", year: str = "",
                  quality: str = "") -> bool:
    if m.get("status", "published") != "published":
        return False
    hay = " ".join([
        m.get("title") or "", m.get("originalTitle") or "",
        " ".join(m.get("genres") or []), " ".join(m.get("tags") or []),
        m.get("director") or "", " ".join(m.get("cast") or []),
        str(m.get("year") or ""), m.get("synopsis") or "",
    ]).lower()
    if q:
        tokens = [t for t in re.split(r"\s+", q.lower().strip()) if t]
        if not all(t in hay for t in tokens):
            return False
    if genre and genre != "全部":
        if genre.lower() not in [g.lower() for g in (m.get("genres") or [])]:
            return False
    if year:
        try:
            if int(year) != int(m.get("year") or 0):
                return False
        except (TypeError, ValueError):
            pass
    if quality:
        quals = {f.get("quality") for f in (m.get("files") or [])}
        if quality not in quals:
            return False
    return True


def search_movies(movies: list[dict], q: str, genre: str = "", year: str = "",
                  quality: str = "", sort: str = "relevance", page: int = 1,
                  page_size: int = 24):
    rows = [m for m in movies if movie_matches(m, q, genre, year, quality)]
    if sort == "year":
        rows.sort(key=lambda m: -(m.get("year") or 0))
    elif sort == "rating":
        rows.sort(key=lambda m: -(m.get("rating") or 0))
    elif sort == "views":
        rows.sort(key=lambda m: -(m.get("views") or 0))
    elif sort == "title":
        rows.sort(key=lambda m: (m.get("title") or "").lower())
    else:
        rows.sort(key=lambda m: (-(m.get("rating") or 0), -(m.get("year") or 0)))
    total = len(rows)
    start = max(0, (page - 1) * page_size)
    return rows[start:start + page_size], total


def all_genres(movies: list[dict]) -> list[str]:
    seen = {}
    for m in movies:
        for g in m.get("genres") or []:
            seen[g] = seen.get(g, 0) + 1
    return [g for g, _ in sorted(seen.items(), key=lambda kv: -kv[1])]
