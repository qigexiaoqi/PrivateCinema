"""Password hashing, session tokens and cookie helpers (stdlib only)."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time

SESSION_COOKIE = "cb_session"
CSRF_COOKIE = "cb_csrf"
SESSION_TTL = 7 * 24 * 3600

_SCRYPT = dict(n=2 ** 14, r=8, p=1, dklen=32)


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or os.urandom(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)
    return salt.hex(), dk.hex()


def verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    try:
        dk = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex), **_SCRYPT)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk.hex(), hash_hex)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def new_csrf() -> str:
    return secrets.token_urlsafe(24)


def ensure_admin(store) -> None:
    """Seed the built-in administrator once.  Credentials never reach the web UI."""
    with store.lock:
        if any(u.get("role") == "admin" for u in store.data["users"]):
            return
        salt, digest = hash_password("admin")
        store.data["users"].append({
            "id": "u_admin",
            "username": "admin",
            "displayName": "管理员",
            "role": "admin",
            "status": "active",
            "salt": salt,
            "hash": digest,
            "createdAt": int(time.time()),
            "lastLoginAt": None,
        })
        store.save()


def purge_expired_sessions(store) -> None:
    cutoff = time.time() - SESSION_TTL
    with store.lock:
        sessions = store.data.get("sessions", {})
        dead = [k for k, v in sessions.items() if v.get("createdAt", 0) < cutoff]
        for k in dead:
            sessions.pop(k, None)
        if dead:
            store.save()


def create_session(store, user: dict, ua: str, ip: str) -> str:
    token = new_token()
    with store.lock:
        store.data.setdefault("sessions", {})[token] = {
            "userId": user["id"],
            "createdAt": int(time.time()),
            "ua": (ua or "")[:160],
            "ip": ip,
        }
        user["lastLoginAt"] = int(time.time())
        store.save()
    return token


def session_user(store, token: str | None):
    if not token:
        return None
    sess = store.data.get("sessions", {}).get(token)
    if not sess:
        return None
    if sess.get("createdAt", 0) < time.time() - SESSION_TTL:
        with store.lock:
            store.data.get("sessions", {}).pop(token, None)
            store.save()
        return None
    user = store.user_by_id(sess["userId"])
    if not user or user.get("status") != "active":
        return None
    return user
