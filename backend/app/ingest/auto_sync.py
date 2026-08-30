"""后台同步时机：定时间隔为主；库文件变化只作触发，不实时解密。"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.engine.metrics import run_rule_scan
from app.ingest.media.wx_paths import db_storage_dir
from app.ingest.wechat_cli.sync_job import run_sync_job
from app.logutil import append_sync_log
from app.models import SyncJob
from app.settings_persist import clamp_limit_per_contact

INTERVAL_CHOICES = (5, 15, 30, 60)
WATCH_QUIET_SECONDS = 45
WATCH_MIN_GAP_SECONDS = 120
STARTUP_GRACE_SECONDS = 20
TICK_SECONDS = 15

_stop = threading.Event()
_lock = threading.Lock()
_started_mono = 0.0
_loop_running = False


def clamp_minutes(value: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 15
    if n in INTERVAL_CHOICES:
        return n
    return min(INTERVAL_CHOICES, key=lambda x: abs(x - n))


def library_fingerprint() -> tuple:
    """只看会话库和最近消息库的 mtime/size，不打开、不解密。"""
    storage = db_storage_dir()
    if not storage:
        return ()
    names = (
        ("session", "session.db"),
        ("session", "session.db-wal"),
        ("message", "message_0.db"),
        ("message", "message_0.db-wal"),
    )
    out: list[tuple[str, int, int]] = []
    for folder, name in names:
        path = storage / folder / name
        try:
            st = path.stat()
            out.append((name, int(st.st_mtime_ns), int(st.st_size)))
        except OSError:
            out.append((name, 0, 0))
    return tuple(out)


def interval_due(now: datetime, last_success: datetime | None, minutes: int, enabled: bool) -> bool:
    if not enabled or minutes <= 0 or last_success is None:
        return False
    return (now - last_success).total_seconds() >= minutes * 60


def watch_settled(dirty_since: datetime | None, now: datetime, quiet_seconds: int = WATCH_QUIET_SECONDS) -> bool:
    if dirty_since is None:
        return False
    return (now - dirty_since).total_seconds() >= quiet_seconds


def step_watch(
    prev_fp,
    new_fp,
    dirty_since: datetime | None,
    now: datetime,
    last_success: datetime | None,
    watch_enabled: bool,
    quiet_seconds: int = WATCH_QUIET_SECONDS,
    min_gap_seconds: int = WATCH_MIN_GAP_SECONDS,
) -> tuple[bool, object, datetime | None]:
    """库文件指纹变化后，安静一段时间再触发。不解密、不按体积实时读库。"""
    if not watch_enabled or not new_fp:
        return False, new_fp or prev_fp, None
    if prev_fp is None:
        return False, new_fp, None
    if new_fp != prev_fp:
        return False, new_fp, now
    if not watch_settled(dirty_since, now, quiet_seconds):
        return False, new_fp, dirty_since
    if last_success and (now - last_success).total_seconds() < min_gap_seconds:
        return False, new_fp, dirty_since
    return True, new_fp, None


def last_success_at(db: Session) -> datetime | None:
    row = (
        db.query(SyncJob)
        .filter(SyncJob.status == "succeeded")
        .order_by(SyncJob.updated_at.desc())
        .first()
    )
    if not row:
        return None
    return row.updated_at or row.created_at


def sync_busy(db: Session) -> bool:
    return (
        db.query(SyncJob)
        .filter(SyncJob.status.in_(["queued", "running"]))
        .first()
        is not None
    )


def _run_sync_thread(
    job_id: str,
    include_groups: bool,
    exclude_names: str,
    include_names: str,
    limit_people_enabled: bool,
    limit_people: int,
    limit_per_group: int,
) -> None:
    db = SessionLocal()
    try:
        job = db.get(SyncJob, job_id)
        if job:
            run_sync_job(
                db,
                job,
                include_groups=include_groups,
                exclude_names=exclude_names,
                include_names=include_names,
                limit_people_enabled=limit_people_enabled,
                limit_people=limit_people,
                limit_per_group=limit_per_group,
            )
            if job.status == "succeeded":
                run_rule_scan(db)
    finally:
        db.close()


def current_sync_job(db: Session) -> SyncJob | None:
    running = (
        db.query(SyncJob)
        .filter(SyncJob.status.in_(["queued", "running"]))
        .order_by(SyncJob.created_at.desc())
        .first()
    )
    if running:
        return running
    return db.query(SyncJob).order_by(SyncJob.created_at.desc()).first()


def enqueue_sync(
    db: Session,
    *,
    days: int,
    reason: str,
    limit_per_contact: int | None = None,
    limit_per_group: int | None = None,
) -> Optional[SyncJob]:
    if sync_busy(db):
        return None
    days = max(1, min(int(days or 14), 90))
    if limit_per_contact is None:
        limit_per_contact = settings.sync_limit_per_contact
    if limit_per_group is None:
        limit_per_group = settings.sync_limit_per_group
    limit_per_contact = clamp_limit_per_contact(limit_per_contact)
    limit_per_group = clamp_limit_per_contact(limit_per_group)
    job = SyncJob(
        id=str(uuid4()),
        status="queued",
        start_date=(datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d"),
        limit_per_contact=limit_per_contact,
    )
    db.add(job)
    db.commit()
    append_sync_log(job.id, reason)
    threading.Thread(
        target=_run_sync_thread,
        args=(
            job.id,
            settings.sync_include_groups,
            settings.sync_exclude_names,
            settings.sync_include_names,
            settings.sync_limit_people_enabled,
            settings.sync_limit_people,
            limit_per_group,
        ),
        daemon=True,
    ).start()
    return job


def auto_sync_status(db: Session) -> dict:
    last = last_success_at(db)
    minutes = clamp_minutes(settings.sync_auto_minutes)
    next_at = ""
    if settings.sync_auto_enabled and last:
        nxt = last + timedelta(minutes=minutes)
        next_at = nxt.isoformat(timespec="minutes")
    return {
        "enabled": bool(settings.sync_auto_enabled),
        "minutes": minutes,
        "watch_enabled": bool(settings.sync_watch_enabled),
        "next_at": next_at,
        "need_first_sync": last is None,
        "note": (
            "不能按库文件体积实时解密。微信库几乎一直在写，WAL 体积常按分页跳动，体积变化不等于有新消息。"
            "定时间隔最稳；勾选库有更新时，只在会话库改动并安静约 1 分钟后再跑同一套同步，最短间隔 2 分钟。"
        ),
    }


def _tick(state: dict) -> None:
    if time.monotonic() - _started_mono < STARTUP_GRACE_SECONDS:
        return
    db = SessionLocal()
    try:
        if not settings.sync_auto_enabled:
            state["fingerprint"] = library_fingerprint()
            state["dirty_since"] = None
            return
        from app.license import status_from_runtime

        if not status_from_runtime().ok:
            return
        if sync_busy(db):
            return
        now = datetime.now()
        last = last_success_at(db)
        minutes = clamp_minutes(settings.sync_auto_minutes)
        due = interval_due(now, last, minutes, True)
        watch_hit, fp, dirty = step_watch(
            state.get("fingerprint"),
            library_fingerprint(),
            state.get("dirty_since"),
            now,
            last,
            bool(settings.sync_watch_enabled),
        )
        state["fingerprint"] = fp
        state["dirty_since"] = dirty
        if due:
            enqueue_sync(db, days=settings.sync_days, reason="定时同步开始")
            state["dirty_since"] = None
            return
        if watch_hit:
            enqueue_sync(db, days=settings.sync_days, reason="检测到微信库有更新，开始同步")
    finally:
        db.close()


def _loop() -> None:
    state: dict = {"fingerprint": None, "dirty_since": None}
    while not _stop.wait(TICK_SECONDS):
        try:
            _tick(state)
        except Exception:
            continue


def start_auto_sync() -> None:
    global _started_mono, _loop_running
    with _lock:
        if _loop_running:
            return
        _stop.clear()
        _started_mono = time.monotonic()
        _loop_running = True
        threading.Thread(target=_loop, name="lingxi-auto-sync", daemon=True).start()


def stop_auto_sync() -> None:
    global _loop_running
    _stop.set()
    with _lock:
        _loop_running = False
