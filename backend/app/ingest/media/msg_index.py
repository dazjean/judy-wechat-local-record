"""从本机已解密的消息库和语音库取出媒体元数据。"""

from __future__ import annotations

import hashlib
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional
from xml.etree import ElementTree as ET

from app.config import settings
from app.ingest.media.sqlcipher import decrypt_wal, full_decrypt
from app.ingest.media.wx_paths import db_storage_dir, load_db_keys

try:
    import zstandard as zstd
except ImportError:  # pragma: no cover
    zstd = None

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
_zstd = zstd.ZstdDecompressor() if zstd else None


@dataclass
class NativeMedia:
    kind: str
    create_time: int
    local_id: int
    file_name: str = ""
    xml_md5: str = ""
    xml_length: int = 0
    xml_aeskey: str = ""
    silk_length: int = 0
    used: bool = False


def _cache_db_paths() -> list[Path]:
    roots = [
        Path(tempfile.gettempdir()) / "wechat_cli_cache",
        Path.home() / ".openclaw" / "tmp" / "wechat_cli_cache",
    ]
    out: list[Path] = []
    for root in roots:
        if root.is_dir():
            out.extend(sorted(root.glob("*.db")))
    return out


def _decode_content(blob) -> str:
    if blob is None:
        return ""
    if isinstance(blob, str):
        return blob
    data = bytes(blob)
    if not data:
        return ""
    if _zstd and data.startswith(ZSTD_MAGIC):
        try:
            return _zstd.decompress(data, max_output_size=8_000_000).decode("utf-8", errors="replace")
        except Exception:
            pass
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        if _zstd:
            try:
                return _zstd.decompress(data, max_output_size=8_000_000).decode("utf-8", errors="replace")
            except Exception:
                pass
        return data.decode("utf-8", errors="replace")


def _parse_xml(text: str) -> Optional[ET.Element]:
    if not text:
        return None
    idx = text.find("<msg")
    if idx < 0:
        idx = text.find("<appmsg")
    if idx < 0:
        return None
    chunk = text[idx:]
    try:
        return ET.fromstring(chunk)
    except ET.ParseError:
        return None


def _app_type(root: ET.Element) -> int:
    node = root.find(".//appmsg")
    if node is None:
        return 0
    raw = (node.findtext("type") or "").strip()
    try:
        return int(raw)
    except ValueError:
        return 0


def _file_title(root: ET.Element) -> str:
    node = root.find(".//appmsg")
    if node is None:
        return ""
    return (node.findtext("title") or "").strip()


def _img_meta(root: ET.Element) -> tuple[str, int, str]:
    img = root.find(".//img")
    if img is None:
        return "", 0, ""
    md5 = (img.attrib.get("md5") or "").strip().lower()
    aeskey = (img.attrib.get("aeskey") or "").strip()
    length = 0
    for key in ("hdlength", "length"):
        raw = (img.attrib.get(key) or "").strip()
        if raw.isdigit():
            length = int(raw)
            if length:
                break
    return md5, length, aeskey


def _voice_len(root: ET.Element) -> int:
    node = root.find(".//voicemsg")
    if node is None:
        return 0
    raw = (node.attrib.get("length") or "").strip()
    return int(raw) if raw.isdigit() else 0


def load_native_media(wxid: str) -> list[NativeMedia]:
    if not wxid:
        return []
    table = "Msg_" + hashlib.md5(wxid.encode("utf-8")).hexdigest()
    best: Optional[tuple[Path, int]] = None
    for db in _cache_db_paths():
        try:
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            hit = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if not hit:
                conn.close()
                continue
            latest = conn.execute(f"SELECT MAX(create_time) FROM {table}").fetchone()[0] or 0
            conn.close()
            if best is None or int(latest) > best[1]:
                best = (db, int(latest))
        except sqlite3.Error:
            continue
    if not best:
        return []
    db_path = best[0]
    rows: list[NativeMedia] = []
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.text_factory = bytes
        cur = conn.execute(
            f"SELECT local_id, local_type, create_time, message_content FROM {table} "
            f"WHERE (local_type & 0xFFFFFFFF) IN (3, 34, 49) ORDER BY create_time ASC"
        )
        for local_id, local_type, create_time, blob in cur:
            base = int(local_type) & 0xFFFFFFFF
            xml = _decode_content(blob)
            root = _parse_xml(xml)
            kind = ""
            item = NativeMedia(kind="", create_time=int(create_time or 0), local_id=int(local_id or 0))
            if base == 3:
                kind = "image"
                if root is not None:
                    item.xml_md5, item.xml_length, item.xml_aeskey = _img_meta(root)
            elif base == 34:
                kind = "voice"
                if root is not None:
                    item.silk_length = _voice_len(root)
            elif base == 49:
                if root is not None and _app_type(root) == 6:
                    kind = "file"
                    item.file_name = _file_title(root)
            if not kind:
                continue
            item.kind = kind
            rows.append(item)
        conn.close()
    except sqlite3.Error:
        return []
    return rows


