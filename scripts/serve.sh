#!/usr/bin/env bash
# Start the local backend and expose it over https via a Cloudflare quick tunnel.
# The printed trycloudflare.com URL is what you open in Chrome on the phone.
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${PORT:-8000}"

uv run uvicorn floorplan_takehome.server:app --host 127.0.0.1 --port "$PORT" --reload --reload-dir src &
UVICORN_PID=$!
trap 'kill $UVICORN_PID 2>/dev/null || true' EXIT

for _ in $(seq 1 30); do
  curl -sf "http://127.0.0.1:$PORT/health" >/dev/null && break
  sleep 0.5
done

cloudflared tunnel --url "http://127.0.0.1:$PORT" --no-autoupdate
