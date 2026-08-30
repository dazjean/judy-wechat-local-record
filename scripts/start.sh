#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -d "$ROOT/.venv" ]; then
  PY=python3
  if command -v python3.12 >/dev/null 2>&1; then
    PY=python3.12
  fi
  "$PY" -m venv "$ROOT/.venv"
fi
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"
pip install -q -r "$ROOT/backend/requirements.txt"

export PYTHONPATH="$ROOT/backend"
exec python -m app.boot
