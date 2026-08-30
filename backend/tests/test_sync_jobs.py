from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.ingest.wechat_cli.runner import _fail_from_output  # noqa: E402
from app.ingest.wechat_cli.sync_job import sync_finish_outcome  # noqa: E402
from app.routers.api import _sync_job_item  # noqa: E402


def test_empty_scan_is_success_not_failure():
    status, err, line = sync_finish_outcome(
        ok=0, hard_error="", scanned=True, written=0, skipped=0
    )
    assert status == "succeeded"
    assert err == ""
    assert "没有新消息" in line
    assert "失败" not in line


def test_empty_scan_still_fails_on_hard_error():
    status, err, line = sync_finish_outcome(
        ok=0, hard_error="请先打开并登录微信，再点同步", scanned=True, written=0, skipped=0
    )
    assert status == "failed"
    assert "登录" in err
    assert line.startswith("同步结束：失败")


def test_no_sessions_still_fails():
    status, err, line = sync_finish_outcome(
        ok=0, hard_error="", scanned=False, written=0, skipped=0
    )
    assert status == "failed"
    assert "暂无可用会话" in err
    assert "没有可用会话" in line


def test_history_not_found_is_not_init_error():
    err = _fail_from_output("找不到聊天对象: 李慧", 1, command="history")
    assert err.code == "no_history"
    assert "初始化" not in err.public_message


def test_missing_keys_still_maps_to_not_inited():
    err = _fail_from_output("0 unique keys", 1)
    assert err.code == "reader_not_ready"



def test_sync_job_item_lists_core_fields():
    job = SimpleNamespace(
        id="job-1",
        status="succeeded",
        start_date="2026-08-15",
        total_contacts=20,
        ok_contacts=18,
        written=120,
        skipped=4,
        error_message="",
        created_at=datetime(2026, 8, 29, 21, 0, 0),
        updated_at=datetime(2026, 8, 29, 21, 5, 0),
    )
    item = _sync_job_item(job)
    assert item["id"] == "job-1"
    assert item["status"] == "succeeded"
    assert item["written"] == 120
    assert "2026" in item["created_at"]
    assert "log" not in item
