from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.engine.review import export_filename, format_seconds, is_review_noise  # noqa: E402
from app.models import Contact  # noqa: E402


def test_format_seconds():
    assert format_seconds(None) == "—"
    assert format_seconds(9) == "9 秒"
    assert format_seconds(80) == "1 分 20 秒"
    assert format_seconds(120) == "2 分"


def test_format_clock():
    from datetime import datetime
    from app.engine.review import format_clock

    assert format_clock(None) == "—"
    assert format_clock(datetime(2026, 8, 29, 16, 28, 5)) == "2026年08月29日 16.28.05"
    assert format_clock("2026-08-29T01:07:46.230763") == "2026年08月29日 01.07.46"
    assert format_clock("20260829") == "2026年08月29日 00.00.00"


def test_review_noise_skips_official_labels():
    gh = Contact(account_id=1, peer_key="gh_abc", nickname="某服务号", remark="")
    assert is_review_noise(gh) is True
    safe = Contact(account_id=1, peer_key="wxid_1", nickname="QQ安全中心", remark="")
    assert is_review_noise(safe) is True
    parent = Contact(account_id=1, peer_key="wxid_2", nickname="张家长", remark="庆总")
    assert is_review_noise(parent) is False
    notice = Contact(account_id=1, peer_key="notifymessage", nickname="服务通知", remark="服务通知")
    assert is_review_noise(notice) is True


def test_export_filename_all_ignores_filters():
    from datetime import datetime

    name = export_filename(
        scope="all",
        start_date="2026-08-15",
        end_date="2026-08-29",
        q="庆总",
        flag="timeout",
        now=datetime(2026, 8, 29, 10, 42, 0),
    )
    assert name == "会话明细_全部_20260829_104200.xlsx"


def test_export_filename_filtered_includes_conditions():
    from datetime import datetime

    name = export_filename(
        scope="filtered",
        start_date="2026-08-15",
        end_date="2026-08-29",
        q="庆总/测试",
        flag="timeout",
        now=datetime(2026, 8, 29, 10, 42, 0),
    )
    assert name == "会话明细_筛选_2026-08-15至2026-08-29_客户庆总_测试_超时未回_20260829_104200.xlsx"


def test_export_filename_filtered_empty():
    from datetime import datetime

    name = export_filename(scope="filtered", now=datetime(2026, 8, 29, 10, 42, 0))
    assert name == "会话明细_筛选_当前列表_20260829_104200.xlsx"
