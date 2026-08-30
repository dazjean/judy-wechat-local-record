#!/usr/bin/env bash
set -u
PIDS="$(lsof -tiTCP:8090 -sTCP:LISTEN 2>/dev/null || true)"
if [ -n "$PIDS" ]; then
  # shellcheck disable=SC2086
  kill $PIDS 2>/dev/null || true
  sleep 1
  # shellcheck disable=SC2086
  kill -9 $PIDS 2>/dev/null || true
  echo "已停止 Judy（端口 8090）"
else
  echo "Judy 未在运行"
fi
