from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.settings_persist import clamp_limit_per_contact, mark_sync_coverage, mark_sync_limit_coverage
from app.ingest.wechat_cli import runner
from app.ingest.wechat_cli.errors import ReaderError
from app.ingest.media.extract import attach_media
from app.ingest.media.self_account import apply_self_profile, read_self_profile
from app.ingest.wechat_cli.parse import ParsedMessage, parse_history_lines, strip_emoji
from app.logutil import append_sync_log
from app.models import Account, Contact, Conversation, Message, SyncJob
from app.product import DEFAULT_SELF_NAME

SKIP_NAMES = {
    "文件传输助手",
    "微信团队",
    "腾讯新闻",
    "微信运动",
    "微信支付",
    "公众号",
    "服务通知",
}
SKIP_KEYS = {
    "filehelper",
    "fmessage",
    "newsapp",
    "weixin",
    "brandsessionholder",
    "officialaccounts",
    "medianote",
    "floatbottle",
    "qqmail",
    "mediatrade",
    "notification_messages",
    "notifymessage",
    "qqsafe",
}
OA_LAST_MSG_TYPES = {"链接/文件", "链接"}
PERSON_KEY_MARKERS = ("@chatroom", "@openim", "@weclaw")


def _session_identity(item: dict) -> tuple[str, str]:
    username = str(item.get("username") or item.get("userName") or item.get("wxid") or "").strip()
    display = ""
    for field in (
        "remark",
        "chat",
        "nick_name",
        "nickname",
        "nickName",
        "name",
        "display_name",
        "title",
    ):
        val = str(item.get(field) or "").strip()
        if val:
            display = val
            break
    display = display or username
    key = username or display
    return key, display


def _should_skip(key: str, display: str, item: dict | None = None) -> bool:
    k = (key or "").strip().lower()
    d = (display or "").strip()
    if not k:
        return True
    if k in SKIP_KEYS or d in SKIP_NAMES:
        return True
    if "sessionholder" in k:
        return True
    if k.startswith("gh_"):
        return True
    if item and _looks_like_official_session(item, k):
        return True
    return False


def _looks_like_official_session(item: dict, key: str) -> bool:
    if _is_group(item, key):
        return False
    if key.startswith("wxid_") or any(key.endswith(mark) for mark in PERSON_KEY_MARKERS):
        return False
    msg_type = str(item.get("msg_type") or "").strip()
    sender = str(item.get("sender") or "").strip()
    return msg_type in OA_LAST_MSG_TYPES and not sender


def looks_like_official_feed(messages) -> bool:
    """单向推送（链接/卡片为主、没有客服回复）视为公众号，已入库的也会在列表里隐藏。"""
    rows = list(messages or [])
    if len(rows) < 2:
        return False
    if any(getattr(m, "sender_role", "") == "cs" for m in rows):
        return False
    n_oa = 0
    for m in rows:
        kind = getattr(m, "msg_type", "") or ""
        content = getattr(m, "content", "") or ""
        if kind in {"other", "link"} or content.startswith(("[链接]", "[小程序]", "[视频号]")):
            n_oa += 1
    return n_oa / len(rows) >= 0.6


def _is_group(item: dict, key: str) -> bool:
    if item.get("is_group") is True:
        return True
    return (key or "").lower().endswith("@chatroom")


def is_window_widened(window_start: str, covered_from: str) -> bool:
    window_start = (window_start or "").strip()
    covered_from = (covered_from or "").strip()
    if not window_start or not covered_from:
        return False
    return window_start < covered_from


def is_limit_raised(job_limit: int, covered_limit: int) -> bool:
    try:
        current = int(covered_limit or 0)
    except (TypeError, ValueError):
        current = 0
    return clamp_limit_per_contact(job_limit) > current


def _peer_is_group(key: str) -> bool:
    return (key or "").lower().endswith("@chatroom")


