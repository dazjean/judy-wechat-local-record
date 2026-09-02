from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.db import Base  # noqa: E402
from app.ingest.media import backfill as media_backfill  # noqa: E402
from app.models import Account, Contact, Conversation, Message, SyncJob  # noqa: E402


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed_missing_image(
    db: Session,
    account: Account,
    peer_key: str = "wxid_judy",
    *,
    raw_hash: str = "hash-image-1",
    nickname: str = "朱迪",
) -> Message:
    contact = Contact(account_id=account.id, peer_key=peer_key, nickname=nickname, remark=nickname)
    db.add(contact)
    db.flush()
    conv = Conversation(
        account_id=account.id,
        contact_id=contact.id,
        started_at=datetime(2026, 9, 2, 10, 0, 0),
        last_msg_at=datetime(2026, 9, 2, 10, 0, 0),
        msg_count=1,
    )
    db.add(conv)
    db.flush()
    msg = Message(
        conversation_id=conv.id,
        account_id=account.id,
        contact_id=contact.id,
        msg_time=datetime(2026, 9, 2, 10, 0, 0),
        sender_role="customer",
        sender_name=nickname,
        msg_type="image",
        content="[图片]",
        media_status="missing",
        raw_hash=raw_hash,
        source_ref=f"{peer_key}|2026-09-02T10:00:00",
    )
    db.add(msg)
    db.commit()
    return msg


def test_message_needs_media():
    msg = Message(msg_type="image", media_status="missing", media_relpath="")
    assert media_backfill.message_needs_media(msg)
    msg2 = Message(msg_type="image", media_status="ready", media_relpath="image/a.png")
    assert not media_backfill.message_needs_media(msg2)
    msg3 = Message(msg_type="voice", media_status="ready", media_relpath="voice/a.mp3", media_mime="audio/silk")
    assert media_backfill.message_needs_media(msg3)


def test_list_contacts_for_backfill_respects_include():
    db = _session()
    account = Account(account_key="acc1", display_name="本机")
    db.add(account)
    db.commit()
    _seed_missing_image(db, account, "wxid_judy", raw_hash="hash-judy")
    _seed_missing_image(db, account, "wxid_other", raw_hash="hash-other", nickname="其他人")
    all_targets = media_backfill.list_contacts_for_backfill(db, account)
    assert len(all_targets) == 2
    only_judy = media_backfill.list_contacts_for_backfill(db, account, include_names="朱迪")
    assert len(only_judy) == 1
    assert only_judy[0][0].peer_key == "wxid_judy"


def test_apply_backfill_results_updates_message():
    msg = Message(
        msg_type="image",
        media_status="missing",
        media_relpath="",
        content="[图片]",
    )
    parsed = media_backfill.message_to_parsed(msg)
    parsed.media_relpath = "image/demo.png"
    parsed.media_name = "demo.png"
    parsed.media_mime = "image/png"
    parsed.media_status = "ready"
    fixed, still = media_backfill.apply_backfill_results([msg], [parsed])
    assert fixed == 1
    assert still == 0
    assert msg.media_relpath == "image/demo.png"
    assert msg.media_status == "ready"


def test_run_media_backfill_job_updates_db(monkeypatch):
    db = _session()
    account = Account(account_key="acc2", display_name="本机")
    db.add(account)
    db.commit()
    msg = _seed_missing_image(db, account, raw_hash="hash-backfill-run")
    job = SyncJob(id="job-media-1", status="queued", account_id=account.id, job_kind="media_backfill")
    db.add(job)
    db.commit()

    def fake_attach(items, peer_key):
        for item in items:
            item.media_relpath = "image/fake.png"
            item.media_name = "fake.png"
            item.media_mime = "image/png"
            item.media_status = "ready"
        return {"image": len(items), "voice": 0, "file": 0, "missing": 0}

    monkeypatch.setattr(media_backfill, "wechat_account_root", lambda: Path("/tmp/wechat"))
    monkeypatch.setattr(media_backfill, "attach_media", fake_attach)
    media_backfill.run_media_backfill_job(db, job)
    db.refresh(job)
    db.refresh(msg)
    assert job.status == "succeeded"
    assert job.written == 1
    assert msg.media_relpath == "image/fake.png"
    assert msg.media_status == "ready"
