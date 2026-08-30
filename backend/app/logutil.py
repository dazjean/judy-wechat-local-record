from __future__ import annotations

from datetime import datetime

from app.config import settings


def append_sync_log(job_id: str, message: str) -> None:
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    path = settings.logs_dir / f"sync-{job_id}.log"
    stamp = datetime.now().strftime("%Y年%m月%d日 %H.%M.%S")
    with path.open("a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {message.rstrip()}\n")
        f.flush()


def read_sync_log(job_id: str, max_lines: int = 300) -> str:
    path = settings.logs_dir / f"sync-{job_id}.log"
    if not path.is_file():
        return ""
    lines = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[-max_lines:])
