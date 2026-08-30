"""Windows 隐藏控制台。对齐灵犀 B36。"""

from __future__ import annotations

import subprocess
import sys

CREATE_NO_WINDOW = int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
STARTF_USESHOWWINDOW = int(getattr(subprocess, "STARTF_USESHOWWINDOW", 1))


def hidden_run_kwargs() -> dict:
    if sys.platform != "win32":
        return {}
    kw: dict = {"creationflags": CREATE_NO_WINDOW}
    si_cls = getattr(subprocess, "STARTUPINFO", None)
    if si_cls is not None:
        si = si_cls()
        si.dwFlags |= STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        kw["startupinfo"] = si
    return kw
