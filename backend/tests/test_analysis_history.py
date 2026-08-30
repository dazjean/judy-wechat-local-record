from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.analyze.jobs import make_result_title  # noqa: E402
from app.analyze.prompt import SYSTEM_PROMPT, SYSTEM_PROMPT_SALES, SYSTEM_PROMPT_SOCIAL  # noqa: E402
from app.analyze.prompt_store import PRESET_PROMPTS, seed_default_prompts  # noqa: E402
from app.db import Base  # noqa: E402
from app.models import AnalysisJob, AnalysisResult, PromptTemplate  # noqa: E402


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_make_result_title_uses_date_and_scene():
    title = make_result_title(datetime(2026, 8, 29, 21, 47), "客服诊断报告")
    assert title == "2026-08-29 21:47 · 客服诊断报告"
    assert make_result_title(None, "") == "诊断报告"


def test_seed_three_presets_idempotent():
    db = _session()
    seed_default_prompts(db)
    seed_default_prompts(db)
    names = [row.name for row in db.query(PromptTemplate).order_by(PromptTemplate.id.asc()).all()]
    assert names.count("客服诊断报告") == 1
    assert names.count("销售诊断报告") == 1
    assert names.count("社交复盘") == 1
    assert names.count("销售·群好友加好友") == 1
    assert names.count("客服·群家长画像") == 1
    assert names.count("社交·群活跃关系") == 1
    assert names.count("群日报") == 1
    assert names.count("群周报") == 1
    report_default = db.query(PromptTemplate).filter_by(kind="report", is_default=True).one()
    group_default = db.query(PromptTemplate).filter_by(kind="group", is_default=True).one()
    digest_default = db.query(PromptTemplate).filter_by(kind="group_digest", is_default=True).one()
    assert report_default.name == "客服诊断报告"
    assert group_default.name == "销售·群好友加好友"
    assert digest_default.name == "群日报"
    assert [p["name"] for p in PRESET_PROMPTS][:3] == ["客服诊断报告", "销售诊断报告", "社交复盘"]


def test_seed_fills_missing_sales_and_social():
    db = _session()
    db.add(PromptTemplate(name="客服诊断报告", kind="report", body=SYSTEM_PROMPT, is_default=True, enabled=True))
    db.add(PromptTemplate(name="跟进清单", kind="scene", body="跟进", is_default=False, enabled=True))
    db.commit()
    seed_default_prompts(db)
    names = {row.name for row in db.query(PromptTemplate).all()}
    assert "销售诊断报告" in names
    assert "社交复盘" in names
    assert db.query(PromptTemplate).filter_by(name="客服诊断报告").count() == 1
    assert db.query(PromptTemplate).filter_by(kind="report", is_default=True).count() == 1
    assert db.query(PromptTemplate).filter_by(kind="group", is_default=True).one().name == "销售·群好友加好友"


def test_sales_and_social_prompts_share_contract_not_cs_scripts():
    assert "只返回 JSON" in SYSTEM_PROMPT_SALES
    assert "只返回 JSON" in SYSTEM_PROMPT_SOCIAL
    assert '"profile"' in SYSTEM_PROMPT_SALES
    assert "犹豫" in SYSTEM_PROMPT_SALES
    assert "退费" not in SYSTEM_PROMPT_SALES
    assert "家长" not in SYSTEM_PROMPT_SALES
    assert "家长" not in SYSTEM_PROMPT_SOCIAL
    assert "退费" not in SYSTEM_PROMPT_SOCIAL
    assert "私人往来" in SYSTEM_PROMPT_SOCIAL
    assert "不是客服" in SYSTEM_PROMPT_SOCIAL


