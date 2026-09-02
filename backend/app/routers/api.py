from __future__ import annotations

import json
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from openpyxl import Workbook
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.accounts import (
    MissingWxid,
    UnknownAccount,
    account_public,
    current_account,
    current_account_key,
    last_account_key,
    migrate_local_accounts,
    resolve_account_scope,
)
from app.analyze.jobs import job_report_type, make_result_title, run_analysis_job
from app.analyze.prompt_generate import generate_prompt_body
from app.analyze.prompt_store import PROMPT_KINDS, get_digest_prompt, get_prompt, seed_default_prompts, set_default
from app.settings_persist import apply_persisted_settings, clamp_limit_per_contact
from app.config import settings
from app.db import SessionLocal, get_db
from app.storage_paths import default_data_dir, override_source, resolve_data_dir, save_data_dir
from app.engine.group_roster import (
    ADD_STATUS,
    STATUS_LABEL,
    build_member_graph,
    is_group_contact,
    list_groups,
    list_members,
    resolve_group_window,
    upsert_mark,
)
from app.engine.metrics import run_rule_scan
from app.engine.radar import list_radar
from app.engine.report_stats import diagnostic_stats
from app.engine.review import (
    annotate_conversation,
    contact_is_official,
    contact_label,
    export_filename,
    flag_text,
    format_clock,
    format_seconds,
    last_sync_info,
    list_daily_messages,
    list_review_items,
    list_review_page,
    timeout_items,
)
from app.engine.speakers import PLACEHOLDER_SELF, speaker_label
from app.ingest.auto_sync import auto_sync_status, clamp_minutes, current_sync_job, enqueue_sync, sync_busy
from app.ingest.media import clear_media_dir, resolve_media_path
from app.ingest.media.self_account import (
    SelfProfile,
    apply_self_profile,
    current_folder_wxid,
    read_self_profile,
)
from app.ingest.wechat_cli.runner import probe_status
from app.license import evaluate
from app.logutil import read_sync_log
from app.product import DEFAULT_SELF_NAME, PRODUCT_NAME, PRODUCT_TAGLINE, PRODUCT_VERSION
from app.restart import schedule_restart
from app.models import (
    Account,
    AnalysisJob,
    AnalysisResult,
    AppSetting,
    Contact,
    Conversation,
    GroupMemberMark,
    HitRecord,
    Lexicon,
    Message,
    MetricDaily,
    PromptTemplate,
    SyncJob,
)

router = APIRouter()


def _scope_account(db: Session, account_id: int | None = None) -> Account | None:
    try:
        return resolve_account_scope(db, account_id)
    except UnknownAccount:
        raise HTTPException(404, "账号不存在") from None


def _scope_id(db: Session, account_id: int | None = None) -> int | None:
    acc = _scope_account(db, account_id)
    return acc.id if acc else None


class SettingOut(BaseModel):
    timeout_seconds: int
    session_gap_hours: int
    model_base_url: str
    model_name: str
    model_key_configured: bool
    self_nickname: str = ""
    wechat_account: str = ""
    wechat_wxid: str = ""
    db_path: str = ""
    data_dir: str = ""
    data_dir_default: str = ""
    data_dir_next: str = ""
    data_dir_source: str = "default"
    data_dir_locked: bool = False
    data_dir_restart_required: bool = False
    sync_include_groups: bool
    sync_exclude_names: str
    sync_include_names: str = ""
    sync_limit_people_enabled: bool
    sync_limit_people: int
    sync_limit_per_contact: int = 1000
    sync_limit_per_group: int = 1000
    sync_days: int = 14
    sync_auto_enabled: bool = False
    sync_auto_minutes: int = 15
    sync_watch_enabled: bool = False


class SettingIn(BaseModel):
    timeout_seconds: int | None = None
    session_gap_hours: int | None = None
    model_base_url: str | None = None
    model_name: str | None = None
    model_api_key: str | None = None
    self_nickname: str | None = None
    data_dir: str | None = None
    sync_include_groups: bool | None = None
    sync_exclude_names: str | None = None
    sync_include_names: str | None = None
    sync_limit_people_enabled: bool | None = None
    sync_limit_people: int | None = None
    sync_limit_per_contact: int | None = None
    sync_limit_per_group: int | None = None
    sync_days: int | None = None
    sync_auto_enabled: bool | None = None
    sync_auto_minutes: int | None = None
    sync_watch_enabled: bool | None = None


class LexiconIn(BaseModel):
    kind: str = "forbidden"
    term: str
    enabled: bool = True


class LexiconPatch(BaseModel):
    kind: str | None = None
    term: str | None = None
    enabled: bool | None = None


class SyncIn(BaseModel):
    days: int = Field(default=14, ge=1, le=90)
    limit_per_contact: int = Field(default=1000, ge=50, le=5000)
    limit_per_group: int = Field(default=1000, ge=50, le=5000)
    include_groups: bool = False
    exclude_names: str = ""
    include_names: str = ""
    limit_people_enabled: bool = True
    limit_people: int = Field(default=20, ge=1, le=300)


class AnalysisIn(BaseModel):
    account_id: int | None = None
    start_date: str = ""
    end_date: str = ""
    prompt_id: int | None = None
    kind: str = "report"
    contact_id: int | None = None
    report_type: str = "portrait"


class PromptIn(BaseModel):
    name: str
    kind: str = "scene"
    body: str = ""
    enabled: bool = True
    is_default: bool = False


class PromptPatch(BaseModel):
    name: str | None = None
    kind: str | None = None
    body: str | None = None
    enabled: bool | None = None
    is_default: bool | None = None


class PromptGenerateIn(BaseModel):
    brief: str = ""
    kind: str = "report"


class MemberMarkIn(BaseModel):
    member_key: str
    member_name: str = ""
    status: str
    note: str = ""


