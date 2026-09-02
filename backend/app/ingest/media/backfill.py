"""对已入库但缺原文件的媒体消息，只补媒体、不重拉聊天文本。"""

from __future__ import annotations

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.accounts import MissingWxid, require_sync_account
from app.engine.review import contact_label
from app.ingest.media.extract import attach_media
from app.ingest.media.wx_paths import wechat_account_root
from app.ingest.wechat_cli.parse import ParsedMessage
from app.ingest.wechat_cli.sync_job import hits_exclude, hits_include, parse_name_list
from app.logutil import append_sync_log
from app.models import Account, Contact, Message, SyncJob

_MEDIA_TYPES = ("image", "voice", "file")


def message_needs_media(msg: Message) -> bool:
    if msg.msg_type not in _MEDIA_TYPES:
        return False
    if msg.media_status == "missing" or not (msg.media_relpath or "").strip():
        return True
    return msg.media_mime == "audio/silk"


def _missing_media_clause():
    return and_(
        Message.msg_type.in_(_MEDIA_TYPES),
        or_(
            Message.media_status == "missing",
            Message.media_relpath == "",
            Message.media_relpath.is_(None),
            Message.media_mime == "audio/silk",
        ),
    )


def count_missing_media(db: Session, account_id: int) -> int:
    return (
        db.query(Message)
        .filter(Message.account_id == account_id, _missing_media_clause())
        .count()
    )


def message_to_parsed(msg: Message) -> ParsedMessage:
    return ParsedMessage(
        msg_time=msg.msg_time,
        sender_role=msg.sender_role,
        sender_name=msg.sender_name,
        content=msg.content,
        msg_type=msg.msg_type,
        raw_hash=msg.raw_hash,
        source_ref=msg.source_ref,
    )


def _contact_display(contact: Contact) -> str:
    return contact_label(contact) or contact.peer_key


def list_contacts_for_backfill(
    db: Session,
    account: Account,
    *,
    include_names: str = "",
    exclude_names: str = "",
) -> list[tuple[Contact, list[Message]]]:
    include = parse_name_list(include_names)
    exclude = parse_name_list(exclude_names)
    rows = (
        db.query(Message)
        .filter(Message.account_id == account.id, _missing_media_clause())
        .order_by(Message.contact_id.asc(), Message.msg_time.asc())
        .all()
    )
    by_contact: dict[int, list[Message]] = {}
    for msg in rows:
        by_contact.setdefault(msg.contact_id, []).append(msg)
    out: list[tuple[Contact, list[Message]]] = []
    for contact_id, messages in by_contact.items():
        contact = db.get(Contact, contact_id)
        if not contact:
            continue
        display = _contact_display(contact)
        if exclude and hits_exclude(contact.peer_key, display, exclude):
            continue
        if include and not hits_include(contact.peer_key, display, include):
            continue
        out.append((contact, messages))
    out.sort(key=lambda item: _contact_display(item[0]).casefold())
    return out


def apply_backfill_results(messages: list[Message], parsed: list[ParsedMessage]) -> tuple[int, int]:
    fixed = 0
    still_missing = 0
    for msg, item in zip(messages, parsed, strict=True):
        if item.media_relpath:
            better = not msg.media_relpath or (
                msg.media_mime == "audio/silk" and item.media_mime == "audio/mpeg"
            )
            if better:
                msg.media_relpath = item.media_relpath
                msg.media_name = item.media_name
                msg.media_mime = item.media_mime
                msg.media_status = item.media_status
                if item.msg_type == "file" and item.content and item.content != msg.content:
                    msg.content = item.content
                fixed += 1
            continue
        if message_needs_media(msg):
            msg.media_status = "missing"
            still_missing += 1
    return fixed, still_missing


def _resolve_job_account(db: Session, job: SyncJob) -> Account:
    if job.account_id:
        row = db.get(Account, job.account_id)
        if row:
            return row
    return require_sync_account(db)


def run_media_backfill_job(
    db: Session,
    job: SyncJob,
    *,
    include_names: str = "",
    exclude_names: str = "",
) -> None:
    log = lambda msg: append_sync_log(job.id, msg)
    job.status = "running"
    db.commit()
    log("开始补拉媒体（不重拉聊天文本）")
    log("请先在微信里点开原图或下载附件，再运行本任务")
    try:
        account = _resolve_job_account(db, job)
        job.account_id = account.id
        db.commit()
    except MissingWxid as exc:
        job.status = "failed"
        job.error_message = str(exc)
        db.commit()
        log(str(exc))
        return
    if not wechat_account_root():
        job.status = "failed"
        job.error_message = "微信读取组件未就绪，请先在微信同步页确认读取状态"
        db.commit()
        log(job.error_message)
        return
    include = parse_name_list(include_names)
    exclude = parse_name_list(exclude_names)
    if include:
        log(f"范围：只补 {len(include)} 个名称")
    if exclude:
        log(f"排除：{len(exclude)} 个名称")
    targets = list_contacts_for_backfill(
        db,
        account,
        include_names=include_names,
        exclude_names=exclude_names,
    )
    job.total_contacts = len(targets)
    db.commit()
    if not targets:
        job.status = "succeeded"
        job.ok_contacts = 0
        job.written = 0
        job.skipped = 0
        db.commit()
        log("没有缺原文件的媒体消息")
        log("补拉结束：成功，无需处理")
        return
    total_msgs = sum(len(msgs) for _, msgs in targets)
    log(f"待补 {total_msgs} 条媒体，涉及 {len(targets)} 个会话")
    fixed_total = 0
    missing_total = 0
    ok = 0
    for contact, messages in targets:
        display = _contact_display(contact)
        parsed = [message_to_parsed(msg) for msg in messages]
        stats = attach_media(parsed, contact.peer_key)
        fixed, still = apply_backfill_results(messages, parsed)
        fixed_total += fixed
        missing_total += still
        ok += 1
        job.ok_contacts = ok
        job.written = fixed_total
        job.skipped = missing_total
        db.commit()
        extra = ""
        if stats["missing"]:
            extra = f"，仍缺 {stats['missing']}"
        log(f"完成：{display} — 补到 {fixed} 条{extra}")
    job.status = "succeeded"
    job.error_message = ""
    db.commit()
    log(f"补拉结束：成功，会话 {ok}，补到 {fixed_total} 条，仍缺 {missing_total} 条")
