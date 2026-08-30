"""聊天展示名：用微信昵称，不用「客户 / 客服」。"""

from __future__ import annotations

SELF_MARKERS = {"me", "我", "自己"}
PLACEHOLDER_SELF = {"", "本机客服", "本机微信", "me", "我"}


def peer_display(sender_name: str, nickname: str, remark: str) -> str:
    name = (sender_name or "").strip()
    if name and name.lower() not in SELF_MARKERS and name != "[系统]":
        return name
    return ((nickname or "").strip() or (remark or "").strip() or "对方")


def self_display(account_name: str) -> str:
    name = (account_name or "").strip()
    if name and name not in PLACEHOLDER_SELF and name.lower() not in SELF_MARKERS:
        return name
    return "我"


def speaker_label(
    *,
    role: str,
    sender_name: str = "",
    nickname: str = "",
    remark: str = "",
    account_name: str = "",
) -> str:
    if role == "system":
        return "系统"
    if role == "customer":
        return peer_display(sender_name, nickname, remark)
    return self_display(account_name)