def _seed_lexicon(db: Session) -> None:
    if db.query(Lexicon).count():
        return
    for term in ("绝对能考上", "保证过", "骗子", "滚"):
        db.add(Lexicon(kind="forbidden", term=term, enabled=True))
    db.commit()


def _storage_fields() -> dict[str, object]:
    current = settings.data_dir.resolve()
    nxt = resolve_data_dir(env_value=settings.judy_data_dir).resolve()
    source = override_source(env_value=settings.judy_data_dir)
    return {
        "db_path": str(settings.db_path.resolve()),
        "data_dir": str(current),
        "data_dir_default": str(default_data_dir().resolve()),
        "data_dir_next": str(nxt),
        "data_dir_source": source,
        "data_dir_locked": source == "env",
        "data_dir_restart_required": current != nxt,
    }


@router.get("/health")
def health():
    return {"ok": True, "name": PRODUCT_NAME, "tagline": PRODUCT_TAGLINE, "version": PRODUCT_VERSION}


@router.get("/license")
def license_status(db: Session = Depends(get_db)):
    profile = _refresh_wechat_account(db)
    status = evaluate(username=current_folder_wxid())
    return status.as_dict()


def _self_nickname(db: Session) -> str:
    account = current_account(db, create=False)
    name = (account.display_name if account else "") or ""
    if name in PLACEHOLDER_SELF:
        return ""
    return name


def _set_self_nickname(db: Session, name: str) -> None:
    clean = (name or "").strip()
    key = current_account_key()
    account = current_account(db, create=bool(key))
    if not account:
        return
    account.display_name = clean or DEFAULT_SELF_NAME


def _refresh_wechat_account(db: Session) -> SelfProfile:
    try:
        profile = read_self_profile()
    except Exception:
        profile = SelfProfile()
    migrate_local_accounts(db, current_account_key())
    key = current_account_key()
    if key:
        account = current_account(db, create=True)
        apply_self_profile(account, profile)
    db.commit()
    return profile


def _wechat_account_label(db: Session, profile: SelfProfile | None = None) -> str:
    if profile and profile.display_account():
        return profile.display_account()
    account = current_account(db, create=False)
    return ((account.wx_username if account else "") or "").strip()


def _wechat_wxid(db: Session, profile: SelfProfile | None = None) -> str:
    return current_folder_wxid()


def _prompt_out(row: PromptTemplate) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "kind": row.kind,
        "body": row.body,
        "is_default": row.is_default,
        "enabled": row.enabled,
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


def _message_speaker(db: Session, m: Message) -> str:
    contact = db.get(Contact, m.contact_id)
    account = db.get(Account, m.account_id)
    return speaker_label(
        role=m.sender_role,
        sender_name=m.sender_name or "",
        nickname=(contact.nickname if contact else "") or "",
        remark=(contact.remark if contact else "") or "",
        account_name=(account.display_name if account else "") or "",
    )


@router.get("/settings", response_model=SettingOut)
def get_settings(db: Session = Depends(get_db)):
    profile = _refresh_wechat_account(db)
    return SettingOut(
        timeout_seconds=settings.timeout_seconds,
        session_gap_hours=settings.session_gap_hours,
        model_base_url=settings.model_base_url,
        model_name=settings.model_name,
        model_key_configured=bool(settings.model_api_key),
        self_nickname=_self_nickname(db),
        wechat_account=_wechat_account_label(db, profile),
        wechat_wxid=_wechat_wxid(db, profile),
        **_storage_fields(),
        sync_include_groups=settings.sync_include_groups,
        sync_exclude_names=settings.sync_exclude_names,
        sync_include_names=settings.sync_include_names,
        sync_limit_people_enabled=settings.sync_limit_people_enabled,
        sync_limit_people=settings.sync_limit_people,
        sync_limit_per_contact=clamp_limit_per_contact(settings.sync_limit_per_contact),
        sync_limit_per_group=clamp_limit_per_contact(settings.sync_limit_per_group),
        sync_days=settings.sync_days,
        sync_auto_enabled=settings.sync_auto_enabled,
        sync_auto_minutes=clamp_minutes(settings.sync_auto_minutes),
        sync_watch_enabled=settings.sync_watch_enabled,
    )


