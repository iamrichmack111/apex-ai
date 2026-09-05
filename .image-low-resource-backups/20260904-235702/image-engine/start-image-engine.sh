#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
LOG="/tmp/apex-quality-image.log"

PY=""
if [ -s "$ROOT/.quality-python" ]; then
  PY="$(cat "$ROOT/.quality-python")"
fi

if [ -z "$PY" ] || [ ! -x "$PY" ]; then
  exit 0
fi

MODEL="$ROOT/models/dreamshaper7/DreamShaper_7_pruned.safetensors"
LORA="$ROOT/models/dreamshaper7/pytorch_lora_weights.safetensors"

# Already healthy?
if curl -fsS http://127.0.0.1:8189/health >/tmp/apex-quality-health.json 2>/dev/null; then
  if grep -q '"engine":"dreamshaper7-lcm-diffusers"' /tmp/apex-quality-health.json || \
     grep -q '"engine": "dreamshaper7-lcm-diffusers"' /tmp/apex-quality-health.json; then
    exit 0
  fi
fi

# Stop ONLY the previous Apex image uvicorn on port 8189.
if command -v fuser >/dev/null 2>&1; then
  for pid in $(fuser 8189/tcp 2>/dev/null || true); do
    cmd="$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true)"
    cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
    if [[ "$cmd" == *"uvicorn"*"server:app"* ]] && [[ "$cwd" == *"image-engine"* ]]; then
      kill "$pid" 2>/dev/null || true
      sleep 1
    fi
  done
fi

cd "$ROOT"
APEX_DREAMSHAPER_MODEL="$MODEL" \
APEX_LCM_LORA="$LORA" \
nohup "$PY" -m uvicorn server:app --host 127.0.0.1 --port 8189 >"$LOG" 2>&1 &
echo $! >/tmp/apex-quality-image.pid
