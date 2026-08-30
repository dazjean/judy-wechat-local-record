"""本机数据目录。可写在安装目录的 data-dir.txt 或环境变量 JUDY_DATA_DIR。

不写进 SQLite：库文件本身就在这个目录里，改路径必须下次启动才生效。
"""

from __future__ import annotations

import os
from pathlib import Path

DATA_DIR_FILENAME = "data-dir.txt"
_FORBIDDEN = ("xwechat_files", "wechat files")
_startup_data_dir: Path | None = None


def _root() -> Path:
    from app.config import project_root

    return project_root()


def default_data_dir(root: Path | None = None) -> Path:
    return (root or _root()) / "data"


def data_dir_file(root: Path | None = None) -> Path:
    return (root or _root()) / DATA_DIR_FILENAME


def read_override_text(root: Path | None = None, env_value: str = "") -> str:
    env = (env_value or os.environ.get("JUDY_DATA_DIR") or "").strip()
    if env:
        return env
    path = data_dir_file(root)
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def override_source(root: Path | None = None, env_value: str = "") -> str:
    if (env_value or os.environ.get("JUDY_DATA_DIR") or "").strip():
        return "env"
    path = data_dir_file(root)
    try:
        if path.is_file() and path.read_text(encoding="utf-8").strip():
            return "file"
    except OSError:
        return "default"
    return "default"


def _looks_like_wechat_store(path: Path) -> bool:
    text = str(path).replace("\\", "/").lower()
    return any(token in text for token in _FORBIDDEN)


def validate_data_dir(raw: str, *, root: Path | None = None) -> Path:
    text = (raw or "").strip()
    if not text:
        raise ValueError("请填写数据目录")
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = (root or _root()) / path
    try:
        path = path.resolve()
    except OSError as exc:
        raise ValueError("无法解析该目录") from exc
    install = (root or _root()).resolve()
    if path == install:
        raise ValueError("不要把数据直接放在软件安装目录，请指定其中的子文件夹或其它磁盘位置")
    if _looks_like_wechat_store(path):
        raise ValueError("不能使用微信自己的数据目录")
    if path.is_file():
        raise ValueError("该路径是文件，请填写文件夹")
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".judy-write-check"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise ValueError("该目录无法创建或写入") from exc
    return path


def resolve_data_dir(root: Path | None = None, env_value: str = "") -> Path:
    text = read_override_text(root, env_value=env_value)
    if not text:
        return default_data_dir(root)
    try:
        return validate_data_dir(text, root=root)
    except ValueError:
        return default_data_dir(root)


def startup_data_dir(root: Path | None = None, env_value: str = "") -> Path:
    global _startup_data_dir
    if _startup_data_dir is None:
        _startup_data_dir = resolve_data_dir(root, env_value=env_value)
    return _startup_data_dir


def reset_startup_cache() -> None:
    global _startup_data_dir
    _startup_data_dir = None


def save_data_dir(raw: str, *, root: Path | None = None) -> Path:
    """写入下次启动使用的目录。空字符串恢复默认。"""
    base = root or _root()
    file = data_dir_file(base)
    text = (raw or "").strip()
    if not text:
        if file.exists():
            file.unlink()
        return default_data_dir(base)
    path = validate_data_dir(text, root=base)
    if path == default_data_dir(base).resolve():
        if file.exists():
            file.unlink()
        return default_data_dir(base)
    file.write_text(str(path), encoding="utf-8")
    return path