def take_native(rows: list[NativeMedia], kind: str, msg_time: datetime) -> Optional[NativeMedia]:
    ts = int(msg_time.timestamp())
    minute = ts - (ts % 60)
    window = (minute, minute + 59) if msg_time.second == 0 else (ts - 2, ts + 2)
    hits = [
        row
        for row in rows
        if not row.used and row.kind == kind and window[0] <= row.create_time <= window[1]
    ]
    if not hits:
        hits = [
            row
            for row in rows
            if not row.used and row.kind == kind and abs(row.create_time - ts) <= 90
        ]
    if not hits:
        return None
    hits.sort(key=lambda r: r.create_time)
    chosen = hits[0]
    chosen.used = True
    return chosen


def decrypt_media_db(rel_key: str) -> Optional[Path]:
    keys = load_db_keys()
    info = keys.get(rel_key)
    if not info:
        for key, value in keys.items():
            norm = str(key).replace("\\", "/")
            if norm == rel_key or norm.endswith("/" + rel_key):
                info = value
                break
    if not info:
        return None
    hex_key = str(info.get("enc_key") or "")
    if len(hex_key) != 64:
        return None
    storage = db_storage_dir()
    if not storage:
        return None
    src = storage / Path(rel_key)
    if not src.is_file():
        return None
    dest = settings.media_cache_dir / rel_key.replace("/", "_")
    marker = dest.with_suffix(dest.suffix + ".mt")
    try:
        src_mt = src.stat().st_mtime
        wal = Path(str(src) + "-wal")
        wal_mt = wal.stat().st_mtime if wal.is_file() else 0
    except OSError:
        return None
    token = f"{src_mt}:{wal_mt}"
    if dest.is_file() and marker.is_file() and marker.read_text(encoding="utf-8") == token:
        return dest
    enc_key = bytes.fromhex(hex_key)
    full_decrypt(str(src), str(dest), enc_key)
    if wal.is_file():
        decrypt_wal(str(wal), str(dest), enc_key)
    marker.write_text(token, encoding="utf-8")
    return dest


def iter_voice_dbs() -> Iterator[Path]:
    for rel in ("message/media_0.db", "message/media_1.db"):
        path = decrypt_media_db(rel)
        if path and path.is_file():
            yield path


def load_voice_blob(wxid: str, create_time: int, silk_length: int = 0) -> Optional[bytes]:
    if not wxid:
        return None
    for db in iter_voice_dbs():
        try:
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        except sqlite3.Error:
            continue
        try:
            rid = conn.execute(
                "SELECT rowid FROM Name2Id WHERE user_name=?", (wxid,)
            ).fetchone()
            if not rid:
                continue
            chat_id = rid[0]
            if silk_length:
                row = conn.execute(
                    "SELECT voice_data FROM VoiceInfo WHERE chat_name_id=? AND length(voice_data)=? "
                    "AND create_time BETWEEN ? AND ? ORDER BY ABS(create_time - ?) LIMIT 1",
                    (chat_id, silk_length, create_time - 90, create_time + 90, create_time),
                ).fetchone()
                if row and row[0]:
                    return bytes(row[0])
            row = conn.execute(
                "SELECT voice_data FROM VoiceInfo WHERE chat_name_id=? "
                "AND create_time BETWEEN ? AND ? ORDER BY ABS(create_time - ?) LIMIT 1",
                (chat_id, create_time - 90, create_time + 90, create_time),
            ).fetchone()
            if row and row[0]:
                return bytes(row[0])
        except sqlite3.Error:
            continue
        finally:
            conn.close()
    return None
