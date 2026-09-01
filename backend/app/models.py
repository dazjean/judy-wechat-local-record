from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _now() -> datetime:
    return datetime.now()


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128), default="本机微信")
    wx_username: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    contacts: Mapped[list[Contact]] = relationship(back_populates="account")


class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("account_id", "peer_key", name="uq_contact_peer"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    peer_key: Mapped[str] = mapped_column(String(128), index=True)
    nickname: Mapped[str] = mapped_column(String(256), default="")
    remark: Mapped[str] = mapped_column(String(256), default="")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    account: Mapped[Account] = relationship(back_populates="contacts")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    last_msg_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    msg_count: Mapped[int] = mapped_column(Integer, default=0)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("account_id", "raw_hash", name="uq_message_account_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    msg_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    sender_role: Mapped[str] = mapped_column(String(16), index=True)
    sender_name: Mapped[str] = mapped_column(String(128), default="")
    msg_type: Mapped[str] = mapped_column(String(16), default="text")
    content: Mapped[str] = mapped_column(Text, default="")
    media_relpath: Mapped[str] = mapped_column(String(512), default="")
    media_name: Mapped[str] = mapped_column(String(256), default="")
    media_mime: Mapped[str] = mapped_column(String(64), default="")
    media_status: Mapped[str] = mapped_column(String(32), default="")
    source_type: Mapped[str] = mapped_column(String(32), default="wechat_cli")
    source_ref: Mapped[str] = mapped_column(String(256), default="")
    raw_hash: Mapped[str] = mapped_column(String(64), index=True)


class SyncJob(Base):
    __tablename__ = "sync_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    account_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    start_date: Mapped[str] = mapped_column(String(16), default="")
    limit_per_contact: Mapped[int] = mapped_column(Integer, default=1000)
    total_contacts: Mapped[int] = mapped_column(Integer, default=0)
    ok_contacts: Mapped[int] = mapped_column(Integer, default=0)
    written: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class Lexicon(Base):
    __tablename__ = "lexicon"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    term: Mapped[str] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class MetricDaily(Base):
    __tablename__ = "metric_daily"
    __table_args__ = (UniqueConstraint("account_id", "day", name="uq_metric_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    day: Mapped[str] = mapped_column(String(8), index=True)
    msg_count: Mapped[int] = mapped_column(Integer, default=0)
    conversation_count: Mapped[int] = mapped_column(Integer, default=0)
    first_response_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_response: Mapped[float | None] = mapped_column(Float, nullable=True)
    timeout_count: Mapped[int] = mapped_column(Integer, default=0)


class HitRecord(Base):
    __tablename__ = "hit_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lexicon_id: Mapped[int] = mapped_column(ForeignKey("lexicon.id"), index=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), index=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    term: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(32))
    msg_time: Mapped[datetime] = mapped_column(DateTime)


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    account_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_date: Mapped[str] = mapped_column(String(16), default="")
    end_date: Mapped[str] = mapped_column(String(16), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    token_usage: Mapped[int] = mapped_column(Integer, default=0)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    progress_label: Mapped[str] = mapped_column(String(64), default="")
    prompt_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(32), default="report", index=True)
    contact_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    report_type: Mapped[str] = mapped_column(String(32), default="portrait", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("analysis_jobs.id"), index=True)
    title: Mapped[str] = mapped_column(String(256), default="")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class GroupMemberMark(Base):
    __tablename__ = "group_member_marks"
    __table_args__ = (UniqueConstraint("contact_id", "member_key", name="uq_group_member"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    member_key: Mapped[str] = mapped_column(String(128), index=True)
    member_name: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(32), default="watch", index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(16), default="user")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    kind: Mapped[str] = mapped_column(String(32), default="report", index=True)
    body: Mapped[str] = mapped_column(Text, default="")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
