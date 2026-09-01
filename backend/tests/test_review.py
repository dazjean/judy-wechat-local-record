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


def test_list_review_page_only_loads_current_page(monkeypatch):
    from datetime import datetime, timedelta

    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker

    from app.db import Base
    from app.engine.review import list_review_page
    from app.models import Account, Contact, Conversation, Message

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    account = Account(account_key="wxid_cs", display_name="客服")
    db.add(account)
    db.flush()
    start = datetime(2026, 8, 1, 10, 0, 0)
    for i in range(30):
        contact = Contact(account_id=account.id, peer_key=f"wxid_{i}", nickname=f"家长{i}", remark=f"家长{i}")
        db.add(contact)
        db.flush()
        conv = Conversation(
            account_id=account.id,
            contact_id=contact.id,
            started_at=start + timedelta(minutes=i),
            last_msg_at=start + timedelta(minutes=i),
            msg_count=80,
        )
        db.add(conv)
        db.flush()
        for n in range(80):
            db.add(
                Message(
                    conversation_id=conv.id,
                    account_id=account.id,
                    contact_id=contact.id,
                    msg_time=start + timedelta(minutes=i, seconds=n),
                    sender_role="customer" if n % 2 == 0 else "cs",
                    sender_name="家长" if n % 2 == 0 else "me",
                    content="课时" if n % 2 == 0 else "好的",
                    raw_hash=f"h-{i}-{n}",
                )
            )
    db.commit()
    queries = {"n": 0}

    def _count(conn, cursor, statement, parameters, context, executemany):
        queries["n"] += 1

    event.listen(engine, "before_cursor_execute", _count)
    items, total = list_review_page(db, account_id=account.id, page=1, page_size=10)
    event.remove(engine, "before_cursor_execute", _count)
    assert total == 30
    assert len(items) == 10
    assert queries["n"] < 12
    assert items[0]["contact"] == "家长29"


def test_list_review_page_skips_system_contacts():
    from datetime import datetime

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db import Base
    from app.engine.review import list_review_page
    from app.models import Account, Contact, Conversation, Message

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    account = Account(account_key="wxid_cs", display_name="客服")
    db.add(account)
    db.flush()
    now = datetime(2026, 8, 1, 12, 0, 0)
    parent = Contact(account_id=account.id, peer_key="wxid_p", nickname="张家长", remark="张家长")
    helper = Contact(account_id=account.id, peer_key="filehelper", nickname="文件传输助手", remark="")
    db.add_all([parent, helper])
    db.flush()
    for contact in (parent, helper):
        conv = Conversation(
            account_id=account.id,
            contact_id=contact.id,
            started_at=now,
            last_msg_at=now,
            msg_count=1,
        )
        db.add(conv)
        db.flush()
        db.add(
            Message(
                conversation_id=conv.id,
                account_id=account.id,
                contact_id=contact.id,
                msg_time=now,
                sender_role="customer",
                content="hi",
                raw_hash=f"h-{contact.id}",
            )
        )
    db.commit()
    items, total = list_review_page(db, account_id=account.id, page=1, page_size=20)
    assert total == 1
    assert items[0]["contact"] == "张家长"
