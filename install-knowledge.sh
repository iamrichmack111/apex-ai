#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

TARGET="${KNOWLEDGE_TARGET_ROWS:-1000000}"
DB="${KNOWLEDGE_DB:-data/knowledge_1m.db}"
VENV=".knowledge-venv"

mkdir -p data

if [ -f "$DB" ]; then
  COUNT="$(python3 - "$DB" <<'PY'
import sqlite3,sys
try:
    c=sqlite3.connect(sys.argv[1]).execute("SELECT value FROM meta WHERE key='count'").fetchone()
    print(c[0] if c else "0")
except Exception:
    print("0")
PY
)"
  if [ "${COUNT:-0}" -ge "$TARGET" ] 2>/dev/null; then
    echo "Knowledge pack already ready: $COUNT Q&A records."
    exit 0
  fi
fi

if [ ! -d "$VENV" ]; then
  python3 -m venv "$VENV"
fi
source "$VENV/bin/activate"
python -m pip install -q --upgrade pip

echo "Installing knowledge-builder dependencies..."
pip install -q "datasets>=3.0,<5" "huggingface_hub>=0.25" "pyarrow>=17"

echo "Building exactly $TARGET searchable Q&A records..."
HF_HUB_DISABLE_PROGRESS_BARS=0 \
python knowledge-engine/build_knowledge.py --db "$DB" --target "$TARGET"

echo "Apex 1M knowledge pack installed."
