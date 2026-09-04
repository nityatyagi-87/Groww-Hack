#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

if [[ ! -d "$ROOT/backend/.venv" ]]; then
  python3 -m venv "$ROOT/backend/.venv"
  PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 "$ROOT/backend/.venv/bin/pip" install -r "$ROOT/backend/requirements.txt"
fi
if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
  (cd "$ROOT/frontend" && npm install)
fi

export PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1
"$ROOT/backend/.venv/bin/uvicorn" app.main:app --app-dir "$ROOT/backend" --host 127.0.0.1 --port 8000 &
BACK_PID=$!
(cd "$ROOT/frontend" && npm run dev -- --host 127.0.0.1 --port 5173) &
FRONT_PID=$!
trap 'kill $BACK_PID $FRONT_PID 2>/dev/null' EXIT
echo "SignalList → http://127.0.0.1:5173  (API :8000)"
wait
