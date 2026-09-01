"""本机微信号归属：一行一个 wxid，查询默认当前号，不为整库。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.ingest.media.self_account import current_folder_wxid
from app.models import (
    Account,
    AnalysisJob,
    AppSetting,
    Contact,
    Conversation,
    GroupMemberMark,
    HitRecord,
    Message,
    MetricDaily,
)
from app.product import DEFAULT_SELF_NAME

LOCAL_KEY = "local"
MIGRATED_SETTING = "account_key_migrated"
LAST_ACCOUNT_SETTING = "last_account_key"


class UnknownAccount(ValueError):
    """请求的 account_id 不存在。"""


class MissingWxid(ValueError):
    """当前没有可写入的微信号。"""

    def __init__(self, message: str = "尚未识别当前微信，请先完成微信读取初始化并登录"):
        super().__init__(message)


def current_account_key() -> str:
    return (current_folder_wxid() or "").strip()


def _setting(db: Session, key: str) -> str:
    row = db.get(AppSetting, key)
    return (row.value if row else "") or ""


def _upsert_setting(db: Session, key: str, value: str) -> None:
    row = db.get(AppSetting, key)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))


def remember_last_account_key(db: Session, account_key: str) -> None:
    key = (account_key or "").strip()
    if key and key != LOCAL_KEY:
        _upsert_setting(db, LAST_ACCOUNT_SETTING, key)


def last_account_key(db: Session) -> str:
    return (_setting(db, LAST_ACCOUNT_SETTING) or "").strip()


def get_or_create_account(db: Session, account_key: str, *, display_name: str | None = None) -> Account:
    key = (account_key or "").strip()
    if not key or key == LOCAL_KEY:
        raise MissingWxid()
    row = db.query(Account).filter_by(account_key=key).one_or_none()
    if row:
        remember_last_account_key(db, key)
        return row
    row = Account(account_key=key, display_name=(display_name or "").strip() or DEFAULT_SELF_NAME)
    db.add(row)
    db.flush()
    remember_last_account_key(db, key)
    return row


def current_account(db: Session, *, create: bool = False) -> Account | None:
    key = current_account_key()
    if key:
        if create:
            return get_or_create_account(db, key)
        row = db.query(Account).filter_by(account_key=key).one_or_none()
        return row
    last = last_account_key(db)
    if last:
        return db.query(Account).filter_by(account_key=last).one_or_none()
    rows = db.query(Account).filter(Account.account_key != LOCAL_KEY).order_by(Account.id.asc()).all()
    if len(rows) == 1:
        return rows[0]
    return None


def require_sync_account(db: Session) -> Account:
    key = current_account_key()
    if not key:
        raise MissingWxid()
    return get_or_create_account(db, key)


def resolve_account_scope(db: Session, requested_id: int | None = None) -> Account | None:
    """本机范围：指定已有账号，或当前/上次识别的号。永不表示「全部」。"""
    if requested_id:
        row = db.get(Account, requested_id)
        if not row:
            raise UnknownAccount("账号不存在")
        return row
    return current_account(db, create=False)


def _reassign_contact(db: Session, src: Contact, dst: Contact) -> None:
    db.query(Conversation).filter_by(contact_id=src.id).update(
        {Conversation.account_id: dst.account_id, Conversation.contact_id: dst.id},
        synchronize_session=False,
    )
    db.query(Message).filter_by(contact_id=src.id).update(
        {Message.account_id: dst.account_id, Message.contact_id: dst.id},
        synchronize_session=False,
    )
    for mark in db.query(GroupMemberMark).filter_by(contact_id=src.id).all():
        other = (
            db.query(GroupMemberMark)
            .filter_by(contact_id=dst.id, member_key=mark.member_key)
            .one_or_none()
        )
        if other:
            db.delete(mark)
        else:
            mark.contact_id = dst.id
    db.delete(src)


def _merge_metrics(db: Session, src_id: int, dst_id: int) -> None:
    dest_days = {row.day: row for row in db.query(MetricDaily).filter_by(account_id=dst_id)}
    for row in db.query(MetricDaily).filter_by(account_id=src_id).all():
        existing = dest_days.get(row.day)
        if existing:
            existing.msg_count += row.msg_count
            existing.conversation_count += row.conversation_count
            existing.timeout_count += row.timeout_count
            db.delete(row)
        else:
            row.account_id = dst_id


def reassign_account_rows(db: Session, src_id: int, dst_id: int) -> None:
    if src_id == dst_id:
        return
    dest_contacts = {c.peer_key: c for c in db.query(Contact).filter_by(account_id=dst_id)}
    for contact in db.query(Contact).filter_by(account_id=src_id).all():
        existing = dest_contacts.get(contact.peer_key)
        if existing:
            _reassign_contact(db, contact, existing)
        else:
            contact.account_id = dst_id
    db.query(Conversation).filter_by(account_id=src_id).update(
        {Conversation.account_id: dst_id}, synchronize_session=False
    )
    db.query(Message).filter_by(account_id=src_id).update(
        {Message.account_id: dst_id}, synchronize_session=False
    )
    db.query(HitRecord).filter_by(account_id=src_id).update(
        {HitRecord.account_id: dst_id}, synchronize_session=False
    )
    db.query(AnalysisJob).filter_by(account_id=src_id).update(
        {AnalysisJob.account_id: dst_id}, synchronize_session=False
    )
    _merge_metrics(db, src_id, dst_id)


def migrate_local_accounts(db: Session, current_wxid: str | None = None) -> Account | None:
    """把历史 account_key=local 改成当前 wxid；识别不到则等下次。"""
    wxid = (current_wxid if current_wxid is not None else current_account_key()).strip()
    local = db.query(Account).filter_by(account_key=LOCAL_KEY).one_or_none()
    if not local:
        if wxid:
            remember_last_account_key(db, wxid)
        _upsert_setting(db, MIGRATED_SETTING, "1")
        return db.query(Account).filter_by(account_key=wxid).one_or_none() if wxid else None
    if not wxid:
        return local
    target = db.query(Account).filter_by(account_key=wxid).one_or_none()
    if not target:
        local.account_key = wxid
        if not (local.wx_username or "").strip():
            local.wx_username = wxid
        remember_last_account_key(db, wxid)
        _upsert_setting(db, MIGRATED_SETTING, "1")
        db.flush()
        _backfill_null_jobs(db, local.id)
        return local
    reassign_account_rows(db, local.id, target.id)
    db.delete(local)
    remember_last_account_key(db, wxid)
    _upsert_setting(db, MIGRATED_SETTING, "1")
    db.flush()
    _backfill_null_jobs(db, target.id)
    return target


def _backfill_null_jobs(db: Session, account_id: int) -> None:
    db.query(AnalysisJob).filter(AnalysisJob.account_id.is_(None)).update(
        {AnalysisJob.account_id: account_id}, synchronize_session=False
    )


def account_public(row: Account, *, current_key: str = "", last_key: str = "") -> dict:
    is_current = False
    if current_key:
        is_current = row.account_key == current_key
    elif last_key:
        is_current = row.account_key == last_key
    return {
        "id": row.id,
        "account_key": row.account_key,
        "display_name": row.display_name,
        "wx_username": row.wx_username or "",
        "is_current": is_current,
    }
