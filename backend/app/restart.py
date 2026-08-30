"""关闭当前进程并拉起新实例。改数据目录后必须走这里。"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path

from app.config import deployed, frozen, runtime_backend, settings


def start_api_script(root: Path) -> Path | None:
    exe = Path(sys.executable).resolve()
    cands: list[Path] = []
    for parent in exe.parents:
        if parent.suffix == ".app":
            cands.append(parent / "Contents" / "Resources" / "scripts" / "start_api.sh")
            break
    cands.append(root / "Judy.app" / "Contents" / "Resources" / "scripts" / "start_api.sh")
    cands.append(root / "scripts" / "start_api.sh")
    for path in cands:
        if path.is_file():
            return path
    return None


def restart_spec() -> tuple[list[str], str, dict[str, str]]:
    env = os.environ.copy()
    root = settings.root
    if deployed() and not frozen():
        script = start_api_script(root)
        env["JUDY_ROOT"] = str(root)
        env["JUDY_DEPLOY"] = "1"
        env["JUDY_NO_WINDOW"] = "1"
        env["JUDY_RESTART"] = "1"
        env["PYTHONPATH"] = str(runtime_backend())
        if script is not None:
            return ["bash", str(script)], str(root), env
    if frozen():
        exe = str(Path(sys.executable).resolve())
        return [exe], str(Path(exe).parent), env
    env["PYTHONPATH"] = str(runtime_backend())
    cmd = [sys.executable, "-m", "app.boot"]
    return cmd, str(root), env


def spawn_new_process() -> None:
    cmd, cwd, env = restart_spec()
    kwargs: dict = {"cwd": cwd, "env": env, "start_new_session": True}
    if sys.platform == "win32":
        quoted = subprocess.list2cmdline(cmd)
        cmd = ["cmd.exe", "/c", f"timeout /t 1 /nobreak >nul & {quoted}"]
        kwargs["start_new_session"] = False
        kwargs["creationflags"] = int(
            getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        )
    else:
        quoted = " ".join(shlex.quote(c) for c in cmd)
        cmd = ["/bin/bash", "-c", f"sleep 1.2; exec {quoted}"]
    subprocess.Popen(cmd, **kwargs)


def schedule_restart(delay: float = 0.6) -> None:
    def _go() -> None:
        time.sleep(delay)
        spawn_new_process()
        os._exit(0)

    threading.Thread(target=_go, daemon=True).start()
