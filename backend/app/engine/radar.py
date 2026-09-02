"""好友雷达：按联系人看状态、诉求、风险，点进对应会话。"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.engine.review import contact_is_official, contact_label, contact_subtitle
from app.models import Contact, Conversation, HitRecord, Message

QUIET_DAYS = 7
SNIPPET_LEN = 36
INTENT_RULES = (
    ("退费", ("退费", "退款", "退钱", "退课时")),
    ("价格", ("多少钱", "报价", "价格", "费用", "优惠", "便宜")),
    ("档期", ("预约", "档期", "什么时候", "几点", "哪天", "能不能来")),
    ("效果", ("效果", "质量", "好不好", "靠谱")),
    ("投诉", ("投诉", "举报", "工商", "律师", "差评")),
    ("课时", ("课时", "上课", "课程")),
)
RISK_TERMS = ("退费", "退款", "投诉", "举报", "律师", "工商", "差评", "骗子", "假的", "报警")
PROMISE_TERMS = ("明天", "稍后", "回头给你", "帮你问", "帮你申请", "给你方案", "跟进一下", "确认后", "回复你")
ROLE_RULES = (
    ("机构", ("我们学校", "校长", "班级", "校本", "教研", "同事", "公司", "单位", "部门")),
    ("家庭", ("孩子", "小孩", "家长", "作业", "我家娃", "我家", "家人", "老公", "老婆")),
    ("个人", ("我自己", "我报名", "我来上课", "个人用", "我自己学")),
)
QUOTE_TERMS = ("报价", "价格", "优惠", "多少钱", "费用", "课时包", "方案")
MATERIAL_TYPES = ("link", "file")
DECISION_TERMS = ("问问", "再考虑", "商量一下", "跟领导确认", "跟校长确认", "再看看", "考虑一下")
EFFECT_TERMS = ("效果", "质量", "好不好", "靠谱", "没效果", "没用")
REFUND_FOLLOW_TERMS = ("退费", "退款", "投诉", "举报")
RETURNING_DAYS = 30
PLACEHOLDER = re.compile(r"^\[(链接|图片|语音|文件|视频|小程序|表情|消息|通话)\]\s*")
TAG_RE = re.compile(r"<[^>]+>")

STATUS_LABEL = {
    "pending": "待回复",
    "new": "新询盘",
    "active": "跟进中",
    "quiet": "沉寂",
}


def clip_snippet(text: str) -> str:
    raw = (text or "").strip()
    raw = PLACEHOLDER.sub("", raw)
    raw = TAG_RE.sub(" ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    if not raw:
        return ""
    if len(raw) <= SNIPPET_LEN:
        return raw
    return raw[:SNIPPET_LEN] + "…"


def detect_intent(texts: list[str]) -> str:
    for text in texts:
        blob = text or ""
        for name, needles in INTENT_RULES:
            if any(n in blob for n in needles):
                return name
    return ""


def has_any(text: str, terms: tuple[str, ...]) -> bool:
    blob = text or ""
    return any(term in blob for term in terms)


def detect_role(texts: list[str]) -> str:
    blob = " ".join(texts or [])
    for name, needles in ROLE_RULES:
        if any(n in blob for n in needles):
            return name
    return ""


def is_quoted_silent(*, last_role: str, last_cs_content: str, last_cs_type: str) -> bool:
    if last_role != "cs":
        return False
    if (last_cs_type or "") in MATERIAL_TYPES:
        return True
    raw = last_cs_content or ""
    if raw.startswith("[链接]") or raw.startswith("[文件]"):
        return True
    return has_any(raw, QUOTE_TERMS)


def has_decision(texts: list[str]) -> bool:
    return any(has_any(t or "", DECISION_TERMS) for t in texts)


def has_refund_precursor(chrono_texts: list[str]) -> bool:
    saw_effect = False
    for text in chrono_texts:
        blob = text or ""
        if has_any(blob, EFFECT_TERMS):
            saw_effect = True
        if saw_effect and has_any(blob, REFUND_FOLLOW_TERMS):
            return True
    return False


def is_returning(*, first_at: datetime | None, last_at: datetime | None) -> bool:
    if not first_at or not last_at:
        return False
    return (last_at - first_at).total_seconds() >= RETURNING_DAYS * 86400


def classify_status(
    *,
    last_role: str,
    last_at: datetime | None,
    first_at: datetime | None,
    customer_texts: int,
    now: datetime,
    timeout_seconds: int,
) -> tuple[str, bool]:
    if not last_at:
        return "quiet", False
    pending = last_role == "customer"
    timeout = pending and (now - last_at).total_seconds() > timeout_seconds
    age_days = (now - last_at).total_seconds() / 86400
    if pending:
        return "pending", timeout
    if age_days >= QUIET_DAYS:
        return "quiet", False
    span_days = 0.0
    if first_at:
        span_days = max(0.0, (last_at - first_at).total_seconds() / 86400)
    if customer_texts <= 3 and span_days <= QUIET_DAYS:
        return "new", False
    return "active", False


def sort_key(row: dict) -> tuple:
    score = 0
    if row.get("risk") or row.get("precursor"):
        score -= 100
    if row.get("timeout"):
        score -= 80
    if row.get("status") == "pending":
        score -= 60
    if row.get("quoted"):
        score -= 50
    if row.get("promise"):
        score -= 40
    if row.get("decision"):
        score -= 30
    if row.get("status") == "new":
        score -= 20
    if row.get("status") == "quiet":
        score += 10
    last = row.get("last_msg_at") or ""
    return (score, last)


def list_radar(
    db: Session,
    *,
    start_date: str = "",
    end_date: str = "",
    status: str = "",
    account_id: int | None = None,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now()
    timeout_seconds = settings.timeout_seconds
    contacts_q = db.query(Contact).order_by(Contact.id.asc())
    if account_id is not None:
        contacts_q = contacts_q.filter(Contact.account_id == account_id)
    contacts = contacts_q.all()
    items: list[dict] = []
    for contact in contacts:
        if contact_is_official(db, contact):
            continue
        if (contact.peer_key or "").lower().endswith("@chatroom"):
            continue
        if (contact.peer_key or "").lower().endswith("@weclaw"):
            continue
        convs = (
            db.query(Conversation)
            .filter_by(contact_id=contact.id)
            .order_by(Conversation.last_msg_at.desc())
            .all()
        )
        if not convs:
            continue
        latest = convs[0]
        msgs = (
            db.query(Message)
            .filter_by(contact_id=contact.id)
            .order_by(Message.msg_time.asc())
            .all()
        )
        if not msgs:
            continue
        if start_date or end_date:
            start_at = datetime.strptime(f"{start_date} 00:00:00", "%Y-%m-%d %H:%M:%S") if start_date else None
            end_at = datetime.strptime(f"{end_date} 23:59:59", "%Y-%m-%d %H:%M:%S") if end_date else None
            in_range = False
            for m in msgs:
                if start_at and m.msg_time < start_at:
                    continue
                if end_at and m.msg_time > end_at:
                    continue
                in_range = True
                break
            if not in_range:
                continue
        last = msgs[-1]
        first = msgs[0]
        customer_texts = [m.content for m in msgs if m.sender_role == "customer" and (m.content or "").strip()]
        last_customer = next((m for m in reversed(msgs) if m.sender_role == "customer"), None)
        status_code, timeout = classify_status(
            last_role=last.sender_role,
            last_at=last.msg_time,
            first_at=first.msg_time,
            customer_texts=len(customer_texts),
            now=now,
            timeout_seconds=timeout_seconds,
        )
        intent = detect_intent(list(reversed(customer_texts)))
        snippet = clip_snippet((last_customer.content if last_customer else "") or last.content)
        all_text = " ".join(m.content or "" for m in msgs)
        risk = has_any(all_text, RISK_TERMS)
        role = detect_role(customer_texts)
        last_cs = next((m for m in reversed(msgs) if m.sender_role == "cs"), None)
        quoted = is_quoted_silent(
            last_role=last.sender_role,
            last_cs_content=(last_cs.content if last_cs else "") or "",
            last_cs_type=(last_cs.msg_type if last_cs else "") or "",
        )
        decision = has_decision(customer_texts)
        precursor = has_refund_precursor(customer_texts)
        returning = is_returning(first_at=first.msg_time, last_at=last.msg_time)
        promise = False
        promise_msg = next(
            (m for m in reversed(msgs) if m.sender_role == "cs" and has_any(m.content or "", PROMISE_TERMS)),
            None,
        )
        if promise_msg:
            later_cs = any(
                m.sender_role == "cs" and m.msg_time > promise_msg.msg_time for m in msgs
            )
            if not later_cs and (
                last.sender_role == "customer" or (now - promise_msg.msg_time) > timedelta(hours=24)
            ):
                promise = True
        conv_ids = [c.id for c in convs]
        forbidden = False
        if conv_ids:
            forbidden = (
                db.query(HitRecord.id)
                .filter(HitRecord.conversation_id.in_(conv_ids), HitRecord.kind == "forbidden")
                .first()
                is not None
            )
        items.append(
            {
                "contact_id": contact.id,
                "conversation_id": latest.id,
                "contact": contact_label(contact),
                "contact_sub": contact_subtitle(contact),
                "has_avatar": bool((contact.avatar_relpath or "").strip()),
                "nickname": (contact.nickname or "").strip(),
                "remark": (contact.remark or "").strip(),
                "status": status_code,
                "status_label": STATUS_LABEL[status_code],
                "intent": intent or "—",
                "role": role or "—",
                "snippet": snippet or "—",
                "timeout": timeout,
                "promise": promise,
                "quoted": quoted,
                "decision": decision,
                "precursor": precursor,
                "returning": returning,
                "risk": risk,
                "forbidden": forbidden,
                "last_msg_at": last.msg_time.isoformat(),
                "last_role": last.sender_role,
                "msg_count": len(msgs),
            }
        )
    items.sort(key=sort_key)
    summary = {
        "customers": len(items),
        "pending": sum(1 for r in items if r["status"] == "pending"),
        "new": sum(1 for r in items if r["status"] == "new"),
        "active": sum(1 for r in items if r["status"] == "active"),
        "quiet": sum(1 for r in items if r["status"] == "quiet"),
        "risk": sum(1 for r in items if r["risk"] or r["precursor"]),
        "timeout": sum(1 for r in items if r["timeout"]),
        "promise": sum(1 for r in items if r["promise"]),
        "quoted": sum(1 for r in items if r["quoted"]),
        "decision": sum(1 for r in items if r["decision"]),
        "precursor": sum(1 for r in items if r["precursor"]),
        "returning": sum(1 for r in items if r["returning"]),
    }
    shown = items
    if status == "risk":
        shown = [r for r in items if r["risk"] or r["precursor"]]
    elif status == "promise":
        shown = [r for r in items if r["promise"]]
    elif status == "timeout":
        shown = [r for r in items if r["timeout"]]
    elif status == "quoted":
        shown = [r for r in items if r["quoted"]]
    elif status == "decision":
        shown = [r for r in items if r["decision"]]
    elif status:
        shown = [r for r in items if r["status"] == status]
    return {"summary": summary, "items": shown}
