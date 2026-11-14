#!/usr/bin/env bash
# Start the dev server. Open http://<this-computer-ip>:8000 on your iPad (same Wi-Fi).
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { cp .env.example .env; echo "Created .env from .env.example (mock mode)."; }
command -v ffmpeg >/dev/null || echo "WARNING: ffmpeg not found — install it (brew install ffmpeg / apt install ffmpeg)."
HOST="${APP_HOST:-0.0.0.0}"; PORT="${APP_PORT:-8000}"
exec python -m uvicorn app.main:app --host "$HOST" --port "$PORT" --reload
