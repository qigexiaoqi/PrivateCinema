#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
echo "CINEBOX  →  http://127.0.0.1:${CINEBOX_PORT:-8426}"
exec python3 app.py