@router.put("/settings", response_model=SettingOut)
def put_settings(body: SettingIn, db: Session = Depends(get_db)):
    if body.timeout_seconds is not None:
        settings.timeout_seconds = body.timeout_seconds
        _upsert_setting(db, "timeout_seconds", str(body.timeout_seconds))
    if body.session_gap_hours is not None:
        settings.session_gap_hours = body.session_gap_hours
        _upsert_setting(db, "session_gap_hours", str(body.session_gap_hours))
    if body.model_base_url is not None:
        settings.model_base_url = body.model_base_url.strip()
        _upsert_setting(db, "model_base_url", settings.model_base_url)
    if body.model_name is not None:
        settings.model_name = body.model_name.strip()
        _upsert_setting(db, "model_name", settings.model_name)
    if body.model_api_key is not None:
        key = body.model_api_key.strip()
        if key:
            settings.model_api_key = key
            _upsert_setting(db, "model_api_key", key)
    if body.self_nickname is not None:
        _set_self_nickname(db, body.self_nickname)
    if body.data_dir is not None:
        if override_source(env_value=settings.judy_data_dir) == "env":
            raise HTTPException(status_code=400, detail="当前由环境变量 JUDY_DATA_DIR 指定，无法在页面修改")
        try:
            save_data_dir(body.data_dir)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if body.sync_include_groups is not None:
        settings.sync_include_groups = body.sync_include_groups
        _upsert_setting(db, "sync_include_groups", "1" if body.sync_include_groups else "0")
    if body.sync_exclude_names is not None:
        settings.sync_exclude_names = body.sync_exclude_names
        _upsert_setting(db, "sync_exclude_names", body.sync_exclude_names)
    if body.sync_include_names is not None:
        settings.sync_include_names = body.sync_include_names
        _upsert_setting(db, "sync_include_names", body.sync_include_names)
    if body.sync_limit_people_enabled is not None:
        settings.sync_limit_people_enabled = body.sync_limit_people_enabled
        _upsert_setting(db, "sync_limit_people_enabled", "1" if body.sync_limit_people_enabled else "0")
    if body.sync_limit_people is not None:
        settings.sync_limit_people = max(1, min(int(body.sync_limit_people), 300))
        _upsert_setting(db, "sync_limit_people", str(settings.sync_limit_people))
    if body.sync_limit_per_contact is not None:
        settings.sync_limit_per_contact = clamp_limit_per_contact(body.sync_limit_per_contact)
        _upsert_setting(db, "sync_limit_per_contact", str(settings.sync_limit_per_contact))
    if body.sync_limit_per_group is not None:
        settings.sync_limit_per_group = clamp_limit_per_contact(body.sync_limit_per_group)
        _upsert_setting(db, "sync_limit_per_group", str(settings.sync_limit_per_group))
    if body.sync_days is not None:
        settings.sync_days = max(1, min(int(body.sync_days), 90))
        _upsert_setting(db, "sync_days", str(settings.sync_days))
    if body.sync_auto_enabled is not None:
        settings.sync_auto_enabled = body.sync_auto_enabled
        _upsert_setting(db, "sync_auto_enabled", "1" if body.sync_auto_enabled else "0")
    if body.sync_auto_minutes is not None:
        settings.sync_auto_minutes = clamp_minutes(body.sync_auto_minutes)
        _upsert_setting(db, "sync_auto_minutes", str(settings.sync_auto_minutes))
    if body.sync_watch_enabled is not None:
        settings.sync_watch_enabled = body.sync_watch_enabled
        _upsert_setting(db, "sync_watch_enabled", "1" if body.sync_watch_enabled else "0")
    db.commit()
    return get_settings(db)


@router.post("/restart")
def restart_app():
    schedule_restart()
    return {"ok": True, "message": "正在重启"}


@router.post("/settings/reveal-data")
def reveal_data_dir():
    import subprocess
    import sys

    path = settings.data_dir
    path.mkdir(parents=True, exist_ok=True)
    target = str(path)
    if sys.platform == "darwin":
        subprocess.Popen(["open", target])
    elif sys.platform == "win32":
        subprocess.Popen(["explorer", target])
    else:
        subprocess.Popen(["xdg-open", target])
    return {"ok": True}


def _upsert_setting(db: Session, key: str, value: str) -> None:
    row = db.get(AppSetting, key)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))


@router.get("/lexicon")
def list_lexicon(db: Session = Depends(get_db)):
    _seed_lexicon(db)
    rows = db.query(Lexicon).order_by(Lexicon.id.asc()).all()
    return [
        {"id": r.id, "kind": r.kind, "term": r.term, "enabled": r.enabled}
        for r in rows
    ]


@router.post("/lexicon")
def add_lexicon(body: LexiconIn, db: Session = Depends(get_db)):
    row = Lexicon(kind=body.kind, term=body.term.strip(), enabled=body.enabled)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "kind": row.kind, "term": row.term, "enabled": row.enabled}


@router.patch("/lexicon/{item_id}")
def patch_lexicon(item_id: int, body: LexiconPatch, db: Session = Depends(get_db)):
    row = db.get(Lexicon, item_id)
    if not row:
        raise HTTPException(404, "词条不存在")
    if body.kind is not None:
        row.kind = body.kind
    if body.term is not None:
        row.term = body.term.strip()
    if body.enabled is not None:
        row.enabled = body.enabled
    db.commit()
    return {"id": row.id, "kind": row.kind, "term": row.term, "enabled": row.enabled}


@router.get("/prompts")
def list_prompts(db: Session = Depends(get_db)):
    seed_default_prompts(db)
    rows = db.query(PromptTemplate).order_by(PromptTemplate.id.asc()).all()
    return [_prompt_out(r) for r in rows]


@router.post("/prompts")
def add_prompt(body: PromptIn, db: Session = Depends(get_db)):
    seed_default_prompts(db)
    kind = body.kind if body.kind in PROMPT_KINDS else "scene"
    row = PromptTemplate(
        name=(body.name or "").strip() or "未命名场景",
        kind=kind,
        body=body.body or "",
        enabled=body.enabled,
        is_default=False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    if body.is_default:
        row = set_default(db, row.id)
    return _prompt_out(row)


@router.patch("/prompts/{item_id}")
def patch_prompt(item_id: int, body: PromptPatch, db: Session = Depends(get_db)):
    row = db.get(PromptTemplate, item_id)
    if not row:
        raise HTTPException(404, "提示词不存在")
    if body.name is not None:
        row.name = body.name.strip() or row.name
    if body.kind is not None and body.kind in PROMPT_KINDS:
        row.kind = body.kind
    if body.body is not None:
        row.body = body.body
    if body.enabled is not None:
        if row.is_default and not body.enabled:
            raise HTTPException(400, "默认提示词不能停用")
        row.enabled = body.enabled
    db.commit()
    db.refresh(row)
    if body.is_default:
        row = set_default(db, row.id)
    return _prompt_out(row)


@router.delete("/prompts/{item_id}")
def delete_prompt(item_id: int, db: Session = Depends(get_db)):
    row = db.get(PromptTemplate, item_id)
    if not row:
        raise HTTPException(404, "提示词不存在")
    if row.is_default:
        raise HTTPException(400, "默认提示词不能删除，请先把另一条设为默认")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.post("/prompts/generate")
def generate_prompt(body: PromptGenerateIn, db: Session = Depends(get_db)):
    apply_persisted_settings(db)
    try:
        text = generate_prompt_body(body.brief, kind=body.kind if body.kind in PROMPT_KINDS else "report")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"body": text}


