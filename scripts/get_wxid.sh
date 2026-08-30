#!/usr/bin/env bash
# 一键读取本机微信数据目录名，作为授权标识。不需要「微信读取初始化」。
# 双击无效时，把本文件拖到「终端」窗口后回车。

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT="$SCRIPT_DIR/本机wxid.txt"
NOW="$(date '+%Y-%m-%d %H:%M:%S')"

is_skip() {
  case "$1" in
    all_users|Backup|backup|old_backup|WMPF|wmpf|Message|Radium|radium) return 0 ;;
    *) return 1 ;;
  esac
}

ident_from_folder() {
  local name="$1"
  local lower
  lower="$(printf '%s' "$name" | tr 'A-Z' 'a-z')"
  case "$lower" in
    wxid_*)
      local suffix="${lower##*_}"
      local prefix="${lower%_*}"
      if [ "$prefix" != "$lower" ] && [ "$prefix" != "wxid" ] \
          && [ ${#suffix} -ge 2 ] && [ ${#suffix} -le 6 ] \
          && printf '%s' "$prefix" | grep -Eq '^wxid_[a-z0-9]+$' \
          && printf '%s' "$suffix" | grep -Eq '^[a-z0-9]+$'; then
        echo "$prefix"
        return
      fi
      echo "$lower"
      ;;
    *)
      echo "$lower"
      ;;
  esac
}

mtime_of() {
  if stat -f %m "$1" >/dev/null 2>&1; then
    stat -f %m "$1"
  else
    stat -c %Y "$1"
  fi
}

ROOTS=""
add_root() {
  [ -d "$1" ] || return 0
  case "$ROOTS" in
    *"|$1|"*) return 0 ;;
  esac
  ROOTS="$ROOTS|$1|"
}

MAC_WX="$HOME/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files"
if [ -d "$MAC_WX" ]; then
  add_root "$MAC_WX"
else
  add_root "$HOME/Documents/xwechat_files"
  add_root "$HOME/xwechat_files"
  add_root "$HOME/Documents/WeChat Files"
fi

LIST="$(mktemp)"
trap 'rm -f "$LIST"' EXIT
: > "$LIST"

IFS="|"
for root in $ROOTS; do
  [ -n "$root" ] || continue
  for dir in "$root"/*; do
    [ -d "$dir" ] || continue
    name="$(basename "$dir")"
    is_skip "$name" && continue
    stamp="$(mtime_of "$dir")"
    ident="$(ident_from_folder "$name")"
    printf '%s %s %s\n' "$stamp" "$ident" "$name" >> "$LIST"
  done
done
unset IFS

CURRENT=""
{
  echo "Judy · 本机微信标识"
  echo "时间：$NOW"
  echo ""
  if [ ! -s "$LIST" ]; then
    echo "未找到微信账号目录。请先打开并登录电脑微信，稍等半分钟后再运行。"
  else
    first=1
    other_header=0
    sort -nr "$LIST" | while IFS=' ' read -r stamp ident folder; do
      [ -n "$stamp" ] || continue
      if [ "$first" -eq 1 ]; then
        first=0
        echo "当前登录（请把这一行发给实施人员）："
        echo "$ident"
        echo ""
        echo "数据目录：$folder"
      else
        if [ "$other_header" -eq 0 ]; then
          other_header=1
          echo ""
          echo "本机还发现这些账号目录（不一定是当前登录）："
        fi
        echo "  $ident  (目录 $folder)"
      fi
    done
  fi
  echo ""
  echo "只发给实施人员，不要发到群里。"
} > "$OUT"

CURRENT="$(sort -nr "$LIST" 2>/dev/null | awk 'NR==1 {print $2}')"
[ -s "$LIST" ] || CURRENT=""

cat "$OUT"
echo ""
if [ -n "$CURRENT" ] && command -v pbcopy >/dev/null 2>&1; then
  printf '%s' "$CURRENT" | pbcopy
  echo "已复制到剪贴板：$CURRENT"
fi
echo "结果已保存：$OUT"
echo ""
if [ -t 0 ]; then
  printf "按回车关闭…"
  read -r _
fi
