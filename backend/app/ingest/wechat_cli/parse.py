from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime

from app.ingest.wechat_cli.normalize import normalize

TIMESTAMP_PATTERN = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}(?::\d{2})?)\]\s+([^:]+?):\s*(.*)$",
    re.DOTALL,
)
SELF_MARKERS = {"me", "我", "自己"}
EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F6FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "\U00002600-\U000026FF"
    "\U00002700-\U000027BF"
    "]+",
    flags=re.UNICODE,
)

PLACEHOLDER_TYPE = {
    "[图片]": "image",
    "[语音]": "voice",
    "[文件]": "file",
    "[视频]": "other",
    "[表情]": "other",
    "[链接]": "link",
    "[小程序]": "other",
    "[位置]": "other",
    "[名片]": "other",
    "[红包]": "other",
    "[消息]": "other",
}


@dataclass
class ParsedMessage:
    msg_time: datetime
    sender_role: str
    sender_name: str
    content: str
    msg_type: str
    raw_hash: str
    source_ref: str
    media_relpath: str = ""
    media_name: str = ""
    media_mime: str = ""
    media_status: str = ""


def strip_emoji(name: str) -> str:
    return EMOJI_RE.sub("", name or "").strip()


def infer_msg_type(content: str) -> str:
    text = (content or "").strip()
    for prefix, kind in PLACEHOLDER_TYPE.items():
        if text.startswith(prefix):
            return kind
    return "text"


def message_raw_hash(
    peer_key: str,
    msg_time: datetime,
    role: str,
    sender: str,
    content: str,
    account_key: str = "",
) -> str:
    payload = f"{peer_key}|{msg_time.isoformat()}|{role}|{sender}|{content}"
    if account_key:
        payload = f"{account_key}|{payload}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_history_lines(lines: list[str], peer_key: str, account_key: str = "") -> list[ParsedMessage]:
    parsed: list[ParsedMessage] = []
    for line in lines:
        if not isinstance(line, str):
            continue
        m = TIMESTAMP_PATTERN.match(line)
        if not m:
            continue
        day_iso = m.group(1)
        time_str = m.group(2)
        sender = m.group(3).strip()
        content = m.group(4).strip()
        if not content:
            continue
        if len(time_str) == 5:
            time_str = time_str + ":00"
        msg_time = datetime.strptime(f"{day_iso} {time_str}", "%Y-%m-%d %H:%M:%S")
        sl = sender.lower()
        if sl in SELF_MARKERS or sender in SELF_MARKERS:
            role = "cs"
            sender_display = "me"
        elif sender == "[系统]":
            role = "system"
            sender_display = sender
        else:
            role = "customer"
            sender_display = sender
        content = content.replace("\t", " ").replace("\n", " ")
        content = normalize(content)
        if not content:
            continue
        digest = message_raw_hash(
            peer_key, msg_time, role, sender_display, content, account_key=account_key
        )
        parsed.append(
            ParsedMessage(
                msg_time=msg_time,
                sender_role=role,
                sender_name=sender_display,
                content=content,
                msg_type=infer_msg_type(content),
                raw_hash=digest,
                source_ref=f"{peer_key}|{msg_time.isoformat()}",
            )
        )
    return parsed
