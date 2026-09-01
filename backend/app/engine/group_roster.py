"""群聊成员名册：按发言人聚合，标记是否加好友。"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.engine.review import contact_label
from app.ingest.wechat_cli.parse import strip_emoji
from app.models import AnalysisJob, AnalysisResult, Contact, Conversation, GroupMemberMark, Message

ADD_STATUS = ("watch", "recommend", "skip", "already_friend", "added")
STATUS_LABEL = {
    "watch": "再观察",
    "recommend": "建议加好友",
    "skip": "暂不加",
    "already_friend": "已是好友",
    "added": "已加过",
}
MODEL_STATUS = {"recommend": "recommend", "watch": "watch", "skip": "skip"}
SELF_KEY = "_self"
SELF_NAME = "我"
REPLY_SECONDS = 180
MAX_GRAPH_NODES = 28
MAX_GRAPH_EDGES = 80


def is_group_contact(contact: Contact | None) -> bool:
    if not contact:
        return False
    return (contact.peer_key or "").lower().endswith("@chatroom")


def member_key(name: str) -> str:
    return strip_emoji(name or "").strip().casefold()


def _in_range(msg: Message, start_date: str, end_date: str) -> bool:
    if start_date and msg.msg_time < datetime.strptime(f"{start_date} 00:00:00", "%Y-%m-%d %H:%M:%S"):
        return False
    if end_date and msg.msg_time > datetime.strptime(f"{end_date} 23:59:59", "%Y-%m-%d %H:%M:%S"):
        return False
    return True


def friend_name_keys(db: Session) -> dict[str, str]:
    keys: dict[str, str] = {}
    for contact in db.query(Contact).all():
        if is_group_contact(contact):
            continue
        label = contact_label(contact)
        for raw in (contact.remark, contact.nickname, label):
            key = member_key(raw)
            if key:
                keys[key] = label or raw
    return keys


def list_groups(db: Session, start_date: str = "", end_date: str = "", q: str = "", account_id: int | None = None) -> list[dict]:
    needle = (q or "").strip().casefold()
    out: list[dict] = []
    contacts = db.query(Contact).order_by(Contact.id.asc())
    if account_id is not None:
        contacts = contacts.filter(Contact.account_id == account_id)
    for contact in contacts.all():
        if not is_group_contact(contact):
            continue
        name = contact_label(contact) or contact.peer_key
        if needle and needle not in name.casefold() and needle not in (contact.peer_key or "").casefold():
            continue
        qmsg = db.query(Message).filter_by(contact_id=contact.id)
        msgs = qmsg.all()
        if start_date or end_date:
            msgs = [m for m in msgs if _in_range(m, start_date, end_date)]
        if not msgs:
            continue
        speakers = {
            member_key(m.sender_name)
            for m in msgs
            if m.sender_role == "customer" and member_key(m.sender_name)
        }
        if not speakers:
            continue
        last = max(msgs, key=lambda m: m.msg_time)
        latest_conv = (
            db.query(Conversation)
            .filter_by(contact_id=contact.id)
            .order_by(Conversation.last_msg_at.desc())
            .first()
        )
        out.append(
            {
                "id": contact.id,
                "name": name,
                "peer_key": contact.peer_key,
                "msg_count": len(msgs),
                "member_count": len(speakers),
                "last_msg_at": last.msg_time.isoformat(),
                "conversation_id": latest_conv.id if latest_conv else None,
            }
        )
    out.sort(key=lambda r: r["last_msg_at"], reverse=True)
    return out


def _activity(count: int) -> str:
    if count >= 8:
        return "high"
    if count >= 3:
        return "mid"
    return "low"


def _mark_map(db: Session, contact_id: int) -> dict[str, GroupMemberMark]:
    rows = db.query(GroupMemberMark).filter_by(contact_id=contact_id).all()
    return {row.member_key: row for row in rows}


def resolve_group_window(
    report_type: str,
    start_date: str = "",
    end_date: str = "",
    today: date | None = None,
) -> tuple[str, str]:
    today = today or date.today()
    end_raw = (end_date or start_date or today.isoformat())[:10]
    try:
        end_d = datetime.strptime(end_raw, "%Y-%m-%d").date()
    except ValueError:
        end_d = today
        end_raw = today.isoformat()
    if report_type == "daily":
        return end_raw, end_raw
    start_raw = (start_date or "")[:10]
    user_start = None
    if start_raw:
        try:
            user_start = datetime.strptime(start_raw, "%Y-%m-%d").date()
        except ValueError:
            user_start = None
    if user_start is not None:
        span = (end_d - user_start).days
        if 0 <= span <= 13:
            return user_start.isoformat(), end_raw
    week_start = end_d - timedelta(days=6)
    return week_start.isoformat(), end_raw


def group_timeline(
    db: Session,
    contact: Contact,
    start_date: str = "",
    end_date: str = "",
    limit: int = 160,
) -> tuple[str, int]:
    msgs = db.query(Message).filter_by(contact_id=contact.id).order_by(Message.msg_time.asc()).all()
    if start_date or end_date:
        msgs = [m for m in msgs if _in_range(m, start_date, end_date)]
    total = len(msgs)
    lines: list[str] = []
    for msg in msgs:
        event = _speaker_event(msg)
        if not event:
            continue
        if msg.msg_type != "text":
            continue
        when, _key, name, content = event
        text = (content or "").strip()
        if not text:
            continue
        lines.append(f"[{when:%Y-%m-%d %H:%M}] {name}: {text}")
    if len(lines) > limit:
        lines = lines[:20] + lines[-(limit - 20) :]
    return "\n".join(lines), total


def digest_prompt_stats(members: list[dict], msg_count: int, start_date: str, end_date: str) -> str:
    window = f"{start_date} 至 {end_date}" if start_date != end_date else (start_date or "当前范围")
    active = [m["name"] for m in members if m.get("activity") in ("high", "mid")]
    quiet = [m["name"] for m in members if m.get("activity") == "low"]
    return (
        f"范围 {window}。消息 {msg_count} 条，发言成员 {len(members)} 人。"
        f"较活跃：{'、'.join(active[:12]) or '无'}。发言较少：{'、'.join(quiet[:12]) or '无'}。"
        "数字以统计为准，不要另编人数。"
    )


def _portrait_jobs(db: Session, contact_id: int, limit: int = 8) -> list[AnalysisJob]:
    return (
        db.query(AnalysisJob)
        .filter_by(kind="group", contact_id=contact_id, status="succeeded")
        .filter(
            or_(
                AnalysisJob.report_type.is_(None),
                AnalysisJob.report_type == "",
                AnalysisJob.report_type == "portrait",
            )
        )
        .order_by(AnalysisJob.created_at.desc())
        .limit(limit)
        .all()
    )


def _profiles_from_payload(payload: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for item in payload.get("members") or []:
        if not isinstance(item, dict):
            continue
        key = member_key(str(item.get("name") or ""))
        if key:
            out[key] = item
    return out


def latest_group_profiles(db: Session, contact_id: int) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for job in _portrait_jobs(db, contact_id):
        result = (
            db.query(AnalysisResult)
            .filter_by(job_id=job.id)
            .order_by(AnalysisResult.id.desc())
            .first()
        )
        if not result:
            continue
        try:
            payload = json.loads(result.payload_json or "{}")
        except json.JSONDecodeError:
            continue
        for key, item in _profiles_from_payload(payload).items():
            if key not in out:
                out[key] = item
    return out


def fill_missing_member_profiles(parsed: dict, members: list[dict], previous: dict[str, dict] | None = None) -> dict:
    previous = previous or {}
    existing = _profiles_from_payload(parsed if isinstance(parsed, dict) else {})
    filled: list[dict] = []
    seen: set[str] = set()
    for roster in members:
        key = roster["key"]
        seen.add(key)
        item = existing.get(key) or {}
        prev = previous.get(key) or {}
        if not (item.get("profile") or "").strip() and (prev.get("profile") or "").strip():
            item = {**prev, **{k: v for k, v in item.items() if v not in (None, "", [])}}
            item["name"] = roster["name"]
        if not item:
            item = {
                "name": roster["name"],
                "activity": roster.get("activity") or prev.get("activity") or "low",
                "profile": (prev.get("profile") or "").strip(),
                "signals": prev.get("signals") or [],
                "add_friend": prev.get("add_friend") or "watch",
                "reason": (prev.get("reason") or "").strip(),
            }
        else:
            item = dict(item)
            item["name"] = roster["name"]
            if not (item.get("profile") or "").strip():
                item["profile"] = (prev.get("profile") or "").strip()
            if not (item.get("reason") or "").strip():
                item["reason"] = (prev.get("reason") or "").strip()
            if not item.get("signals"):
                item["signals"] = prev.get("signals") or []
        filled.append(item)
    for key, item in existing.items():
        if key not in seen:
            filled.append(item)
    parsed = dict(parsed or {})
    parsed["members"] = filled
    return parsed


def list_members(
    db: Session,
    contact: Contact,
    start_date: str = "",
    end_date: str = "",
    min_msgs: int = 1,
) -> list[dict]:
    msgs = db.query(Message).filter_by(contact_id=contact.id).order_by(Message.msg_time.asc()).all()
    if start_date or end_date:
        msgs = [m for m in msgs if _in_range(m, start_date, end_date)]
    buckets: dict[str, dict] = {}
    for msg in msgs:
        if msg.sender_role != "customer":
            continue
        key = member_key(msg.sender_name)
        if not key:
            continue
        bucket = buckets.get(key)
        if not bucket:
            bucket = {
                "key": key,
                "name": (msg.sender_name or "").strip() or key,
                "msg_count": 0,
                "text_count": 0,
                "first_at": msg.msg_time,
                "last_at": msg.msg_time,
                "samples": [],
            }
            buckets[key] = bucket
        bucket["msg_count"] += 1
        bucket["last_at"] = msg.msg_time
        if msg.msg_type == "text" and (msg.content or "").strip():
            bucket["text_count"] += 1
            if len(bucket["samples"]) < 12:
                bucket["samples"].append(f"[{msg.msg_time:%Y-%m-%d %H:%M}] {bucket['name']}: {msg.content}")
    friends = friend_name_keys(db)
    marks = _mark_map(db, contact.id)
    profiles = latest_group_profiles(db, contact.id)
    out: list[dict] = []
    for key, bucket in buckets.items():
        if bucket["msg_count"] < max(1, min_msgs):
            continue
        mark = marks.get(key)
        friend_label = friends.get(key) or ""
        already = bool(friend_label)
        status = "already_friend" if already else "watch"
        source = "auto" if already else ""
        note = ""
        if mark:
            status = mark.status if mark.status in ADD_STATUS else status
            source = mark.source or source
            note = mark.note or ""
            if already and mark.source != "user" and status not in ("added", "already_friend"):
                status = "already_friend"
                source = "auto"
        elif already:
            status = "already_friend"
            source = "auto"
        profile = profiles.get(key) or {}
        out.append(
            {
                "key": key,
                "name": bucket["name"],
                "msg_count": bucket["msg_count"],
                "text_count": bucket["text_count"],
                "activity": _activity(bucket["msg_count"]),
                "first_at": bucket["first_at"].isoformat(),
                "last_at": bucket["last_at"].isoformat(),
                "status": status,
                "status_label": STATUS_LABEL.get(status, status),
                "source": source,
                "note": note,
                "already_friend": already,
                "friend_label": friend_label,
                "profile": (profile.get("profile") or "").strip(),
                "signals": profile.get("signals") or [],
                "reason": (profile.get("reason") or "").strip(),
                "suggested": (profile.get("add_friend") or "").strip(),
                "samples": bucket["samples"],
            }
        )
    out.sort(key=lambda r: (-r["msg_count"], r["name"]))
    return out


def _speaker_event(msg: Message) -> tuple[datetime, str, str, str] | None:
    if msg.sender_role == "system":
        return None
    if msg.sender_role == "cs":
        return msg.msg_time, SELF_KEY, SELF_NAME, msg.content or ""
    key = member_key(msg.sender_name)
    if not key:
        return None
    return msg.msg_time, key, (msg.sender_name or "").strip() or key, msg.content or ""


def _pair_key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


def relation_graph(
    events: list[tuple[datetime, str, str, str]],
    roster: list[dict],
    *,
    reply_seconds: int = REPLY_SECONDS,
    max_nodes: int = MAX_GRAPH_NODES,
    max_edges: int = MAX_GRAPH_EDGES,
) -> dict:
    roster_nodes = list(roster[: max(1, max_nodes)])
    allowed = {item["key"] for item in roster_nodes}
    names = {item["key"]: item["name"] for item in roster_nodes}
    has_self = any(key == SELF_KEY for _, key, _, _ in events)
    if has_self:
        allowed.add(SELF_KEY)
        names[SELF_KEY] = SELF_NAME
    mention_needles = sorted(
        ((key, name) for key, name in names.items() if key != SELF_KEY and len(name) >= 2),
        key=lambda item: -len(item[1]),
    )
    edges: dict[tuple[str, str], dict] = {}

    def bump(a: str, b: str, kind: str) -> None:
        if a == b or a not in allowed or b not in allowed:
            return
        pair = _pair_key(a, b)
        row = edges.get(pair)
        if not row:
            row = {"source": pair[0], "target": pair[1], "replies": 0, "mentions": 0, "weight": 0}
            edges[pair] = row
        if kind == "reply":
            row["replies"] += 1
        else:
            row["mentions"] += 1
        row["weight"] = row["replies"] + row["mentions"] * 2

    prev = None
    for when, key, _name, content in events:
        if key not in allowed:
            prev = None
            continue
        if prev:
            pwhen, pkey = prev
            gap = (when - pwhen).total_seconds()
            if 0 <= gap <= reply_seconds:
                bump(key, pkey, "reply")
        text = content or ""
        if text:
            for other, needle in mention_needles:
                if other == key:
                    continue
                if needle in text:
                    bump(key, other, "mention")
        prev = (when, key)

    ranked = sorted(edges.values(), key=lambda e: (-e["weight"], e["source"], e["target"]))[:max_edges]
    linked = {e["source"] for e in ranked} | {e["target"] for e in ranked}
    degree: dict[str, int] = {}
    strength: dict[str, int] = {}
    for edge in ranked:
        degree[edge["source"]] = degree.get(edge["source"], 0) + 1
        degree[edge["target"]] = degree.get(edge["target"], 0) + 1
        strength[edge["source"]] = strength.get(edge["source"], 0) + edge["weight"]
        strength[edge["target"]] = strength.get(edge["target"], 0) + edge["weight"]

    nodes = []
    if has_self:
        nodes.append(
            {
                "key": SELF_KEY,
                "name": SELF_NAME,
                "self": True,
                "msg_count": sum(1 for _, key, _, _ in events if key == SELF_KEY),
                "activity": "mid",
                "status": "self",
                "status_label": "本机",
                "degree": degree.get(SELF_KEY, 0),
                "strength": strength.get(SELF_KEY, 0),
                "isolated": SELF_KEY not in linked,
            }
        )
    for item in roster_nodes:
        nodes.append(
            {
                "key": item["key"],
                "name": item["name"],
                "self": False,
                "msg_count": item["msg_count"],
                "activity": item["activity"],
                "status": item["status"],
                "status_label": item["status_label"],
                "degree": degree.get(item["key"], 0),
                "strength": strength.get(item["key"], 0),
                "isolated": item["key"] not in linked,
            }
        )
    hub = max(nodes, key=lambda n: (n["strength"], n["msg_count"])) if nodes else None
    return {
        "nodes": nodes,
        "edges": ranked,
        "edge_count": len(ranked),
        "linked": len(linked),
        "isolated": sum(1 for n in nodes if n["isolated"] and not n["self"]),
        "hub": {"key": hub["key"], "name": hub["name"]} if hub and hub["strength"] else None,
    }


def build_member_graph(
    db: Session,
    contact: Contact,
    members: list[dict],
    start_date: str = "",
    end_date: str = "",
) -> dict:
    msgs = db.query(Message).filter_by(contact_id=contact.id).order_by(Message.msg_time.asc()).all()
    if start_date or end_date:
        msgs = [m for m in msgs if _in_range(m, start_date, end_date)]
    events = []
    for msg in msgs:
        event = _speaker_event(msg)
        if event:
            events.append(event)
    return relation_graph(events, members)


def graph_for_prompt(graph: dict, limit: int = 12) -> str:
    edges = graph.get("edges") or []
    if not edges:
        return "【互动】当前范围几乎没有紧挨着的对话或点名。"
    names = {n["key"]: n["name"] for n in graph.get("nodes") or []}
    lines = [f"【互动】{graph.get('edge_count') or 0} 对关系，孤立发言 {graph.get('isolated') or 0} 人。"]
    hub = graph.get("hub") or {}
    if hub.get("name"):
        lines.append(f"互动最密：{hub['name']}")
    for edge in edges[:limit]:
        left = names.get(edge["source"], edge["source"])
        right = names.get(edge["target"], edge["target"])
        bits = []
        if edge["replies"]:
            bits.append(f"紧挨回复{edge['replies']}")
        if edge["mentions"]:
            bits.append(f"点名{edge['mentions']}")
        lines.append(f"- {left} ↔ {right} {'、'.join(bits)}")
    return "\n".join(lines)


def group_prompt_stats(members: list[dict]) -> str:
    recommend = sum(1 for m in members if m["status"] == "recommend")
    friends = sum(1 for m in members if m["status"] == "already_friend" or m["already_friend"])
    active = sum(1 for m in members if m["activity"] in ("high", "mid"))
    return (
        f"成员 {len(members)} 人，较活跃 {active} 人，已是好友 {friends} 人，当前标记建议加好友 {recommend} 人。"
        "数字以名册为准，不要另编人数。"
    )


def group_snippets(group_name: str, members: list[dict], limit: int = 40) -> str:
    lines = [f"【群】{group_name}", "【成员名册】"]
    for item in members[:limit]:
        friend = " 已是好友" if item["already_friend"] else ""
        lines.append(
            f"- {item['name']} 发言{item['msg_count']} 最近{item['last_at'][:16].replace('T', ' ')}{friend}"
        )
    lines.append("【按人摘录】")
    used = 0
    for item in members[:limit]:
        if not item["samples"]:
            continue
        lines.append(f"### {item['name']}")
        lines.extend(item["samples"])
        used += 1
        if used >= limit:
            break
    return "\n".join(lines)


def upsert_mark(
    db: Session,
    contact_id: int,
    key: str,
    *,
    name: str,
    status: str,
    note: str = "",
    source: str = "user",
    commit: bool = True,
) -> GroupMemberMark:
    key = member_key(key)
    if not key:
        raise ValueError("成员名不能为空")
    if status not in ADD_STATUS:
        raise ValueError("状态无效")
    row = db.query(GroupMemberMark).filter_by(contact_id=contact_id, member_key=key).one_or_none()
    if not row:
        row = GroupMemberMark(contact_id=contact_id, member_key=key)
        db.add(row)
    row.member_name = (name or "").strip() or key
    row.status = status
    row.note = (note or "").strip()
    row.source = source
    if commit:
        db.commit()
        db.refresh(row)
    return row


def apply_model_marks(db: Session, contact_id: int, members: list[dict], payload: dict) -> None:
    existing = _mark_map(db, contact_id)
    by_key = {m["key"]: m for m in members}
    for item in payload.get("members") or []:
        if not isinstance(item, dict):
            continue
        key = member_key(str(item.get("name") or ""))
        roster = by_key.get(key)
        if not roster:
            continue
        mark = existing.get(key)
        if mark and mark.source == "user":
            continue
        if roster["already_friend"]:
            status = "already_friend"
            source = "auto"
        else:
            status = MODEL_STATUS.get(str(item.get("add_friend") or "").strip(), "watch")
            source = "model"
        row = upsert_mark(
            db,
            contact_id,
            key,
            name=roster["name"],
            status=status,
            note=(item.get("reason") or "").strip(),
            source=source,
            commit=False,
        )
        existing[key] = row
    db.commit()
