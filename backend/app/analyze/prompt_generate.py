from __future__ import annotations

import re

import httpx

from app.analyze.prompt import GENERATE_SYSTEM, GENERATE_SYSTEM_GROUP, GENERATE_SYSTEM_GROUP_DIGEST
from app.analyze.prompt_store import resolve_prompt_body
from app.config import settings
from app.settings_persist import model_config_error


def _strip_fences(text: str) -> str:
    out = (text or "").strip()
    if out.startswith("```"):
        out = re.sub(r"^```(?:\w+)?", "", out, flags=re.I).strip()
        out = re.sub(r"```$", "", out).strip()
    return out


def generate_prompt_body(brief: str, kind: str = "report") -> str:
    missing = model_config_error()
    if missing:
        raise ValueError(missing)
    text = (brief or "").strip()
    if not text:
        raise ValueError("请填写一句大白话需求")
    if kind == "group_digest":
        system = GENERATE_SYSTEM_GROUP_DIGEST
    elif kind == "group":
        system = GENERATE_SYSTEM_GROUP
    else:
        system = GENERATE_SYSTEM
    payload = {
        "model": settings.model_name,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ],
        "temperature": 0.3,
    }
    url = settings.model_base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {settings.model_api_key}"}
    try:
        with httpx.Client(timeout=120) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        content = _strip_fences(data["choices"][0]["message"]["content"])
    except ValueError:
        raise
    except Exception:
        raise RuntimeError("模型调用失败，请检查地址、模型名和额度") from None
    if not content:
        raise RuntimeError("模型没有返回提示词，请重试")
    return resolve_prompt_body(content, kind=kind)
