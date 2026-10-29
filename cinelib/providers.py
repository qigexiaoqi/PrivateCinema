"""Film source + metadata providers.

Everything here talks to public APIs, normalised into one candidate shape so the
admin UI can import a film (with real, playable qualities) in one click.

Providers
---------
archive  : Internet Archive – public-domain features with genuine multi-bitrate
           MP4 derivatives.  No API key.  Gives playable *and* downloadable files.
itunes   : Apple iTunes Search API – rich metadata + official trailer MP4.
           No API key.
tvmaze   : TVmaze – series/episode metadata.  No API key.
tmdb     : The Movie Database – best-in-class metadata.  Needs a v3 API key
           (free, themoviedb.org/settings/api).
omdb     : OMDb – IMDb ratings and plot.  Needs a free key.
"""
from __future__ import annotations

import html
import re
import urllib.parse

from . import net

ARCHIVE_SEARCH = "https://archive.org/advancedsearch.php"
ARCHIVE_META = "https://archive.org/metadata/{ident}"
ARCHIVE_DL = "https://archive.org/download/{ident}/{file}"
ARCHIVE_IMG = "https://archive.org/services/img/{ident}"
ITUNES = "https://itunes.apple.com/search"
TVMAZE = "https://api.tvmaze.com/search/shows"
TMDB = "https://api.themoviedb.org/3"
OMDB = "https://www.omdbapi.com/"

PROVIDERS = [
    {"id": "archive", "name": "Internet Archive", "kind": "片源 + 元数据", "key": False,
     "site": "archive.org", "note": "公版影片，多码率 MP4，可播可下"},
    {"id": "itunes", "name": "iTunes Search", "kind": "元数据 + 预告片", "key": False,
     "site": "itunes.apple.com", "note": "官方海报、简介、预告片 MP4"},
    {"id": "tvmaze", "name": "TVmaze", "kind": "剧集元数据", "key": False,
     "site": "tvmaze.com", "note": "剧集/季/集信息与剧照"},
    {"id": "wiki", "name": "Wikipedia", "kind": "简介 + 剧照", "key": False,
     "site": "wikipedia.org", "note": "中文条目摘要，适合补全剧情与海报"},
    {"id": "tmdb", "name": "TMDB", "kind": "全量元数据", "key": True,
     "site": "themoviedb.org", "note": "需在站点设置填入 v3 Key"},
    {"id": "omdb", "name": "OMDb", "kind": "评分/剧情", "key": True,
     "site": "omdbapi.com", "note": "需免费 Key，用于补全 IMDb 评分"},
]


def _strip_html(text: str | None) -> str:
    if not text:
        return ""
    if isinstance(text, list):
        text = " ".join(str(t) for t in text)
    text = re.sub(r"<br\s*/?>", "\n", str(text))
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def quality_for_height(height) -> str:
    try:
        h = int(height)
    except (TypeError, ValueError):
        return "SD"
    for limit, label in ((2160, "2160p"), (1440, "1440p"), (1080, "1080p"),
                         (720, "720p"), (576, "576p"), (480, "480p"),
                         (360, "360p"), (240, "240p")):
        if h >= limit:
            return label
    return "SD"


QUALITY_RANK = {"2160p": 100, "1440p": 90, "1080p": 80, "720p": 70,
                "576p": 60, "480p": 50, "360p": 40, "240p": 30, "SD": 10}


# --------------------------------------------------------------- archive.org
def archive_search(query: str, settings: dict, rows: int = 18) -> list[dict]:
    params = {
        "q": f'({query}) AND mediatype:(movies)',
        "fl[]": ["identifier", "title", "year", "downloads", "description"],
        "rows": str(rows),
        "page": "1",
        "output": "json",
        "sort[]": "downloads desc",
    }
    url = ARCHIVE_SEARCH + "?" + urllib.parse.urlencode(params, doseq=True)
    data = net.fetch_json(url, settings=settings, timeout=25)
    docs = (data.get("response") or {}).get("docs") or []
    items = []
    for doc in docs:
        ident = doc.get("identifier")
        if not ident:
            continue
        items.append({
            "provider": "archive",
            "uid": ident,
            "title": doc.get("title") or ident,
            "year": _year(doc.get("year")),
            "poster": ARCHIVE_IMG.format(ident=ident),
            "backdrop": "",
            "synopsis": _strip_html(doc.get("description"))[:600],
            "genres": [],
            "rating": None,
            "runtime": None,
            "type": "movie",
            "license": "公共领域 / 见源站声明",
            "sourceUrl": f"https://archive.org/details/{ident}",
            "files": [],
            "needsDetail": True,
        })
    return items


