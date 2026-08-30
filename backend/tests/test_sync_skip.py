from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.ingest.wechat_cli.sync_job import (  # noqa: E402
    _is_group,
    _session_identity,
    _should_query_contacts,
    _should_skip,
    apply_people_limit,
    expand_include_from_contacts,
    history_start_for_contact,
    hits_exclude,
    hits_include,
    is_limit_raised,
    is_window_widened,
    history_limit_for_peer,
    looks_like_official_feed,
    parse_exclude_names,
    parse_name_list,
    select_sync_targets,
    unmatched_include_names,
)


def test_skip_system_sessions():
    assert _should_skip("brandsessionholder", "brandsessionholder")
    assert _should_skip("filehelper", "文件传输助手")
    assert _should_skip("gh_abc", "某公众号")
    assert _should_skip("notifymessage", "服务通知")
    assert _should_skip("qqsafe", "QQ安全中心")
    assert not _should_skip("wxid_customer", "张家长")
    assert not _should_skip("43981388909@chatroom", "班级群")
    assert _should_skip("brandsessionholder", "公众号")


def test_skip_official_by_last_message_type():
    item = {"is_group": False, "msg_type": "链接/文件", "sender": ""}
    assert _should_skip("cmb4008205555", "招商银行信用卡", item)
    assert _should_skip("Jack_Jones_China", "杰克琼斯", item)
    assert not _should_skip("wxid_meituan", "美团", item)
    assert not _should_skip("gs295422248", "高升", {"is_group": False, "msg_type": "文本", "sender": ""})
    assert not _should_skip(
        "mmo9cq801nXK__9UjXeUarG_tv6uGY@weclaw",
        "小龙虾",
        item,
    )


def test_official_feed_hides_broadcasts():
    class M:
        def __init__(self, role, kind, content=""):
            self.sender_role = role
            self.msg_type = kind
            self.content = content

    oa = [M("customer", "other", "[链接] 通知") for _ in range(5)]
    assert looks_like_official_feed(oa) is True
    mixed = [M("customer", "text", "课时怎么退"), M("cs", "text", "您好")]
    assert looks_like_official_feed(mixed) is False
    unanswered = [M("customer", "text", "在吗"), M("customer", "text", "帮看一下")]
    assert looks_like_official_feed(unanswered) is False


def test_group_detection():
    assert _is_group({"is_group": True, "username": "wxid_x"}, "wxid_x")
    assert _is_group({"is_group": False}, "123@chatroom")
    assert not _is_group({"is_group": False, "username": "wxid_x"}, "wxid_x")


def test_exclude_list_matches_remark_or_nick():
    names = parse_exclude_names("妈妈\n\n张三\n")
    assert names == ["妈妈", "张三"]
    assert hits_exclude("wxid_abc", "妈妈", names)
    assert hits_exclude("wxid_abc", "张三", names)
    assert not hits_exclude("wxid_abc", "李家长", names)


def test_people_limit_keeps_first_n():
    rows = [(f"u{i}", f"人{i}") for i in range(30)]
    kept, dropped = apply_people_limit(rows, 20, True)
    assert len(kept) == 20
    assert dropped == 10
    assert kept[0][0] == "u0"
    all_kept, none_dropped = apply_people_limit(rows, 20, False)
    assert len(all_kept) == 30
    assert none_dropped == 0


def test_query_contacts_only_for_human_names():
    assert _should_query_contacts("张家长")
    assert not _should_query_contacts("brandsessionholder")
    assert not _should_query_contacts("43981388909@chatroom")
    assert not _should_query_contacts("wxid_abc")


def test_session_identity_prefers_chat_or_remark():
    key, display = _session_identity(
        {"username": "wxid_abc", "chat": "张家长", "remark": ""}
    )
    assert key == "wxid_abc"
    assert display == "张家长"
    key, display = _session_identity({"username": "123@chatroom", "chat": "班级群"})
    assert key == "123@chatroom"
    assert display == "班级群"
    key, display = _session_identity({"username": "wxid_only"})
    assert key == display == "wxid_only"


def test_history_start_incremental_from_last_success_day():
    window = "2026-08-15"
    last = datetime(2026, 8, 29, 22, 10, 0)
    assert history_start_for_contact(window, None, False) == window
    assert history_start_for_contact(window, last, False) == "2026-08-29 22:08:00"
    assert history_start_for_contact(window, last, True) == window


def test_history_start_does_not_go_before_window():
    window = "2026-08-20"
    last = datetime(2026, 8, 10, 8, 0, 0)
    assert history_start_for_contact(window, last, False) == window


