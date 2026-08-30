"""把系统设置从数据库灌回内存。API Key 只存本机库，不回显。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import settings
from app.models import AppSetting


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _clamp_minutes(value) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 15
    choices = (5, 15, 30, 60)
    if n in choices:
        return n
    return min(choices, key=lambda x: abs(x - n))


def clamp_limit_per_contact(value) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 1000
    return max(50, min(n, 5000))


def apply_setting_mapping(mapping: dict[str, str]) -> None:
    if "timeout_seconds" in mapping:
        try:
            settings.timeout_seconds = int(mapping["timeout_seconds"])
        except ValueError:
            pass
    if "session_gap_hours" in mapping:
        try:
            settings.session_gap_hours = int(mapping["session_gap_hours"])
        except ValueError:
            pass
    url = (mapping.get("model_base_url") or "").strip()
    if url:
        settings.model_base_url = url
    name = (mapping.get("model_name") or "").strip()
    if name:
        settings.model_name = name
    key = (mapping.get("model_api_key") or "").strip()
    if key:
        settings.model_api_key = key
    if "sync_include_groups" in mapping:
        settings.sync_include_groups = _truthy(mapping["sync_include_groups"])
    if "sync_exclude_names" in mapping:
        settings.sync_exclude_names = mapping["sync_exclude_names"]
    if "sync_include_names" in mapping:
        settings.sync_include_names = mapping["sync_include_names"]
    if "sync_limit_people_enabled" in mapping:
        settings.sync_limit_people_enabled = _truthy(mapping["sync_limit_people_enabled"])
    if "sync_limit_people" in mapping:
        try:
            settings.sync_limit_people = max(1, min(int(mapping["sync_limit_people"]), 300))
        except ValueError:
            settings.sync_limit_people = 20
    if "sync_limit_per_contact" in mapping:
        settings.sync_limit_per_contact = clamp_limit_per_contact(mapping["sync_limit_per_contact"])
        if "sync_limit_per_group" not in mapping:
            settings.sync_limit_per_group = settings.sync_limit_per_contact
    if "sync_limit_per_group" in mapping:
        settings.sync_limit_per_group = clamp_limit_per_contact(mapping["sync_limit_per_group"])
    if "sync_limit_covered" in mapping:
        try:
            settings.sync_limit_covered = max(0, min(int(mapping["sync_limit_covered"]), 5000))
        except ValueError:
            settings.sync_limit_covered = 1000
        if "sync_limit_group_covered" not in mapping:
            settings.sync_limit_group_covered = settings.sync_limit_covered
    if "sync_limit_group_covered" in mapping:
        try:
            settings.sync_limit_group_covered = max(0, min(int(mapping["sync_limit_group_covered"]), 5000))
        except ValueError:
            settings.sync_limit_group_covered = 1000
    if "sync_days" in mapping:
        try:
            settings.sync_days = max(1, min(int(mapping["sync_days"]), 90))
        except ValueError:
            settings.sync_days = 14
    if "sync_auto_enabled" in mapping:
        settings.sync_auto_enabled = _truthy(mapping["sync_auto_enabled"])
    if "sync_auto_minutes" in mapping:
        settings.sync_auto_minutes = _clamp_minutes(mapping["sync_auto_minutes"])
    if "sync_watch_enabled" in mapping:
        settings.sync_watch_enabled = _truthy(mapping["sync_watch_enabled"])
    covered = (mapping.get("sync_covered_from") or "").strip()
    if covered:
        settings.sync_covered_from = covered


def apply_persisted_settings(db: Session) -> None:
    mapping = {row.key: row.value for row in db.query(AppSetting).all()}
    apply_setting_mapping(mapping)


def mark_sync_coverage(db: Session, window_start: str) -> None:
    """记下已经拉过的最早日期；把天数调大时才再往前补。"""
    window_start = (window_start or "").strip()
    if not window_start:
        return
    current = (settings.sync_covered_from or "").strip()
    if current and current <= window_start:
        return
    settings.sync_covered_from = window_start
    row = db.get(AppSetting, "sync_covered_from")
    if row:
        row.value = window_start
    else:
        db.add(AppSetting(key="sync_covered_from", value=window_start))


def mark_sync_limit_coverage(db: Session, limit: int, *, group: bool = False) -> None:
    """记下已经用过的每人条数上限；把上限调大时才再往前补。"""
    try:
        limit = clamp_limit_per_contact(limit)
    except (TypeError, ValueError):
        return
    attr = "sync_limit_group_covered" if group else "sync_limit_covered"
    key = attr
    current = 0
    try:
        current = int(getattr(settings, attr) or 0)
    except (TypeError, ValueError):
        current = 0
    if current >= limit:
        return
    setattr(settings, attr, limit)
    row = db.get(AppSetting, key)
    if row:
        row.value = str(limit)
    else:
        db.add(AppSetting(key=key, value=str(limit)))


def model_config_error() -> str:
    if not (settings.model_base_url or "").strip():
        return "请先在系统设置中填写模型地址"
    if not (settings.model_name or "").strip():
        return "请先在系统设置中填写模型名"
    if not (settings.model_api_key or "").strip():
        return "请先在系统设置中填写模型 API Key 并保存"
    return ""
