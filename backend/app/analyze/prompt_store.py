from __future__ import annotations

from app.analyze.prompt import (
    DIGEST_JSON_CONTRACT,
    GROUP_JSON_CONTRACT,
    JSON_CONTRACT,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_GROUP_CS,
    SYSTEM_PROMPT_GROUP_DAILY,
    SYSTEM_PROMPT_GROUP_SALES,
    SYSTEM_PROMPT_GROUP_SOCIAL,
    SYSTEM_PROMPT_GROUP_WEEKLY,
    SYSTEM_PROMPT_SALES,
    SYSTEM_PROMPT_SOCIAL,
)
from app.models import PromptTemplate
from sqlalchemy.orm import Session

PRESET_PROMPTS = (
    {
        "name": "客服诊断报告",
        "kind": "report",
        "body": SYSTEM_PROMPT,
        "is_default": True,
    },
    {
        "name": "销售诊断报告",
        "kind": "report",
        "body": SYSTEM_PROMPT_SALES,
        "is_default": False,
    },
    {
        "name": "社交复盘",
        "kind": "report",
        "body": SYSTEM_PROMPT_SOCIAL,
        "is_default": False,
    },
    {
        "name": "销售·群好友加好友",
        "kind": "group",
        "body": SYSTEM_PROMPT_GROUP_SALES,
        "is_default": True,
    },
    {
        "name": "客服·群家长画像",
        "kind": "group",
        "body": SYSTEM_PROMPT_GROUP_CS,
        "is_default": False,
    },
    {
        "name": "社交·群活跃关系",
        "kind": "group",
        "body": SYSTEM_PROMPT_GROUP_SOCIAL,
        "is_default": False,
    },
    {
        "name": "群日报",
        "kind": "group_digest",
        "body": SYSTEM_PROMPT_GROUP_DAILY,
        "is_default": True,
    },
    {
        "name": "群周报",
        "kind": "group_digest",
        "body": SYSTEM_PROMPT_GROUP_WEEKLY,
        "is_default": False,
    },
)

PROMPT_KINDS = ("report", "scene", "group", "group_digest")
REPORT_KINDS = ("report", "scene")
DIGEST_NAMES = {"daily": "群日报", "weekly": "群周报"}


def seed_default_prompts(db: Session) -> None:
    rows = db.query(PromptTemplate).all()
    existing = {r.name for r in rows}
    default_kinds = {r.kind for r in rows if r.is_default}
    added = False
    for spec in PRESET_PROMPTS:
        if spec["name"] in existing:
            continue
        is_default = bool(spec["is_default"]) and spec["kind"] not in default_kinds
        db.add(
            PromptTemplate(
                name=spec["name"],
                kind=spec["kind"],
                body=spec["body"],
                is_default=is_default,
                enabled=True,
            )
        )
        if is_default:
            default_kinds.add(spec["kind"])
        added = True
    if added:
        db.commit()


def resolve_prompt_body(text: str, kind: str = "report") -> str:
    body = (text or "").strip()
    if kind == "group_digest":
        if not body:
            return SYSTEM_PROMPT_GROUP_DAILY
        if "只返回 JSON" in body or '"headline"' in body or '"highlights"' in body:
            return body
        return body.rstrip() + "\n\n" + DIGEST_JSON_CONTRACT
    if kind == "group":
        if not body:
            return SYSTEM_PROMPT_GROUP_SALES
        if "只返回 JSON" in body or '"members"' in body or "add_friend" in body:
            return body
        return body.rstrip() + "\n\n" + GROUP_JSON_CONTRACT
    if not body:
        return SYSTEM_PROMPT
    if "只返回 JSON" in body or '"profile"' in body:
        return body
    return body.rstrip() + "\n\n" + JSON_CONTRACT


def _kind_filter(kind: str | None):
    if kind == "group":
        return ("group",)
    if kind == "group_digest":
        return ("group_digest",)
    if kind in ("report", "scene"):
        return REPORT_KINDS
    return None


def get_prompt(db: Session, prompt_id: int | None, kind: str | None = None) -> PromptTemplate | None:
    allowed = _kind_filter(kind)
    if prompt_id:
        row = db.get(PromptTemplate, prompt_id)
        if row and row.enabled and (not allowed or row.kind in allowed):
            return row
    q = db.query(PromptTemplate).filter_by(enabled=True)
    if allowed:
        q = q.filter(PromptTemplate.kind.in_(allowed))
    return (
        q.filter_by(is_default=True).order_by(PromptTemplate.id.asc()).first()
        or q.order_by(PromptTemplate.id.asc()).first()
    )


def set_default(db: Session, prompt_id: int) -> PromptTemplate:
    row = db.get(PromptTemplate, prompt_id)
    if not row:
        raise ValueError("提示词不存在")
    for other in db.query(PromptTemplate).filter_by(kind=row.kind).all():
        other.is_default = other.id == prompt_id
        if other.id == prompt_id:
            other.enabled = True
    db.commit()
    db.refresh(row)
    return row


def get_digest_prompt(db: Session, prompt_id: int | None, report_type: str) -> PromptTemplate | None:
    if prompt_id:
        row = get_prompt(db, prompt_id, kind="group_digest")
        if row:
            return row
    prefer = DIGEST_NAMES.get(report_type) or "群日报"
    hit = (
        db.query(PromptTemplate)
        .filter_by(name=prefer, enabled=True, kind="group_digest")
        .order_by(PromptTemplate.id.asc())
        .first()
    )
    return hit or get_prompt(db, None, kind="group_digest")
