"""识别本机微信账号。

授权只认数据目录名：wxid_ 开头则用目录名（去掉设备后缀），否则用完整目录名。
聊天身份仍可从已解密库读取系统 wxid。不把标识写进日志。
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from app.config import settings
from app.ingest.media.msg_index import decrypt_media_db
from app.ingest.media.wx_paths import SKIP_ACCOUNT_FOLDERS, load_db_keys, newest_account_dir, wechat_account_root

_FOLDER_SUFFIX = re.compile(r"^wxid_[a-z0-9]+_[0-9a-z]{2,6}$", re.I)
PLACEHOLDER_SELF = {"", "本机客服", "本机微信", "me", "我"}


@dataclass(frozen=True)
class SelfProfile:
    username: str = ""
    alias: str = ""
    nickname: str = ""

    def display_account(self) -> str:
        return (self.username or "").strip()


def username_from_folder(name: str) -> str:
    text = (name or "").strip()
    if not text.startswith("wxid_"):
        return ""
    if _FOLDER_SUFFIX.match(text):
        return text.rsplit("_", 1)[0]
    return text


def folder_wxid(name: str) -> str:
    """授权标识：wxid_ 目录去掉设备后缀，其它目录用完整名称。"""
    text = (name or "").strip()
    if not text or text.lower() in SKIP_ACCOUNT_FOLDERS:
        return ""
    return username_from_folder(text) or text


_FOLDER_WXID_CACHE: tuple[float, str] | None = None
_FOLDER_WXID_TTL = 20.0


def current_folder_wxid() -> str:
    global _FOLDER_WXID_CACHE
    now = time.monotonic()
    if _FOLDER_WXID_CACHE and now - _FOLDER_WXID_CACHE[0] < _FOLDER_WXID_TTL:
        return _FOLDER_WXID_CACHE[1]
    folder = newest_account_dir() or wechat_account_root()
    value = folder_wxid(folder.name if folder else "")
    _FOLDER_WXID_CACHE = (now, value)
    return value


def resolve_self_wxid() -> str:
    """运行校验只用文件夹名，不读库、不要求读取初始化。"""
    return current_folder_wxid()


def infer_self_username(name2id: set[str], contact_usernames: set[str]) -> str:
    own = [
        u
        for u in name2id
        if u and str(u).startswith("wxid_") and u not in contact_usernames
    ]
    if len(own) == 1:
        return own[0]
    return ""


def wxid_from_dbs() -> str:
    contact_db = _open_decrypted("contact/contact.db")
    contacts = _contact_usernames(contact_db) if contact_db else set()
    if not contacts:
        return ""
    for rel in _message_rel_keys()[:8]:
        path = _open_decrypted(rel)
        if not path:
            continue
        found = infer_self_username(_name2id_usernames(path), contacts)
        if found:
            return found
    return ""


def profile_from_contact_row(username: str, alias: str = "", nickname: str = "") -> SelfProfile:
    return SelfProfile(
        username=(username or "").strip(),
        alias=(alias or "").strip(),
        nickname=(nickname or "").strip(),
    )


def apply_self_profile(account, profile: SelfProfile) -> None:
    """写入本机 Account。已有手填昵称时不覆盖。"""
    if not profile.username:
        return
    if hasattr(account, "wx_username"):
        account.wx_username = profile.username
    nick = profile.nickname
    current = (getattr(account, "display_name", None) or "").strip()
    if nick and current in PLACEHOLDER_SELF:
        account.display_name = nick


def _table_usernames(path: Path, sql: str) -> set[str]:
    if not path or not path.is_file():
        return set()
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return set()
    try:
        rows = con.execute(sql).fetchall()
    except sqlite3.Error:
        return set()
    finally:
        con.close()
    return {str(r[0]) for r in rows if r and r[0]}


def _contact_usernames(path: Path) -> set[str]:
    names = _table_usernames(path, "SELECT username FROM contact")
    names |= _table_usernames(path, "SELECT username FROM stranger")
    return names


def _name2id_usernames(path: Path) -> set[str]:
    return _table_usernames(path, "SELECT user_name FROM Name2Id")


def _lookup_contact(path: Path, username: str) -> tuple[str, str]:
    if not path or not path.is_file() or not username:
        return "", ""
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return "", ""
    try:
        row = con.execute(
            "SELECT ifnull(alias,''), ifnull(nick_name,'') FROM contact WHERE username=?",
            (username,),
        ).fetchone()
        if not row:
            row = con.execute(
                "SELECT ifnull(alias,''), ifnull(nick_name,'') FROM stranger WHERE username=?",
                (username,),
            ).fetchone()
    except sqlite3.Error:
        return "", ""
    finally:
        con.close()
    if not row:
        return "", ""
    return str(row[0] or "").strip(), str(row[1] or "").strip()


def _message_rel_keys() -> list[str]:
    found: list[tuple[int, str]] = []
    for key in load_db_keys():
        norm = str(key).replace("\\", "/")
        name = Path(norm).name
        if not name.startswith("message_") or not name.endswith(".db"):
            continue
        if "biz_" in name or "fts" in name or "resource" in name:
            continue
        stem = name[len("message_") : -3]
        if stem.isdigit():
            found.append((int(stem), str(key)))
    found.sort()
    return [rel for _, rel in found]


def _open_decrypted(rel: str) -> Path | None:
    dest = settings.media_cache_dir / rel.replace("/", "_")
    if dest.is_file() and dest.stat().st_size > 4096:
        return dest
    return decrypt_media_db(rel)


_PROFILE_CACHE: tuple[float, SelfProfile] | None = None
_PROFILE_TTL = 600.0


def read_self_profile() -> SelfProfile:
    global _PROFILE_CACHE
    now = time.monotonic()
    if _PROFILE_CACHE and now - _PROFILE_CACHE[0] < _PROFILE_TTL:
        return _PROFILE_CACHE[1]
    profile = _read_self_profile()
    if profile.username:
        _PROFILE_CACHE = (now, profile)
    return profile


def _read_self_profile() -> SelfProfile:
    username = wxid_from_dbs()
    if not username:
        return SelfProfile()
    contact_db = _open_decrypted("contact/contact.db")
    alias, nickname = _lookup_contact(contact_db, username) if contact_db else ("", "")
    return profile_from_contact_row(username, alias, nickname)
