"""ffmpeg helpers: probe, HLS ladder generation, software-decode rendition."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"
_LOCK = threading.Lock()


def available() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def probe(path: str) -> dict:
    if not available() or not os.path.isfile(path):
        return {}
    try:
        out = subprocess.run(
            [FFPROBE, "-v", "error", "-print_format", "json", "-show_format",
             "-show_streams", path],
            capture_output=True, text=True, timeout=40,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if out.returncode != 0:
            return {}
        data = json.loads(out.stdout or "{}")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return {}
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})
    fmt = data.get("format") or {}
    return {
        "width": video.get("width"),
        "height": video.get("height"),
        "codec": video.get("codec_name"),
        "fps": _fps(video.get("avg_frame_rate")),
        "audio": audio.get("codec_name"),
        "duration": float(fmt.get("duration") or video.get("duration") or 0) or None,
        "bitrate": int(fmt.get("bit_rate") or 0) or None,
        "sizeBytes": int(fmt.get("size") or 0) or None,
    }


def _fps(rate) -> float | None:
    try:
        num, den = str(rate).split("/")
        return round(float(num) / float(den), 2) if float(den) else None
    except (ValueError, ZeroDivisionError):
        return None


def _run(args: list[str], timeout: int = 900) -> tuple[int, str]:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return proc.returncode, (proc.stderr or "")[-1500:]
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)


def make_soft_rendition(src: str, dst: str, max_seconds: int = 1800, crf: int = 26) -> bool:
    """Baseline H.264 twin used by the player's software-decode mode."""
    info = probe(src)
    if info.get("duration") and info["duration"] > max_seconds:
        return False
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with _LOCK:
        code, _log = _run([
            FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", src,
            "-map", "0:v:0", "-map", "0:a:0?",
            "-c:v", "libx264", "-profile:v", "baseline", "-level", "3.1",
            "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", dst,
        ], timeout=1800)
    return code == 0 and os.path.isfile(dst)


def build_hls(src: str, outdir: str, heights=(1080, 720, 480), crf: int = 23,
              preset: str = "veryfast", gpu: dict | None = None) -> dict:
    """Generate a multi-bitrate HLS ladder + master playlist."""
    info = probe(src)
    source_h = int(info.get("height") or 1080)
    ladder = [h for h in heights if h <= source_h] or [min(heights)]
    os.makedirs(outdir, exist_ok=True)
    master = ["#EXTM3U", "#EXT-X-VERSION:3"]
    made = []
    for h in ladder:
        width = int(round(h * 16 / 9 / 2) * 2)
        sub = f"{h}p"
        subdir = os.path.join(outdir, sub)
        os.makedirs(subdir, exist_ok=True)
        base_args = [
            FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", src,
            "-vf", f"scale=-2:{h}:force_original_aspect_ratio=decrease,pad=ceil(iw/2)*2:ceil(ih/2)*2",
        ]
        tail = [
            "-maxrate", f"{max(600, h*2)}k", "-bufsize", f"{max(1200, h*4)}k",
            "-g", "48", "-keyint_min", "48", "-sc_threshold", "0",
            "-c:a", "aac", "-b:a", "128k", "-ac", "2",
            "-f", "hls", "-hls_time", "4", "-hls_playlist_type", "vod",
            "-hls_segment_filename", os.path.join(subdir, "seg%04d.ts"),
            os.path.join(subdir, "index.m3u8"),
        ]
        code, log = _run(base_args + _codec_args(gpu, preset, crf) + tail, timeout=3600)
        if code != 0 and gpu:
            # GPU encoder refused this input -> try CPU (when the admin allows it)
            if gpu.get("fallback", True):
                code, log = _run(base_args + _codec_args(None, preset, crf) + tail, timeout=3600)
        if code != 0:
            continue
        bandwidth = max(800000, h * 4500)
        master.append(f"#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},RESOLUTION={width}x{h},"
                      f"NAME=\"{h}p\"")
        master.append(f"{sub}/index.m3u8")
        made.append({"height": h, "width": width, "path": f"{sub}/index.m3u8",
                     "bandwidth": bandwidth})
    if not made:
        return {"ok": False, "variants": []}
    with open(os.path.join(outdir, "master.m3u8"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(master) + "\n")
    return {"ok": True, "variants": made}

_GPU_CACHE = {"at": 0, "options": []}


def gpu_options(force: bool = False) -> list[dict]:
    """Detected hardware H.264 encoders (NVENC / QSV / AMF / VideoToolbox)."""
    import time

    if not force and _GPU_CACHE["options"] and time.time() - _GPU_CACHE["at"] < 300:
        return _GPU_CACHE["options"]
    opts: list[dict] = []
    if available():
        try:
            out = subprocess.run([FFMPEG, "-hide_banner", "-encoders"], capture_output=True,
                                 text=True, timeout=20,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            text = out.stdout or ""
            if "h264_nvenc" in text:
                opts.append({"id": "nvenc", "name": "NVIDIA NVENC", "encoder": "h264_nvenc"})
            if "h264_qsv" in text:
                opts.append({"id": "qsv", "name": "Intel Quick Sync (QSV)", "encoder": "h264_qsv"})
            if "h264_amf" in text:
                opts.append({"id": "amf", "name": "AMD AMF", "encoder": "h264_amf"})
            if "h264_videotoolbox" in text:
                opts.append({"id": "videotoolbox", "name": "Apple VideoToolbox",
                             "encoder": "h264_videotoolbox"})
        except (OSError, subprocess.SubprocessError):
            pass
    _GPU_CACHE.update({"at": time.time(), "options": opts})
    return opts


def _codec_args(gpu: dict | None, preset: str, crf: int) -> list[str]:
    if not gpu:
        return ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p"]
    enc = gpu.get("encoder") or ""
    if enc == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", str(crf),
                "-b:v", "0", "-pix_fmt", "yuv420p"]
    if enc == "h264_qsv":
        return ["-c:v", "h264_qsv", "-global_quality", str(crf), "-pix_fmt", "nv12"]
    if enc == "h264_amf":
        return ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "cqp",
                "-qp_i", str(crf), "-qp_p", str(crf), "-pix_fmt", "yuv420p"]
    if enc == "h264_videotoolbox":
        return ["-c:v", "h264_videotoolbox", "-q:v", str(max(20, 100 - crf * 2)),
                "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p"]
