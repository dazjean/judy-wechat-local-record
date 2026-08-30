from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.ingest.media.self_account import (  # noqa: E402
    SelfProfile,
    apply_self_profile,
    infer_self_username,
    profile_from_contact_row,
    username_from_folder,
)
from app.models import Account  # noqa: E402


def test_infer_unique_wxid_not_in_contacts():
    name2id = {"wxid_selfabc123", "wxid_friend", "filehelper", "123@chatroom"}
    contacts = {"wxid_friend", "filehelper", "123@chatroom"}
    assert infer_self_username(name2id, contacts) == "wxid_selfabc123"


def test_infer_empty_when_multiple_wxids_not_in_contacts():
    name2id = {"wxid_a", "wxid_b"}
    contacts = {"wxid_c"}
    assert infer_self_username(name2id, contacts) == ""


def test_infer_empty_when_all_wxids_are_contacts():
    name2id = {"wxid_a", "wxid_b"}
    contacts = {"wxid_a", "wxid_b"}
    assert infer_self_username(name2id, contacts) == ""


def test_folder_wxid_strips_device_suffix():
    assert username_from_folder("wxid_cuq10j0fdu6m29_00de") == "wxid_cuq10j0fdu6m29"
    assert username_from_folder("nxss11_c6ad") == ""
    assert username_from_folder("wxid_plain") == "wxid_plain"


def test_folder_wxid_uses_alias_dir_as_identifier():
    from app.ingest.media.self_account import folder_wxid

    assert folder_wxid("nxss11_c6ad") == "nxss11_c6ad"
    assert folder_wxid("wxid_cuq10j0fdu6m29_00de") == "wxid_cuq10j0fdu6m29"
    assert folder_wxid("all_users") == ""


def test_resolve_uses_folder_name_only(monkeypatch, tmp_path: Path):
    from app.ingest.media.self_account import resolve_self_wxid
    import app.ingest.media.self_account as mod

    folder = tmp_path / "nxss11_c6ad"
    folder.mkdir()
    monkeypatch.setattr(mod, "newest_account_dir", lambda: folder)
    monkeypatch.setattr(mod, "wechat_account_root", lambda: folder)
    assert resolve_self_wxid() == "nxss11_c6ad"


def test_display_account_uses_wxid_only():
    profile = profile_from_contact_row("wxid_selfabc123", alias="my-wechat", nickname="小佳")
    assert profile.display_account() == "wxid_selfabc123"
    assert profile_from_contact_row("wxid_selfabc123").display_account() == "wxid_selfabc123"


def test_apply_fills_placeholder_nickname_only():
    acc = Account(account_key="local", display_name="本机客服", wx_username="")
    apply_self_profile(acc, SelfProfile(username="wxid_selfabc123", nickname="小佳"))
    assert acc.wx_username == "wxid_selfabc123"
    assert acc.display_name == "小佳"
    apply_self_profile(acc, SelfProfile(username="wxid_selfabc123", nickname="别的名字"))
    assert acc.display_name == "小佳"


def test_profile_from_sqlite_contact_row(tmp_path: Path):
    db = tmp_path / "contact.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE contact (username TEXT, alias TEXT, nick_name TEXT)")
    con.execute(
        "INSERT INTO contact VALUES (?,?,?)",
        ("wxid_selfabc123", "my-wechat", "小佳"),
    )
    con.commit()
    con.close()
    from app.ingest.media import self_account as mod

    alias, nick = mod._lookup_contact(db, "wxid_selfabc123")
    assert alias == "my-wechat"
    assert nick == "小佳"
    assert mod._lookup_contact(db, "missing") == ("", "")
