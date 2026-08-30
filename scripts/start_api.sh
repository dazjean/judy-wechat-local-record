#!/bin/bash
# 启动 Judy API（8090），不打开窗口。供 Judy.app 与 install 后的命令行共用。
set -euo pipefail

API_PORT="${JUDY_API_PORT:-8090}"

if [[ -z "${JUDY_ROOT:-}" ]]; then
  _DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  if [[ "$_DIR" == *"/Contents/Resources/scripts" ]]; then
    JUDY_ROOT="$(cd "$_DIR/../../../.." && pwd)"
  else
    JUDY_ROOT="$(cd "$_DIR/.." && pwd)"
  fi
fi
export JUDY_ROOT
export SKILL_ROOT="$JUDY_ROOT"
export JUDY_DEPLOY=1
export JUDY_NO_WINDOW=1
APP_RES="$JUDY_ROOT/Judy.app/Contents/Resources"
if [[ -d "$APP_RES/backend" ]]; then
  export PYTHONPATH="$APP_RES/backend${PYTHONPATH:+:$PYTHONPATH}"
else
  export PYTHONPATH="$JUDY_ROOT/backend${PYTHONPATH:+:$PYTHONPATH}"
fi

mkdir -p "$JUDY_ROOT/logs"
LOG_FILE="${JUDY_API_LOG:-$JUDY_ROOT/logs/judy-api.log}"

if [[ -n "${JUDY_RESTART:-}" ]]; then
  _deadline=$((SECONDS + 15))
  while (( SECONDS < _deadline )); do
    if ! lsof -Pi :"$API_PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
      break
    fi
    sleep 0.3
  done
fi

if lsof -Pi :"$API_PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
  echo "Judy 已在端口 $API_PORT 运行"
  exit 0
fi

PYTHON_BIN="${JUDY_PYTHON:-${LINGXI_PYTHON:-}}"
if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
  if [[ -x "$JUDY_ROOT/Judy.app/Contents/Resources/python/bin/python3" ]]; then
    PYTHON_BIN="$JUDY_ROOT/Judy.app/Contents/Resources/python/bin/python3"
  elif [[ -x "$JUDY_ROOT/.venv/bin/python" ]]; then
    PYTHON_BIN="$JUDY_ROOT/.venv/bin/python"
  else
    PYTHON_BIN="$(command -v python3 || true)"
  fi
fi
if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
  echo "找不到 Python。请使用带内嵌 Python 的 Judy.app，或先运行 bash install.sh。" >&2
  exit 1
fi
if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "Judy 需要 Python 3.10+，当前是 $PYTHON_BIN" >&2
  exit 1
fi

export JUDY_PYTHON="$PYTHON_BIN"
echo "启动 Judy API ($API_PORT)  Python=$PYTHON_BIN"
cd "$JUDY_ROOT"
: >"$LOG_FILE"
nohup "$PYTHON_BIN" -c 'from app.boot import main; raise SystemExit(main() or 0)' >>"$LOG_FILE" 2>&1 &
API_PID=$!

READY=0
_deadline=$((SECONDS + 25))
while (( SECONDS < _deadline )); do
  if curl -sf "http://127.0.0.1:$API_PORT/api/health" >/dev/null 2>&1; then
    READY=1
    break
  fi
  if ! kill -0 "$API_PID" 2>/dev/null; then
    break
  fi
  sleep 0.4
done

if [[ "$READY" -ne 1 ]]; then
  echo "Judy 服务启动失败，查看 $LOG_FILE" >&2
  tail -n 40 "$LOG_FILE" >&2 || true
  exit 1
fi
echo "Judy 服务已启动"
