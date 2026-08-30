#!/bin/bash
# 完全停止：关掉 8090 上的 Judy 服务。Judy.app 退出时调用。
set -euo pipefail
_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$_DIR/stop_api.sh"
