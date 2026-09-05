#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
ENGINE="$ROOT/image-engine"
MODEL="$ENGINE/models/dreamshaper7/DreamShaper_7_pruned.safetensors"
LORA="$ENGINE/models/dreamshaper7/pytorch_lora_weights.safetensors"

echo "Apex DreamShaper PEFT + Low Resource Fix"
echo "========================================"
echo "No model download."
echo "No compilation."
echo "No Ollama changes."
echo

if [ ! -s "$MODEL" ]; then
  echo "ERROR: Existing DreamShaper model was not found:"
  echo "  $MODEL"
  echo "This fix will NOT download it again."
  exit 1
fi

if [ ! -s "$LORA" ]; then
  echo "ERROR: Existing LCM adapter was not found:"
  echo "  $LORA"
  echo "This fix will NOT download it again."
  exit 1
fi

PY=""
if [ -s "$ENGINE/.quality-python" ]; then
  CAND="$(cat "$ENGINE/.quality-python")"
  [ -x "$CAND" ] && PY="$CAND"
fi

if [ -z "$PY" ]; then
  RUNTIMES=(
    "$ENGINE/.venv/bin/python"
    "$ROOT/.venv/bin/python"
    "$HOME/Downloads/apex-ai-v6/image-engine/.venv/bin/python"
    "$HOME/Downloads/apex-ai-v5/image-engine/.venv/bin/python"
    "$HOME/Downloads/richmack-chat-v4-lite-fast/image-engine/.venv/bin/python"
    "$HOME/Downloads/richmack-chat-v4-lite/image-engine/.venv/bin/python"
  )

  for CAND in "${RUNTIMES[@]}"; do
    [ -x "$CAND" ] || continue
    if "$CAND" -c 'import torch,diffusers,transformers,fastapi,uvicorn,PIL' >/dev/null 2>&1; then
      PY="$CAND"
      break
    fi
  done
fi

if [ -z "$PY" ]; then
  echo "ERROR: Existing image Python environment not found."
  exit 1
fi

printf '%s\n' "$PY" > "$ENGINE/.quality-python"

echo "Using:"
echo "  $PY"
echo

if "$PY" -c 'import peft, accelerate' >/dev/null 2>&1; then
  echo "PEFT backend is already installed."
else
  echo "Installing the small missing PEFT backend..."
  "$PY" -m pip install --disable-pip-version-check --no-cache-dir \
    "peft>=0.10,<0.18" "accelerate>=0.28,<2"
fi

"$PY" - <<'PY'
import peft, accelerate, diffusers, torch
print("PEFT:", peft.__version__)
print("Accelerate:", accelerate.__version__)
print("Diffusers:", diffusers.__version__)
print("Torch:", torch.__version__)
print("PEFT backend check: PASS")
PY
