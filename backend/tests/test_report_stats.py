from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.analyze.jobs import _parse_model_json  # noqa: E402
from app.engine.report_stats import compact_duration, median, stats_for_prompt  # noqa: E402


def test_median():
    assert median([]) is None
    assert median([20]) == 20
    assert median([10, 20, 30]) == 20
    assert median([10, 20, 30, 40]) == 25


def test_compact_duration():
    assert compact_duration(None) == "—"
    assert compact_duration(20) == "20秒"
    assert compact_duration(330) == "5.5分钟"


def test_stats_for_prompt_mentions_median():
    text = stats_for_prompt({"median_label": "20秒", "avg_label": "12.7分钟", "within_5min_pct": 88.7})
    assert "20秒" in text
    assert "88.7%" in text


def test_parse_model_json_fence():
    parsed = _parse_model_json('```json\n{"headline":"ok"}\n```')
    assert parsed["headline"] == "ok"
