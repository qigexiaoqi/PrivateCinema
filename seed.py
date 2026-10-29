#!/usr/bin/env python3
"""Seed the library: generated demo films (local, multi-quality, HLS) plus
public-domain features imported from Internet Archive with real bitrates.

    python seed.py             # demo clips + archive.org imports
    python seed.py --local     # demo clips only (offline)
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from cinelib import media, net, providers  # noqa: E402
from cinelib.store import Store, new_id, now_ts  # noqa: E402

MEDIA = os.path.join(ROOT, "media")
DATA = os.path.join(ROOT, "data")
STORE = Store(os.path.join(DATA, "db.json"))

COLORS_A = ("0x061222", "0x0d3b57", "0x4a1250", "0x0a1a2e")
COLORS_B = ("0x02131a", "0x0a4b4b", "0x123a63", "0x051018")


def run(args, timeout=1800) -> bool:
    proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if proc.returncode != 0:
        print("   ffmpeg failed:", (proc.stderr or "")[-400:])
    return proc.returncode == 0


def clip(src_desc, out, seconds, size, colors, freq=110):
    os.makedirs(os.path.dirname(out), exist_ok=True)
    colors_args = []
    for i, c in enumerate(colors):
        colors_args += [f"c{i}={c}"]
    vf = (f"gradients=s={size}:d={seconds}:r=25:speed=0.012:nb_colors={len(colors)}:"
          + ":".join(colors_args))
    return run([
        media.FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", vf,
        "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}",
        "-vf", "format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "27", "-profile:v", "high",
        "-c:a", "aac", "-b:a", "96k", "-af", "volume=0.12", "-shortest",
        "-movflags", "+faststart", out,
    ])


def downscale(src, out, height):
    width = int(round(height * 16 / 9 / 2) * 2)
    return run([media.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", src,
                "-vf", f"scale={width}:{height}:flags=lanczos", "-c:v", "libx264",
                "-preset", "veryfast", "-crf", "28", "-profile:v", "high",
                "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", out])


def poster(out, colors, size="600x900", seed=None):
    os.makedirs(os.path.dirname(out), exist_ok=True)
    colors_args = []
    for i, c in enumerate(colors):
        colors_args += [f"c{i}={c}"]
    vf = (f"gradients=s={size}:d=1:r=1:nb_colors={len(colors)}:"
          + ":".join(colors_args))
    return run([media.FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", vf, "-frames:v", "1", "-q:v", "3", out])


def add_movie(movie: dict) -> str:
    existing = next((m for m in STORE.data["movies"] if m["id"] == movie["id"]), None)
    if existing:
        return "skip"
    STORE.data["movies"].append(movie)
    STORE.save()
    return "added"


def local_file(mid, fid, quality, label, path, info, size, source_label="本地片源",
               hls: str | None = None):
    entry = {
        "id": fid, "quality": quality, "label": label,
        "width": info.get("width"), "height": info.get("height"),
        "codec": info.get("codec") or "h264", "fps": info.get("fps"),
        "duration": info.get("duration"), "sizeBytes": size,
        "sourceLabel": source_label,
        "watch": {"type": "hls" if hls else "local", "value": hls or path},
        "download": {"enabled": True, "type": "local", "value": path},
    }
    return entry


def make_demo(mid: str, title: str, year: int, colors, seconds: int, freq: int,
              genres, rating, synopsis, director, cast, featured, make_hls=False,
              tags=None):
    base = f"local/{mid}"
    os.makedirs(os.path.join(MEDIA, "local", mid), exist_ok=True)
    master = os.path.join(MEDIA, "local", mid, f"{mid}_master.mp4")
    print(f"[demo] {title}: 生成母版 {seconds}s …", flush=True)
    if not clip(None, master, seconds, "1920x1080", colors, freq):
        return None
    master_info = media.probe(master)
    files = []
    ladder = [(1080, "1080p", "1080P · 演示母版"), (720, "720p", "720P · 均衡"),
              (480, "480p", "480P · 省流")]
    for height, quality, label in ladder:
        fid = f"f_{mid.split('_')[-1]}_{height}"
        out = os.path.join(MEDIA, "local", mid, f"{fid}.mp4")
        if height == 1080:
            os.replace(master, out)
        else:
            if not downscale(out_master := os.path.join(MEDIA, "local", mid,
                                                        f"f_{mid.split('_')[-1]}_1080.mp4"), out, height):
                continue
        info = media.probe(out) or master_info
        info.setdefault("duration", seconds)
        files.append(local_file(mid, fid, quality, label, f"{base}/{fid}.mp4", info,
                                os.path.getsize(out), hls=None))
    if not files:
        return None
    # software-decode rendition of the 720p file
    soft_src = os.path.join(MEDIA, "local", mid, f"f_{mid.split('_')[-1]}_720.mp4")
    soft_out = os.path.join(MEDIA, "soft", mid, f"f_{mid.split('_')[-1]}_720.mp4")
    if os.path.isfile(soft_src):
        print("[demo] 生成软解基准档 …", flush=True)
        media.make_soft_rendition(soft_src, soft_out)
    if make_hls:
        print("[demo] 生成 HLS 多码率阶梯 …", flush=True)
        hls_dir = os.path.join(MEDIA, "hls", mid, f"f_{mid.split('_')[-1]}_1080")
        result = media.build_hls(os.path.join(MEDIA, "local", mid,
                                              f"f_{mid.split('_')[-1]}_1080.mp4"), hls_dir)
        if result.get("ok"):
            for f in files:
                if f["quality"] == "1080p":
                    f["watch"] = {"type": "hls",
                                  "value": f"hls/{mid}/{f['id']}/master.m3u8"}
                    f["hlsVariants"] = result["variants"]
    poster_path = os.path.join(MEDIA, "assets", "posters", f"{mid}.jpg")
    poster(poster_path, colors)
    movie = {
        "id": mid, "title": title, "originalTitle": title,
        "year": year, "genres": genres, "tags": tags or [],
        "rating": rating, "runtime": round(seconds / 60) or 1,
        "country": "中国", "language": "汉语",
        "director": director, "cast": cast,
        "synopsis": synopsis,
        "poster": f"/media/assets/posters/{mid}.jpg",
        "backdrop": "", "featured": featured, "status": "published", "views": 0,
        "source": {"provider": "local", "uid": mid, "license": "演示样片，可自由使用",
                   "url": ""},
        "files": files,
        "subtitles": [{"id": "s_zh", "lang": "zh", "label": "简体中文",
                       "url": "", "value": f"assets/subs/{mid}.zh.srt"}],
        "createdAt": now_ts(), "updatedAt": now_ts(),
    }
    sub_path = os.path.join(MEDIA, "assets", "subs", f"{mid}.zh.srt")
    os.makedirs(os.path.dirname(sub_path), exist_ok=True)
    with open(sub_path, "w", encoding="utf-8") as fh:
        fh.write(f"""1
