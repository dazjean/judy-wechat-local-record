#!/bin/bash
# 只停 Judy API（8090），不关桌面壳。
set -euo pipefail
API_PORT="${JUDY_API_PORT:-8090}"
PIDS="$(lsof -tiTCP:"$API_PORT" -sTCP:LISTEN 2>/dev/null || true)"
if [[ -n "$PIDS" ]]; then
  kill $PIDS 2>/dev/null || true
  sleep 1
  kill -9 $PIDS 2>/dev/null || true
  echo "已停止 Judy 服务"
else
  echo "Judy 服务未在运行"
fi
