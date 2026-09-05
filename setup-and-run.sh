#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

[ -f .env ] || cp .env.example .env
mkdir -p data/generated

# Migrate prior Apex database.
if [ ! -f data/apex_ai.db ]; then
  for OLD in \
    ../apex-ai-v6/data/apex_ai.db \
    ../apex-ai-v5/data/apex_ai.db \
    ../richmack-chat-v4-lite-fast/data/richmack_ai.db \
    ../richmack-chat-v4-lite/data/richmack_ai.db \
    ../richmack-chat-v4/data/richmack_ai.db \
    ../richmack-chat-v3/data/richmack_ai.db; do
    if [ -f "$OLD" ]; then
      echo "Migrating your existing users and chats into Apex AI V7..."
      cp "$OLD" data/apex_ai.db
      break
    fi
  done
fi

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
python -m pip install -q --upgrade pip
pip install -q -r requirements.txt

OLLAMA_BASE_URL="$(grep '^OLLAMA_BASE_URL=' .env | cut -d= -f2-)"
DEFAULT_MODEL="$(grep '^DEFAULT_MODEL=' .env | cut -d= -f2-)"

if command -v ollama >/dev/null 2>&1; then
  if ! curl -fsS "$OLLAMA_BASE_URL/api/tags" >/dev/null 2>&1; then
    echo "Starting Ollama..."
    nohup ollama serve >/tmp/apex-ollama.log 2>&1 &
    sleep 3
  fi
  if ! ollama list 2>/dev/null | awk 'NR>1 {print $1}' | grep -Fxq "$DEFAULT_MODEL"; then
    echo "Installing default chat model: $DEFAULT_MODEL"
    ollama pull "$DEFAULT_MODEL"
  fi
else
  echo "WARNING: Ollama is not installed."
fi

if [ "${SKIP_IMAGE_ENGINE:-0}" != "1" ] && [ ! -f image-engine/.installed ]; then
  echo
  echo "Installing higher-quality DreamShaper LCM image engine."
  echo "The model download is about 1.63 GB."
  echo
  ./install-image-engine.sh || echo "Image setup failed. Chat will still work."
fi

if [ "${SKIP_KNOWLEDGE:-0}" != "1" ]; then
  echo
  echo "Preparing Apex's 1,000,000-entry local Q&A knowledge pack."
  echo "This is indexed once; future launches reuse it."
  echo
  ./install-knowledge.sh || echo "Knowledge-pack setup failed. Chat will still work without retrieval."
fi

exec ./run.sh
