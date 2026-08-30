from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.db import Base  # noqa: E402
from app.engine.group_roster import (  # noqa: E402
    SELF_KEY,
    apply_model_marks,
    build_member_graph,
    fill_missing_member_profiles,
    friend_name_keys,
    graph_for_prompt,
    group_timeline,
    is_group_contact,
    latest_group_profiles,
    list_groups,
    list_members,
    member_key,
    relation_graph,
    upsert_mark,
)
from app.models import Account, AnalysisJob, AnalysisResult, Contact, Conversation, Message  # noqa: E402


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed(db: Session) -> tuple[Contact, Contact]:
    account = Account(account_key="local", display_name="销售小王")
    db.add(account)
    db.flush()
    group = Contact(
        account_id=account.id,
        peer_key="123456@chatroom",
        nickname="二2班家长群",
        remark="",
    )
    person = Contact(
        account_id=account.id,
        peer_key="wxid_parent",
        nickname="李慧",
        remark="李慧",
    )
    db.add_all([group, person])
    db.flush()
    conv = Conversation(
        account_id=account.id,
        contact_id=group.id,
        started_at=datetime(2026, 8, 28, 9, 0),
        last_msg_at=datetime(2026, 8, 29, 18, 0),
        msg_count=4,
    )
    db.add(conv)
    db.flush()
    rows = [
        (datetime(2026, 8, 28, 9, 1), "customer", "张家长", "孩子下周能试听吗"),
        (datetime(2026, 8, 28, 9, 2), "cs", "me", "可以，我私发你档期"),
        (datetime(2026, 8, 29, 10, 0), "customer", "李慧", "报价发群里了吗"),
        (datetime(2026, 8, 29, 10, 1), "customer", "张家长", "价格多少"),
        (datetime(2026, 8, 29, 10, 2), "customer", "水群的", "哈哈"),
        (datetime(2026, 8, 29, 18, 0), "system", "[系统]", "张家长加入群聊"),
    ]
    for i, (when, role, name, text) in enumerate(rows, start=1):
        db.add(
            Message(
                conversation_id=conv.id,
                account_id=account.id,
                contact_id=group.id,
                msg_time=when,
                sender_role=role,
                sender_name=name,
                msg_type="text",
                content=text,
                raw_hash=f"h{i}",
            )
        )
    db.commit()
    return group, person


def test_is_group_contact_by_peer_key():
    assert is_group_contact(Contact(peer_key="1@chatroom"))
    assert not is_group_contact(Contact(peer_key="wxid_abc"))
    assert not is_group_contact(None)


def test_list_groups_and_active_members():
    db = _session()
    group, _ = _seed(db)
    groups = list_groups(db)
    assert len(groups) == 1
    assert groups[0]["name"] == "二2班家长群"
    assert groups[0]["member_count"] == 3
    members = list_members(db, group, min_msgs=1)
    names = {m["name"] for m in members}
    assert names == {"张家长", "李慧", "水群的"}
    assert all(m["name"] != "me" for m in members)
    zhang = next(m for m in members if m["name"] == "张家长")
    assert zhang["msg_count"] == 2
    assert zhang["activity"] == "low"
    li = next(m for m in members if m["name"] == "李慧")
    assert li["already_friend"] is True
    assert li["status"] == "already_friend"


def test_user_mark_not_overwritten_by_model():
    db = _session()
    group, _ = _seed(db)
    members = list_members(db, group)
    zhang = next(m for m in members if m["name"] == "张家长")
    upsert_mark(db, group.id, zhang["key"], name=zhang["name"], status="skip", note="广告", source="user")
    apply_model_marks(
        db,
        group.id,
        members,
        {"members": [{"name": "张家长", "add_friend": "recommend", "reason": "有意向"}]},
    )
    again = list_members(db, group)
    zhang2 = next(m for m in again if m["name"] == "张家长")
    assert zhang2["status"] == "skip"
    assert zhang2["source"] == "user"


def test_model_mark_and_friend_keys():
    db = _session()
    group, _ = _seed(db)
    members = list_members(db, group)
    apply_model_marks(
        db,
        group.id,
        members,
        {"members": [{"name": "张家长", "add_friend": "recommend", "reason": "问价格"}]},
    )
    again = list_members(db, group)
    zhang = next(m for m in again if m["name"] == "张家长")
    assert zhang["status"] == "recommend"
    assert zhang["source"] == "model"
    assert member_key("李慧") in friend_name_keys(db)
    li = next(m for m in again if m["name"] == "李慧")
    apply_model_marks(
        db,
        group.id,
        again,
        {"members": [{"name": "李慧", "add_friend": "recommend", "reason": "应加"}]},
    )
    li2 = next(m for m in list_members(db, group) if m["name"] == "李慧")
    assert li2["status"] == "already_friend"


def test_relation_graph_replies_mentions_and_self():
    db = _session()
    group, _ = _seed(db)
    members = list_members(db, group, min_msgs=1)
    graph = build_member_graph(db, group, members)
    keys = {n["key"] for n in graph["nodes"]}
    assert SELF_KEY in keys
    pairs = {(e["source"], e["target"]) for e in graph["edges"]}
    zhang = member_key("张家长")
    li = member_key("李慧")
    water = member_key("水群的")
    assert _pair(zhang, SELF_KEY) in pairs
    assert _pair(zhang, li) in pairs
    assert _pair(zhang, water) in pairs
    mention = relation_graph(
        [
            (datetime(2026, 8, 29, 11, 0), li, "李慧", "张家长报价发了吗"),
            (datetime(2026, 8, 29, 12, 0), zhang, "张家长", "好的"),
        ],
        members,
    )
    hit = next(e for e in mention["edges"] if _pair(e["source"], e["target"]) == _pair(zhang, li))
    assert hit["mentions"] >= 1
    text = graph_for_prompt(graph)
    assert "互动" in text
    assert "张家长" in text


