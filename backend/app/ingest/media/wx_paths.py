"""定位本机微信数据根目录。只读配置，不把内部路径写进对用户可见文案。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

SKIP_ACCOUNT_FOLDERS = frozenset(
    {
        "all_users",
        "backup",
        "old_backup",
        "wmpf",
        "message",
        "radium",
    }
)


def reader_config_path() -> Path:
    return Path.home() / ".wechat-cli" / "config.json"


def keys_path() -> Path:
    return Path.home() / ".wechat-cli" / "all_keys.json"


def wechat_account_root() -> Optional[Path]:
    cfg = reader_config_path()
    if not cfg.is_file():
        return None
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    db_dir = Path(str(data.get("db_dir") or "")).expanduser()
    if not db_dir:
        return None
    root = db_dir.parent if db_dir.name == "db_storage" else db_dir
    return root if root.is_dir() else None


def wechat_files_roots() -> list[Path]:
    home = Path.home()
    mac = home / "Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files"
    if mac.is_dir():
        return [mac]
    found: list[Path] = []
    for path in (
        home / "Documents" / "xwechat_files",
        home / "xwechat_files",
        home / "Documents" / "WeChat Files",
    ):
        if path.is_dir() and path not in found:
            found.append(path)
    return found


def newest_account_dir() -> Optional[Path]:
    """xwechat_files 下最近修改的账号目录。Mac 上该目录名即当前 wxid。"""
    best: Optional[Path] = None
    best_mtime = -1.0
    for root in wechat_files_roots():
        try:
            children = list(root.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir() or child.name.startswith("."):
                continue
            if child.name.lower() in SKIP_ACCOUNT_FOLDERS:
                continue
            try:
                mtime = child.stat().st_mtime
            except OSError:
                continue
            if mtime >= best_mtime:
                best_mtime = mtime
                best = child
    return best


def db_storage_dir() -> Optional[Path]:
    root = wechat_account_root()
    if not root:
        return None
    storage = root / "db_storage"
    return storage if storage.is_dir() else None


def load_db_keys() -> dict[str, dict]:
    path = keys_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, dict) and not str(k).startswith("_")}
