"""把微信 SILK 语音条转成可播放的 MP3。"""

from __future__ import annotations

import os
import shutil
import subprocess
from io import BytesIO
from pathlib import Path
from typing import Optional

_FFMPEG_CANDIDATES = (
    "/opt/homebrew/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
)


def ffmpeg_bin() -> Optional[str]:
    found = shutil.which("ffmpeg")
    if found and os.access(found, os.X_OK):
        return found
    for path in _FFMPEG_CANDIDATES:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def silk_payload(data: bytes) -> bytes:
    if data[:1] == b"\x02" and data[1:7] == b"#!SILK":
        return data[1:]
    return data


def _decode_pcm(payload: bytes) -> tuple[bytes, int]:
    import pysilk

    for rate in (24000, 16000, 12000):
        pcm = BytesIO()
        try:
            pysilk.decode(BytesIO(payload), pcm, rate)
        except Exception:
            continue
        raw = pcm.getvalue()
        if len(raw) >= 960:
            return raw, rate
    return b"", 0


def silk_to_mp3(data: bytes) -> Optional[bytes]:
    if not data:
        return None
    ffmpeg = ffmpeg_bin()
    if not ffmpeg:
        return None
    payload = silk_payload(data)
    if b"SILK" not in payload[:16]:
        return None
    pcm, rate = _decode_pcm(payload)
    if not pcm or not rate:
        return None
    try:
        proc = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "s16le",
                "-ar",
                str(rate),
                "-ac",
                "1",
                "-i",
                "pipe:0",
                "-codec:a",
                "libmp3lame",
                "-q:a",
                "4",
                "-f",
                "mp3",
                "pipe:1",
            ],
            input=pcm,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    out = proc.stdout
    if out.startswith(b"ID3") or (len(out) > 2 and out[0] == 0xFF and (out[1] & 0xE0) == 0xE0):
        return out
    return None
