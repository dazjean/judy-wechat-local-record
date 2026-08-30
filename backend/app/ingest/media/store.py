from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

from app.config import settings

_SAFE_NAME = re.compile(r"[^\w.\u4e00-\u9fff-]+", re.UNICODE)


def safe_filename(name: str, fallback: str = "file") -> str:
    text = (name or "").strip() or fallback
    text = text.replace("/", "_").replace("\\", "_")
    text = _SAFE_NAME.sub("_", text).strip("._") or fallback
    return text[:180]


def sniff_mime(data: bytes, name: str = "") -> tuple[str, str]:
    ext = Path(name).suffix.lower().lstrip(".")
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "jpg"
    if data.startswith(b"\x89PNG"):
        return "image/png", "png"
    if data.startswith(b"GIF8"):
        return "image/gif", "gif"
    if data.startswith(b"RIFF") and b"WEBP" in data[:16]:
        return "image/webp", "webp"
    if data.startswith(b"%PDF"):
        return "application/pdf", "pdf"
    if data.startswith(b"PK"):
        if ext in {"docx", "xlsx", "pptx", "zip"}:
            mime = {
                "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            }.get(ext, "application/zip")
            return mime, ext or "zip"
        return "application/zip", ext or "zip"
    if data.startswith(b"ID3") or (len(data) > 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0):
        return "audio/mpeg", "mp3"
    if data.startswith(b"#!SILK") or (len(data) > 8 and data[1:7] == b"#!SILK"):
        return "audio/silk", "silk"
    if data[:4] == b"RIFF" and b"WAVE" in data[:16]:
        return "audio/wav", "wav"
    if ext:
        return "application/octet-stream", ext
    return "application/octet-stream", "bin"


def save_bytes(kind: str, data: bytes, name: str) -> tuple[str, str, str]:
    """写入 data/media/{kind}/，返回 (relpath, mime, stored_name)。"""
    if not data:
        raise ValueError("empty media")
    mime, ext = sniff_mime(data, name)
    digest = hashlib.sha256(data).hexdigest()[:16]
    stem = safe_filename(Path(name).stem or kind, kind)
    stored = f"{stem}_{digest}.{ext}"
    dest_dir = settings.media_dir / kind
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / stored
    if not dest.exists():
        dest.write_bytes(data)
    rel = f"{kind}/{stored}"
    return rel, mime, Path(name).name or stored


def save_file(kind: str, src: Path, name: str = "") -> tuple[str, str, str]:
    data = src.read_bytes()
    return save_bytes(kind, data, name or src.name)


def resolve_media_path(relpath: str) -> Path | None:
    rel = (relpath or "").replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/"):
        return None
    root = settings.media_dir.resolve()
    path = (settings.media_dir / rel).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path if path.is_file() else None


def clear_media_dir() -> None:
    if not settings.media_dir.exists():
        return
    for child in settings.media_dir.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            try:
                child.unlink()
            except OSError:
                pass
