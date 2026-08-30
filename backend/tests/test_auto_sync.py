from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.config import settings  # noqa: E402
from app.ingest.auto_sync import (  # noqa: E402
    clamp_minutes,
    interval_due,
    library_fingerprint,
    step_watch,
    watch_settled,
)
from app.settings_persist import apply_setting_mapping  # noqa: E402


def test_clamp_minutes_snaps_to_allowed():
    assert clamp_minutes(15) == 15
    assert clamp_minutes(7) == 5
    assert clamp_minutes(40) == 30
    assert clamp_minutes("bad") == 15


def test_interval_waits_for_first_success():
    now = datetime(2026, 8, 29, 12, 0, 0)
    assert interval_due(now, None, 15, True) is False
    assert interval_due(now, now - timedelta(minutes=14), 15, True) is False
    assert interval_due(now, now - timedelta(minutes=15), 15, True) is True
    assert interval_due(now, now - timedelta(minutes=60), 15, False) is False


def test_watch_needs_quiet_then_fires_once():
    now = datetime(2026, 8, 29, 12, 0, 0)
    fp1 = (("session.db", 1, 10),)
    fp2 = (("session.db", 2, 10),)
    hit, kept, dirty = step_watch(None, fp1, None, now, None, True)
    assert hit is False and kept == fp1 and dirty is None
    hit, kept, dirty = step_watch(fp1, fp2, None, now, None, True, quiet_seconds=45)
    assert hit is False and kept == fp2 and dirty == now
    later = now + timedelta(seconds=20)
    hit, kept, dirty = step_watch(fp2, fp2, now, later, None, True, quiet_seconds=45)
    assert hit is False
    settled = now + timedelta(seconds=45)
    hit, kept, dirty = step_watch(fp2, fp2, now, settled, None, True, quiet_seconds=45)
    assert hit is True and dirty is None


def test_watch_respects_min_gap_after_success():
    now = datetime(2026, 8, 29, 12, 0, 0)
    fp = (("session.db", 1, 10),)
    last = now - timedelta(seconds=30)
    dirty = now - timedelta(seconds=50)
    hit, _, kept_dirty = step_watch(fp, fp, dirty, now, last, True, quiet_seconds=45, min_gap_seconds=120)
    assert hit is False
    assert kept_dirty == dirty


def test_watch_settled():
    now = datetime(2026, 8, 29, 12, 0, 0)
    assert watch_settled(None, now) is False
    assert watch_settled(now - timedelta(seconds=10), now, 45) is False
    assert watch_settled(now - timedelta(seconds=45), now, 45) is True


def test_fingerprint_changes_with_file(monkeypatch, tmp_path):
    (tmp_path / "session").mkdir()
    (tmp_path / "message").mkdir()
    db = tmp_path / "session" / "session.db"
    db.write_bytes(b"a")
    monkeypatch.setattr("app.ingest.auto_sync.db_storage_dir", lambda: tmp_path)
    first = library_fingerprint()
    db.write_bytes(b"ab")
    second = library_fingerprint()
    assert first != second
    assert first[0][0] == "session.db"


def test_apply_mapping_loads_auto_sync():
    old = (
        settings.sync_days,
        settings.sync_auto_enabled,
        settings.sync_auto_minutes,
        settings.sync_watch_enabled,
        settings.sync_include_names,
        settings.sync_limit_per_contact,
        settings.sync_limit_per_group,
    )
    try:
        apply_setting_mapping(
            {
                "sync_days": "7",
                "sync_auto_enabled": "1",
                "sync_auto_minutes": "30",
                "sync_watch_enabled": "true",
                "sync_include_names": "张家长\n班级群",
                "sync_limit_per_contact": "1000",
                "sync_limit_per_group": "3000",
            }
        )
        assert settings.sync_days == 7
        assert settings.sync_auto_enabled is True
        assert settings.sync_auto_minutes == 30
        assert settings.sync_watch_enabled is True
        assert settings.sync_include_names == "张家长\n班级群"
        assert settings.sync_limit_per_contact == 1000
        assert settings.sync_limit_per_group == 3000
    finally:
        (
            settings.sync_days,
            settings.sync_auto_enabled,
            settings.sync_auto_minutes,
            settings.sync_watch_enabled,
            settings.sync_include_names,
            settings.sync_limit_per_contact,
            settings.sync_limit_per_group,
        ) = old
