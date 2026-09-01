"""复盘用的会话标记、时长格式、噪音客户过滤。"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings
from app.engine.metrics import _response_stats
from app.ingest.wechat_cli.sync_job import _should_skip, looks_like_official_feed
from app.models import Contact, Conversation, HitRecord, Message, SyncJob

NOISE_LABELS = ("安全中心", "公众号", "文件传输助手", "微信团队", "微信支付", "腾讯新闻", "服务通知")
FLAG_LABELS = {"timeout": "超时未回", "forbidden": "禁用词", "missing_media": "缺原文件"}
_BAD_FILENAME = '\\/:*?"<>|\n\r\t'


def format_seconds(value: float | None) -> str:
    if value is None:
        return "—"
    total = int(round(value))
    if total < 60:
        return f"{total} 秒"
    minutes, sec = divmod(total, 60)
    if sec == 0:
        return f"{minutes} 分"
    return f"{minutes} 分 {sec} 秒"


def format_clock(value: datetime | str | None) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).strip()
        if len(raw) == 8 and raw.isdigit():
            dt = datetime.strptime(raw, "%Y%m%d")
        else:
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00").split("+")[0])
            except ValueError:
                try:
                    dt = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    return "—"
    return f"{dt.year:04d}年{dt.month:02d}月{dt.day:02d}日 {dt.hour:02d}.{dt.minute:02d}.{dt.second:02d}"


def contact_label(contact: Contact | None) -> str:
    if not contact:
        return ""
    return (contact.remark or contact.nickname or contact.peer_key or "").strip()


def is_review_noise(contact: Contact | None) -> bool:
    if not contact:
        return True
    label = contact_label(contact)
    if _should_skip(contact.peer_key, label):
        return True
    return any(part in label for part in NOISE_LABELS)


def contact_is_official(db: Session, contact: Contact | None, messages: list[Message] | None = None) -> bool:
    if not contact:
        return False
    if is_review_noise(contact):
        return True
    if messages is None:
        messages = (
            db.query(Message)
            .filter_by(contact_id=contact.id)
            .order_by(Message.msg_time.desc())
            .limit(50)
            .all()
        )
    return looks_like_official_feed(messages)


def _load_messages(db: Session, conv_id: int) -> list[Message]:
    return (
        db.query(Message)
        .filter_by(conversation_id=conv_id)
        .order_by(Message.msg_time.asc())
        .all()
    )


def _flags_from_messages(msgs: list[Message], hit: bool) -> dict:
    _firsts, _avgs, timeouts = _response_stats(msgs, settings.timeout_seconds)
    missing_media = any(
        m.msg_type in {"image", "voice", "file"} and (m.media_status == "missing" or not m.media_relpath)
        for m in msgs
    )
    return {
        "timeout": timeouts > 0,
        "timeout_count": timeouts,
        "forbidden": hit,
        "missing_media": missing_media,
        "official": looks_like_official_feed(msgs),
    }


def conversation_flags(db: Session, conv: Conversation) -> dict:
    msgs = _load_messages(db, conv.id)
    has_hit = (
        db.query(HitRecord.id)
        .filter(HitRecord.conversation_id == conv.id, HitRecord.kind == "forbidden")
        .first()
        is not None
    )
    return _flags_from_messages(msgs, has_hit)


def _item_from_flags(conv: Conversation, contact: Contact | None, flags: dict) -> dict:
    return {
        "id": conv.id,
        "contact": contact_label(contact),
        "started_at": conv.started_at.isoformat(),
        "last_msg_at": conv.last_msg_at.isoformat(),
        "msg_count": conv.msg_count,
        "timeout": flags["timeout"],
        "timeout_count": flags["timeout_count"],
        "forbidden": flags["forbidden"],
        "missing_media": flags["missing_media"],
        "noise": is_review_noise(contact) or flags["official"],
    }


def annotate_conversation(db: Session, conv: Conversation, contact: Contact | None = None) -> dict:
    contact = contact or db.get(Contact, conv.contact_id)
    flags = conversation_flags(db, conv)
    return _item_from_flags(conv, contact, flags)


def last_sync_info(db: Session) -> dict | None:
    job = db.query(SyncJob).order_by(SyncJob.created_at.desc()).first()
    if not job:
        return None
    return {
        "at": job.updated_at.isoformat() if job.updated_at else (job.created_at.isoformat() if job.created_at else ""),
        "status": job.status,
        "written": job.written,
        "ok_contacts": job.ok_contacts,
        "start_date": job.start_date,
        "error_message": job.error_message or "",
    }


def timeout_items(
    db: Session, start_date: str, end_date: str, limit: int = 8, account_id: int | None = None
) -> list[dict]:
    rows = _convs_in_range(db, start_date, end_date, account_id=account_id)
    out: list[dict] = []
    for conv in rows:
        contact = db.get(Contact, conv.contact_id)
        if is_review_noise(contact):
            continue
        flags = conversation_flags(db, conv)
        if flags["official"] or not flags["timeout"]:
            continue
        out.append(
            {
                "conversation_id": conv.id,
                "contact": contact_label(contact),
                "last_msg_at": conv.last_msg_at.isoformat(),
                "timeout_count": flags["timeout_count"],
            }
        )
        if len(out) >= limit:
            break
    return out


def _convs_in_range(
    db: Session, start_date: str, end_date: str, account_id: int | None = None
) -> list[Conversation]:
    q = db.query(Conversation)
    if account_id is not None:
        q = q.filter(Conversation.account_id == account_id)
    if start_date:
        q = q.filter(Conversation.last_msg_at >= f"{start_date} 00:00:00")
    if end_date:
        q = q.filter(Conversation.started_at <= f"{end_date} 23:59:59")
    return q.order_by(Conversation.last_msg_at.desc()).limit(400).all()


def _candidate_pairs(
    db: Session,
    *,
    account_id: int | None,
    start_date: str,
    end_date: str,
    q: str,
    apply_filters: bool,
    max_convs: int,
) -> list[tuple[Conversation, Contact]]:
    query = db.query(Conversation, Contact).join(Contact, Conversation.contact_id == Contact.id)
    if account_id is not None:
        query = query.filter(Conversation.account_id == account_id)
    if apply_filters:
        if start_date:
            query = query.filter(Conversation.last_msg_at >= f"{start_date} 00:00:00")
        if end_date:
            query = query.filter(Conversation.started_at <= f"{end_date} 23:59:59")
        needle = (q or "").strip()
        if needle:
            like = f"%{needle}%"
            query = query.filter(
                or_(Contact.remark.like(like), Contact.nickname.like(like), Contact.peer_key.like(like))
            )
    rows = query.order_by(Conversation.last_msg_at.desc()).limit(max_convs).all()
    return [(conv, contact) for conv, contact in rows if not is_review_noise(contact)]


def _annotate_chunk(db: Session, pairs: list[tuple[Conversation, Contact]]) -> list[dict]:
    ids = [conv.id for conv, _ in pairs]
    if not ids:
        return []
    msgs = (
        db.query(Message)
        .filter(Message.conversation_id.in_(ids))
        .order_by(Message.conversation_id.asc(), Message.msg_time.asc())
        .all()
    )
    by_conv: dict[int, list[Message]] = defaultdict(list)
    for msg in msgs:
        by_conv[msg.conversation_id].append(msg)
    hit_ids = {
        row[0]
        for row in db.query(HitRecord.conversation_id)
        .filter(HitRecord.conversation_id.in_(ids), HitRecord.kind == "forbidden")
        .distinct()
        .all()
    }
    return [
        _item_from_flags(conv, contact, _flags_from_messages(by_conv.get(conv.id, []), conv.id in hit_ids))
        for conv, contact in pairs
    ]


def _annotate_many(db: Session, pairs: list[tuple[Conversation, Contact]], chunk: int = 40) -> list[dict]:
    items: list[dict] = []
    for i in range(0, len(pairs), chunk):
        items.extend(_annotate_chunk(db, pairs[i : i + chunk]))
    return items


def _flag_match(item: dict, flag: str) -> bool:
    if flag == "timeout":
        return bool(item["timeout"])
    if flag == "forbidden":
        return bool(item["forbidden"])
    if flag == "missing_media":
        return bool(item["missing_media"])
    return True


def list_review_page(
    db: Session,
    *,
    account_id: int | None = None,
    start_date: str = "",
    end_date: str = "",
    q: str = "",
    flag: str = "",
    page: int = 1,
    page_size: int = 20,
    max_convs: int = 400,
) -> tuple[list[dict], int]:
    pairs = _candidate_pairs(
        db,
        account_id=account_id,
        start_date=start_date,
        end_date=end_date,
        q=q,
        apply_filters=True,
        max_convs=max_convs,
    )
    page = max(1, page)
    page_size = max(1, page_size)
    start = (page - 1) * page_size
    if flag:
        items = [item for item in _annotate_many(db, pairs) if not item["noise"] and _flag_match(item, flag)]
        return items[start : start + page_size], len(items)
    extra = min(40, page_size)
    window = pairs[start : start + page_size + extra]
    items = [item for item in _annotate_chunk(db, window) if not item["noise"]][:page_size]
    return items, len(pairs)


def list_review_items(
    db: Session,
    *,
    account_id: int | None = None,
    start_date: str = "",
    end_date: str = "",
    q: str = "",
    flag: str = "",
    apply_filters: bool = True,
    max_convs: int = 400,
) -> list[dict]:
    pairs = _candidate_pairs(
        db,
        account_id=account_id,
        start_date=start_date,
        end_date=end_date,
        q=q,
        apply_filters=apply_filters,
        max_convs=max_convs,
    )
    items = [item for item in _annotate_many(db, pairs) if not item["noise"]]
    if apply_filters and flag:
        items = [item for item in items if _flag_match(item, flag)]
    return items


def flag_text(item: dict) -> str:
    tags = []
    if item.get("timeout"):
        tags.append("超时")
    if item.get("forbidden"):
        tags.append("禁用词")
    if item.get("missing_media"):
        tags.append("缺原文件")
    return "、".join(tags)


def _safe_filename_part(text: str, limit: int = 40) -> str:
    cleaned = "".join("_" if c in _BAD_FILENAME else c for c in (text or "").strip())
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    cleaned = cleaned.strip(" ._")
    return (cleaned[:limit] or "未命名")


def export_filename(
    *,
    scope: str,
    start_date: str = "",
    end_date: str = "",
    q: str = "",
    flag: str = "",
    now: datetime | None = None,
) -> str:
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    parts = ["会话明细"]
    if scope == "all":
        parts.append("全部")
    else:
        parts.append("筛选")
        if start_date and end_date:
            parts.append(f"{start_date}至{end_date}")
        elif start_date:
            parts.append(f"自{start_date}")
        elif end_date:
            parts.append(f"至{end_date}")
        needle = (q or "").strip()
        if needle:
            parts.append(f"客户{needle}")
        if flag in FLAG_LABELS:
            parts.append(FLAG_LABELS[flag])
        if len(parts) == 2:
            parts.append("当前列表")
    name = "_".join(_safe_filename_part(p) for p in parts)
    return f"{name}_{stamp}.xlsx"
