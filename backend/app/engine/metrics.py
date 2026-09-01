from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from sqlalchemy.orm import Session

from app.config import settings
from app.ingest.wechat_cli.sync_job import _should_skip, looks_like_official_feed
from app.models import Contact, Conversation, HitRecord, Lexicon, Message, MetricDaily


def _response_stats(messages: list[Message], timeout_seconds: int) -> tuple[list[float], list[float], int]:
    firsts: list[float] = []
    avgs: list[float] = []
    timeouts = 0
    first_customer: datetime | None = None
    first_cs: datetime | None = None
    pending: datetime | None = None
    for msg in messages:
        if msg.msg_type != "text":
            continue
        if msg.sender_role == "customer":
            if first_customer is None:
                first_customer = msg.msg_time
            pending = msg.msg_time
        elif msg.sender_role == "cs" and pending is not None:
            delta = (msg.msg_time - pending).total_seconds()
            if delta >= 0:
                avgs.append(delta)
                if delta > timeout_seconds:
                    timeouts += 1
            if first_cs is None:
                first_cs = msg.msg_time
            pending = None
    if first_customer and first_cs and first_cs >= first_customer:
        firsts.append((first_cs - first_customer).total_seconds())
    if pending is not None:
        age = (datetime.now() - pending).total_seconds()
        if age > timeout_seconds:
            timeouts += 1
    return firsts, avgs, timeouts


def run_rule_scan(db: Session, account_id: int | None = None) -> dict:
    timeout = settings.timeout_seconds
    q = db.query(Conversation)
    if account_id is not None:
        q = q.filter(Conversation.account_id == account_id)
    conversations = q.all()
    daily: dict[tuple[int, str], dict] = defaultdict(
        lambda: {
            "msg_count": 0,
            "conversation_count": 0,
            "firsts": [],
            "avgs": [],
            "timeout_count": 0,
        }
    )
    official_cache: dict[int, bool] = {}
    for conv in conversations:
        msgs = (
            db.query(Message)
            .filter_by(conversation_id=conv.id)
            .order_by(Message.msg_time.asc())
            .all()
        )
        if not msgs:
            continue
        contact = db.get(Contact, conv.contact_id)
        cid = conv.contact_id
        if cid not in official_cache:
            label = ((contact.remark if contact else "") or (contact.nickname if contact else "") or "")
            peer = contact.peer_key if contact else ""
            all_msgs = db.query(Message).filter_by(contact_id=cid).all()
            official_cache[cid] = _should_skip(peer, label) or looks_like_official_feed(all_msgs)
        if official_cache[cid]:
            continue
        day = conv.started_at.strftime("%Y%m%d")
        bucket = daily[(conv.account_id, day)]
        bucket["msg_count"] += len(msgs)
        bucket["conversation_count"] += 1
        firsts, avgs, timeouts = _response_stats(msgs, timeout)
        bucket["firsts"].extend(firsts)
        bucket["avgs"].extend(avgs)
        bucket["timeout_count"] += timeouts

    if account_id is not None:
        db.query(MetricDaily).filter(MetricDaily.account_id == account_id).delete()
    else:
        db.query(MetricDaily).delete()
    for (acc_id, day), bucket in daily.items():
        first_avg = (
            sum(bucket["firsts"]) / len(bucket["firsts"]) if bucket["firsts"] else None
        )
        avg_resp = sum(bucket["avgs"]) / len(bucket["avgs"]) if bucket["avgs"] else None
        db.add(
            MetricDaily(
                account_id=acc_id,
                day=day,
                msg_count=bucket["msg_count"],
                conversation_count=bucket["conversation_count"],
                first_response_avg=first_avg,
                avg_response=avg_resp,
                timeout_count=bucket["timeout_count"],
            )
        )

    if account_id is not None:
        db.query(HitRecord).filter(HitRecord.account_id == account_id).delete()
    else:
        db.query(HitRecord).delete()
    terms = db.query(Lexicon).filter_by(enabled=True).all()
    if terms:
        msg_q = db.query(Message).filter(Message.sender_role == "cs", Message.msg_type == "text")
        if account_id is not None:
            msg_q = msg_q.filter(Message.account_id == account_id)
        for msg in msg_q.all():
            text = msg.content or ""
            for lex in terms:
                if lex.term and lex.term in text:
                    db.add(
                        HitRecord(
                            lexicon_id=lex.id,
                            message_id=msg.id,
                            conversation_id=msg.conversation_id,
                            account_id=msg.account_id,
                            term=lex.term,
                            kind=lex.kind,
                            msg_time=msg.msg_time,
                        )
                    )
    db.commit()
    hits_q = db.query(HitRecord)
    if account_id is not None:
        hits_q = hits_q.filter(HitRecord.account_id == account_id)
    return {"days": len(daily), "hits": hits_q.count()}