def history_limit_for_peer(key: str, person_limit: int, group_limit: int) -> int:
    return group_limit if _peer_is_group(key) else person_limit


def history_start_for_contact(
    window_start: str,
    last_synced_at: datetime | None,
    widened: bool,
) -> str:
    """已同步过的人从上次成功时间起拉；新人或不在覆盖范围时用最近 N 天。"""
    window_start = (window_start or "").strip()
    if widened or last_synced_at is None:
        return window_start
    synced = last_synced_at - timedelta(minutes=2)
    stamp = synced.strftime("%Y-%m-%d %H:%M:%S")
    if window_start and stamp[:10] < window_start:
        return window_start
    return stamp


def parse_name_list(text: str) -> list[str]:
    names: list[str] = []
    for line in (text or "").splitlines():
        name = line.strip()
        if name and name not in names:
            names.append(name)
    return names


parse_exclude_names = parse_name_list


def _norm_name(value: str) -> str:
    return strip_emoji(value or "").strip().casefold()


def hits_name_list(key: str, display: str, names: list[str], *, loose: bool = False) -> bool:
    if not names:
        return False
    candidates = {_norm_name(key), _norm_name(display)}
    candidates.discard("")
    for name in names:
        needle = _norm_name(name)
        if not needle:
            continue
        if needle in candidates:
            return True
        if loose and len(needle) >= 2 and any(needle in c for c in candidates):
            return True
    return False


def hits_exclude(key: str, display: str, names: list[str]) -> bool:
    return hits_name_list(key, display, names, loose=False)


def hits_include(key: str, display: str, names: list[str]) -> bool:
    return hits_name_list(key, display, names, loose=True)


def apply_people_limit(
    usable: list[tuple[str, str]],
    limit: int,
    enabled: bool,
) -> tuple[list[tuple[str, str]], int]:
    if not enabled:
        return usable, 0
    cap = max(1, min(int(limit or 20), 300))
    if len(usable) <= cap:
        return usable, 0
    return usable[:cap], len(usable) - cap


def select_sync_targets(
    sessions: list[dict],
    *,
    include_groups: bool,
    exclude: list[str],
    include: list[str],
    limit_people_enabled: bool,
    limit_people: int,
) -> tuple[list[tuple[str, str]], dict]:
    usable: list[tuple[str, str]] = []
    skipped_sys = 0
    skipped_group = 0
    skipped_exclude: list[str] = []
    skipped_not_include = 0
    seen: set[str] = set()
    for item in sessions:
        key, display = _session_identity(item)
        label = display or key
        if _should_skip(key, display, item):
            skipped_sys += 1
            continue
        is_group = _is_group(item, key)
        if include:
            if not hits_include(key, display, include):
                skipped_not_include += 1
                continue
        elif not include_groups and is_group:
            skipped_group += 1
            continue
        if hits_exclude(key, display, exclude):
            skipped_exclude.append(label)
            continue
        if key in seen:
            continue
        seen.add(key)
        usable.append((key, display))
    dropped = 0
    if not include:
        usable, dropped = apply_people_limit(usable, limit_people, limit_people_enabled)
    return usable, {
        "skipped_sys": skipped_sys,
        "skipped_group": skipped_group,
        "skipped_exclude": skipped_exclude,
        "skipped_not_include": skipped_not_include,
        "dropped_limit": dropped,
    }


def unmatched_include_names(usable: list[tuple[str, str]], include: list[str]) -> list[str]:
    missing: list[str] = []
    for name in include:
        if not any(hits_include(key, display, [name]) for key, display in usable):
            missing.append(name)
    return missing


