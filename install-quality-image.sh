#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

ROOT="$(pwd)"
ENGINE="$ROOT/image-engine"
DEST="$ENGINE/models/dreamshaper7"
MODEL="$DEST/DreamShaper_7_pruned.safetensors"
LORA="$DEST/pytorch_lora_weights.safetensors"

MODEL_URL="https://huggingface.co/Lykon/DreamShaper/resolve/main/DreamShaper_7_pruned.safetensors?download=true"
LORA_URL="https://huggingface.co/latent-consistency/lcm-lora-sdv1-5/resolve/main/pytorch_lora_weights.safetensors?download=true"

mkdir -p "$DEST"

echo "Apex Quality Image Fix"
echo "======================"
echo "NO C++ compilation."
echo "NO Ollama changes."
echo "NO chat/database/knowledge deletion."
echo

# Find and reuse an existing full checkpoint first.
if [ ! -s "$MODEL" ] || [ "$(stat -c%s "$MODEL" 2>/dev/null || echo 0)" -lt 1800000000 ]; then
  FOUND="$(find "$HOME/Downloads" "$HOME/.cache/huggingface" \
    -type f -name 'DreamShaper_7_pruned.safetensors' -size +1800M \
    2>/dev/null | head -n 1 || true)"
  if [ -n "$FOUND" ] && [ "$FOUND" != "$MODEL" ]; then
    echo "Reusing existing DreamShaper checkpoint:"
    echo "  $FOUND"
    ln -sfn "$FOUND" "$MODEL"
  fi
fi

# Find and reuse an existing LCM LoRA first.
if [ ! -s "$LORA" ] || [ "$(stat -Lc%s "$LORA" 2>/dev/null || echo 0)" -lt 100000000 ]; then
  FOUND_LORA="$(find "$HOME/Downloads" "$HOME/.cache/huggingface" \
    -type f -name 'pytorch_lora_weights.safetensors' -size +120M -size -150M \
    2>/dev/null | head -n 1 || true)"
  if [ -n "$FOUND_LORA" ] && [ "$FOUND_LORA" != "$LORA" ]; then
    echo "Reusing existing LCM adapter:"
    echo "  $FOUND_LORA"
    ln -sfn "$FOUND_LORA" "$LORA"
  fi
fi

MODEL_SIZE="$(stat -Lc%s "$MODEL" 2>/dev/null || echo 0)"
if [ "$MODEL_SIZE" -lt 1800000000 ]; then
  echo
  echo "Downloading DreamShaper 7 checkpoint (~2.13 GB)."
  echo "This is the only large download and it is resumable."
  PART="$DEST/DreamShaper_7_pruned.safetensors.part"
  curl -L --fail --retry 5 --retry-delay 3 -C - "$MODEL_URL" -o "$PART"
  mv "$PART" "$MODEL"
fi

LORA_SIZE="$(stat -Lc%s "$LORA" 2>/dev/null || echo 0)"
if [ "$LORA_SIZE" -lt 100000000 ]; then
  echo
  echo "Downloading LCM speed adapter (~135 MB)."
  PART="$DEST/pytorch_lora_weights.safetensors.part"
  curl -L --fail --retry 5 --retry-delay 3 -C - "$LORA_URL" -o "$PART"
  mv "$PART" "$LORA"
fi

# Find the already-working Tiny-SD Python runtime. Do not pip-install anything.
RUNTIMES=(
  "$ENGINE/.venv/bin/python"
  "$HOME/Downloads/apex-ai-v6/image-engine/.venv/bin/python"
  "$HOME/Downloads/apex-ai-v5/image-engine/.venv/bin/python"
  "$HOME/Downloads/richmack-chat-v4-lite-fast/image-engine/.venv/bin/python"
  "$HOME/Downloads/richmack-chat-v4-lite/image-engine/.venv/bin/python"
  "$HOME/Downloads/richmack-chat-v4/image-engine/.venv/bin/python"
)

PY=""
for CAND in "${RUNTIMES[@]}"; do
  [ -x "$CAND" ] || continue
  if "$CAND" -c 'import torch,diffusers,transformers,fastapi,uvicorn,PIL' >/dev/null 2>&1; then
    PY="$CAND"
    break
  fi
done

if [ -z "$PY" ]; then
  echo
  echo "ERROR: I could not find the Diffusers/PyTorch runtime from the old working image engine."
  echo "Nothing else was downloaded or installed."
  exit 1
fi

printf '%s\n' "$PY" > "$ENGINE/.quality-python"
echo
echo "Using existing image Python runtime:"
echo "  $PY"
echo
echo "DreamShaper quality image engine is ready."
