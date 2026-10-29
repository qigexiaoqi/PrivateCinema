"""JSON document store with atomic writes and a process-wide lock.

The whole site state lives in data/db.json.  It is small (catalog + users +
playlists), so a single locked dict is both simple and fast.  Writes go
through a temp file + os.replace so a crash never leaves a half-written db.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid

from .source_defaults import DEFAULT_SOURCES


def new_id(prefix: str = "id") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def now_ts() -> int:
    return int(time.time())


DEFAULT_SETTINGS = {
    "siteName": "XX的影院",
    "tagline": "私人影库 · 自托管放映厅",
    "announcement": "欢迎回到放映厅。登录后可播放、下载与管理你的片库。",
    "allowSignup": True,
    "allowGuestSearch": True,
    "publicRegistrationRole": "user",
    "proxyUrl": "http://127.0.0.1:7897",
    "proxyEnabled": False,
    "tmdbKey": "",
    "omdbKey": "",
    "defaultDecoding": "auto",
    "transcodeEnabled": True,
    "hlsHeights": "1080,720,480",
    "hlsCrf": 23,
    "hlsPreset": "veryfast",
    "softCrf": 26,
    "softMaxMinutes": 30,
    "gpuTranscodeEnabled": False,
    "gpuDevice": "auto",
    "gpuAutoFallback": True,
    "downloadExtrasDefault": ["poster", "nfo", "json", "readme"],
    "maxUploadMb": 4096,
    "maintenance": False,
    "themeAccent": "#48d6c8",
}

DEFAULT_DB = {
    "version": 1,
    "createdAt": now_ts(),
    "settings": dict(DEFAULT_SETTINGS),
    "users": [],
    "movies": [],
    "sessions": {},
    "playlists": {},
    "history": {},
    "downloads": {},
    "providerCache": {},
    "sources": [],
    "audit": [],
    "stats": {"startedAt": now_ts(), "plays": 0, "downloads": 0, "searches": 0},
}


def _migrate_sources(existing: list) -> list:
    """Seed defaults once; afterwards the admin's list (including deletions) wins."""
    by_id = {s.get("id"): s for s in existing if isinstance(s, dict) and s.get("id")}
    out = []
    for default in DEFAULT_SOURCES:
        cur = by_id.pop(default["id"], None)
        out.append({**json.loads(json.dumps(default)), **(cur or {})})
    out.extend(by_id.values())
    return out


class Store:
    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        self.lock = threading.RLock()
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.data = self._load()
    # ------------------------------------------------------------------ io
    def _load(self) -> dict:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    base = json.loads(json.dumps(DEFAULT_DB))
                    base.update(data)
                    base["settings"] = {**DEFAULT_SETTINGS, **data.get("settings", {})}
                    if data.get("sourcesInitialized"):
                        base["sources"] = data.get("sources") or []
                    else:
                        base["sources"] = _migrate_sources(data.get("sources") or [])
                        base["sourcesInitialized"] = True
                    return base
            except Exception as exc:  # corrupted db -> keep a copy, start clean
                print(f"[store] failed to read db ({exc}); starting fresh")
                try:
                    os.replace(self.path, self.path + f".broken.{now_ts()}")
                except OSError:
                    pass
        fresh = json.loads(json.dumps(DEFAULT_DB))
        fresh["sources"] = _migrate_sources([])
        fresh["sourcesInitialized"] = True
        return fresh

    def save(self) -> None:
        with self.lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, ensure_ascii=False, separators=(",", ":"))
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)

    # --------------------------------------------------------------- access
    def tx(self, fn):
        """Run fn(data) under the write lock, then persist."""
        with self.lock:
            result = fn(self.data)
            self.save()
            return result

    def audit(self, user: str, action: str, detail: str = "") -> None:
        with self.lock:
            entry = {"at": now_ts(), "user": user, "action": action, "detail": detail[:400]}
            self.data.setdefault("audit", []).insert(0, entry)
            del self.data["audit"][400:]

    # ------------------------------------------------------------ settings
    @property
    def settings(self) -> dict:
        return self.data["settings"]

    def public_settings(self) -> dict:
        s = self.settings
        return {
            "siteName": s.get("siteName"),
            "tagline": s.get("tagline"),
            "announcement": s.get("announcement"),
            "allowSignup": s.get("allowSignup", False),
            "allowGuestSearch": s.get("allowGuestSearch", True),
            "defaultDecoding": s.get("defaultDecoding", "auto"),
            "downloadExtrasDefault": s.get("downloadExtrasDefault", []),
            "maintenance": s.get("maintenance", False),
            "themeAccent": s.get("themeAccent", "#48d6c8"),
        }

    # --------------------------------------------------------------- users
    def find_user(self, **kw):
        for u in self.data["users"]:
            if all(u.get(k) == v for k, v in kw.items()):
                return u
        return None

    def user_by_id(self, uid: str):
        return self.find_user(id=uid)

    # -------------------------------------------------------------- movies
    def movie(self, mid: str):
        for m in self.data["movies"]:
            if m["id"] == mid:
                return m
        return None

    def published(self):
        return [m for m in self.data["movies"] if m.get("status", "published") == "published"]