def expand_include_from_contacts(
    usable: list[tuple[str, str]],
    include: list[str],
    exclude: list[str],
    contacts_for,
    log=None,
) -> list[tuple[str, str]]:
    if not include:
        return usable
    seen = {key for key, _ in usable}
    for name in unmatched_include_names(usable, include):
        if not _should_query_contacts(name):
            if log:
                log(f"名单未匹配到最近会话：{name}")
            continue
        added = 0
        for cand in contacts_for(name) or []:
            if not isinstance(cand, dict):
                continue
            key, display = _session_identity(cand)
            if not key or _should_skip(key, display, cand):
                continue
            if hits_exclude(key, display, exclude):
                continue
            if not hits_include(key, display, include):
                continue
            if key in seen:
                continue
            seen.add(key)
            usable.append((key, display))
            added += 1
        if log:
            if added:
                log(f"已从通讯录补入「{name}」相关会话 {added} 个")
            else:
                log(f"名单未匹配到：{name}")
    return usable


def _should_query_contacts(name: str) -> bool:
    text = (name or "").strip()
    if not text or "@" in text or text.startswith("wxid_"):
        return False
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _local_account(db: Session) -> Account:
    row = db.query(Account).filter_by(account_key="local").one_or_none()
    if row:
        return row
        row = Account(account_key="local", display_name=DEFAULT_SELF_NAME)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _get_or_create_contact(db: Session, account: Account, peer_key: str, display: str) -> Contact:
    row = (
        db.query(Contact)
        .filter_by(account_id=account.id, peer_key=peer_key)
        .one_or_none()
    )
    if row:
        if display and row.remark != display:
            row.remark = display
            row.nickname = row.nickname or display
        return row
    row = Contact(
        account_id=account.id,
        peer_key=peer_key,
        nickname=display,
        remark=display,
    )
    db.add(row)
    db.flush()
    return row


def _assign_conversation(
    db: Session,
    account: Account,
    contact: Contact,
    msg_time: datetime,
    gap_hours: int,
) -> Conversation:
    latest = (
        db.query(Conversation)
        .filter_by(account_id=account.id, contact_id=contact.id)
        .order_by(Conversation.last_msg_at.desc())
        .first()
    )
    if latest and msg_time - latest.last_msg_at <= timedelta(hours=gap_hours):
        if msg_time < latest.started_at:
            latest.started_at = msg_time
        if msg_time > latest.last_msg_at:
            latest.last_msg_at = msg_time
        latest.msg_count += 1
        return latest
    conv = Conversation(
        account_id=account.id,
        contact_id=contact.id,
        started_at=msg_time,
        last_msg_at=msg_time,
        msg_count=1,
    )
    db.add(conv)
    db.flush()
    return conv


def _insert_messages(
    db: Session,
    account: Account,
    contact: Contact,
    items: list[ParsedMessage],
    gap_hours: int,
) -> tuple[int, int]:
    written = 0
    skipped = 0
    seen: set[str] = set()
    for item in items:
        if item.raw_hash in seen:
            skipped += 1
            continue
        exists = db.query(Message).filter_by(raw_hash=item.raw_hash).first()
        if exists:
            better = item.media_relpath and (
                not exists.media_relpath
                or (exists.media_mime == "audio/silk" and item.media_mime == "audio/mpeg")
            )
            if better:
                exists.media_relpath = item.media_relpath
                exists.media_name = item.media_name
                exists.media_mime = item.media_mime
                exists.media_status = item.media_status
            skipped += 1
            continue
        seen.add(item.raw_hash)
        conv = _assign_conversation(db, account, contact, item.msg_time, gap_hours)
        db.add(
            Message(
                conversation_id=conv.id,
                account_id=account.id,
                contact_id=contact.id,
                msg_time=item.msg_time,
                sender_role=item.sender_role,
                sender_name=item.sender_name,
                msg_type=item.msg_type,
                content=item.content,
                media_relpath=item.media_relpath,
                media_name=item.media_name,
                media_mime=item.media_mime,
                media_status=item.media_status,
                source_ref=item.source_ref,
                raw_hash=item.raw_hash,
            )
        )
        written += 1
    return written, skipped