def test_window_widened_when_days_increase():
    assert is_window_widened("2026-07-30", "2026-08-15") is True
    assert is_window_widened("2026-08-15", "2026-08-15") is False
    assert is_window_widened("2026-08-20", "2026-08-15") is False
    assert is_window_widened("2026-08-15", "") is False


def test_limit_raised_only_when_higher_than_covered():
    assert is_limit_raised(1000, 1000) is False
    assert is_limit_raised(3000, 1000) is True
    assert is_limit_raised(50, 0) is True
    assert is_limit_raised(5000, 3000) is True
    assert is_limit_raised(800, 1000) is False


def test_history_limit_splits_person_and_group():
    assert history_limit_for_peer("wxid_abc", 1000, 3000) == 1000
    assert history_limit_for_peer("123@chatroom", 1000, 3000) == 3000
    assert history_limit_for_peer("123@CHATROOM", 800, 2000) == 2000


def _sess(username: str, chat: str, *, group: bool = False, **extra) -> dict:
    item = {"username": username, "chat": chat, "is_group": group}
    item.update(extra)
    return item


def test_include_list_loose_match():
    names = parse_name_list("顺其自然\n班级群")
    assert names == ["顺其自然", "班级群"]
    assert hits_include("wxid_a", "顺其自然 为所当为", names)
    assert hits_include("123@chatroom", "三年二班班级群", names)
    assert not hits_include("wxid_b", "李家长", names)
    assert hits_include("wxid_a", "顺其自然", names)


def test_include_does_not_substring_single_char():
    assert not hits_include("wxid_a", "张家长", ["张"])
    assert hits_include("wxid_a", "张家长", ["张家长"])


def test_select_sync_targets_only_include_and_skips_limit():
    sessions = [
        _sess("wxid_a", "张家长"),
        _sess("wxid_b", "李家长"),
        _sess("wxid_c", "顺其自然 为所当为"),
        *[_sess(f"wxid_{i}", f"人{i}") for i in range(30)],
    ]
    usable, stats = select_sync_targets(
        sessions,
        include_groups=False,
        exclude=[],
        include=["顺其自然", "张家长"],
        limit_people_enabled=True,
        limit_people=1,
    )
    displays = [d for _, d in usable]
    assert displays == ["张家长", "顺其自然 为所当为"]
    assert stats["dropped_limit"] == 0


def test_select_sync_targets_whitelist_group_without_include_groups():
    sessions = [
        _sess("wxid_a", "张家长"),
        _sess("123@chatroom", "班级群A", group=True),
        _sess("456@chatroom", "无关群", group=True),
    ]
    usable, stats = select_sync_targets(
        sessions,
        include_groups=False,
        exclude=[],
        include=["班级群A"],
        limit_people_enabled=True,
        limit_people=20,
    )
    assert usable == [("123@chatroom", "班级群A")]
    assert stats["skipped_group"] == 0


def test_select_sync_targets_exclude_wins_over_include():
    sessions = [
        _sess("wxid_a", "张家长"),
        _sess("wxid_b", "李家长"),
    ]
    usable, stats = select_sync_targets(
        sessions,
        include_groups=False,
        exclude=["张家长"],
        include=["张家长", "李家长"],
        limit_people_enabled=False,
        limit_people=20,
    )
    assert usable == [("wxid_b", "李家长")]
    assert stats["skipped_exclude"] == ["张家长"]


def test_select_sync_targets_empty_include_keeps_recent_limit():
    sessions = [_sess(f"wxid_{i}", f"人{i}") for i in range(8)]
    sessions.append(_sess("9@chatroom", "班级群", group=True))
    usable, stats = select_sync_targets(
        sessions,
        include_groups=False,
        exclude=[],
        include=[],
        limit_people_enabled=True,
        limit_people=5,
    )
    assert len(usable) == 5
    assert stats["skipped_group"] == 1
    assert stats["dropped_limit"] == 3


def test_expand_include_from_contacts_and_unmatched_log():
    usable = [("wxid_a", "张家长")]
    logs: list[str] = []

    def contacts_for(name: str):
        if name == "蓝天白云":
            return [{"username": "wxid_blue", "nickname": "蓝天白云"}]
        return []

    out = expand_include_from_contacts(
        usable,
        ["张家长", "蓝天白云", "不存在的人"],
        [],
        contacts_for,
        logs.append,
    )
    assert ("wxid_blue", "蓝天白云") in out
    assert unmatched_include_names(out, ["张家长", "蓝天白云"]) == []
    assert any("不存在的人" in line for line in logs)
    assert parse_exclude_names is parse_name_list

