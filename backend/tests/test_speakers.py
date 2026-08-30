from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.engine.speakers import peer_display, self_display, speaker_label  # noqa: E402


def test_peer_uses_chat_nickname():
    assert peer_display("张家长", "微信名", "备注") == "张家长"
    assert peer_display("me", "微信名", "备注张") == "微信名"
    assert peer_display("", "", "备注张") == "备注张"


def test_self_hides_placeholder():
    assert self_display("本机客服") == "我"
    assert self_display("本机微信") == "我"
    assert self_display("庆总") == "庆总"


def test_speaker_label_roles():
    assert speaker_label(role="system") == "系统"
    assert speaker_label(role="customer", sender_name="李老师") == "李老师"
    assert speaker_label(role="cs", account_name="本机客服") == "我"
    assert speaker_label(role="cs", account_name="小佳") == "小佳"
