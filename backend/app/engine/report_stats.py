"""诊断报告用的响应与时段统计，口径对齐客户样例。"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy.orm import Session

from app.engine.review import contact_is_official
from app.models import Contact, Message


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2


def compact_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    if seconds < 60:
        return f"{int(round(seconds))}秒"
    return f"{seconds / 60:.1f}分钟"


def _pct(part: int, whole: int) -> float | None:
    if not whole:
        return None
    return round(100.0 * part / whole, 1)


def diagnostic_stats(db: Session, start_date: str = "", end_date: str = "", account_id: int | None = None) -> dict:
    q = db.query(Message).join(Contact, Message.contact_id == Contact.id)
    if account_id:
        q = q.filter(Message.account_id == account_id)
    if start_date:
        q = q.filter(Message.msg_time >= f"{start_date} 00:00:00")
    if end_date:
        q = q.filter(Message.msg_time <= f"{end_date} 23:59:59")
    rows = q.order_by(Message.conversation_id.asc(), Message.msg_time.asc()).all()

    by_conv: dict[int, list[Message]] = defaultdict(list)
    contact_ids: dict[int, int] = {}
    for msg in rows:
        by_conv[msg.conversation_id].append(msg)
        contact_ids[msg.conversation_id] = msg.contact_id

    noise_contacts: dict[int, bool] = {}
    deltas: list[float] = []
    hour_cs = [0] * 24
    cs_total = 0
    evening_cs = 0
    night_cs = 0
    evening_customer = 0
    evening_customer_replied = 0
    conv_count = 0
    msg_count = 0

    for conv_id, msgs in by_conv.items():
        cid = contact_ids.get(conv_id)
        if cid not in noise_contacts:
            noise_contacts[cid] = contact_is_official(db, db.get(Contact, cid) if cid else None)
        if noise_contacts.get(cid):
            continue
        conv_count += 1
        msg_count += len(msgs)
        pending = None
        later_cs_times = [m.msg_time for m in msgs if m.sender_role == "cs"]
        for msg in msgs:
            if msg.sender_role == "cs":
                hour_cs[msg.msg_time.hour] += 1
                cs_total += 1
                if msg.msg_time.hour >= 17:
                    evening_cs += 1
                if msg.msg_time.hour < 8:
                    night_cs += 1
                if pending is not None and msg.msg_type == "text":
                    delta = (msg.msg_time - pending).total_seconds()
                    if delta >= 0:
                        deltas.append(delta)
                    pending = None
            elif msg.sender_role == "customer":
                if msg.msg_type == "text":
                    pending = msg.msg_time
                if msg.msg_time.hour >= 17:
                    evening_customer += 1
                    if any(t > msg.msg_time for t in later_cs_times):
                        evening_customer_replied += 1

    med = median(deltas)
    avg = (sum(deltas) / len(deltas)) if deltas else None
    within_5 = sum(1 for d in deltas if d <= 300)
    within_1h = sum(1 for d in deltas if d <= 3600)
    max_hour = max(hour_cs) if any(hour_cs) else 1
    return {
        "conversation_count": conv_count,
        "msg_count": msg_count,
        "reply_count": len(deltas),
        "median_seconds": med,
        "median_label": compact_duration(med),
        "avg_seconds": avg,
        "avg_label": compact_duration(avg),
        "within_5min_pct": _pct(within_5, len(deltas)),
        "within_1h_pct": _pct(within_1h, len(deltas)),
        "hour_cs": hour_cs,
        "hour_max": max_hour,
        "evening_share_pct": _pct(evening_cs, cs_total),
        "night_share_pct": _pct(night_cs, cs_total),
        "evening_customer": evening_customer,
        "evening_replied": evening_customer_replied,
        "evening_reply_pct": _pct(evening_customer_replied, evening_customer),
        "cs_total": cs_total,
    }


def stats_for_prompt(stats: dict) -> str:
    def pct(v):
        return "—" if v is None else f"{v}%"

    return (
        f"会话 {stats.get('conversation_count') or 0} 段，"
        f"消息 {stats.get('msg_count') or 0} 条，"
        f"可统计回复 {stats.get('reply_count') or 0} 次。"
        f"中位回复 {stats.get('median_label')}，平均 {stats.get('avg_label')}。"
        f"5 分钟内回复 {pct(stats.get('within_5min_pct'))}，"
        f"1 小时内 {pct(stats.get('within_1h_pct'))}。"
        f"17 点后客服消息占比 {pct(stats.get('evening_share_pct'))}，"
        f"深夜 0–8 点占比 {pct(stats.get('night_share_pct'))}。"
        f"下班后客户消息 {stats.get('evening_customer') or 0} 条，"
        f"回复率 {pct(stats.get('evening_reply_pct'))}。"
    )