def _year(value):
    if isinstance(value, list):
        value = value[0] if value else None
    try:
        return int(str(value)[:4])
    except (TypeError, ValueError):
        return None


def archive_item(identifier: str, settings: dict) -> dict:
    meta = net.fetch_json(ARCHIVE_META.format(ident=urllib.parse.quote(identifier)),
                          settings=settings, timeout=25)
    md = meta.get("metadata") or {}
    files = []
    for f in meta.get("files") or []:
        name = f.get("name") or ""
        if not name.lower().endswith(".mp4"):
            continue
        height = f.get("height")
        width = f.get("width")
        try:
            height = int(height) if height else None
            width = int(width) if width else None
        except (TypeError, ValueError):
            height = width = None
        if not height:
            continue
        label = str(f.get("format") or "MP4")
        quality = quality_for_height(height)
        files.append({
            "quality": quality,
            "label": f"{quality.upper()} · {label}",
            "width": width,
            "height": height,
            "sizeBytes": int(f["size"]) if str(f.get("size", "")).isdigit() else None,
            "codec": "h264",
            "url": ARCHIVE_DL.format(ident=identifier, file=urllib.parse.quote(name)),
            "fileName": name,
        })
    # keep the best bitrate per quality bucket
    best: dict[str, dict] = {}
    for f in files:
        cur = best.get(f["quality"])
        if not cur or (f.get("sizeBytes") or 0) > (cur.get("sizeBytes") or 0):
            best[f["quality"]] = f
    files = sorted(best.values(), key=lambda x: -QUALITY_RANK.get(x["quality"], 0))
    year = _year(md.get("year") or md.get("date"))
    synopsis = _strip_html(md.get("description") or md.get("plot") or "")
    genres = md.get("subject") or []
    if isinstance(genres, str):
        genres = [g.strip() for g in re.split(r"[;,]", genres) if g.strip()]
    return {
        "provider": "archive",
        "uid": identifier,
        "title": (md.get("title") or identifier).strip(),
        "originalTitle": md.get("title") or "",
        "year": year,
        "poster": ARCHIVE_IMG.format(ident=identifier),
        "backdrop": "",
        "synopsis": synopsis[:1500],
        "genres": [g for g in genres if isinstance(g, str)][:6],
        "rating": None,
        "runtime": _runtime_minutes(md.get("runtime")),
        "director": md.get("director") if isinstance(md.get("director"), str) else "",
        "cast": [c.strip() for c in (md.get("cast") or "").split(",") if c.strip()][:8]
        if isinstance(md.get("cast"), str) else [],
        "type": "movie",
        "license": md.get("licenseurl") or "公共领域 / 见源站声明",
        "sourceUrl": f"https://archive.org/details/{identifier}",
        "files": files,
        "needsDetail": False,
    }


def _runtime_minutes(value):
    try:
        seconds = float(value)
        return int(round(seconds / 60)) or None
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------- itunes
def itunes_search(query: str, settings: dict, rows: int = 18) -> list[dict]:
    params = {"term": query, "media": "all", "limit": str(max(rows, 20)),
              "country": "US", "lang": "en_us"}
    url = ITUNES + "?" + urllib.parse.urlencode(params)
    data = net.fetch_json(url, settings=settings, timeout=20)
    out = []
    for r in data.get("results") or []:
        kind = str(r.get("kind") or r.get("wrapperType") or "")
        if "movie" not in kind:
            continue
        art = (r.get("artworkUrl100") or "").replace("100x100bb", "600x900bb")
        files = []
        if r.get("previewUrl"):
            files.append({
                "quality": "预告",
                "label": "官方预告片 · MP4",
                "width": 640, "height": 360,
                "sizeBytes": None, "codec": "h264",
                "url": r["previewUrl"], "fileName": "trailer.m4v",
            })
        out.append({
            "provider": "itunes",
            "uid": str(r.get("trackId") or ""),
            "title": r.get("trackName") or "",
            "originalTitle": r.get("trackCensoredName") or "",
            "year": _year(r.get("releaseDate")),
            "poster": art,
            "backdrop": art,
            "synopsis": _strip_html(r.get("longDescription") or r.get("shortDescription")),
            "genres": [r.get("primaryGenreName")] if r.get("primaryGenreName") else [],
            "rating": None,
            "runtime": int(round((r.get("trackTimeMillis") or 0) / 60000)) or None,
            "director": r.get("artistName") or "",
            "cast": [],
            "type": "movie",
            "license": "Apple iTunes 元数据，预告片版权归发行方",
            "sourceUrl": r.get("trackViewUrl") or "",
            "files": files,
            "needsDetail": False,
        })
    return out