@router.get("/accounts")
def list_accounts(db: Session = Depends(get_db)):
    _refresh_wechat_account(db)
    current_key = current_account_key()
    last_key = last_account_key(db)
    rows = db.query(Account).order_by(Account.id.asc()).all()
    out = []
    for row in rows:
        item = account_public(row, current_key=current_key, last_key=last_key)
        item["conversation_count"] = db.query(Conversation).filter_by(account_id=row.id).count()
        item["message_count"] = db.query(Message).filter_by(account_id=row.id).count()
        out.append(item)
    return out


@router.get("/wechat/status")
def wechat_status(db: Session = Depends(get_db)):
    status = probe_status()
    profile = _refresh_wechat_account(db)
    evaluate(username=current_folder_wxid())
    status["wechat_account"] = _wechat_account_label(db, profile)
    status["wechat_wxid"] = _wechat_wxid(db, profile)
    account = current_account(db, create=False)
    status["account_id"] = account.id if account else None
    status["account_key"] = account.account_key if account else current_account_key()
    job = current_sync_job(db)
    status["last_sync"] = last_sync_info(db)
    status["auto_sync"] = auto_sync_status(db)
    status["sync_job_id"] = job.id if job else ""
    status["sync_job_status"] = job.status if job else ""
    return status


@router.post("/data/reset")
def reset_data(db: Session = Depends(get_db)):
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
    clear_media_dir()
    if settings.logs_dir.is_dir():
        for path in settings.logs_dir.glob("sync-*.log"):
            try:
                path.unlink()
            except OSError:
                pass
    return {"ok": True, "message": "已清空会话、消息、统计和分析结果"}


@router.get("/groups")
def groups_index(
    db: Session = Depends(get_db),
    start_date: str = "",
    end_date: str = "",
    q: str = "",
    account_id: int | None = None,
):
    scoped = _scope_id(db, account_id)
    if scoped is None:
        return {"items": []}
    return {"items": list_groups(db, start_date, end_date, q, account_id=scoped)}


@router.get("/groups/{contact_id}")
def group_detail(
    contact_id: int,
    db: Session = Depends(get_db),
    start_date: str = "",
    end_date: str = "",
    min_msgs: int = Query(default=1, ge=1, le=50),
    account_id: int | None = None,
):
    scoped = _scope_id(db, account_id)
    contact = db.get(Contact, contact_id)
    if not is_group_contact(contact) or scoped is None or contact.account_id != scoped:
        raise HTTPException(404, "群不存在")
    members = list_members(db, contact, start_date, end_date, min_msgs)
    groups = [g for g in list_groups(db, start_date, end_date, account_id=scoped) if g["id"] == contact_id]
    info = groups[0] if groups else {
        "id": contact.id,
        "name": contact_label(contact),
        "peer_key": contact.peer_key,
        "msg_count": 0,
        "member_count": len(members),
        "last_msg_at": "",
        "conversation_id": None,
    }
    summary = {
        "members": len(members),
        "active": sum(1 for m in members if m["activity"] in ("high", "mid")),
        "recommend": sum(1 for m in members if m["status"] == "recommend"),
        "already_friend": sum(1 for m in members if m["status"] == "already_friend" or m["already_friend"]),
        "watch": sum(1 for m in members if m["status"] == "watch"),
        "skip": sum(1 for m in members if m["status"] == "skip"),
        "added": sum(1 for m in members if m["status"] == "added"),
    }
    graph = build_member_graph(db, contact, members, start_date, end_date)
    return {
        "group": info,
        "summary": summary,
        "members": members,
        "graph": graph,
        "status_options": [{"value": k, "label": STATUS_LABEL[k]} for k in ADD_STATUS],
    }


