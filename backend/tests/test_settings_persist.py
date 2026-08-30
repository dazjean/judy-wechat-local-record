from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.config import settings  # noqa: E402
from app.settings_persist import apply_setting_mapping, clamp_limit_per_contact, model_config_error  # noqa: E402


def test_apply_mapping_loads_api_key():
    old = (settings.model_api_key, settings.model_base_url, settings.model_name)
    try:
        settings.model_api_key = ""
        settings.model_base_url = ""
        settings.model_name = ""
        apply_setting_mapping(
            {
                "model_base_url": " https://api.example.com/v1 ",
                "model_name": " demo-model ",
                "model_api_key": " sk-test ",
            }
        )
        assert settings.model_base_url == "https://api.example.com/v1"
        assert settings.model_name == "demo-model"
        assert settings.model_api_key == "sk-test"
        assert model_config_error() == ""
    finally:
        settings.model_api_key, settings.model_base_url, settings.model_name = old


def test_model_config_error_missing_key():
    old = (settings.model_api_key, settings.model_base_url, settings.model_name)
    try:
        settings.model_base_url = "https://api.example.com/v1"
        settings.model_name = "demo"
        settings.model_api_key = ""
        assert "API Key" in model_config_error()
    finally:
        settings.model_api_key, settings.model_base_url, settings.model_name = old


def test_clamp_limit_per_contact():
    assert clamp_limit_per_contact(1000) == 1000
    assert clamp_limit_per_contact(10) == 50
    assert clamp_limit_per_contact(99999) == 5000
    assert clamp_limit_per_contact("3000") == 3000
    assert clamp_limit_per_contact("x") == 1000


def test_group_limit_inherits_person_limit_on_upgrade():
    old = (settings.sync_limit_per_contact, settings.sync_limit_per_group)
    try:
        settings.sync_limit_per_contact = 1000
        settings.sync_limit_per_group = 1000
        apply_setting_mapping({"sync_limit_per_contact": "3000"})
        assert settings.sync_limit_per_contact == 3000
        assert settings.sync_limit_per_group == 3000
    finally:
        settings.sync_limit_per_contact, settings.sync_limit_per_group = old