# --------------------------------------------------------------------- tvmaze
def tvmaze_search(query: str, settings: dict, rows: int = 18) -> list[dict]:
    url = TVMAZE + "?" + urllib.parse.urlencode({"q": query})
    data = net.fetch_json(url, settings=settings, timeout=20)
    out = []
    for row in (data or [])[:rows]:
        show = row.get("show") or {}
        image = (show.get("image") or {})
        out.append({
            "provider": "tvmaze",
            "uid": str(show.get("id") or ""),
            "title": show.get("name") or "",
            "originalTitle": show.get("name") or "",
            "year": _year(show.get("premiered")),
            "poster": image.get("original") or image.get("medium") or "",
            "backdrop": "",
            "synopsis": _strip_html(show.get("summary")),
            "genres": show.get("genres") or [],
            "rating": (show.get("rating") or {}).get("average"),
            "runtime": show.get("averageRuntime") or show.get("runtime"),
            "director": "",
            "cast": [],
            "type": "series",
            "license": "TVmaze 元数据 (CC BY-SA)",
            "sourceUrl": show.get("url") or "",
            "files": [],
            "needsDetail": False,
        })
    return out


# ----------------------------------------------------------------------- tmdb
def tmdb_search(query: str, settings: dict, rows: int = 18) -> list[dict]:
    key = (settings.get("tmdbKey") or "").strip()
    if not key:
        raise IOError("未配置 TMDB API Key")
    params = {"api_key": key, "query": query, "language": "zh-CN", "include_adult": "false"}
    data = net.fetch_json(TMDB + "/search/movie?" + urllib.parse.urlencode(params),
                          settings=settings, timeout=20)
    out = []
    for r in (data.get("results") or [])[:rows]:
        poster = f"https://image.tmdb.org/t/p/w780{r['poster_path']}" if r.get("poster_path") else ""
        backdrop = f"https://image.tmdb.org/t/p/original{r['backdrop_path']}" if r.get("backdrop_path") else ""
        out.append({
            "provider": "tmdb",
            "uid": str(r.get("id") or ""),
            "title": r.get("title") or r.get("original_title") or "",
            "originalTitle": r.get("original_title") or "",
            "year": _year(r.get("release_date")),
            "poster": poster,
            "backdrop": backdrop,
            "synopsis": r.get("overview") or "",
            "genres": [],
            "rating": round(r["vote_average"], 1) if r.get("vote_average") else None,
            "runtime": None,
            "director": "",
            "cast": [],
            "type": "movie",
            "license": "TMDB 元数据（需署名）",
            "sourceUrl": f"https://www.themoviedb.org/movie/{r.get('id')}",
            "files": [],
            "needsDetail": True,
        })
    return out


def tmdb_detail(tmdb_id: str, settings: dict) -> dict:
    key = (settings.get("tmdbKey") or "").strip()
    if not key:
        raise IOError("未配置 TMDB API Key")
    url = (f"{TMDB}/movie/{urllib.parse.quote(str(tmdb_id))}?api_key={key}"
           f"&language=zh-CN&append_to_response=credits")
    d = net.fetch_json(url, settings=settings, timeout=20)
    return {
        "title": d.get("title") or "",
        "originalTitle": d.get("original_title") or "",
        "year": _year(d.get("release_date")),
        "poster": f"https://image.tmdb.org/t/p/w780{d['poster_path']}" if d.get("poster_path") else "",
        "backdrop": f"https://image.tmdb.org/t/p/original{d['backdrop_path']}" if d.get("backdrop_path") else "",
        "synopsis": d.get("overview") or "",
        "genres": [g.get("name") for g in d.get("genres") or [] if g.get("name")],
        "rating": round(d["vote_average"], 1) if d.get("vote_average") else None,
        "runtime": d.get("runtime"),
        "director": ", ".join(c["name"] for c in (d.get("credits") or {}).get("crew", [])
                              if c.get("job") == "Director"),
        "cast": [c["name"] for c in (d.get("credits") or {}).get("cast", [])[:8]],
    }