@router.patch("/groups/{contact_id}/members")
def patch_group_member(
    contact_id: int,
    body: MemberMarkIn,
    db: Session = Depends(get_db),
    account_id: int | None = None,
):
    scoped = _scope_id(db, account_id)
    contact = db.get(Contact, contact_id)
    if not is_group_contact(contact) or scoped is None or contact.account_id != scoped:
        raise HTTPException(404, "群不存在")
    try:
        row = upsert_mark(
            db,
            contact_id,
            body.member_key,
            name=body.member_name,
            status=body.status,
            note=body.note,
            source="user",
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return {
        "key": row.member_key,
        "name": row.member_name,
        "status": row.status,
        "status_label": STATUS_LABEL.get(row.status, row.status),
        "note": row.note,
        "source": row.source,
    }


def _persist_sync_scope(db: Session, body: SyncIn) -> None:
    settings.sync_include_groups = body.include_groups
    settings.sync_exclude_names = body.exclude_names
    settings.sync_include_names = body.include_names
    settings.sync_limit_people_enabled = body.limit_people_enabled
    settings.sync_limit_people = body.limit_people
    settings.sync_limit_per_contact = clamp_limit_per_contact(body.limit_per_contact)
    settings.sync_limit_per_group = clamp_limit_per_contact(body.limit_per_group)
    settings.sync_days = max(1, min(int(body.days), 90))
    _upsert_setting(db, "sync_include_groups", "1" if body.include_groups else "0")
    _upsert_setting(db, "sync_exclude_names", body.exclude_names)
    _upsert_setting(db, "sync_include_names", body.include_names)
    _upsert_setting(db, "sync_limit_people_enabled", "1" if body.limit_people_enabled else "0")
    _upsert_setting(db, "sync_limit_people", str(body.limit_people))
    _upsert_setting(db, "sync_limit_per_contact", str(settings.sync_limit_per_contact))
    _upsert_setting(db, "sync_limit_per_group", str(settings.sync_limit_per_group))
    _upsert_setting(db, "sync_days", str(settings.sync_days))


def _sync_job_item(job: SyncJob) -> dict:
    return {
        "id": job.id,
        "status": job.status,
        "start_date": job.start_date or "",
        "total_contacts": job.total_contacts,
        "ok_contacts": job.ok_contacts,
        "written": job.written,
        "skipped": job.skipped,
        "error_message": job.error_message or "",
        "created_at": job.created_at.isoformat() if job.created_at else "",
        "updated_at": job.updated_at.isoformat() if job.updated_at else "",
    }


@router.post("/wechat/sync")
def start_sync(body: SyncIn, db: Session = Depends(get_db)):
    if sync_busy(db):
        raise HTTPException(409, "已有同步任务在进行，请稍后再试")
    _persist_sync_scope(db, body)
    try:
        job = enqueue_sync(
            db,
            days=body.days,
            reason="手动同步开始",
            limit_per_contact=body.limit_per_contact,
            limit_per_group=body.limit_per_group,
        )
    except MissingWxid as exc:
        raise HTTPException(400, str(exc)) from None
    if not job:
        raise HTTPException(409, "已有同步任务在进行，请稍后再试")
    return {
        "id": job.id,
        "status": job.status,
        "total_contacts": 0,
        "ok_contacts": 0,
        "written": 0,
        "skipped": 0,
        "error_message": "",
        "log": "",
    }


@router.get("/wechat/sync")
def list_sync_jobs(db: Session = Depends(get_db), limit: int = Query(40, ge=1, le=100)):
    rows = db.query(SyncJob).order_by(SyncJob.created_at.desc()).limit(limit).all()
    return {"items": [_sync_job_item(row) for row in rows]}


@router.get("/wechat/sync/{job_id}")
def get_sync(job_id: str, db: Session = Depends(get_db)):
    job = db.get(SyncJob, job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    return JSONResponse(
        {
            **_sync_job_item(job),
            "log": read_sync_log(job.id),
        },
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@router.get("/conversations")
def list_conversations(
    db: Session = Depends(get_db),
    account_id: int | None = None,
    start_date: str = "",
    end_date: str = "",
    q: str = "",
    flag: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    scoped = _scope_id(db, account_id)
    if scoped is None:
        return {"total": 0, "items": []}
    items, total = list_review_page(
        db,
        account_id=scoped,
        start_date=start_date,
        end_date=end_date,
        q=q,
        flag=flag,
        page=page,
        page_size=page_size,
    )
    return {"total": total, "items": items}


@router.get("/radar")
def customer_radar(
    db: Session = Depends(get_db),
    start_date: str = "",
    end_date: str = "",
    status: str = "",
    account_id: int | None = None,
):
    scoped = _scope_id(db, account_id)
    if scoped is None:
        return {"summary": {}, "items": []}
    return list_radar(db, start_date=start_date, end_date=end_date, status=status, account_id=scoped)


@router.get("/conversations/daily/messages")
def daily_conv_messages(
    contact_id: int = Query(..., ge=1),
    day: str = Query(..., min_length=10, max_length=10),
    db: Session = Depends(get_db),
    account_id: int | None = None,
):
    scoped = _scope_id(db, account_id)
    if scoped is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    rows = list_daily_messages(db, contact_id=contact_id, day=day, account_id=scoped)
    if rows is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return [
        {
            "id": m.id,
            "msg_time": m.msg_time.isoformat(),
            "sender_role": m.sender_role,
            "sender_name": m.sender_name,
            "speaker": _message_speaker(db, m),
            "msg_type": m.msg_type,
            "content": m.content,
            "media_name": m.media_name,
            "media_mime": m.media_mime,
            "media_status": m.media_status,
            "has_media": bool(m.media_relpath),
        }
        for m in rows
    ]


@router.get("/conversations/{conv_id}")
def get_conversation(conv_id: int, db: Session = Depends(get_db), account_id: int | None = None):
    conv = db.get(Conversation, conv_id)
    scoped = _scope_id(db, account_id)
    if not conv or scoped is None or conv.account_id != scoped:
        raise HTTPException(status_code=404, detail="会话不存在")
    return annotate_conversation(db, conv)


@router.get("/conversations/{conv_id}/messages")
def conv_messages(conv_id: int, db: Session = Depends(get_db), account_id: int | None = None):
    conv = db.get(Conversation, conv_id)
    scoped = _scope_id(db, account_id)
    if not conv or scoped is None or conv.account_id != scoped:
        raise HTTPException(status_code=404, detail="会话不存在")
    rows = (
        db.query(Message)
        .filter_by(conversation_id=conv_id)
        .order_by(Message.msg_time.asc())
        .all()
    )
    return [
        {
            "id": m.id,
            "msg_time": m.msg_time.isoformat(),
            "sender_role": m.sender_role,
            "sender_name": m.sender_name,
            "speaker": _message_speaker(db, m),
            "msg_type": m.msg_type,
            "content": m.content,
            "media_name": m.media_name,
            "media_mime": m.media_mime,
            "media_status": m.media_status,
            "has_media": bool(m.media_relpath),
        }
        for m in rows
    ]


@router.get("/messages/{msg_id}/media")
def message_media(msg_id: int, db: Session = Depends(get_db)):
    row = db.get(Message, msg_id)
    if not row or not row.media_relpath:
        raise HTTPException(status_code=404, detail="没有可预览的原文件")
    path = resolve_media_path(row.media_relpath)
    if not path:
        raise HTTPException(status_code=404, detail="原文件不在本地")
    filename = row.media_name or path.name
    inline = (row.media_mime or "").startswith(("image/", "audio/", "video/")) and row.media_mime != "audio/silk"
    return FileResponse(
        path,
        media_type=row.media_mime or "application/octet-stream",
        filename=filename,
        content_disposition_type="inline" if inline else "attachment",
    )


@router.get("/messages")
def list_messages(
    db: Session = Depends(get_db),
    account_id: int | None = None,
    start_date: str = "",
    end_date: str = "",
    sender_role: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    scoped = _scope_id(db, account_id)
    if scoped is None:
        return {"total": 0, "items": []}
    q = db.query(Message).filter(Message.account_id == scoped)
    if start_date:
        q = q.filter(Message.msg_time >= f"{start_date} 00:00:00")
    if end_date:
        q = q.filter(Message.msg_time <= f"{end_date} 23:59:59")
    if sender_role:
        q = q.filter(Message.sender_role == sender_role)
    total = q.count()
    rows = (
        q.order_by(Message.msg_time.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "total": total,
        "items": [
            {
                "id": m.id,
                "conversation_id": m.conversation_id,
                "msg_time": m.msg_time.isoformat(),
                "sender_role": m.sender_role,
                "content": m.content,
            }
            for m in rows
        ],
    }


@router.post("/exports")
def export_messages(
    db: Session = Depends(get_db),
    account_id: int | None = None,
    start_date: str = "",
    end_date: str = "",
    q: str = "",
    flag: str = "",
    scope: str = "filtered",
):
    scoped = _scope_id(db, account_id)
    if scoped is None:
        apply_filters = scope != "all"
        filename = export_filename(
            scope="all" if scope == "all" else "filtered",
            start_date=start_date if apply_filters else "",
            end_date=end_date if apply_filters else "",
            q=q if apply_filters else "",
            flag=flag if apply_filters else "",
        )
        settings.exports_dir.mkdir(parents=True, exist_ok=True)
        path = settings.exports_dir / filename
        wb = Workbook()
        ws = wb.active
        ws.title = "messages"
        ws.append(["对方", "时间", "昵称", "发送者", "类型", "内容", "标记"])
        wb.save(path)
        return FileResponse(path, filename=filename)
    apply_filters = scope != "all"
    items = list_review_items(
        db,
        account_id=scoped,
        start_date=start_date,
        end_date=end_date,
        q=q,
        flag=flag,
        apply_filters=apply_filters,
        max_convs=5000 if scope == "all" else 400,
    )
    by_key = {item["id"]: item for item in items}
    rows = []
    for item in items:
        day = item.get("day") or ""
        contact_id = item.get("contact_id")
        if not day or not contact_id:
            continue
        chunk = (
            db.query(Message)
            .filter(
                Message.contact_id == contact_id,
                Message.msg_time >= f"{day} 00:00:00",
                Message.msg_time <= f"{day} 23:59:59",
            )
            .order_by(Message.msg_time.asc())
            .all()
        )
        rows.extend(chunk)
    if len(rows) > 20000:
        rows = rows[:20000]
    wb = Workbook()
    ws = wb.active
    ws.title = "messages"
    ws.append(["对方", "时间", "昵称", "发送者", "类型", "内容", "标记"])
    for m in rows:
        day = m.msg_time.strftime("%Y-%m-%d")
        item = by_key.get(f"{m.contact_id}:{day}") or {}
        ws.append(
            [
                item.get("contact") or "",
                format_clock(m.msg_time),
                _message_speaker(db, m),
                m.sender_name,
                m.msg_type,
                m.content,
                flag_text(item),
            ]
        )
    filename = export_filename(
        scope="all" if scope == "all" else "filtered",
        start_date=start_date if apply_filters else "",
        end_date=end_date if apply_filters else "",
        q=q if apply_filters else "",
        flag=flag if apply_filters else "",
    )
    settings.exports_dir.mkdir(parents=True, exist_ok=True)
    path = settings.exports_dir / filename
    wb.save(path)
    return FileResponse(path, filename=filename)


@router.post("/jobs/rule-scan")
def rule_scan(db: Session = Depends(get_db), account_id: int | None = None):
    scoped = _scope_id(db, account_id)
    if scoped is None:
        return {"ok": True, "days": 0, "hits": 0}
    return run_rule_scan(db, scoped)


def _ymd(value: str) -> str:
    return (value or "").replace("-", "")[:8]


@router.get("/metrics/overview")
def metrics_overview(
    db: Session = Depends(get_db),
    account_id: int | None = None,
    start_date: str = "",
    end_date: str = "",
):
    scoped = _scope_id(db, account_id)
    if scoped is None:
        return {
            "msg_count": 0,
            "conversation_count": 0,
            "timeout_count": 0,
            "first_response_avg": None,
            "avg_response": None,
            "first_response_label": "—",
            "avg_response_label": "—",
            "median_response": None,
            "median_response_label": "—",
            "reply_within_5min": None,
            "reply_within_1h": None,
            "last_sync": last_sync_info(db),
            "timeouts": [],
            "hits": [],
        }
    q = db.query(MetricDaily).filter(MetricDaily.account_id == scoped)
    start = _ymd(start_date)
    end = _ymd(end_date)
    if start:
        q = q.filter(MetricDaily.day >= start)
    if end:
        q = q.filter(MetricDaily.day <= end)
    rows = q.all()
    msg_count = sum(r.msg_count for r in rows)
    conv_count = sum(r.conversation_count for r in rows)
    firsts = [r.first_response_avg for r in rows if r.first_response_avg is not None]
    avgs = [r.avg_response for r in rows if r.avg_response is not None]
    first_avg = sum(firsts) / len(firsts) if firsts else None
    avg_resp = sum(avgs) / len(avgs) if avgs else None
    hits = list_hits(db, kind="forbidden", start_date=start_date, end_date=end_date, account_id=scoped)[:8]
    timeouts = timeout_items(db, start_date, end_date, limit=400, account_id=scoped)
    diag = diagnostic_stats(db, start_date, end_date, scoped)
    return {
        "msg_count": diag.get("msg_count") or msg_count,
        "conversation_count": diag.get("conversation_count") or conv_count,
        "timeout_count": len(timeouts),
        "first_response_avg": first_avg,
        "avg_response": avg_resp,
        "first_response_label": format_seconds(first_avg),
        "avg_response_label": format_seconds(avg_resp),
        "median_response": diag.get("median_seconds"),
        "median_response_label": diag.get("median_label"),
        "reply_within_5min": diag.get("within_5min_pct"),
        "reply_within_1h": diag.get("within_1h_pct"),
        "last_sync": last_sync_info(db),
        "timeouts": timeouts[:8],
        "hits": hits,
    }


@router.get("/metrics/daily")
def metrics_daily(
    db: Session = Depends(get_db),
    account_id: int | None = None,
    start_date: str = "",
    end_date: str = "",
):
    scoped = _scope_id(db, account_id)
    if scoped is None:
        return []
    q = db.query(MetricDaily).filter(MetricDaily.account_id == scoped)
    start = _ymd(start_date)
    end = _ymd(end_date)
    if start:
        q = q.filter(MetricDaily.day >= start)
    if end:
        q = q.filter(MetricDaily.day <= end)
    rows = q.order_by(MetricDaily.day.desc()).all()
    return [
        {
            "day": r.day,
            "msg_count": r.msg_count,
            "conversation_count": r.conversation_count,
            "first_response_avg": r.first_response_avg,
            "first_response_label": format_seconds(r.first_response_avg),
            "avg_response": r.avg_response,
            "avg_response_label": format_seconds(r.avg_response),
            "timeout_count": r.timeout_count,
        }
        for r in rows
    ]


@router.get("/hits")
def list_hits(
    db: Session = Depends(get_db),
    kind: str = "",
    start_date: str = "",
    end_date: str = "",
    account_id: int | None = None,
):
    scoped = _scope_id(db, account_id)
    if scoped is None:
        return []
    q = db.query(HitRecord).filter(HitRecord.account_id == scoped)
    if kind:
        q = q.filter(HitRecord.kind == kind)
    if start_date:
        q = q.filter(HitRecord.msg_time >= f"{start_date} 00:00:00")
    if end_date:
        q = q.filter(HitRecord.msg_time <= f"{end_date} 23:59:59")
    rows = q.order_by(HitRecord.msg_time.desc()).limit(200).all()
    out = []
    for r in rows:
        conv = db.get(Conversation, r.conversation_id)
        contact = db.get(Contact, conv.contact_id) if conv else None
        if contact_is_official(db, contact):
            continue
        msg = db.get(Message, r.message_id)
        snippet = ((msg.content or "")[:40] if msg else "")
        out.append(
            {
                "id": r.id,
                "term": r.term,
                "kind": r.kind,
                "message_id": r.message_id,
                "conversation_id": r.conversation_id,
                "contact": contact_label(contact),
                "snippet": snippet,
                "msg_time": r.msg_time.isoformat(),
            }
        )
    return out


def _run_analysis(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(AnalysisJob, job_id)
        if job:
            run_analysis_job(db, job)
    finally:
        db.close()


@router.post("/jobs/analysis")
def start_analysis(body: AnalysisIn, background: BackgroundTasks, db: Session = Depends(get_db)):
    seed_default_prompts(db)
    account = _scope_account(db, body.account_id)
    if account is None:
        raise HTTPException(400, "尚未识别当前微信，请先完成微信读取初始化并登录")
    kind = "group" if body.kind == "group" else "report"
    report_type = body.report_type if body.report_type in ("daily", "weekly", "portrait") else "portrait"
    start_date = body.start_date
    end_date = body.end_date
    if kind == "group":
        contact = db.get(Contact, body.contact_id) if body.contact_id else None
        if not is_group_contact(contact) or contact.account_id != account.id:
            raise HTTPException(400, "请选择一个已同步的群")
        if report_type in ("daily", "weekly"):
            prompt = get_digest_prompt(db, body.prompt_id, report_type)
            start_date, end_date = resolve_group_window(report_type, body.start_date, body.end_date)
        else:
            prompt = get_prompt(db, body.prompt_id, kind="group")
            report_type = "portrait"
    else:
        prompt = get_prompt(db, body.prompt_id, kind="report")
        report_type = "portrait"
    job = AnalysisJob(
        id=str(uuid4()),
        status="queued",
        account_id=account.id,
        start_date=start_date,
        end_date=end_date,
        prompt_id=prompt.id if prompt else None,
        kind=kind,
        contact_id=body.contact_id if kind == "group" else None,
        report_type=report_type,
        progress=5,
        progress_label="排队中",
    )
    db.add(job)
    db.commit()
    background.add_task(_run_analysis, job.id)
    return {
        "id": job.id,
        "status": job.status,
        "progress": job.progress,
        "progress_label": job.progress_label,
        "kind": job.kind,
        "contact_id": job.contact_id,
        "report_type": job.report_type,
    }


@router.get("/jobs/analysis/{job_id}")
def get_analysis_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    return {
        "id": job.id,
        "status": job.status,
        "error_message": job.error_message,
        "token_usage": job.token_usage,
        "progress": job.progress or 0,
        "progress_label": job.progress_label or "",
        "kind": job.kind or "report",
        "contact_id": job.contact_id,
        "report_type": job_report_type(job),
        "created_at": job.created_at.isoformat() if job.created_at else "",
    }


def _prompt_map(db: Session, ids: set[int]) -> dict[int, PromptTemplate]:
    if not ids:
        return {}
    rows = db.query(PromptTemplate).filter(PromptTemplate.id.in_(ids)).all()
    return {row.id: row for row in rows}


def _result_title(result: AnalysisResult, job: AnalysisJob, prompt: PromptTemplate | None) -> str:
    if (result.title or "").strip():
        return result.title.strip()
    when = result.created_at or job.created_at
    return make_result_title(when, prompt.name if prompt else "")


def _history_item(result: AnalysisResult, job: AnalysisJob, prompt: PromptTemplate | None) -> dict:
    created = result.created_at or job.created_at
    return {
        "id": result.id,
        "job_id": job.id,
        "title": _result_title(result, job, prompt),
        "created_at": created.isoformat() if created else "",
        "start_date": job.start_date,
        "end_date": job.end_date,
        "prompt_id": job.prompt_id,
        "prompt_name": prompt.name if prompt else "",
        "kind": job.kind or "report",
        "contact_id": job.contact_id,
        "report_type": job_report_type(job),
    }


def _filter_group_report_type(q, report_type: str):
    if report_type in ("daily", "weekly"):
        return q.filter(AnalysisJob.report_type == report_type)
    return q.filter(
        or_(
            AnalysisJob.report_type.is_(None),
            AnalysisJob.report_type == "",
            AnalysisJob.report_type == "portrait",
        )
    )


def _list_history(
    db: Session,
    prompt_id: int | None = None,
    limit: int = 100,
    kind: str = "report",
    contact_id: int | None = None,
    report_type: str = "portrait",
    account_id: int | None = None,
) -> list[dict]:
    q = (
        db.query(AnalysisResult, AnalysisJob)
        .join(AnalysisJob, AnalysisResult.job_id == AnalysisJob.id)
        .filter(AnalysisJob.status == "succeeded")
        .order_by(AnalysisResult.id.desc())
    )
    if account_id is not None:
        q = q.filter(AnalysisJob.account_id == account_id)
    if kind == "group":
        q = q.filter(AnalysisJob.kind == "group")
        if contact_id:
            q = q.filter(AnalysisJob.contact_id == contact_id)
        q = _filter_group_report_type(q, report_type)
    else:
        q = q.filter(AnalysisJob.kind != "group")
    if prompt_id:
        q = q.filter(AnalysisJob.prompt_id == prompt_id)
    rows = q.limit(limit).all()
    prompts = _prompt_map(db, {job.prompt_id for _, job in rows if job.prompt_id})
    return [_history_item(result, job, prompts.get(job.prompt_id) if job.prompt_id else None) for result, job in rows]


def _analysis_out(
    db: Session,
    job: AnalysisJob | None,
    result: AnalysisResult | None,
    start_date: str,
    end_date: str,
    history: list[dict],
    account_id: int | None = None,
) -> dict:
    stats = diagnostic_stats(db, start_date, end_date, job.account_id if job else account_id)
    if not job:
        return {
            "job_id": None,
            "result_id": None,
            "payload": None,
            "start_date": start_date,
            "end_date": end_date,
            "stats": stats,
            "history": history,
        }
    prompt = db.get(PromptTemplate, job.prompt_id) if job.prompt_id else None
    created = (result.created_at if result else None) or job.created_at
    return {
        "job_id": job.id,
        "result_id": result.id if result else None,
        "created_at": created.isoformat() if created else "",
        "title": _result_title(result, job, prompt) if result else "",
        "start_date": job.start_date,
        "end_date": job.end_date,
        "prompt_id": job.prompt_id,
        "prompt_name": prompt.name if prompt else "",
        "kind": job.kind or "report",
        "report_type": job_report_type(job),
        "payload": json.loads(result.payload_json) if result else None,
        "stats": stats,
        "history": history,
    }


@router.get("/analysis/results")
def latest_analysis(
    db: Session = Depends(get_db),
    start_date: str = "",
    end_date: str = "",
    prompt_id: int | None = None,
    kind: str = "report",
    contact_id: int | None = None,
    report_type: str = "",
    account_id: int | None = None,
):
    scoped = _scope_id(db, account_id)
    if scoped is None:
        return _analysis_out(db, None, None, start_date, end_date, [], account_id=None)
    kind = "group" if kind == "group" else "report"
    rt = report_type if report_type in ("daily", "weekly", "portrait") else "portrait"
    q = db.query(AnalysisJob).filter_by(status="succeeded").filter(AnalysisJob.account_id == scoped)
    if kind == "group":
        q = q.filter(AnalysisJob.kind == "group")
        if contact_id:
            q = q.filter(AnalysisJob.contact_id == contact_id)
        q = _filter_group_report_type(q, rt)
    else:
        q = q.filter(AnalysisJob.kind != "group")
    jobs = q.order_by(AnalysisJob.created_at.desc()).all()
    job = None
    for cand in jobs:
        if prompt_id and cand.prompt_id != prompt_id:
            continue
        if not start_date and not end_date:
            job = cand
            break
        if (cand.start_date or "") == (start_date or "") and (cand.end_date or "") == (end_date or ""):
            job = cand
            break
    history = _list_history(
        db,
        prompt_id=prompt_id,
        kind=kind,
        contact_id=contact_id,
        report_type=rt if kind == "group" else "portrait",
        account_id=scoped,
    )
    if not job:
        return _analysis_out(db, None, None, start_date, end_date, history, account_id=scoped)
    result = (
        db.query(AnalysisResult)
        .filter_by(job_id=job.id)
        .order_by(AnalysisResult.id.desc())
        .first()
    )
    return _analysis_out(db, job, result, start_date, end_date, history)


@router.get("/analysis/results/{result_id}")
def get_analysis_result(result_id: int, db: Session = Depends(get_db), account_id: int | None = None):
    result = db.get(AnalysisResult, result_id)
    if not result:
        raise HTTPException(404, "报告不存在")
    job = db.get(AnalysisJob, result.job_id)
    if not job:
        raise HTTPException(404, "报告不存在")
    scoped = _scope_id(db, account_id)
    if scoped is None or (job.account_id is not None and job.account_id != scoped):
        raise HTTPException(404, "报告不存在")
    kind = "group" if (job.kind or "report") == "group" else "report"
    rt = job_report_type(job) if kind == "group" else "portrait"
    history = _list_history(
        db,
        prompt_id=job.prompt_id if kind != "group" else None,
        kind=kind,
        contact_id=job.contact_id,
        report_type=rt,
        account_id=job.account_id if job.account_id is not None else scoped,
    )
    return _analysis_out(db, job, result, job.start_date or "", job.end_date or "", history)
