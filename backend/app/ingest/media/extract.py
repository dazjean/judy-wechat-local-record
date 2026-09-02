"""把已查看图片、已下载文件、语音原条落到本机 media 目录。"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.ingest.media.dat_decrypt import decrypt_dat
from app.ingest.media.msg_index import (
    NativeMedia,
    load_native_media,
    load_voice_blob,
    parse_local_id,
    resolve_native,
)
from app.ingest.media.silk_mp3 import silk_to_mp3
from app.ingest.media.store import save_bytes, save_file
from app.ingest.media.wx_paths import wechat_account_root
from app.ingest.wechat_cli.parse import ParsedMessage

_DAT_HEADER = 31


def _chat_hash(wxid: str) -> str:
    return hashlib.md5((wxid or "").encode("utf-8")).hexdigest()


def _is_preview_image(path: Path) -> bool:
    try:
        head = path.read_bytes()[:16]
    except OSError:
        return False
    return head.startswith(b"\xff\xd8\xff") or head.startswith(b"\x89PNG") or head.startswith(b"GIF8")


def _best_dat(img_dir: Path, xml_md5: str, create_time: int, xml_length: int = 0) -> Optional[Path]:
    if not img_dir.is_dir():
        return None
    files = [p for p in img_dir.glob("*.dat") if p.is_file() and not p.name.endswith("_t.dat")]
    if not files:
        return None
    ranked: list[tuple[int, int, int, Path]] = []
    for path in files:
        name = path.name
        try:
            st = path.stat()
            delta = abs(int(st.st_mtime) - create_time)
            plain = max(st.st_size - _DAT_HEADER, 0)
        except OSError:
            delta = 10**9
            plain = 0
        tier = 0
        if xml_md5 and xml_md5 in name:
            tier = 40 if name.endswith("_h.dat") else 35
        elif xml_length and abs(plain - xml_length) <= 1:
            tier = 30
        elif delta <= 120:
            tier = 20 if not name.endswith("_h.dat") else 10
        elif name.endswith("_h.dat"):
            tier = 3
        else:
            tier = 2
        size_penalty = abs(plain - xml_length) if xml_length else 0
        ranked.append((tier, -delta, -size_penalty, path))
    ranked.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    return ranked[0][3] if ranked else None


def build_opened_image_pool(root: Path) -> list[tuple[int, Path]]:
    """新版 macOS 微信把点开后的原图写到 temp/RWTemp，体积常与 XML length 不一致。"""
    pool: list[tuple[int, Path]] = []
    base = root / "temp"
    if not base.is_dir():
        return pool
    scan_roots: list[Path] = []
    for name in ("RWTemp", "InputTemp", "inputtemp", "ImageTemp"):
        path = base / name
        if path.is_dir():
            scan_roots.append(path)
    if not scan_roots:
        return pool
    for scan_root in scan_roots:
        for path in scan_root.rglob("*"):
            if not path.is_file() or not _is_preview_image(path):
                continue
            try:
                mtime = int(path.stat().st_mtime)
            except OSError:
                continue
            pool.append((mtime, path))
    pool.sort(key=lambda row: row[0])
    return pool


def take_opened_preview(
    pool: list[tuple[int, Path]],
    used: set[Path],
    create_time: int,
    dat: Optional[Path] = None,
    *,
    max_after: int = 86400 * 7,
    max_before: int = 300,
) -> Optional[Path]:
    dat_stem = dat.stem.replace("_h", "").replace("_t", "") if dat else ""
    best: Optional[tuple[int, Path]] = None
    for mtime, path in pool:
        if path in used:
            continue
        offset = mtime - create_time
        if offset < -max_before or offset > max_after:
            continue
        score = abs(offset)
        if dat_stem and dat_stem in path.name:
            score -= 1_000_000
        if best is None or score < best[0]:
            best = (score, path)
    if best is None:
        return None
    used.add(best[1])
    return best[1]


def build_preview_index(root: Path) -> dict[int, list[Path]]:
    index: dict[int, list[Path]] = {}
    base = root / "temp"
    if not base.is_dir():
        return index
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size <= 32:
            continue
        if not _is_preview_image(path):
            continue
        index.setdefault(size, []).append(path)
    return index


def _find_preview_by_size(
    index: dict[int, list[Path]], size: int, create_time: int
) -> Optional[Path]:
    paths = index.get(size) or []
    if not paths:
        return None
    best: Optional[tuple[int, Path]] = None
    for path in paths:
        try:
            delta = abs(int(path.stat().st_mtime) - create_time)
        except OSError:
            delta = 10**9
        if best is None or delta < best[0]:
            best = (delta, path)
    return best[1] if best else None


def _find_image_bytes(
    wxid: str, native: NativeMedia, preview_index: dict[int, list[Path]]
) -> Optional[tuple[bytes, str]]:
    root = wechat_account_root()
    if not root:
        return None
    month = datetime.fromtimestamp(native.create_time).strftime("%Y-%m")
    img_dir = root / "msg" / "attach" / _chat_hash(wxid) / month / "Img"
    dat = _best_dat(img_dir, native.xml_md5, native.create_time, native.xml_length)
    sizes: list[int] = []
    if native.xml_length:
        sizes.append(native.xml_length)
    if dat:
        try:
            sizes.append(max(dat.stat().st_size - _DAT_HEADER, 0))
        except OSError:
            pass
    seen: set[int] = set()
    for size in sizes:
        if size in seen or size <= 32:
            continue
        seen.add(size)
        preview = _find_preview_by_size(preview_index, size, native.create_time)
        if preview:
            try:
                return preview.read_bytes(), preview.name
            except OSError:
                continue
    if dat and not dat.name.endswith("_t.dat"):
        plain = decrypt_dat(dat, native.xml_aeskey)
        if plain:
            return plain, dat.name
    return None


def _find_downloaded_file(native: NativeMedia) -> Optional[Path]:
    root = wechat_account_root()
    title = (native.file_name or "").strip()
    if not root or not title:
        return None
    file_root = root / "msg" / "file"
    if not file_root.is_dir():
        return None
    month = datetime.fromtimestamp(native.create_time).strftime("%Y-%m")
    folders: list[Path] = []
    preferred = file_root / month
    if preferred.is_dir():
        folders.append(preferred)
    for path in sorted(file_root.iterdir(), reverse=True):
        if path.is_dir() and path not in folders:
            folders.append(path)
    for folder in folders:
        exact = folder / title
        if exact.is_file():
            return exact
    for folder in folders:
        try:
            children = list(folder.iterdir())
        except OSError:
            continue
        for path in children:
            if path.is_file() and (title in path.name or path.name in title):
                return path
    return None


def attach_media(items: list[ParsedMessage], peer_key: str) -> dict[str, int]:
    stats = {"image": 0, "voice": 0, "file": 0, "missing": 0}
    if not items or not peer_key:
        return stats
    natives = load_native_media(peer_key)
    root = wechat_account_root()
    preview_index = build_preview_index(root) if root else {}
    opened_pool = build_opened_image_pool(root) if root else []
    used_opened: set[Path] = set()
    pending_images: list[tuple[ParsedMessage, NativeMedia]] = []
    for item in items:
        if item.msg_type not in {"image", "voice", "file"}:
            continue
        native = resolve_native(
            natives,
            item.msg_type,
            item.msg_time,
            local_id=parse_local_id(item.content),
        )
        if native is None:
            native = NativeMedia(
                kind=item.msg_type,
                create_time=int(item.msg_time.timestamp()),
                local_id=0,
                file_name=item.content[4:].strip() if item.content.startswith("[文件]") else "",
            )
        rel = name = mime = status = ""
        try:
            if item.msg_type == "image":
                found = _find_image_bytes(peer_key, native, preview_index)
                if found:
                    data, src_name = found
                    rel, mime, name = save_bytes("image", data, src_name)
                    status = "ready"
                else:
                    pending_images.append((item, native))
                    continue
            elif item.msg_type == "file":
                if not native.file_name and item.content.startswith("[文件]"):
                    native.file_name = item.content[4:].strip()
                src = _find_downloaded_file(native)
                if src:
                    rel, mime, name = save_file("file", src, native.file_name or src.name)
                    status = "ready"
                    if native.file_name:
                        item.content = f"[文件] {native.file_name}"
            elif item.msg_type == "voice":
                blob = load_voice_blob(peer_key, native.create_time, native.silk_length)
                if blob:
                    mp3 = silk_to_mp3(blob)
                    if mp3:
                        rel, mime, name = save_bytes("voice", mp3, "voice.mp3")
                    else:
                        rel, mime, name = save_bytes("voice", blob, "voice.silk")
                    status = "ready"
        except OSError:
            rel = ""
            status = ""
        if rel:
            item.media_relpath = rel
            item.media_name = name
            item.media_mime = mime
            item.media_status = status
            stats[item.msg_type] += 1
        else:
            item.media_status = "missing"
            stats["missing"] += 1

    pending_images.sort(key=lambda pair: pair[1].create_time, reverse=True)
    for item, native in pending_images:
        rel = name = mime = status = ""
        try:
            if root:
                month = datetime.fromtimestamp(native.create_time).strftime("%Y-%m")
                img_dir = root / "msg" / "attach" / _chat_hash(peer_key) / month / "Img"
                dat = _best_dat(img_dir, native.xml_md5, native.create_time, native.xml_length)
                preview = take_opened_preview(opened_pool, used_opened, native.create_time, dat)
                if preview:
                    data = preview.read_bytes()
                    rel, mime, name = save_bytes("image", data, preview.name)
                    status = "ready"
        except OSError:
            rel = ""
            status = ""
        if rel:
            item.media_relpath = rel
            item.media_name = name
            item.media_mime = mime
            item.media_status = status
            stats["image"] += 1
        else:
            item.media_status = "missing"
            stats["missing"] += 1
    return stats
