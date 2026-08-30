#!/usr/bin/env bash
# 下载并缓存 python-build-standalone → 嵌入 Judy.app（与灵犀同一套解释器）
# 用法:
#   bash desktop/judy-tauri/scripts/fetch-bundled-python.sh
#   bash desktop/judy-tauri/scripts/fetch-bundled-python.sh /path/to/Judy.app

set -euo pipefail

if [[ "$(uname)" != "Darwin" ]]; then
    echo "skip: fetch-bundled-python 仅 Darwin" >&2
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TAURI_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LINGXI_CACHE="$HOME/.openclaw/skills/wechat-automation/desktop/lingxi-tauri/.cache/python-standalone"
if [[ -n "${JUDY_PYTHON_CACHE:-}" ]]; then
    CACHE_DIR="$JUDY_PYTHON_CACHE"
elif [[ -n "${LINGXI_PYTHON_CACHE:-}" ]]; then
    CACHE_DIR="$LINGXI_PYTHON_CACHE"
elif [[ -x "$LINGXI_CACHE/aarch64-apple-darwin-3.12.12/python/bin/python3" || -x "$LINGXI_CACHE/x86_64-apple-darwin-3.12.12/python/bin/python3" ]]; then
    CACHE_DIR="$LINGXI_CACHE"
else
    CACHE_DIR="$TAURI_DIR/.cache/python-standalone"
fi
# 固定版本便于复现；install_only_stripped 体积较小
RELEASE_TAG="${JUDY_PYTHON_RELEASE:-${LINGXI_PYTHON_RELEASE:-20251010}}"
PY_VER="${JUDY_PYTHON_VERSION:-${LINGXI_PYTHON_VERSION:-3.12.12}}"
ARCH="$(uname -m)"
case "$ARCH" in
    arm64) TRIPLE="aarch64-apple-darwin" ;;
    x86_64) TRIPLE="x86_64-apple-darwin" ;;
    *) echo "❌ 不支持的架构: $ARCH" >&2; exit 1 ;;
esac

ASSET="cpython-${PY_VER}+${RELEASE_TAG}-${TRIPLE}-install_only_stripped.tar.gz"
URL="https://github.com/astral-sh/python-build-standalone/releases/download/${RELEASE_TAG}/${ASSET}"

mkdir -p "$CACHE_DIR"
TARBALL="$CACHE_DIR/$ASSET"
EXTRACTED="$CACHE_DIR/${TRIPLE}-${PY_VER}"

download_standalone_tarball() {
    local dest="$1"
    local urls=()
    if [[ -n "${LINGXI_PYTHON_URL:-}" ]]; then
        urls+=("$LINGXI_PYTHON_URL")
    fi
    urls+=(
        "$URL"
        "https://ghproxy.net/${URL}"
        "https://ghfast.top/${URL}"
    )
    local u max_t
    for u in "${urls[@]}"; do
        echo "📥 $u"
        max_t=3600
        if [[ "$u" == "$URL" ]]; then
            max_t=90
        fi
        # 同一源断点续传；换源则丢掉残片，避免 Range 对不上
        if curl -fL -C - --retry 5 --retry-all-errors --retry-delay 3 \
            --connect-timeout 20 --max-time "$max_t" \
            -o "$dest.partial" "$u"; then
            mv "$dest.partial" "$dest"
            return 0
        fi
        rm -f "$dest.partial"
        echo "⚠️ 该源失败，尝试下一个…" >&2
    done
    echo "❌ 无法下载 $ASSET（可设 LINGXI_PYTHON_URL 指定镜像）" >&2
    return 1
}

if [[ ! -x "$EXTRACTED/python/bin/python3" ]]; then
    if [[ ! -f "$TARBALL" ]]; then
        echo "📥 下载 $ASSET …"
        download_standalone_tarball "$TARBALL"
    else
        echo "📦 使用已缓存 tarball: $TARBALL"
    fi
    rm -rf "$EXTRACTED"
    mkdir -p "$EXTRACTED"
    echo "📦 解压到 $EXTRACTED …"
    tar -xzf "$TARBALL" -C "$EXTRACTED"
    # tarball 顶层通常为 python/
    if [[ ! -x "$EXTRACTED/python/bin/python3" ]]; then
        echo "❌ 解压后未找到 python/bin/python3" >&2
        ls -la "$EXTRACTED" >&2 || true
        exit 1
    fi
else
    echo "✅ 使用已缓存解释器: $EXTRACTED/python/bin/python3（跳过下载）"
fi

# 缓存内预装 zstandard，避免仅嵌入后改动再触发客户机签名/隔离问题
ensure_zstandard_in_prefix() {
    local prefix="$1"
    local py="$prefix/bin/python3"
    [[ -x "$py" ]] || return 1
    if "$py" -c "import zstandard" 2>/dev/null; then
        return 0
    fi
    echo "📦 安装 zstandard → $prefix …"
    "$py" -m pip install --quiet zstandard
    "$py" -c "import zstandard"
}

# 对内嵌树做 ad-hoc 签名，降低 macOS 对改动后二进制直接 SIGKILL 的概率
codesign_python_prefix() {
    local prefix="$1"
    local f
    [[ -d "$prefix" ]] || return 0
    command -v codesign >/dev/null 2>&1 || return 0
    while IFS= read -r f; do
        codesign --force --sign - --timestamp=none "$f" >/dev/null 2>&1 || true
    done < <(find "$prefix" \( -name 'python3*' -o -name 'python' -o -name 'libpython*.dylib' -o -name '*.so' \) -type f 2>/dev/null)
}

ensure_zstandard_in_prefix "$EXTRACTED/python" || {
    echo "❌ 缓存解释器无法安装 zstandard" >&2
    exit 1
}
codesign_python_prefix "$EXTRACTED/python"

embed_into_app() {
    local app="$1"
    local dest="$app/Contents/Resources/python"
    mkdir -p "$app/Contents/Resources"
    rm -rf "$dest"
    cp -R "$EXTRACTED/python" "$dest"
    # 确保可执行
    chmod +x "$dest/bin/python3" "$dest/bin/python"* 2>/dev/null || true
    # 复制后重签 + 清隔离，便于本机立刻可跑
    xattr -cr "$dest" 2>/dev/null || true
    codesign_python_prefix "$dest"
    echo "✅ 已嵌入: $dest"
    "$dest/bin/python3" -c "import sys; print(sys.version)"
    "$dest/bin/python3" -c "import zstandard; print('zstandard ok')"
}

if [[ $# -ge 1 ]]; then
    embed_into_app "$1"
else
    echo "✅ 缓存就绪: $EXTRACTED/python/bin/python3"
    echo "   嵌入请传 Judy.app 路径: $0 /path/to/Judy.app"
fi
