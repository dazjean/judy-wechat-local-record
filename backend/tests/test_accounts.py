from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.accounts import (  # noqa: E402
    LOCAL_KEY,
    MissingWxid,
    UnknownAccount,
    get_or_create_account,
    migrate_local_accounts,
    resolve_account_scope,
)
from app.db import Base  # noqa: E402
from app.engine.group_roster import list_groups  # noqa: E402
from app.engine.radar import list_radar  # noqa: E402
from app.ingest.wechat_cli.parse import message_raw_hash, parse_history_lines  # noqa: E402
from app.models import (  # noqa: E402
    Account,
    AnalysisJob,
    AnalysisResult,
    Contact,
    Conversation,
    GroupMemberMark,
    HitRecord,
    Message,
    MetricDaily,
    SyncJob,
)


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _account(db: Session, key: str) -> Account:
    row = Account(account_key=key, display_name=key)
    db.add(row)
    db.flush()
    return row


def _chat(db: Session, account: Account, peer: str, raw_hash: str, content: str = "你好") -> Message:
    contact = Contact(account_id=account.id, peer_key=peer, nickname=peer, remark=peer)
    db.add(contact)
    db.flush()
    conv = Conversation(
        account_id=account.id,
        contact_id=contact.id,
        started_at=datetime(2026, 8, 1, 10, 0, 0),
        last_msg_at=datetime(2026, 8, 1, 10, 0, 0),
        msg_count=1,
    )
    db.add(conv)
    db.flush()
    msg = Message(
        conversation_id=conv.id,
        account_id=account.id,
        contact_id=contact.id,
        msg_time=datetime(2026, 8, 1, 10, 0, 0),
        sender_role="customer",
        sender_name=peer,
        content=content,
        raw_hash=raw_hash,
    )
    db.add(msg)
    db.flush()
    return msg


def test_get_or_create_rejects_local_and_empty():
    db = _session()
    try:
        get_or_create_account(db, "local")
        assert False
    except MissingWxid:
        pass
    try:
        get_or_create_account(db, "")
        assert False
    except MissingWxid:
        pass


def test_two_accounts_same_peer_keep_separate_rows():
    db = _session()
    a = _account(db, "wxid_cs_a")
    b = _account(db, "wxid_cs_b")
    _chat(db, a, "wxid_parent", "hash-same", "课时怎么退")
    _chat(db, b, "wxid_parent", "hash-same", "课时怎么退")
    db.commit()
    assert db.query(Contact).count() == 2
    assert db.query(Message).count() == 2
    assert db.query(Message).filter_by(account_id=a.id).count() == 1
    assert db.query(Message).filter_by(account_id=b.id).count() == 1
    groups_a = list_groups(db, account_id=a.id)
    groups_b = list_groups(db, account_id=b.id)
    assert groups_a == []
    assert groups_b == []
    radar_a = list_radar(db, account_id=a.id)
    radar_b = list_radar(db, account_id=b.id)
    assert radar_a["summary"]["customers"] == 1
    assert radar_b["summary"]["customers"] == 1
    assert radar_a["items"][0]["contact"]
    mixed = list_radar(db)
    assert mixed["summary"]["customers"] == 2


def test_migrate_renames_local_to_current_wxid():
    db = _session()
    local = Account(account_key=LOCAL_KEY, display_name="本机客服")
    db.add(local)
    db.flush()
    _chat(db, local, "wxid_friend", "h1")
    db.commit()
    out = migrate_local_accounts(db, "nxss11_c6ad")
    db.commit()
    assert out.account_key == "nxss11_c6ad"
    assert db.query(Account).filter_by(account_key=LOCAL_KEY).count() == 0
    assert db.query(Message).filter_by(account_id=out.id).count() == 1


def test_migrate_merges_local_into_existing_wxid():
    db = _session()
    target = _account(db, "wxid_cs")
    _chat(db, target, "wxid_old", "h-old")
    local = Account(account_key=LOCAL_KEY, display_name="本机")
    db.add(local)
    db.flush()
    _chat(db, local, "wxid_new", "h-new")
    db.commit()
    out = migrate_local_accounts(db, "wxid_cs")
    db.commit()
    assert out.id == target.id
    assert db.query(Account).count() == 1
    assert db.query(Contact).filter_by(account_id=target.id).count() == 2
    assert db.query(Message).filter_by(account_id=target.id).count() == 2


def test_migrate_waits_when_wxid_unknown():
    db = _session()
    local = Account(account_key=LOCAL_KEY, display_name="本机")
    db.add(local)
    db.commit()
    out = migrate_local_accounts(db, "")
    assert out.account_key == LOCAL_KEY


def test_resolve_scope_never_means_all(monkeypatch):
    db = _session()
    a = _account(db, "wxid_a")
    b = _account(db, "wxid_b")
    db.commit()
    monkeypatch.setattr("app.accounts.current_account_key", lambda: "wxid_a")
    assert resolve_account_scope(db, None).id == a.id
    assert resolve_account_scope(db, b.id).id == b.id
    try:
        resolve_account_scope(db, 99999)
        assert False
    except UnknownAccount:
        pass


def test_reset_keeps_account_rows():
    db = _session()
    acc = _account(db, "wxid_keep")
    _chat(db, acc, "wxid_friend", "h1")
    db.add(SyncJob(id="s1", status="succeeded", account_id=acc.id))
    db.add(AnalysisJob(id="j1", status="succeeded", account_id=acc.id))
    db.flush()
    db.add(AnalysisResult(job_id="j1", title="t", payload_json="{}"))
    db.commit()
    for model in (
        HitRecord,
        GroupMemberMark,
        Message,
        Conversation,
        AnalysisResult,
        AnalysisJob,
        MetricDaily,
        Contact,
        SyncJob,
    ):
        db.query(model).delete(synchronize_session=False)
    db.commit()
    assert db.query(Account).count() == 1
    assert db.query(Account).one().account_key == "wxid_keep"
    assert db.query(Message).count() == 0


def test_hash_includes_account_key():
    lines = ["[2026-08-01 09:00] 家长: 你好"]
    plain = parse_history_lines(lines, "peer-a")
    keyed_a = parse_history_lines(lines, "peer-a", account_key="wxid_a")
    keyed_b = parse_history_lines(lines, "peer-a", account_key="wxid_b")
    assert plain[0].raw_hash != keyed_a[0].raw_hash
    assert keyed_a[0].raw_hash != keyed_b[0].raw_hash
    assert keyed_a[0].raw_hash == message_raw_hash(
        "peer-a",
        keyed_a[0].msg_time,
        keyed_a[0].sender_role,
        keyed_a[0].sender_name,
        keyed_a[0].content,
        account_key="wxid_a",
    )
