#!/bin/bash
# 构建 Judy.app（Tauri 内嵌 WebView + python-build-standalone）
# 用法:
#   bash desktop/judy-tauri/build-app.sh
#   bash desktop/judy-tauri/build-app.sh /path/to/output/Judy.app

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="Judy.app"
OUT="${1:-$SRC_DIR/dist/$APP_NAME}"

if [[ "$(uname)" != "Darwin" ]]; then
  echo "build-app.sh 仅支持 macOS" >&2
  exit 1
fi

cp "$SRC_DIR/../shared/package_root.py" "$SRC_DIR/src-tauri/resources/package_root.py"

cd "$SRC_DIR"
python3 "$SRC_DIR/scripts/sync_desktop_version.py"
if [[ ! -d node_modules ]]; then
  npm install
fi

npm run tauri build

if [[ -n "${CARGO_TARGET_DIR:-}" ]]; then
  BUNDLE_DIR="$CARGO_TARGET_DIR/release/bundle/macos"
else
  BUNDLE_DIR="$SRC_DIR/src-tauri/target/release/bundle/macos"
fi
BUILT="$(find "$BUNDLE_DIR" -maxdepth 1 -name '*.app' -print -quit)"
if [[ -z "$BUILT" || ! -d "$BUILT" ]]; then
  echo "未找到 Tauri 构建产物: $BUNDLE_DIR" >&2
  exit 1
fi

rm -rf "$OUT"
mkdir -p "$(dirname "$OUT")"
cp -R "$BUILT" "$OUT"

FETCH="$SRC_DIR/scripts/fetch-bundled-python.sh"
chmod +x "$FETCH"
if bash "$FETCH" "$OUT"; then
  echo "内嵌 Python 已写入 $OUT/Contents/Resources/python"
else
  echo "内嵌 Python 失败" >&2
  if [[ "${JUDY_REQUIRE_BUNDLED_PYTHON:-${LINGXI_REQUIRE_BUNDLED_PYTHON:-}}" == "1" ]]; then
    exit 1
  fi
fi

echo "已构建: $OUT"
