#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
APP_ROOT="$(cd "$ROOT/.." && pwd)"
PY="$APP_ROOT/.venv/bin/python"
MODEL="$ROOT/models/dreamshaper-7-lcm-q4_0.gguf"
LOG="/tmp/apex-dreamshaper-image.log"

[ -x "$PY" ] || exit 0
[ -f "$ROOT/server.py" ] || exit 0

SD_CLI=""
if [ -s "$ROOT/.sd-cli-path" ]; then
  SD_CLI="$(cat "$ROOT/.sd-cli-path")"
fi
if [ -z "$SD_CLI" ] || [ ! -x "$SD_CLI" ]; then
  SD_CLI="$(find "$ROOT" -type f -path '*/bin/sd-cli' -perm -u+x 2>/dev/null | head -n 1 || true)"
fi

if curl -fsS http://127.0.0.1:8189/health >/tmp/apex-image-health.json 2>/dev/null; then
  READY="$("$PY" - <<'PY'
import json
try:
    d=json.load(open("/tmp/apex-image-health.json"))
    print("1" if d.get("status")=="ok" and d.get("binary_present") and d.get("model_present") else "0")
except Exception:
    print("0")
PY
)"
  [ "$READY" = "1" ] && exit 0
fi

# Stop only an old Apex image-server process, never Ollama.
if command -v fuser >/dev/null 2>&1; then
  for pid in $(fuser 8189/tcp 2>/dev/null || true); do
    cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
    cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
    if [[ "$cmd" == *"uvicorn"*"server:app"* ]] && [[ "$cwd" == "$ROOT"* ]]; then
      kill "$pid" 2>/dev/null || true
      sleep 1
    fi
  done
fi

if [ ! -x "$SD_CLI" ] || [ ! -s "$MODEL" ]; then
  echo "DreamShaper components missing. Run ./repair-image-engine.sh" >> "$LOG"
  exit 0
fi

cd "$ROOT"
APEX_SD_CLI="$SD_CLI" \
APEX_IMAGE_MODEL="$MODEL" \
nohup "$PY" -m uvicorn server:app --host 127.0.0.1 --port 8189 >"$LOG" 2>&1 &
echo $! >/tmp/apex-dreamshaper-image.pid