def test_group_prompts_use_member_contract():
    from app.analyze.prompt import SYSTEM_PROMPT_GROUP_CS, SYSTEM_PROMPT_GROUP_SALES, SYSTEM_PROMPT_GROUP_SOCIAL
    from app.analyze.prompt_store import get_prompt, resolve_prompt_body, set_default

    for body in (SYSTEM_PROMPT_GROUP_SALES, SYSTEM_PROMPT_GROUP_CS, SYSTEM_PROMPT_GROUP_SOCIAL):
        assert "add_friend" in body
        assert '"members"' in body
        assert "不要漏掉" in body
    assert "加好友" in SYSTEM_PROMPT_GROUP_SALES
    assert "家长" in SYSTEM_PROMPT_GROUP_CS
    assert "销售漏斗" in SYSTEM_PROMPT_GROUP_SOCIAL
    assert "六个" not in SYSTEM_PROMPT_GROUP_SALES
    out = resolve_prompt_body("看群里谁值得加", kind="group")
    assert "看群里谁值得加" in out
    assert "add_friend" in out
    db = _session()
    seed_default_prompts(db)
    group = get_prompt(db, None, kind="group")
    report = get_prompt(db, None, kind="report")
    assert group.name == "销售·群好友加好友"
    assert report.name == "客服诊断报告"
    social = db.query(PromptTemplate).filter_by(name="社交·群活跃关系").one()
    set_default(db, social.id)
    assert get_prompt(db, None, kind="group").name == "社交·群活跃关系"
    assert get_prompt(db, None, kind="report").name == "客服诊断报告"


def test_digest_prompts_use_headline_contract():
    from datetime import date

    from app.analyze.prompt import SYSTEM_PROMPT_GROUP_DAILY, SYSTEM_PROMPT_GROUP_WEEKLY
    from app.analyze.prompt_store import get_digest_prompt, get_prompt, resolve_prompt_body
    from app.engine.group_roster import resolve_group_window

    for body in (SYSTEM_PROMPT_GROUP_DAILY, SYSTEM_PROMPT_GROUP_WEEKLY):
        assert '"headline"' in body
        assert '"highlights"' in body
        assert "add_friend" not in body
        assert '"members"' not in body
    out = resolve_prompt_body("写家长群日报，盯作业和投诉", kind="group_digest")
    assert "写家长群日报" in out
    assert '"headline"' in out
    db = _session()
    seed_default_prompts(db)
    assert get_digest_prompt(db, None, "daily").name == "群日报"
    assert get_digest_prompt(db, None, "weekly").name == "群周报"
    assert get_prompt(db, None, kind="group").name == "销售·群好友加好友"
    assert resolve_group_window("daily", "2026-08-01", "2026-08-30", today=date(2026, 8, 30)) == (
        "2026-08-30",
        "2026-08-30",
    )
    assert resolve_group_window("weekly", "", "", today=date(2026, 8, 30)) == ("2026-08-24", "2026-08-30")
    assert resolve_group_window("weekly", "2026-08-25", "2026-08-30", today=date(2026, 8, 30)) == (
        "2026-08-25",
        "2026-08-30",
    )
    assert resolve_group_window("weekly", "2026-07-01", "2026-08-30", today=date(2026, 8, 30)) == (
        "2026-08-24",
        "2026-08-30",
    )


def test_analysis_results_append_not_overwrite():
    db = _session()
    db.add(AnalysisJob(id="job-a", status="succeeded", start_date="2026-08-28", end_date="2026-08-28"))
    db.add(AnalysisJob(id="job-b", status="succeeded", start_date="2026-08-29", end_date="2026-08-29"))
    db.flush()
    db.add(
        AnalysisResult(
            job_id="job-a",
            title="2026-08-28 10:00 · 客服诊断报告",
            payload_json=json.dumps({"profile": {"title": "first"}}, ensure_ascii=False),
        )
    )
    db.add(
        AnalysisResult(
            job_id="job-b",
            title="2026-08-29 11:00 · 客服诊断报告",
            payload_json=json.dumps({"profile": {"title": "second"}}, ensure_ascii=False),
        )
    )
    db.commit()
    rows = db.query(AnalysisResult).order_by(AnalysisResult.id.asc()).all()
    assert len(rows) == 2
    assert json.loads(rows[0].payload_json)["profile"]["title"] == "first"
    assert json.loads(rows[1].payload_json)["profile"]["title"] == "second"
    assert rows[0].title != rows[1].title


def test_set_job_progress_clamps_and_labels():
    from app.analyze.jobs import set_job_progress

    db = _session()
    job = AnalysisJob(id="job-p", status="running")
    db.add(job)
    db.commit()
    set_job_progress(db, job, 150, "调用模型")
    assert job.progress == 100
    assert job.progress_label == "调用模型"
    set_job_progress(db, job, -4, "排队中")
    assert job.progress == 0
    assert job.progress_label == "排队中"
