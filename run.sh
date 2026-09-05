#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
[ -f .env ] || cp .env.example .env

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt

OLLAMA_BASE_URL="$(grep '^OLLAMA_BASE_URL=' .env | cut -d= -f2-)"
PORT="$(grep '^PORT=' .env | cut -d= -f2-)"
PORT="${PORT:-8765}"

if [[ "$OLLAMA_BASE_URL" == http://127.0.0.1:* || "$OLLAMA_BASE_URL" == http://localhost:* ]]; then
  if command -v ollama >/dev/null 2>&1 && ! curl -fsS "$OLLAMA_BASE_URL/api/tags" >/dev/null 2>&1; then
    nohup ollama serve >/tmp/apex-ollama.log 2>&1 &
    sleep 2
  fi
fi

if [ -x image-engine/start-image-engine.sh ]; then
  ./image-engine/start-image-engine.sh >/dev/null 2>&1 || true
fi

if command -v fuser >/dev/null 2>&1; then
  fuser -k "${PORT}/tcp" >/dev/null 2>&1 || true
  sleep 1
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
