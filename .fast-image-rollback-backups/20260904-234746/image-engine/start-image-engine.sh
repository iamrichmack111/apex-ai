#!/usr/bin/env bash
set -u

ROOT="$(cd "$(dirname "$0")" && pwd)"
LOG="/tmp/apex-tiny-image.log"

# If the old Tiny-SD server is already healthy, keep using it.
if curl -fsS http://127.0.0.1:8189/health >/tmp/apex-tiny-health.json 2>/dev/null; then
  if grep -qi 'segmind/tiny-sd\|Apex Tiny' /tmp/apex-tiny-health.json; then
    exit 0
  fi
fi

# Search for the working Tiny-SD installation you already used before.
CANDIDATES=(
  "$ROOT"
  "$HOME/Downloads/apex-ai-v6/image-engine"
  "$HOME/Downloads/apex-ai-v5/image-engine"
  "$HOME/Downloads/richmack-chat-v4-lite-fast/image-engine"
  "$HOME/Downloads/richmack-chat-v4-lite/image-engine"
  "$HOME/Downloads/richmack-chat-v4/image-engine"
)

PY=""
MODEL=""

for DIR in "${CANDIDATES[@]}"; do
  [ -f "$DIR/models/tiny-sd/model_index.json" ] || continue

  for PYCAND in "$DIR/.venv/bin/python" "$ROOT/.venv/bin/python"; do
    [ -x "$PYCAND" ] || continue
    if "$PYCAND" -c 'import torch,diffusers,fastapi,uvicorn,PIL' >/dev/null 2>&1; then
      PY="$PYCAND"
      MODEL="$DIR/models/tiny-sd"
      break 2
    fi
  done
done

if [ -z "$PY" ] || [ -z "$MODEL" ]; then
  {
    echo "No existing working Tiny-SD install was found."
    echo "No download or compilation was started."
    echo "Looked in:"
    printf '  %s\n' "${CANDIDATES[@]}"
  } >>"$LOG"
  exit 0
fi

# Stop ONLY an Apex image server on 8189 if it is the wrong engine.
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
TINY_SD_MODEL_DIR="$MODEL" \
nohup "$PY" -m uvicorn server:app --host 127.0.0.1 --port 8189 >"$LOG" 2>&1 &
echo $! >/tmp/apex-tiny-image.pid

echo "Reusing Tiny-SD model: $MODEL" >>"$LOG"
echo "Reusing Python runtime: $PY" >>"$LOG"
