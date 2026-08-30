from __future__ import annotations

import json
import re
from datetime import datetime

import httpx

from app.analyze.prompt_store import get_digest_prompt, get_prompt, resolve_prompt_body
from app.config import settings
from app.engine.group_roster import (
    apply_model_marks,
    build_member_graph,
    digest_prompt_stats,
    fill_missing_member_profiles,
    graph_for_prompt,
    group_prompt_stats,
    group_snippets,
    group_timeline,
    is_group_contact,
    latest_group_profiles,
    list_members,
)
from app.engine.report_stats import diagnostic_stats, stats_for_prompt
from app.engine.review import contact_label, contact_is_official
from app.engine.speakers import speaker_label
from app.models import Account, AnalysisJob, AnalysisResult, Contact, Conversation, Message
from app.settings_persist import apply_persisted_settings, model_config_error
from sqlalchemy.orm import Session


def make_result_title(when: datetime | None, prompt_name: str, extra: str = "") -> str:
    name = (prompt_name or "").strip() or "诊断报告"
    if extra:
        name = f"{name} · {extra}"
    if when:
        return f"{when:%Y-%m-%d %H:%M} · {name}"
    return name


def _conv_text(db: Session, conv: Conversation, limit: int = 40) -> str:
    contact = db.get(Contact, conv.contact_id)
    account = db.get(Account, conv.account_id)
    peer = contact_label(contact)
    header = f"[会话#{conv.id} 对方:{peer}]"
    msgs = (
        db.query(Message)
        .filter_by(conversation_id=conv.id, msg_type="text")
        .order_by(Message.msg_time.asc())
        .all()
    )
    if len(msgs) > limit:
        msgs = msgs[:10] + msgs[-30:]
    lines = [header]
    for m in msgs:
        who = speaker_label(
            role=m.sender_role,
            sender_name=m.sender_name or "",
            nickname=(contact.nickname if contact else "") or "",
            remark=(contact.remark if contact else "") or "",
            account_name=(account.display_name if account else "") or "",
        )
        lines.append(f"[{m.msg_time:%Y-%m-%d %H:%M}] {who}: {m.content}")
    return "\n".join(lines)


def _parse_model_json(content: str) -> dict:
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.I).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        return {"raw": content}


def set_job_progress(db: Session, job: AnalysisJob, pct: int, label: str = "") -> None:
    job.progress = max(0, min(100, int(pct)))
    job.progress_label = (label or "").strip()
    db.commit()


def _call_model(system: str, user: str) -> tuple[dict, int]:
    payload = {
        "model": settings.model_name,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
    }
    url = settings.model_base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {settings.model_api_key}"}
    with httpx.Client(timeout=120) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    content = data["choices"][0]["message"]["content"]
    usage = int((data.get("usage") or {}).get("total_tokens") or 0)
    return _parse_model_json(content), usage


def _fail(db: Session, job: AnalysisJob, message: str) -> None:
    job.status = "failed"
    job.error_message = message
    db.commit()


def job_report_type(job: AnalysisJob) -> str:
    raw = (job.report_type or "portrait").strip() or "portrait"
    return raw if raw in ("daily", "weekly", "portrait") else "portrait"


def run_analysis_job(db: Session, job: AnalysisJob) -> None:
    job.status = "running"
    set_job_progress(db, job, 12, "开始分析")
    apply_persisted_settings(db)
    missing = model_config_error()
    if missing:
        _fail(db, job, missing)
        return
    if (job.kind or "report") == "group":
        if job_report_type(job) in ("daily", "weekly"):
            _run_group_digest_job(db, job)
            return
        _run_group_job(db, job)
        return
    _run_report_job(db, job)


def _run_group_job(db: Session, job: AnalysisJob) -> None:
    contact = db.get(Contact, job.contact_id) if job.contact_id else None
    if not is_group_contact(contact):
        _fail(db, job, "请选择一个已同步的群")
        return
    set_job_progress(db, job, 28, "整理群成员")
    members = list_members(db, contact, job.start_date or "", job.end_date or "", min_msgs=1)
    if not members:
        _fail(db, job, "这个群在选定范围内没有发言成员")
        return
    previous = latest_group_profiles(db, contact.id)
    prompt = get_prompt(db, job.prompt_id, kind="group")
    system = resolve_prompt_body(prompt.body if prompt else "", kind="group")
    group_name = contact_label(contact) or contact.peer_key
    graph = build_member_graph(db, contact, members, job.start_date or "", job.end_date or "")
    user = (
        "【规则统计，写结论时引用这些数字，不要另编】\n"
        + group_prompt_stats(members)
        + "\n"
        + graph_for_prompt(graph)
        + "\n\n以下是群聊摘录：\n\n"
        + group_snippets(group_name, members)[:24000]
    )
    set_job_progress(db, job, 48, "调用模型")
    try:
        parsed, usage = _call_model(system, user)
        set_job_progress(db, job, 88, "整理结论")
        parsed = fill_missing_member_profiles(parsed, members, previous)
        apply_model_marks(db, contact.id, members, parsed)
        title = make_result_title(datetime.now(), prompt.name if prompt else "群画像", group_name)
        db.add(
            AnalysisResult(
                job_id=job.id,
                title=title,
                payload_json=json.dumps(parsed, ensure_ascii=False),
            )
        )
        job.token_usage = usage
        job.status = "succeeded"
        job.error_message = ""
        job.progress = 100
        job.progress_label = "已完成"
        db.commit()
    except Exception:
        _fail(db, job, "模型调用失败，请检查地址、模型名和额度")


