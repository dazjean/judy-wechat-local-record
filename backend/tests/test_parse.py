from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.ingest.wechat_cli.normalize import normalize  # noqa: E402
from app.ingest.wechat_cli.parse import parse_history_lines  # noqa: E402


def test_parse_roles_and_minute_padding():
    lines = [
        "[2026-08-01 09:00] 家长: 课时怎么退",
        "[2026-08-01 09:01] me: 您好，我帮您看一下",
        "[2026-08-01 09:02] [系统]: 以上是打招呼消息",
    ]
    parsed = parse_history_lines(lines, "wxid_demo")
    assert len(parsed) == 3
    assert parsed[0].sender_role == "customer"
    assert parsed[1].sender_role == "cs"
    assert parsed[2].sender_role == "system"
    assert parsed[0].msg_time.second == 0
    assert parsed[0].msg_type == "text"


def test_parse_image_placeholder():
    lines = ["[2026-08-01 10:00:03] 家长: [图片]"]
    parsed = parse_history_lines(lines, "wxid_demo")
    assert parsed[0].msg_type == "image"


def test_normalize_link_keeps_title_and_url():
    xml = (
        "<msg><appmsg appid=''>"
        "<title>课时退费</title>"
        "<des>查看详情</des>"
        "<type>5</type>"
        "<url><![CDATA[https://example.com/refund]]></url>"
        "</appmsg></msg>"
    )
    out = normalize(xml)
    assert out.startswith("[链接] 课时退费")
    assert "https://example.com/refund" in out
    assert "查看详情" in out


def test_parse_link_message_type():
    lines = [
        "[2026-08-01 10:00:03] 家长: "
        "<msg><appmsg><title>课程表</title>"
        "<url>https://example.com/a</url></appmsg></msg>"
    ]
    parsed = parse_history_lines(lines, "wxid_demo")
    assert parsed[0].msg_type == "link"
    assert "https://example.com/a" in parsed[0].content
    assert "课程表" in parsed[0].content


def test_normalize_link_fallback_http_in_share_url():
    xml = (
        "<appmsg><title>活动</title>"
        "<shareUrlOpen>https://mp.weixin.qq.com/s?id=1</shareUrlOpen>"
        "</appmsg>"
    )
    out = normalize(xml)
    assert out.startswith("[链接] 活动")
    assert "https://mp.weixin.qq.com/s?id=1" in out


def test_dedup_hash_stable():
    lines = ["[2026-08-01 09:00] 家长: 你好"]
    a = parse_history_lines(lines, "peer-a")
    b = parse_history_lines(lines, "peer-a")
    c = parse_history_lines(lines, "peer-b")
    d = parse_history_lines(["[2026-08-01 09:00] 另一人: 你好"], "peer-a")
    assert a[0].raw_hash == b[0].raw_hash
    assert a[0].raw_hash != c[0].raw_hash
    assert a[0].raw_hash != d[0].raw_hash
