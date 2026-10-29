"""MacCMS / 苹果CMS V10 resource-site API adapter.

These endpoints (used by most Chinese "资源站") answer:

    GET {base}?ac=videolist&wd=关键词   -> {"list": [{vod_id, vod_name, vod_pic, ...}]}
    GET {base}?ac=detail&ids=123       -> {"list": [{..., vod_play_url: "第01集$url#第02集$url$$$线路2$..."}]}

`vod_play_url` packs one or more play lines; every line is `名称$地址`, groups are
separated by `$$$`.  Addresses are m3u8 / mp4 (direct) or an H5 share page.
"""
from __future__ import annotations

import html
import re
import urllib.parse

from . import net

TIMEOUT = 15


def _clean(text) -> str:
    if not text:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", str(text))
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def _api(base: str, **params) -> dict:
    sep = "&" if "?" in base else "?"
    url = base + sep + urllib.parse.urlencode(params)
    return net.fetch_json(url, timeout=TIMEOUT)


def _kind(url: str) -> str:
    low = url.lower()
    if ".m3u8" in low:
        return "hls"
    if ".mp4" in low:
        return "mp4"
    return "embed"


def _quality(label: str, url: str) -> str:
    up = (label or "").upper()
    if "2160" in up or "4K" in up:
        return "2160p"
    if "1080" in up:
        return "1080p"
    if "720" in up:
        return "720p"
    if "480" in up:
        return "480p"
    if "HD" in up:
        return "HD"
    kind = _kind(url)
    return "HLS" if kind == "hls" else ("MP4" if kind == "mp4" else "网页")


def parse_play_url(raw: str, limit: int = 60) -> list[dict]:
    files: list[dict] = []
    seen: set[str] = set()
    for group in (raw or "").split("$$$"):
        for entry in group.split("#"):
            entry = entry.strip()
            if "$" not in entry:
                continue
            label, url = entry.rsplit("$", 1)
            url = url.strip()
            if not url.startswith("http") or url in seen:
                continue
            seen.add(url)
            files.append({
                "label": _clean(label) or _quality("", url),
                "quality": _quality(label, url),
                "url": url,
                "kind": _kind(url),
                "height": None,
                "width": None,
                "sizeBytes": None,
            })
            if len(files) >= limit:
                break
        if len(files) >= limit:
            break
    files.sort(key=lambda f: {"hls": 0, "mp4": 1}.get(f["kind"], 2))
    return files


def _candidate(src: dict, row: dict) -> dict:
    play = row.get("vod_play_url") or row.get("vod_play_from") or ""
    files = parse_play_url(play)
    if not files and row.get("vod_play_from"):
        files = []
    name = _clean(row.get("vod_name")) or "未命名"
    year = None
    m = re.search(r"(19|20)\d{2}", str(row.get("vod_year") or ""))
    if m:
        year = int(m.group(0))
    return {
        "uid": str(row.get("vod_id") or ""),
        "title": name,
        "originalTitle": "",
        "year": year,
        "poster": row.get("vod_pic") or "",
        "backdrop": row.get("vod_pic_slide") or row.get("vod_pic") or "",
        "synopsis": _clean(row.get("vod_content") or row.get("vod_blurb") or "")[:1500],
        "genres": [g for g in re.split(r"[,/，、]", str(row.get("type_name") or "")) if g][:5],
        "rating": None,
        "runtime": None,
        "director": _clean(row.get("vod_director"))[:80],
        "cast": [c.strip() for c in re.split(r"[,，、/]", _clean(row.get("vod_actor"))) if c.strip()][:8],
        "type": "movie",
        "files": files,
        "license": f"{src.get('name')} 资源接口 · 仅索引",
        "sourceUrl": "",
        "remark": row.get("vod_remarks") or "",
    }


def search(src: dict, query: str, settings: dict = None) -> list[dict]:
    base = (src.get("endpoint") or "").strip()
    if not base:
        return []
    data = _api(base, ac="videolist", wd=query)
    rows = data.get("list") or []
    return [_candidate(src, r) for r in rows if r.get("vod_name")]


def item(src: dict, uid: str, settings: dict = None) -> dict:
    base = (src.get("endpoint") or "").strip()
    if not base:
        raise IOError("资源接口地址为空")
    data = _api(base, ac="detail", ids=uid)
    rows = data.get("list") or []
    if not rows:
        # some endpoints ignore `ids`; fall back to search by id
        raise IOError("资源站未返回该条目")
    return _candidate(src, rows[0])


def test(endpoint: str, keyword: str = "流浪地球") -> dict:
    src = {"name": "测试源", "endpoint": endpoint}
    rows = search(src, keyword)
    sample = rows[0] if rows else {}
    return {
        "count": len(rows),
        "sample": sample.get("title"),
        "files": len(sample.get("files") or []),
        "play": (sample.get("files") or [{}])[0].get("url", "")[:120],
    }