00:00:01,000 --> 00:00:06,000
{title}（{year}）— CineBox 演示样片

2
00:00:06,500 --> 00:00:13,000
本片由 ffmpeg 实时生成，用于验证多清晰度切换、
下载打包与本机解码模式。

3
00:00:14,000 --> 00:00:22,000
在播放器右下角可切换「硬解 / 软解 / 直读」，
下载页可勾选海报、NFO、字幕等元数据。

4
00:00:23,000 --> 00:00:30,000
真实影片请通过「后台 → 在线片源」从
Internet Archive / iTunes / TMDB 导入。

5
00:00:31,000 --> 00:00:40,000
祝你观影愉快。
""")
    return movie


def import_archive(identifiers):
    added = 0
    for ident in identifiers:
        print(f"[archive] 拉取元数据 {ident} …", flush=True)
        try:
            cand = providers.archive_item(ident, STORE.settings)
        except Exception as exc:  # noqa: BLE001
            print(f"   ! 跳过 {ident}: {exc}")
            continue
        if not cand.get("files"):
            print(f"   ! {ident} 没有可播放的 MP4 变体，跳过")
            continue
        mid = f"m_{ident.lower()[:18].replace('.', '_')}"
        files = []
        for raw in cand["files"][:5]:
            fid = new_id("f")
            files.append({
                "id": fid,
                "quality": raw["quality"],
                "label": raw.get("label") or raw["quality"],
                "width": raw.get("width"), "height": raw.get("height"),
                "codec": "h264",
                "sizeBytes": raw.get("sizeBytes"),
                "sourceLabel": "Internet Archive",
                "watch": {"type": "remote", "value": raw["url"]},
                "download": {"enabled": True, "type": "remote", "value": raw["url"]},
            })
        movie = {
            "id": mid,
            "title": cand["title"][:80],
            "originalTitle": (cand.get("originalTitle") or "")[:80],
            "year": cand.get("year"), "genres": cand.get("genres") or [],
            "tags": ["公版影片"], "rating": cand.get("rating"),
            "runtime": cand.get("runtime"),
            "country": "", "language": "英语",
            "director": cand.get("director") or "", "cast": cand.get("cast") or [],
            "synopsis": cand.get("synopsis") or "",
            "poster": cand.get("poster") or "", "backdrop": "",
            "featured": False, "status": "published", "views": 0,
            "source": {"provider": "archive", "uid": ident,
                       "license": cand.get("license") or "", "url": cand.get("sourceUrl") or ""},
            "files": files, "subtitles": [],
            "createdAt": now_ts(), "updatedAt": now_ts(),
        }
        if add_movie(movie) == "added":
            added += 1
            print(f"   + {movie['title']} [{', '.join(f['quality'] for f in files)}]")
    return added


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    offline = "--local" in sys.argv
    t0 = time.time()
    print("可用 ffmpeg:", media.available())
    demo1 = make_demo(
        "m_neon_echo", "霓虹回声", 2024, COLORS_A, 42, 110,
        ["科幻", "悬疑", "剧情"], 8.4,
        "雨夜的九龙，一名声音修复师在旧磁带里听见了三天后才会发生的一场爆炸。"
        "她循着杂音走进霓虹深处，发现整座城市正在被人重新混录。",
        "林知远", ["周砚", "陈以宁", "梁峻"], True, make_hls=True,
        tags=["赛博", "悬疑", "原创"],
    )
    demo2 = make_demo(
        "m_deep_sea_train", "深海列车", 2023, COLORS_B, 36, 82,
        ["剧情", "冒险"], 7.9,
        "一列永不停靠的深海列车载着最后一批乘客，穿过没有光亮的洋脊。"
        "当列车长宣布终点站取消，所有人必须决定：继续向前，还是打开舱门。",
        "苏黎", ["顾青", "罗岚", "辛野"], True,
        tags=["文艺", "公路"],
    )
    for movie in (demo1, demo2):
        if movie:
            status = add_movie(movie)
            print(f"[db] {movie['title']}: {status}")
    if not offline:
        added = import_archive([
            "Sita_Sings_the_Blues",
            "his_girl_friday",
            "house_on_haunted_hill_ipod",
            "charlie_chaplin_film_fest",
            "JungleBook",
        ])
        print(f"[archive] 新增 {added} 部")
    print(f"完成，用时 {time.time()-t0:.1f}s；片库共 {len(STORE.data['movies'])} 部")


if __name__ == "__main__":
    main()

