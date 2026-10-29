"""Reset transient site state (keep films, users and settings).

Used before shipping/sharing the instance: removes test playlists, watch
history, download records, sessions, audit log and counters.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from cinelib.store import Store, now_ts  # noqa: E402


def main():
    store = Store(os.path.join(ROOT, "data", "db.json"))
    keep_users = [u for u in store.data["users"] if u.get("username") == "admin"]
    with store.lock:
        store.data["users"] = keep_users or store.data["users"]
        store.data["sessions"] = {}
        store.data["playlists"] = {}
        store.data["history"] = {}
        store.data["downloads"] = {}
        store.data["audit"] = []
        store.data["stats"] = {"startedAt": now_ts(), "plays": 0, "downloads": 0, "searches": 0}
        for m in store.data["movies"]:
            m["views"] = 0
        store.save()
    print(f"reset ok · movies={len(store.data['movies'])} users={len(store.data['users'])}")


if __name__ == "__main__":
    main()
