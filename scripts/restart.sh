#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
"$ROOT/scripts/stop.sh"
exec "$ROOT/scripts/start.sh"
