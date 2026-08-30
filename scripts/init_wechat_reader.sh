#!/usr/bin/env bash
# 微信读取初始化。请先打开并登录微信，必要时使用管理员/sudo。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

find_bin() {
  local p
  for p in \
    "$ROOT/Judy.app/Contents/Resources/vendor/wechat-cli" \
    "$ROOT/vendor/wechat-cli" \
    "$ROOT/.venv/bin/wechat-cli" \
    "$ROOT/backend/.venv/bin/wechat-cli"
  do
    if [ -x "$p" ]; then
      echo "$p"
      return 0
    fi
  done
  if command -v wechat-cli >/dev/null 2>&1; then
    command -v wechat-cli
    return 0
  fi
  return 1
}

echo "正在初始化微信读取，请保持微信已登录…"
BIN="$(find_bin)" || {
  echo "微信读取组件未就绪，请重新安装本系统。"
  exit 1
}
if ! "$BIN" init; then
  echo "尚未完成微信读取初始化，或当前微信版本不兼容。"
  exit 1
fi
echo "微信读取初始化完成。请打开系统，在「微信同步」页查看状态。"