def _history_with_fallback(display: str, username: str, start_date: str, limit: int) -> list[str]:
    names = []
    for n in (username, display, strip_emoji(display)):
        if n and n not in names:
            names.append(n)
    last_err: ReaderError | None = None
    for name in names:
        try:
            lines = runner.fetch_history(name, start_date, limit)
            if lines:
                return lines
        except ReaderError as exc:
            last_err = exc
            continue
    lookup = display or username
    if _should_query_contacts(lookup):
        for cand in runner.query_contacts(lookup):
            uname = str(cand.get("username") or "").strip()
            if not uname:
                continue
            try:
                lines = runner.fetch_history(uname, start_date, limit)
                if lines:
                    return lines
            except ReaderError as exc:
                last_err = exc
    if last_err:
        raise last_err
    return []


def run_sync_job(
    db: Session,
    job: SyncJob,
    *,
    include_groups: bool = False,
    exclude_names: str = "",
    include_names: str = "",
    limit_people_enabled: bool = True,
    limit_people: int = 20,
    limit_per_group: int | None = None,
) -> None:
    log = lambda msg: append_sync_log(job.id, msg)
    job.status = "running"
    db.commit()
    exclude = parse_name_list(exclude_names)
    include = parse_name_list(include_names)
    log("开始同步")
    if include:
        log(f"只同步这些人：{len(include)} 个名称（人数上限不生效）")
        log("范围：只同步名单中的会话；写了群名就会同步该群")
    elif include_groups:
        log("范围：个人聊天 + 群聊")
    else:
        log("范围：仅个人聊天（群聊默认不同步）")
    if exclude:
        log(f"排除名单：{len(exclude)} 人")
    if include:
        log("人数上限：已指定只同步这些人，不限制")
    elif limit_people_enabled:
        log(f"人数上限：最近 {max(1, min(int(limit_people or 20), 300))} 人")
    else:
        log("人数上限：不限制")
    person_limit = clamp_limit_per_contact(job.limit_per_contact or settings.sync_limit_per_contact)
    group_limit = clamp_limit_per_contact(
        limit_per_group if limit_per_group is not None else settings.sync_limit_per_group
    )
    log(f"每人条数上限：个人 {person_limit}，群聊 {group_limit}")
    try:
        log("正在拉取最近会话列表，大约需要十几秒…")
        sessions = runner.list_sessions(limit=300)
        log(f"拉到 {len(sessions)} 个最近会话")
        usable, stats = select_sync_targets(
            sessions,
            include_groups=include_groups,
            exclude=exclude,
            include=include,
            limit_people_enabled=limit_people_enabled,
            limit_people=limit_people,
        )
        skipped_sys = stats["skipped_sys"]
        if skipped_sys:
            log(f"已跳过 {skipped_sys} 个系统/公众号会话")
        if stats["skipped_group"]:
            log(f"已跳过 {stats['skipped_group']} 个群聊")
        if stats["skipped_not_include"]:
            log(f"名单外会话已跳过 {stats['skipped_not_include']} 个")
        for label in stats["skipped_exclude"]:
            log(f"跳过排除名单：{label}")
        if stats["dropped_limit"]:
            log(f"超出人数上限，其余 {stats['dropped_limit']} 人本次不同步")
        if include:
            usable = expand_include_from_contacts(
                usable,
                include,
                exclude,
                runner.query_contacts,
                log,
            )
        log(f"待读取 {len(usable)} 个会话")
        log("同步时会提取本机已查看的图片、已下载的文件和语音原条")
        account = _local_account(db)
        try:
            apply_self_profile(account, read_self_profile())
            db.commit()
        except Exception:
            pass
        gap = settings.session_gap_hours
        window_start = job.start_date
        days_widened = is_window_widened(window_start, settings.sync_covered_from)
        person_raised = is_limit_raised(person_limit, settings.sync_limit_covered)
        group_raised = is_limit_raised(group_limit, settings.sync_limit_group_covered)
        if days_widened:
            log("已把同步天数调大，本次按新窗口补更早的记录")
        if person_raised:
            log("已把个人每人条数调大，个人会话按最近天数补更早的记录")
        if group_raised:
            log("已把群聊每人条数调大，群聊按最近天数补更早的记录")
        if not days_widened and not person_raised and not group_raised:
            log("已同步过的人只拉上次成功当天及之后的消息，新人仍按最近天数")
        job.total_contacts = len(usable)
        db.commit()
        written_total = 0
        skipped_total = 0
        ok = 0
        last_public = ""
        synced_person = False
        synced_group = False
        for key, display in usable:
            existing = (
                db.query(Contact)
                .filter_by(account_id=account.id, peer_key=key)
                .one_or_none()
            )
            is_group = _peer_is_group(key)
            limit = history_limit_for_peer(key, person_limit, group_limit)
            widened = days_widened or (group_raised if is_group else person_raised)
            start_date = history_start_for_contact(
                window_start,
                existing.last_synced_at if existing else None,
                widened,
            )
            log(f"读取：{display or key}（自 {start_date or window_start}）")
            try:
                lines = _history_with_fallback(display, key, start_date, limit)
            except ReaderError as exc:
                last_public = exc.public_message
                if exc.code == "no_history":
                    log(f"跳过：{display or key} — 暂无记录或名称未能匹配")
                else:
                    log(f"失败：{display or key} — {exc.public_message}")
                continue
            parsed = parse_history_lines(lines, key)
            if looks_like_official_feed(parsed):
                skipped_sys += 1
                log(f"跳过公众号：{display or key}")
                continue
            media_stats = attach_media(parsed, key)
            contact = _get_or_create_contact(db, account, key, display)
            w, s = _insert_messages(db, account, contact, parsed, gap)
            contact.last_synced_at = datetime.now()
            written_total += w
            skipped_total += s
            ok += 1
            job.ok_contacts = ok
            job.written = written_total
            job.skipped = skipped_total
            db.commit()
            extra = ""
            ready = media_stats["image"] + media_stats["voice"] + media_stats["file"]
            if ready or media_stats["missing"]:
                extra = (
                    f"，媒体 {ready}（图 {media_stats['image']} / "
                    f"语音 {media_stats['voice']} / 文件 {media_stats['file']}）"
                )
                if media_stats["missing"]:
                    extra += f"，未缓存 {media_stats['missing']}"
            log(f"完成：{display or key}，写入 {w}，跳过 {s}{extra}")
            if is_group:
                synced_group = True
            else:
                synced_person = True
        job.written = written_total
        job.skipped = skipped_total
        job.ok_contacts = ok
        if ok == 0 and last_public:
            job.status = "failed"
            job.error_message = last_public
            log(f"同步结束：失败 — {last_public}")
        elif ok == 0:
            job.status = "failed"
            job.error_message = "暂无可用会话，请确认微信已登录"
            log("同步结束：没有可用会话")
        else:
            job.status = "succeeded"
            job.error_message = ""
            mark_sync_coverage(db, window_start)
            if synced_person:
                mark_sync_limit_coverage(db, person_limit, group=False)
            if synced_group:
                mark_sync_limit_coverage(db, group_limit, group=True)
            log(f"同步结束：成功，会话 {ok}，写入 {written_total}，跳过 {skipped_total}")
            try:
                from app.engine.metrics import run_rule_scan

                scan = run_rule_scan(db, account.id)
                log(f"已更新效率统计，命中 {scan.get('hits', 0)} 条")
            except Exception:
                log("效率统计未更新，可在效率页点重新统计")
        db.commit()
    except ReaderError as exc:
        db.rollback()
        job.status = "failed"
        job.error_message = exc.public_message
        db.commit()
        log(f"同步中断：{exc.public_message}")
    except Exception:
        db.rollback()
        job.status = "failed"
        job.error_message = "同步失败，请稍后重试"
        db.commit()
        log("同步中断：写入冲突或内部错误，已标记失败")
