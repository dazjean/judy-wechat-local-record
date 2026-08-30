from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from app.config import settings

DEFAULT_TIMEOUT = 30


def _lock_path() -> Path:
    path = settings.data_dir / "locks" / "wx_reader.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def reader_lock(timeout: Optional[int] = None) -> Iterator[None]:
    """多任务串行读库，避免同时打开本机微信库。"""
    wait = DEFAULT_TIMEOUT if timeout is None else timeout
    path = _lock_path()
    fd = os.open(str(path), os.O_CREAT | os.O_RDWR)
    start = time.time()
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt

            while True:
                try:
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    acquired = True
                    break
                except OSError:
                    if time.time() - start >= wait:
                        from app.ingest.wechat_cli.errors import map_failure

                        raise map_failure("lock_timeout")
                    time.sleep(0.05)
        else:
            import fcntl

            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except (BlockingIOError, OSError):
                    if time.time() - start >= wait:
                        from app.ingest.wechat_cli.errors import map_failure

                        raise map_failure("lock_timeout")
                    time.sleep(0.05)
        yield
    finally:
        if acquired:
            try:
                if os.name == "nt":
                    import msvcrt

                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(fd)