def test_group_timeline_includes_self_skips_system():
    db = _session()
    group, _ = _seed(db)
    text, count = group_timeline(db, group, "", "")
    assert count == 6
    assert "我: 可以，我私发你档期" in text
    assert "张家长: 孩子下周能试听吗" in text
    assert "加入群聊" not in text
    day, day_count = group_timeline(db, group, "2026-08-29", "2026-08-29")
    assert "李慧" in day
    assert "我:" not in day
    assert day_count == 4


def test_latest_group_profiles_ignores_digest_jobs():
    db = _session()
    group, _ = _seed(db)
    digest = AnalysisJob(
        id="job-d",
        status="succeeded",
        kind="group",
        contact_id=group.id,
        report_type="daily",
        created_at=datetime(2026, 8, 30, 18, 0),
    )
    portrait = AnalysisJob(
        id="job-p",
        status="succeeded",
        kind="group",
        contact_id=group.id,
        report_type="portrait",
        created_at=datetime(2026, 8, 29, 10, 0),
    )
    db.add_all([digest, portrait])
    db.flush()
    db.add(
        AnalysisResult(
            job_id="job-d",
            title="日报",
            payload_json='{"headline":"今日","members":[{"name":"张家长","profile":"不该出现"}]}',
        )
    )
    db.add(
        AnalysisResult(
            job_id="job-p",
            title="画像",
            payload_json='{"members":[{"name":"张家长","profile":"问试听","add_friend":"recommend"}]}',
        )
    )
    db.commit()
    profiles = latest_group_profiles(db, group.id)
    assert profiles[member_key("张家长")]["profile"] == "问试听"


def test_latest_group_profiles_keeps_omitted_member_from_older_job():
    db = _session()
    group, _ = _seed(db)
    older = AnalysisJob(
        id="job-old",
        status="succeeded",
        kind="group",
        contact_id=group.id,
        report_type="portrait",
        created_at=datetime(2026, 8, 29, 10, 0),
    )
    newer = AnalysisJob(
        id="job-new",
        status="succeeded",
        kind="group",
        contact_id=group.id,
        report_type="portrait",
        created_at=datetime(2026, 8, 30, 10, 0),
    )
    db.add_all([older, newer])
    db.flush()
    db.add(
        AnalysisResult(
            job_id="job-old",
            title="旧",
            payload_json='{"members":[{"name":"张家长","profile":"问试听","reason":"报价"}]}',
        )
    )
    db.add(
        AnalysisResult(
            job_id="job-new",
            title="新",
            payload_json='{"members":[{"name":"李慧","profile":"已是好友"}]}',
        )
    )
    db.commit()
    profiles = latest_group_profiles(db, group.id)
    assert profiles[member_key("李慧")]["profile"] == "已是好友"
    assert profiles[member_key("张家长")]["profile"] == "问试听"


def test_fill_missing_member_profiles_copies_previous():
    members = [
        {"key": member_key("张家长"), "name": "张家长", "activity": "high"},
        {"key": member_key("李慧"), "name": "李慧", "activity": "mid"},
    ]
    parsed = {"members": [{"name": "李慧", "profile": "新结论"}]}
    previous = {member_key("张家长"): {"name": "张家长", "profile": "问试听", "reason": "报价"}}
    out = fill_missing_member_profiles(parsed, members, previous)
    names = {item["name"]: item["profile"] for item in out["members"]}
    assert names["张家长"] == "问试听"
    assert names["李慧"] == "新结论"


def test_digest_job_does_not_apply_marks(monkeypatch):
    from app.analyze.jobs import run_analysis_job
    from app.analyze.prompt_store import seed_default_prompts

    db = _session()
    group, _ = _seed(db)
    seed_default_prompts(db)
    job = AnalysisJob(
        id="job-digest",
        status="queued",
        kind="group",
        report_type="daily",
        contact_id=group.id,
        start_date="2026-08-29",
        end_date="2026-08-29",
    )
    db.add(job)
    db.commit()
    called = {"marks": 0}

    def fake_model(system, user):
        assert "群日报" in user or "日报" in user
        assert "add_friend" not in system
        return {"headline": "报价讨论", "summary": "李慧问报价", "highlights": [], "actions": ["私发档期"]}, 12

    def fake_marks(*args, **kwargs):
        called["marks"] += 1

    monkeypatch.setattr("app.analyze.jobs._call_model", fake_model)
    monkeypatch.setattr("app.analyze.jobs.apply_model_marks", fake_marks)
    monkeypatch.setattr("app.analyze.jobs.apply_persisted_settings", lambda _db: None)
    monkeypatch.setattr("app.analyze.jobs.model_config_error", lambda: None)
    run_analysis_job(db, job)
    assert job.status == "succeeded"
    assert called["marks"] == 0
    members = list_members(db, group)
    zhang = next(m for m in members if m["name"] == "张家长")
    assert zhang["status"] in ("watch", "already_friend")
    assert zhang["profile"] == ""


def _pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)
