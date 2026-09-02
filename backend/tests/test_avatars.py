from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.db import Base  # noqa: E402
from app.ingest.media import avatars as avatar_mod  # noqa: E402
from app.models import Account, Contact  # noqa: E402


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_sync_contact_avatar_updates_contact(monkeypatch):
    db = _session()
    account = Account(account_key="acc1", display_name="本机")
    db.add(account)
    db.flush()
    contact = Contact(
        account_id=account.id,
        peer_key="wxid_judy",
        nickname="朱迪",
        remark="朱迪",
    )
    db.add(contact)
    db.commit()

    blob = b"\xff\xd8\xff" + b"\x00" * 128
    monkeypatch.setattr(
        avatar_mod,
        "fetch_avatar_row",
        lambda username: (blob, "abc123", 100) if username == "wxid_judy" else None,
    )
    assert avatar_mod.sync_contact_avatar(contact) == "updated"
    assert contact.avatar_relpath.startswith("avatar/")
    assert contact.avatar_md5 == "abc123"
    assert avatar_mod.sync_contact_avatar(contact) == "skipped"


def test_sync_contact_avatars_skips_groups(monkeypatch):
    db = _session()
    account = Account(account_key="acc2", display_name="本机")
    db.add(account)
    db.flush()
    person = Contact(account_id=account.id, peer_key="wxid_a", nickname="A", remark="A")
    group = Contact(account_id=account.id, peer_key="room@chatroom", nickname="群", remark="群")
    db.add_all([person, group])
    db.commit()

    blob = b"\xff\xd8\xff" + b"\x00" * 64
    monkeypatch.setattr(
        avatar_mod,
        "fetch_avatar_row",
        lambda username: (blob, "md5", 1) if username == "wxid_a" else None,
    )
    stats = avatar_mod.sync_contact_avatars(db, account.id, peer_keys=["wxid_a", "room@chatroom"])
    assert stats["updated"] == 1
    assert stats["missing"] == 1
