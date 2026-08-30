from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.analyze.prompt import SYSTEM_PROMPT  # noqa: E402
from app.analyze.prompt_generate import generate_prompt_body  # noqa: E402
from app.analyze.prompt_store import resolve_prompt_body  # noqa: E402
from app.config import settings  # noqa: E402


def test_resolve_keeps_full_report_prompt():
    assert "只返回 JSON" in resolve_prompt_body(SYSTEM_PROMPT)
    assert resolve_prompt_body(SYSTEM_PROMPT).count("只返回 JSON") == 1


def test_resolve_appends_contract_for_short_scene():
    out = resolve_prompt_body("列出今天要跟的人")
    assert "列出今天要跟的人" in out
    assert "只返回 JSON" in out


def test_generate_requires_model_config():
    old = (settings.model_api_key, settings.model_base_url, settings.model_name)
    try:
        settings.model_base_url = ""
        settings.model_name = "demo"
        settings.model_api_key = "sk-test"
        try:
            generate_prompt_body("帮我看销售跟进里谁在犹豫")
            raise AssertionError("should fail")
        except ValueError as exc:
            assert "模型地址" in str(exc)
        settings.model_base_url = "https://api.example.com/v1"
        settings.model_api_key = ""
        try:
            generate_prompt_body("帮我看销售跟进里谁在犹豫")
            raise AssertionError("should fail")
        except ValueError as exc:
            assert "API Key" in str(exc)
            assert "sk-" not in str(exc)
    finally:
        settings.model_api_key, settings.model_base_url, settings.model_name = old


def test_generate_requires_brief():
    old = (settings.model_api_key, settings.model_base_url, settings.model_name)
    try:
        settings.model_base_url = "https://api.example.com/v1"
        settings.model_name = "demo"
        settings.model_api_key = "sk-test"
        try:
            generate_prompt_body("  ")
            raise AssertionError("should fail")
        except ValueError as exc:
            assert "大白话" in str(exc)
    finally:
        settings.model_api_key, settings.model_base_url, settings.model_name = old


def test_generate_fills_body_from_model():
    old = (settings.model_api_key, settings.model_base_url, settings.model_name)
    fake_resp = MagicMock()
    fake_resp.json.return_value = {
        "choices": [{"message": {"content": "```\n你是销售跟进顾问。\n```"}}]
    }
    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = False
    fake_client.post.return_value = fake_resp
    try:
        settings.model_base_url = "https://api.example.com/v1"
        settings.model_name = "demo"
        settings.model_api_key = "sk-secret-key"
        with patch("app.analyze.prompt_generate.httpx.Client", return_value=fake_client):
            body = generate_prompt_body("帮我看销售跟进里谁在犹豫")
        assert "销售跟进顾问" in body
        assert "只返回 JSON" in body
        sent = fake_client.post.call_args
        assert "sk-secret-key" not in json_safe(sent.kwargs.get("json"))
        assert "Authorization" in sent.kwargs["headers"]
    finally:
        settings.model_api_key, settings.model_base_url, settings.model_name = old


def json_safe(payload) -> str:
    return str(payload or "")



def test_resolve_keeps_full_report_prompt():
    assert "只返回 JSON" in resolve_prompt_body(SYSTEM_PROMPT)
    assert resolve_prompt_body(SYSTEM_PROMPT).count("只返回 JSON") == 1


def test_resolve_appends_contract_for_short_scene():
    out = resolve_prompt_body("列出今天要跟的人")
    assert "列出今天要跟的人" in out
    assert "只返回 JSON" in out