def _run_group_digest_job(db: Session, job: AnalysisJob) -> None:
    contact = db.get(Contact, job.contact_id) if job.contact_id else None
    if not is_group_contact(contact):
        _fail(db, job, "请选择一个已同步的群")
        return
    report_type = job_report_type(job)
    set_job_progress(db, job, 28, "整理群消息")
    timeline, msg_count = group_timeline(db, contact, job.start_date or "", job.end_date or "")
    if msg_count == 0 or not timeline.strip():
        _fail(db, job, "这个群在选定范围内没有聊天")
        return
    members = list_members(db, contact, job.start_date or "", job.end_date or "", min_msgs=1)
    prompt = get_digest_prompt(db, job.prompt_id, report_type)
    system = resolve_prompt_body(prompt.body if prompt else "", kind="group_digest")
    group_name = contact_label(contact) or contact.peer_key
    period = "群日报" if report_type == "daily" else "群周报"
    window = (
        f"{job.start_date} 至 {job.end_date}"
        if job.start_date and job.end_date and job.start_date != job.end_date
        else (job.start_date or job.end_date or "")
    )
    user = (
        f"【这是{period}】范围：{window}\n"
        "【规则统计，写结论时引用这些数字，不要另编】\n"
        + digest_prompt_stats(members, msg_count, job.start_date or "", job.end_date or "")
        + "\n\n以下是群聊按时间摘录：\n\n"
        + timeline[:24000]
    )
    set_job_progress(db, job, 48, "调用模型")
    try:
        parsed, usage = _call_model(system, user)
        set_job_progress(db, job, 88, "整理结论")
        title = make_result_title(datetime.now(), prompt.name if prompt else period, group_name)
        db.add(
            AnalysisResult(
                job_id=job.id,
                title=title,
                payload_json=json.dumps(parsed, ensure_ascii=False),
            )
        )
        job.token_usage = usage
        job.status = "succeeded"
        job.error_message = ""
        job.progress = 100
        job.progress_label = "已完成"
        db.commit()
    except Exception:
        _fail(db, job, "模型调用失败，请检查地址、模型名和额度")


def _run_report_job(db: Session, job: AnalysisJob) -> None:
    q = db.query(Conversation)
    if job.account_id:
        q = q.filter(Conversation.account_id == job.account_id)
    if job.start_date:
        q = q.filter(Conversation.last_msg_at >= f"{job.start_date} 00:00:00")
    if job.end_date:
        q = q.filter(Conversation.started_at <= f"{job.end_date} 23:59:59")
    convs = []
    for conv in q.order_by(Conversation.last_msg_at.desc()).limit(80).all():
        if contact_is_official(db, db.get(Contact, conv.contact_id)):
            continue
        if is_group_contact(db.get(Contact, conv.contact_id)):
            continue
        convs.append(conv)
        if len(convs) >= 40:
            break
    if not convs:
        _fail(db, job, "选定范围内没有会话")
        return
    set_job_progress(db, job, 28, "整理会话")
    snippets = [_conv_text(db, conv) for conv in convs]
    stats = diagnostic_stats(db, job.start_date or "", job.end_date or "", job.account_id)
    prompt = get_prompt(db, job.prompt_id, kind="report")
    system = resolve_prompt_body(prompt.body if prompt else "", kind="report")
    set_job_progress(db, job, 48, "调用模型")
    try:
        parsed, usage = _call_model(
            system,
            (
                "【规则统计，写结论时引用这些数字，不要另编】\n"
                + stats_for_prompt(stats)
                + "\n\n以下是会话摘录：\n\n"
                + "\n\n----\n\n".join(snippets)[:24000]
            ),
        )
        set_job_progress(db, job, 88, "整理结论")
        title = make_result_title(datetime.now(), prompt.name if prompt else "")
        db.add(
            AnalysisResult(
                job_id=job.id,
                title=title,
                payload_json=json.dumps(parsed, ensure_ascii=False),
            )
        )
        job.token_usage = usage
        job.status = "succeeded"
        job.error_message = ""
        job.progress = 100
        job.progress_label = "已完成"
        db.commit()
    except Exception:
        _fail(db, job, "模型调用失败，请检查地址、模型名和额度")
