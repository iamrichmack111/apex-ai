#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

ENGINE_DIR="$(pwd)/image-engine"
SDCPP="$ENGINE_DIR/stable-diffusion.cpp"
MODEL_DIR="$ENGINE_DIR/models"
MODEL="$MODEL_DIR/dreamshaper-7-lcm-q4_0.gguf"
MODEL_URL="https://huggingface.co/Hatchetsballz/TokForge-DreamShaper-LCM-GGUF-q4/resolve/main/dreamshaper-7-lcm-q4_0.gguf"

mkdir -p "$MODEL_DIR"

need_pkg=0
command -v git >/dev/null 2>&1 || need_pkg=1
command -v cmake >/dev/null 2>&1 || need_pkg=1
command -v c++ >/dev/null 2>&1 || need_pkg=1
command -v curl >/dev/null 2>&1 || need_pkg=1

if [ "$need_pkg" = "1" ]; then
  echo "Installing build tools for the image engine..."
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y build-essential cmake git curl
  else
    echo "ERROR: Install git, cmake, a C++ compiler, and curl, then rerun."
    exit 1
  fi
fi

if [ ! -d "$SDCPP/.git" ]; then
  echo "Cloning stable-diffusion.cpp..."
  git clone --depth 1 https://github.com/leejet/stable-diffusion.cpp.git "$SDCPP"
else
  git -C "$SDCPP" pull --ff-only || true
fi

echo "Building stable-diffusion.cpp..."
cmake -S "$SDCPP" -B "$SDCPP/build" -DCMAKE_BUILD_TYPE=Release
cmake --build "$SDCPP/build" --config Release -j"$(nproc 2>/dev/null || echo 4)"

if [ ! -s "$MODEL" ]; then
  echo "Downloading DreamShaper-7 LCM Q4 image model (~1.63 GB)..."
  curl -L --fail --retry 4 -C - "$MODEL_URL" -o "$MODEL"
else
  echo "DreamShaper image model already present."
fi

# Image server uses the app venv, so no second huge PyTorch install is needed.
touch "$ENGINE_DIR/.installed"
chmod +x "$ENGINE_DIR/start-image-engine.sh"
echo "DreamShaper image engine ready."
