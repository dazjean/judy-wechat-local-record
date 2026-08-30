from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.engine.radar import (  # noqa: E402
    classify_status,
    clip_snippet,
    detect_intent,
    detect_role,
    has_decision,
    has_refund_precursor,
    is_quoted_silent,
    is_returning,
    sort_key,
)


def test_clip_snippet_strips_link_prefix():
    assert clip_snippet("[链接] 支付成功通知") == "支付成功通知"
    assert clip_snippet("") == ""


def test_detect_intent_prefers_refund():
    texts = ["多少钱一节", "想退费"]
    assert detect_intent(list(reversed(texts))) == "退费"


def test_classify_pending_timeout():
    now = datetime(2026, 8, 29, 18, 0, 0)
    last = now - timedelta(minutes=10)
    status, timeout = classify_status(
        last_role="customer",
        last_at=last,
        first_at=last,
        customer_texts=2,
        now=now,
        timeout_seconds=180,
    )
    assert status == "pending"
    assert timeout is True


def test_classify_quiet_after_week():
    now = datetime(2026, 8, 29, 18, 0, 0)
    last = now - timedelta(days=8)
    status, timeout = classify_status(
        last_role="cs",
        last_at=last,
        first_at=last - timedelta(days=2),
        customer_texts=6,
        now=now,
        timeout_seconds=180,
    )
    assert status == "quiet"
    assert timeout is False


def test_sort_risk_before_quiet():
    risk = {"risk": True, "timeout": False, "status": "active", "promise": False, "quoted": False, "decision": False, "precursor": False, "last_msg_at": "1"}
    quiet = {"risk": False, "timeout": False, "status": "quiet", "promise": False, "quoted": False, "decision": False, "precursor": False, "last_msg_at": "9"}
    assert sort_key(risk) < sort_key(quiet)


def test_detect_role_teacher_before_parent():
    assert detect_role(["我们学校的孩子也要用"]) == "老师"
    assert detect_role(["孩子作业跟不上"]) == "家长"
    assert detect_role(["我自己学一套"]) == "学员"


def test_quoted_silent_after_price_or_file():
    assert is_quoted_silent(last_role="cs", last_cs_content="发你报价", last_cs_type="text")
    assert is_quoted_silent(last_role="cs", last_cs_content="看下资料", last_cs_type="link")
    assert not is_quoted_silent(last_role="customer", last_cs_content="发你报价", last_cs_type="text")


def test_decision_and_precursor_and_returning():
    assert has_decision(["我再考虑一下"])
    assert has_refund_precursor(["效果不太好", "能退费吗"])
    assert not has_refund_precursor(["能退费吗"])
    now = datetime(2026, 8, 29, 18, 0, 0)
    assert is_returning(first_at=now - timedelta(days=40), last_at=now)
    assert not is_returning(first_at=now - timedelta(days=3), last_at=now)


def test_sort_quoted_before_new():
    quoted = {"risk": False, "timeout": False, "status": "active", "promise": False, "quoted": True, "decision": False, "precursor": False, "last_msg_at": "1"}
    new = {"risk": False, "timeout": False, "status": "new", "promise": False, "quoted": False, "decision": False, "precursor": False, "last_msg_at": "9"}
    assert sort_key(quoted) < sort_key(new)
