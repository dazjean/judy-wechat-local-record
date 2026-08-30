#!/bin/bash
# 客户安装：清隔离 + ad-hoc 签名（与灵犀 install.sh 同一口径）。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

APP="$ROOT/Judy.app"
LIC="$APP/Contents/Resources/license.dat"
if [[ ! -d "$APP" ]]; then
  echo "请在解压后的 Judy 交付目录运行本脚本（需有 Judy.app）。" >&2
  exit 1
fi
if [[ ! -f "$LIC" && ! -f "$ROOT/license.dat" ]]; then
  echo "未找到授权文件。请重新解压完整安装包。" >&2
  exit 1
fi

echo "正在解除隔离并签名 Judy…"
xattr -cr "$ROOT" 2>/dev/null || true

BACKEND="$APP/Contents/Resources/backend"
if [[ -d "$BACKEND" ]]; then
  while IFS= read -r so; do
    codesign --force --sign - --timestamp=none "$so" >/dev/null 2>&1 || true
  done < <(find "$BACKEND" -name '*.so' -type f 2>/dev/null)
fi

xattr -cr "$APP" 2>/dev/null || true
if ! codesign --force --deep --sign - --timestamp=none "$APP"; then
  echo "Judy.app 签名失败。可再试一次，或把整个文件夹拷到非 iCloud 目录后重跑本脚本。" >&2
  exit 1
fi

echo "完成。请双击 Judy.app。"
echo "首次使用请再运行「微信读取初始化」，并保持约定的微信已登录。"
