from __future__ import annotations

import re
from html import unescape

RE_REDPACKET_LINK = re.compile(
    r"<_wc_custom_link_[^>]*>(?P<label>[^<]{0,40})</_wc_custom_link_>",
    re.IGNORECASE,
)
RE_SYSMSG_IMG = re.compile(
    r'<img\s+src="SystemMessages_[^"]+"\s*/?>\s*',
    re.IGNORECASE,
)
RE_REPLY_MARKER = re.compile(
    r"(?P<lead>.*?)(?P<sep>\s*↳\s*回复(?:\s+[^:：]+)?[:：]\s*)(?P<body>.+)$",
    re.DOTALL,
)
RE_TITLE = re.compile(r"<title[^>]*>(?P<text>.*?)</title>", re.IGNORECASE | re.DOTALL)
RE_DES = re.compile(r"<des[^>]*>(?P<text>.*?)</des>", re.IGNORECASE | re.DOTALL)
RE_URL = re.compile(r"<url[^>]*>(?P<text>.*?)</url>", re.IGNORECASE | re.DOTALL)
RE_XML_DECL = re.compile(r"<\?xml[^>]*\?>", re.IGNORECASE)
RE_VOICE_XML = re.compile(r"^\s*\[语音\]\s*<msg[\s\S]*?</msg>\s*$")
RE_MSG_XML = re.compile(r"<msg[\s>][\s\S]*?</msg>", re.IGNORECASE)
RE_APPMSG_XML = re.compile(r"<appmsg[\s>][\s\S]*?</appmsg>", re.IGNORECASE)
RE_WC_TAG_ANY = re.compile(r"</?_wc_[a-z_]+[^>]*>", re.IGNORECASE)
RE_WX_PRIVATE_TAG = re.compile(
    r"</?(?:msg|appmsg|appinfo|appattach|finder[a-z]*|voicemsg|referitem|refermsg|"
    r"weappinfo|shareUrlOpen|shareUrlOriginal|pagepath|showtype|soundtype|mediatagname|"
    r"cdn_[a-z_]+|md5|thumburl|thumbcrc|content_type|username|nickname|"
    r"payment[a-z]*|hongbao[a-z_]*|type|action|extinfo|category|item|title|des|url|"
    r"content|hint|footer)\b[^>]*/?>",
    re.IGNORECASE,
)


def _clean_xml_text(text: str) -> str:
    text = unescape(text or "").strip()
    text = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", text, flags=re.S).strip()
    return unescape(text).strip()


def _first_group(pattern, s):
    m = pattern.search(s)
    if not m:
        return None
    text = _clean_xml_text(m.group("text"))
    return text or None


def _link_card(title: str | None, url: str | None, des: str | None) -> str:
    lines = [f"[链接] {title}" if title else "[链接]"]
    if url:
        lines.append(url)
    if des and des != title:
        lines.append(des)
    return "\n".join(lines)


def _classify_bare_xml(xml):
    x = xml.lower()
    if "<appmsg" in x:
        title = _first_group(RE_TITLE, xml)
        des = _first_group(RE_DES, xml)
        url = _first_group(RE_URL, xml)
        if "<weappinfo" in x or "<pagepath" in x:
            return f"[小程序] {title}" if title else "[小程序]"
        if "<findernamecard" in x or "<finderlive" in x:
            return "[视频号]"
        if "<appattach" in x and ("fileext" in x or "totallen" in x):
            return "[文件]"
        http_url = url if url and url.lower().startswith(("http://", "https://")) else None
        if not http_url:
            found = re.search(r"https?://[^\s<>\"']+", xml, re.IGNORECASE)
            if found:
                http_url = found.group(0)
        return _link_card(title, http_url, des)
    if "<findernamecard" in x or "<finderlive" in x:
        return "[视频号]"
    if "<streamvideo" in x or "<streamweishi" in x:
        return "[视频]"
    if "<voicemsg" in x:
        return "[语音]"
    if "<img aeskey" in x or "<img md5=" in x or "cdnthumbaeskey" in x:
        return "[图片]"
    if "<emoji" in x or 'emoji="' in x or "emojiinfo" in x:
        return "[表情]"
    if "<weappinfo" in x or "<pagepath" in x:
        return "[小程序]"
    if "<location" in x:
        return "[位置]"
    if "<contactinfo" in x or "<personinfo" in x:
        return "[名片]"
    if "<appattach" in x and ("fileext" in x or "totallen" in x):
        return "[文件]"
    return "[消息]"


def _normalize_redpacket(text):
    if "SystemMessages_HongbaoIcon" not in text and "weixinhongbao" not in text:
        return text
    s = RE_SYSMSG_IMG.sub("", text)
    s = RE_REDPACKET_LINK.sub(lambda m: m.group("label") or "红包", s)
    s = RE_WC_TAG_ANY.sub("", s)
    s = re.sub(r"^\s*\[系统\]\s*", "[红包] ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s.startswith("[红包]"):
        s = "[红包] " + s
    return s


def _normalize_voice(text):
    if RE_VOICE_XML.match(text):
        return "[语音]"
    return re.sub(r"<msg[\s\S]*?</msg>", "", text).strip()


def _normalize_reply(text):
    m = RE_REPLY_MARKER.match(text)
    if not m:
        return text
    lead = m.group("lead")
    sep = m.group("sep")
    body = m.group("body").strip()
    body = RE_XML_DECL.sub("", body).strip()
    body_low = body.lower()
    if body.startswith("<") and ("<msg" in body_low or "<appmsg" in body_low):
        summary = _classify_bare_xml(body)
    else:
        summary = body
    return "{}{}{}".format(lead, sep, summary)


def normalize(content: str) -> str:
    if not content or not isinstance(content, str):
        return content or ""
    if "<" not in content and "&lt;" not in content and "SystemMessages" not in content:
        return content
    s = content
    if "&lt;" in s and "&gt;" in s:
        s = unescape(s)
    if "SystemMessages_HongbaoIcon" in s or "weixinhongbao" in s:
        s = _normalize_redpacket(s)
    if s.lstrip().startswith("[语音]"):
        s = _normalize_voice(s)
    if "↳ 回复" in s:
        s = _normalize_reply(s)
    if "<msg" in s.lower() or "<appmsg" in s.lower():
        s = RE_MSG_XML.sub(lambda m: _classify_bare_xml(m.group(0)), s)
        s = RE_APPMSG_XML.sub(lambda m: _classify_bare_xml(m.group(0)), s)
    s = RE_WC_TAG_ANY.sub("", s)
    s = RE_WX_PRIVATE_TAG.sub("", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.strip()
