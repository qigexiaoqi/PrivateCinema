"""Auth routes: login / logout / me / register / password."""
from __future__ import annotations

import time

from . import auth


def public_user(u: dict) -> dict:
    return {
        "id": u["id"],
        "username": u.get("username"),
        "displayName": u.get("displayName") or u.get("username"),
        "role": u.get("role", "user"),
        "status": u.get("status", "active"),
        "createdAt": u.get("createdAt"),
        "lastLoginAt": u.get("lastLoginAt"),
        "avatarColor": u.get("avatarColor") or "#48d6c8",
    }


_FAILS: dict[str, list[float]] = {}
_WINDOW = 600
_MAX_FAILS = 8


def _rate_limited(ip: str) -> bool:
    now = time.time()
    hits = [t for t in _FAILS.get(ip, []) if now - t < _WINDOW]
    _FAILS[ip] = hits
    return len(hits) >= _MAX_FAILS


def _note_fail(ip: str) -> None:
    _FAILS.setdefault(ip, []).append(time.time())


def h_login(ctx):
    body = ctx.body_json()
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if not username or not password:
        return ctx.error("请输入账号与密码", 400, "missing_credentials")
    if _rate_limited(ctx.client_ip):
        return ctx.error("尝试次数过多，请 10 分钟后再试", 429, "rate_limited")
    user = ctx.store.find_user(username=username)
    if not user or not auth.verify_password(password, user.get("salt", ""), user.get("hash", "")):
        _note_fail(ctx.client_ip)
        ctx.store.audit(username, "login_failed", ctx.client_ip)
        return ctx.error("账号或密码不正确", 401, "bad_credentials")
    if user.get("status") != "active":
        return ctx.error("该账号已被停用", 403, "disabled")
    if ctx.settings.get("maintenance") and user.get("role") != "admin":
        return ctx.error("站点维护中，仅管理员可登录", 503, "maintenance")
    token = auth.create_session(ctx.store, user, ctx.handler.headers.get("User-Agent", ""),
                                ctx.client_ip)
    csrf = auth.new_csrf()
    ctx.extra_headers.append(("Set-Cookie", f"{auth.SESSION_COOKIE}={token}; Path=/; HttpOnly; "
                                            f"SameSite=Lax; Max-Age={auth.SESSION_TTL}"))
    ctx.extra_headers.append(("Set-Cookie", f"{auth.CSRF_COOKIE}={csrf}; Path=/; "
                                            f"SameSite=Lax; Max-Age={auth.SESSION_TTL}"))
    ctx.store.audit(user["username"], "login", ctx.client_ip)
    ctx.store.tx(lambda d: d["stats"].__setitem__("logins", d["stats"].get("logins", 0) + 1))
    ctx.json({"ok": True, "user": public_user(user), "csrf": csrf,
              "settings": ctx.store.public_settings()})


def h_logout(ctx):
    token = ctx.cookies.get(auth.SESSION_COOKIE)
    if token:
        ctx.store.tx(lambda d: d.get("sessions", {}).pop(token, None))
    ctx.extra_headers.append(("Set-Cookie", f"{auth.SESSION_COOKIE}=; Path=/; HttpOnly; "
                                            "SameSite=Lax; Max-Age=0"))
    ctx.json({"ok": True})


def h_me(ctx):
    ctx.json({
        "ok": True,
        "user": public_user(ctx.user) if ctx.user else None,
        "settings": ctx.store.public_settings(),
        "csrf": ctx.cookies.get(auth.CSRF_COOKIE) or "",
        "serverTime": int(time.time()),
    })


def h_register(ctx):
    if not ctx.settings.get("allowSignup"):
        return ctx.error("站点已关闭注册", 403, "signup_closed")
    body = ctx.body_json()
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    display = (body.get("displayName") or username).strip()[:24]
    if len(username) < 3 or len(username) > 20:
        return ctx.error("账号长度需为 3-20 位", 400, "bad_username")
    if len(password) < 6:
        return ctx.error("密码至少 6 位", 400, "bad_password")
    if not username.replace("_", "").replace("-", "").isalnum():
        return ctx.error("账号只能包含字母、数字、下划线与短横线", 400, "bad_username")
    if ctx.store.find_user(username=username):
        return ctx.error("该账号已存在", 409, "exists")
    salt, digest = auth.hash_password(password)
    user = {
        "id": f"u_{int(time.time()*1000)}_{username[:6]}",
        "username": username,
        "displayName": display or username,
        "role": "user",
        "status": "active",
        "salt": salt,
        "hash": digest,
        "createdAt": int(time.time()),
        "lastLoginAt": None,
        "avatarColor": "#7c9cff",
    }
    ctx.store.tx(lambda d: d["users"].append(user))
    ctx.store.audit(username, "register", ctx.client_ip)
    token = auth.create_session(ctx.store, user, ctx.handler.headers.get("User-Agent", ""),
                                ctx.client_ip)
    csrf = auth.new_csrf()
    ctx.extra_headers.append(("Set-Cookie", f"{auth.SESSION_COOKIE}={token}; Path=/; HttpOnly; "
                                            f"SameSite=Lax; Max-Age={auth.SESSION_TTL}"))
    ctx.extra_headers.append(("Set-Cookie", f"{auth.CSRF_COOKIE}={csrf}; Path=/; "
                                            f"SameSite=Lax; Max-Age={auth.SESSION_TTL}"))
    ctx.json({"ok": True, "user": public_user(user), "csrf": csrf,
              "settings": ctx.store.public_settings()})


def h_update_me(ctx):
    body = ctx.body_json()
    def apply(db):
        user = next(u for u in db["users"] if u["id"] == ctx.user["id"])
        if body.get("displayName"):
            user["displayName"] = str(body["displayName"])[:24]
        if body.get("avatarColor"):
            user["avatarColor"] = str(body["avatarColor"])[:16]
        return public_user(user)
    user = ctx.store.tx(apply)
    ctx.json({"ok": True, "user": user})


def h_change_password(ctx):
    body = ctx.body_json()
    current = body.get("current") or ""
    nxt = body.get("next") or ""
    if len(nxt) < 6:
        return ctx.error("新密码至少 6 位", 400, "bad_password")
    if not auth.verify_password(current, ctx.user.get("salt", ""), ctx.user.get("hash", "")):
        return ctx.error("当前密码不正确", 403, "bad_password")
    salt, digest = auth.hash_password(nxt)
    def apply(db):
        user = next(u for u in db["users"] if u["id"] == ctx.user["id"])
        user["salt"], user["hash"] = salt, digest
        # invalidate other sessions of this user
        for tok, sess in list(db.get("sessions", {}).items()):
            if sess.get("userId") == user["id"] and tok != ctx.cookies.get(auth.SESSION_COOKIE):
                db["sessions"].pop(tok, None)
    ctx.store.tx(apply)
    ctx.store.audit(ctx.user["username"], "password_changed")
    ctx.json({"ok": True})
