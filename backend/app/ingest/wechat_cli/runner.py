"""定位并调用内部微信读取组件。不把命令名暴露给调用方以外的日志用户界面。"""

from __future__ import annotations

import json
import os
import signal
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

from app.config import settings
from app.ingest.wechat_cli.errors import ReaderError, map_failure
from app.ingest.wechat_cli.lock import reader_lock
from app.ingest.win_hidden import hidden_run_kwargs

_BIN_NAMES = ("wechat-cli.exe", "wechat-cli") if sys.platform == "win32" else ("wechat-cli",)


def resolve_reader_bin() -> Optional[Path]:
    """只在 Judy.app 内嵌目录 / 仓库 vendor / venv 查找，不依赖系统 PATH 作为首选。"""
    from app.config import bundled_vendor_dirs

    roots = [
        *bundled_vendor_dirs(),
        settings.vendor_dir,
        settings.root / "backend" / ".venv" / ("Scripts" if sys.platform == "win32" else "bin"),
        settings.root / ".venv" / ("Scripts" if sys.platform == "win32" else "bin"),
        Path(sys.executable).resolve().parent,
    ]
    if sys.platform == "win32":
        roots.append(Path(sys.executable).resolve().parent / "Scripts")

    for directory in roots:
        if not directory.is_dir():
            continue
        for name in _BIN_NAMES:
            cand = directory / name
            if cand.is_file():
                return cand

    for name in _BIN_NAMES:
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def _decode(raw: bytes) -> str:
    raw = raw or b""
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc).strip()
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace").strip()


def _popen_kwargs() -> dict[str, Any]:
    kw: dict[str, Any] = hidden_run_kwargs()
    if sys.platform == "win32":
        kw["creationflags"] = int(kw.get("creationflags") or 0) | int(
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        )
    else:
        kw["start_new_session"] = True
    return kw


def _kill_proc(proc: subprocess.Popen) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            **hidden_run_kwargs(),
        )
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        proc.kill()


def _run(args: list[str], timeout: int = 90) -> tuple[str, int]:
    bin_path = resolve_reader_bin()
    if not bin_path:
        raise map_failure("not_found")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env["PATH"] = str(bin_path.parent) + os.pathsep + env.get("PATH", "")
    kw: dict[str, Any] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "env": env,
    }
    kw.update(_popen_kwargs())
    try:
        with reader_lock():
            proc = subprocess.Popen([str(bin_path), *args], **kw)
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                _kill_proc(proc)
                try:
                    proc.communicate(timeout=3)
                except Exception:
                    pass
                raise map_failure("timeout") from exc
    except FileNotFoundError as exc:
        raise map_failure("not_found") from exc
    out = _decode(stdout)
    err = _decode(stderr)
    if proc.returncode != 0:
        combined = "\n".join(part for part in (out, err) if part).strip()
        return combined, proc.returncode
    return out, proc.returncode


def _parse_json(raw: str) -> Any:
    text = (raw or "").strip()
    if not text:
        return None
    start_obj = text.find("{")
    start_arr = text.find("[")
    starts = [i for i in (start_obj, start_arr) if i >= 0]
    if not starts:
        return None
    try:
        return json.loads(text[min(starts) :])
    except json.JSONDecodeError:
        return None


def probe_status() -> dict[str, Any]:
    """对外字段不含内部路径与命令名。"""
    bin_path = resolve_reader_bin()
    if not bin_path:
        return {
            "reader_ready": False,
            "wechat_logged_in": False,
            "hint": "微信读取组件未就绪，请重新安装本系统",
        }
    try:
        out, code = _run(["sessions", "--limit", "1"], timeout=30)
    except ReaderError as exc:
        return {
            "reader_ready": False,
            "wechat_logged_in": False,
            "hint": exc.public_message,
        }
    data = _parse_json(out)
    ready = code == 0 and data is not None
    if not ready:
        err = (out or "").lower()
        if "not running" in err or "未运行" in err or "weixin" in err:
            hint = map_failure("wechat_down").public_message
        else:
            hint = map_failure("not_inited").public_message
        return {"reader_ready": False, "wechat_logged_in": False, "hint": hint}
    items = _as_list(data)
    return {
        "reader_ready": True,
        "wechat_logged_in": True,
        "hint": "微信读取已就绪" if items is not None else "微信读取已就绪，暂无最近会话",
        "session_preview_count": len(items or []),
    }


def list_sessions(limit: int = 200) -> list[dict]:
    out, code = _run(["sessions", "--limit", str(limit)], timeout=60)
    data = _parse_json(out)
    if code != 0 or data is None:
        raise _fail_from_output(out, code)
    return _as_list(data)


def query_contacts(name: str) -> list[dict]:
    out, code = _run(["contacts", "--query", name], timeout=20)
    data = _parse_json(out)
    if code != 0 or data is None:
        return []
    return _as_list(data)


def fetch_history(name: str, start_date: str, limit: int) -> list[str]:
    args = ["history", name, "--limit", str(limit)]
    if start_date:
        args.extend(["--start-time", start_date])
    out, code = _run(args, timeout=90)
    data = _parse_json(out)
    if code != 0:
        raise _fail_from_output(out, code, command="history")
    if not isinstance(data, dict):
        return []
    messages = data.get("messages") or []
    return [m for m in messages if isinstance(m, str)]


def init_reader() -> None:
    """供 scripts/init_wechat_reader 调用。"""
    out, code = _run(["init"], timeout=180)
    if code != 0:
        raise _fail_from_output(out, code)


def _as_list(data: Any) -> list[dict]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("sessions", "contacts", "data", "items", "list"):
            if isinstance(data.get(key), list):
                return [x for x in data[key] if isinstance(x, dict)]
    return []


def _fail_from_output(out: str, code: int, command: str = "") -> ReaderError:
    text = (out or "").lower()
    if "not running" in text or "未运行" in text:
        return map_failure("wechat_down")
    if "0 unique" in text or "0 key" in text or "no key" in text:
        return map_failure("not_inited")
    if any(
        token in text
        for token in ("找不到", "not found", "no chat", "无记录", "不存在", "no history", "no session")
    ):
        return map_failure("no_session")
    if command == "history" and code != 0:
        return map_failure("no_session")
    if code != 0:
        return map_failure("not_inited")
    return map_failure("parse")
