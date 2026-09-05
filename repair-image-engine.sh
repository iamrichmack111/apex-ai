#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

ROOT="$(pwd)"
ENGINE_DIR="$ROOT/image-engine"
MODEL_DIR="$ENGINE_DIR/models"
MODEL="$MODEL_DIR/dreamshaper-7-lcm-q4_0.gguf"
MODEL_URL="https://huggingface.co/Hatchetsballz/TokForge-DreamShaper-LCM-GGUF-q4/resolve/main/dreamshaper-7-lcm-q4_0.gguf"

mkdir -p "$MODEL_DIR"

echo "NON-DESTRUCTIVE Apex image repair"
echo "- no Ollama model changes"
echo "- no database/chat/knowledge deletion"
echo "- old image-engine files are preserved"
echo

missing_tools=0
for cmd in git cmake c++ curl; do
  command -v "$cmd" >/dev/null 2>&1 || missing_tools=1
done
if [ "$missing_tools" = "1" ]; then
  sudo apt-get update
  sudo apt-get install -y build-essential cmake git curl
fi

SDCPP="$ENGINE_DIR/stable-diffusion.cpp-v8"
if [ -e "$SDCPP" ] && [ ! -d "$SDCPP/.git" ]; then
  SDCPP="$ENGINE_DIR/stable-diffusion.cpp-v8-$(date +%Y%m%d-%H%M%S)"
fi

if [ ! -d "$SDCPP/.git" ]; then
  echo "Cloning stable-diffusion.cpp recursively into a NEW folder..."
  git clone --recurse-submodules --shallow-submodules --depth 1 \
    https://github.com/leejet/stable-diffusion.cpp.git "$SDCPP"
else
  echo "Repairing V8 engine submodules..."
  git -C "$SDCPP" submodule sync --recursive
  git -C "$SDCPP" submodule update --init --recursive --depth 1
fi

if [ ! -f "$SDCPP/ggml/CMakeLists.txt" ]; then
  git -C "$SDCPP" submodule update --init --recursive
fi
if [ ! -f "$SDCPP/ggml/CMakeLists.txt" ]; then
  echo "ERROR: ggml submodule is missing."
  exit 1
fi

SD_CLI="$(find "$SDCPP" -type f -path '*/bin/sd-cli' -perm -u+x 2>/dev/null | head -n 1 || true)"
if [ -z "$SD_CLI" ]; then
  BUILD="$SDCPP/build-apex-$(date +%Y%m%d-%H%M%S)"
  echo "Building in a NEW directory: $BUILD"
  CMAKE_ARGS=(-DCMAKE_BUILD_TYPE=Release)
  if command -v nvcc >/dev/null 2>&1; then
    echo "CUDA detected."
    CMAKE_ARGS+=( -DSD_CUDA=ON )
  fi
  cmake -S "$SDCPP" -B "$BUILD" "${CMAKE_ARGS[@]}"
  cmake --build "$BUILD" --config Release -j"$(nproc 2>/dev/null || echo 4)"
  SD_CLI="$BUILD/bin/sd-cli"
fi

if [ ! -x "$SD_CLI" ]; then
  echo "ERROR: sd-cli was not produced."
  exit 1
fi
printf '%s\n' "$SD_CLI" > "$ENGINE_DIR/.sd-cli-path"

MODEL_SIZE="$(stat -c%s "$MODEL" 2>/dev/null || echo 0)"
if [ "$MODEL_SIZE" -gt 100000000 ]; then
  echo "DreamShaper model already exists; keeping it."
else
  echo "Downloading DreamShaper-7 LCM Q4 (~1.63 GB)..."
  PART="$MODEL.download"
  curl -L --fail --retry 5 --retry-delay 3 -C - "$MODEL_URL" -o "$PART"
  mv "$PART" "$MODEL"
fi

touch "$ENGINE_DIR/.installed-v8"
echo "Image-engine repair files are ready."
echo "sd-cli: $SD_CLI"
