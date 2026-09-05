#!/usr/bin/env bash
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
APP_ROOT="$(cd "$ROOT/.." && pwd)"
PY="$APP_ROOT/.venv/bin/python"

[ -x "$PY" ] || exit 0
[ -f "$ROOT/server.py" ] || exit 0

if curl -fsS http://127.0.0.1:8189/health >/dev/null 2>&1; then
  exit 0
fi

cd "$ROOT"
APEX_SD_CLI="$ROOT/stable-diffusion.cpp/build/bin/sd-cli" \
APEX_IMAGE_MODEL="$ROOT/models/dreamshaper-7-lcm-q4_0.gguf" \
nohup "$PY" -m uvicorn server:app --host 127.0.0.1 --port 8189 \
  >/tmp/apex-dreamshaper-image.log 2>&1 &
