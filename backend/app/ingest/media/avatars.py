"""从 head_image.db 同步联系人头像到本机 media/avatar。"""

from __future__ import annotations

import sqlite3
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.ingest.media.msg_index import decrypt_media_db
from app.ingest.media.store import save_bytes
from app.models import Contact

_HEAD_IMAGE_DB = "head_image/head_image.db"


def _open_head_image_db() -> sqlite3.Connection | None:
    path = decrypt_media_db(_HEAD_IMAGE_DB)
    if not path or not path.is_file():
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None


def fetch_avatar_row(username: str) -> Optional[tuple[bytes, str, int]]:
    peer = (username or "").strip()
    if not peer:
        return None
    conn = _open_head_image_db()
    if not conn:
        return None
    try:
        row = conn.execute(
            "SELECT image_buffer, md5, update_time FROM head_image WHERE username=?",
            (peer,),
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    if not row or not row[0]:
        return None
    blob = bytes(row[0])
    if len(blob) < 32:
        return None
    md5 = str(row[1] or "").strip()
    update_time = int(row[2] or 0)
    return blob, md5, update_time


def sync_contact_avatar(contact: Contact) -> str:
    """返回 updated / skipped / missing。"""
    row = fetch_avatar_row(contact.peer_key)
    if not row:
        return "missing"
    blob, md5, _update_time = row
    if md5 and md5 == (contact.avatar_md5 or "").strip() and (contact.avatar_relpath or "").strip():
        return "skipped"
    rel, _mime, _name = save_bytes("avatar", blob, f"{contact.peer_key}.jpg")
    contact.avatar_relpath = rel
    contact.avatar_md5 = md5
    return "updated"


def sync_contact_avatars(
    db: Session,
    account_id: int,
    *,
    peer_keys: list[str] | None = None,
    log: Callable[[str], None] | None = None,
) -> dict[str, int]:
    stats = {"updated": 0, "skipped": 0, "missing": 0, "total": 0}
    query = db.query(Contact).filter(Contact.account_id == account_id)
    if peer_keys:
        keys = [k for k in peer_keys if k]
        if not keys:
            return stats
        query = query.filter(Contact.peer_key.in_(keys))
    contacts = query.all()
    stats["total"] = len(contacts)
    for contact in contacts:
        if (contact.peer_key or "").lower().endswith("@chatroom"):
            stats["missing"] += 1
            continue
        outcome = sync_contact_avatar(contact)
        stats[outcome] += 1
    if log and stats["total"]:
        log(
            f"头像：更新 {stats['updated']}，未变 {stats['skipped']}，"
            f"无缓存 {stats['missing']}"
        )
    return stats


def contact_has_avatar(contact: Contact | None) -> bool:
    return bool(contact and (contact.avatar_relpath or "").strip())