# ----------------------------------------------------------------------- omdb
def omdb_lookup(title: str, year, settings: dict) -> dict:
    key = (settings.get("omdbKey") or "").strip()
    if not key:
        raise IOError("未配置 OMDb API Key")
    params = {"apikey": key, "t": title, "plot": "full"}
    if year:
        params["y"] = str(year)
    data = net.fetch_json(OMDB + "?" + urllib.parse.urlencode(params), settings=settings, timeout=20)
    if data.get("Response") == "False":
        raise IOError(data.get("Error") or "OMDb 未找到")
    return {
        "title": data.get("Title") or title,
        "year": _year(data.get("Year")),
        "poster": data.get("Poster") if data.get("Poster") not in (None, "N/A") else "",
        "synopsis": data.get("Plot") if data.get("Plot") != "N/A" else "",
        "genres": [g.strip() for g in (data.get("Genre") or "").split(",") if g.strip()],
        "rating": float(data["imdbRating"]) if data.get("imdbRating") not in (None, "N/A") else None,
        "runtime": int(re.sub(r"\D", "", data.get("Runtime") or "") or 0) or None,
        "director": data.get("Director") if data.get("Director") != "N/A" else "",
        "cast": [c.strip() for c in (data.get("Actors") or "").split(",") if c.strip()],
    }


# ------------------------------------------------------------------ wikipedia
WIKI_SUMMARY = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"
WIKI_SEARCH = ("https://{lang}.wikipedia.org/w/api.php?action=query&list=search"
               "&srsearch={q}&format=json&srlimit=8")


def wikipedia_search(query: str, settings: dict, lang: str = "zh") -> list[dict]:
    """Free metadata source: Wikipedia summary + poster thumbnail."""
    from concurrent.futures import ThreadPoolExecutor

    url = WIKI_SEARCH.format(lang=lang, q=urllib.parse.quote(query))
    data = net.fetch_json(url, settings=settings, timeout=20)
    titles = [x["title"] for x in (data.get("query") or {}).get("search") or []][:4]
    if not titles:
        return []

    def one(title):
        try:
            return wikipedia_summary(title, settings, lang)
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        return [d for d in pool.map(one, titles) if d]


def wikipedia_summary(title: str, settings: dict, lang: str = "zh") -> dict | None:
    url = WIKI_SUMMARY.format(lang=lang, title=urllib.parse.quote(title.replace(" ", "_")))
    d = net.fetch_json(url, settings=settings, timeout=20)
    if not d.get("extract"):
        return None
    thumb = ((d.get("originalimage") or {}).get("source")
             or (d.get("thumbnail") or {}).get("source") or "")
    return {
        "provider": "wiki",
        "uid": title,
        "title": d.get("title") or title,
        "originalTitle": (d.get("titles") or {}).get("normalized") or "",
        "year": _year_from_text(d.get("extract") or ""),
        "poster": thumb,
        "backdrop": thumb,
        "synopsis": d.get("extract") or "",
        "genres": ["维基百科条目"],
        "rating": None,
        "runtime": None,
        "director": "",
        "cast": [],
        "type": "movie",
        "license": "维基百科 (CC BY-SA)",
        "sourceUrl": (d.get("content_urls") or {}).get("desktop", {}).get("page", ""),
        "files": [],
        "needsDetail": False,
    }


def _year_from_text(text: str):
    import re as _re
    m = _re.search(r"(\d{4})\s*年", text or "")
    return int(m.group(1)) if m else None


# ------------------------------------------------------------------ dispatch
def search(provider: str, query: str, settings: dict) -> list[dict]:
    query = (query or "").strip()
    if not query:
        return []
    if provider == "archive":
        return archive_search(query, settings)
    if provider == "itunes":
        return itunes_search(query, settings)
    if provider == "tvmaze":
        return tvmaze_search(query, settings)
    if provider == "tmdb":
        return tmdb_search(query, settings)
    if provider == "wiki":
        return wikipedia_search(query, settings)
    if provider == "omdb":
        d = omdb_lookup(query, None, settings)
        return [{"provider": "omdb", "uid": query, "title": d["title"], "year": d.get("year"),
                 "poster": d.get("poster"), "backdrop": "", "synopsis": d.get("synopsis"),
                 "genres": d.get("genres"), "rating": d.get("rating"),
                 "runtime": d.get("runtime"), "type": "movie", "files": [],
                 "needsDetail": False, "sourceUrl": ""}]
    raise IOError("未知供应商")
