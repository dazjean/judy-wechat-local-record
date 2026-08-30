"""解密微信 attach 目录里已查看原图对应的 V1/V2 .dat。"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Optional

from Crypto.Cipher import AES

V1_MAGIC = b"\x07\x08V1\x08\x07"
V2_MAGIC = b"\x07\x08V2\x08\x07"
V1_AES_KEY = b"cfcd208495d565ef"
_IMAGE_HEADS = (b"\xff\xd8\xff", b"\x89PNG", b"GIF8", b"RIFF")


def _is_image(data: bytes) -> bool:
    if not data:
        return False
    if data.startswith(b"RIFF"):
        return len(data) >= 12 and data[8:12] == b"WEBP"
    return any(data.startswith(h) for h in _IMAGE_HEADS if h != b"RIFF")


def _parse_aes_key(raw: str) -> Optional[bytes]:
    text = (raw or "").strip()
    if len(text) == 32:
        try:
            key = bytes.fromhex(text)
        except ValueError:
            return None
        return key if len(key) == 16 else None
    if len(text) == 16 and text.isascii():
        return text.encode("ascii")
    return None


def _aes_keys(xml_aeskey: str) -> list[bytes]:
    keys: list[bytes] = []
    seen: set[bytes] = set()
    for candidate in (_parse_aes_key(xml_aeskey), V1_AES_KEY):
        if candidate and len(candidate) == 16 and candidate not in seen:
            seen.add(candidate)
            keys.append(candidate)
    return keys


def _xor_from_tail(tail: bytes) -> int:
    if len(tail) >= 2:
        k1 = tail[-2] ^ 0xFF
        k2 = tail[-1] ^ 0xD9
        if k1 == k2:
            return k1
    return 0x88


def _v1_v2_decrypt(data: bytes, aes_key: bytes, xor_key: int) -> Optional[bytes]:
    if data[:6] not in (V1_MAGIC, V2_MAGIC) or len(data) < 15:
        return None
    aes_size = struct.unpack_from("<I", data, 6)[0]
    xor_size = struct.unpack_from("<I", data, 10)[0]
    if aes_size <= 0 or aes_size > len(data) or xor_size < 0:
        return None
    offset = 15
    aes_blocks = ((aes_size + 15) // 16) * 16
    if offset + aes_blocks > len(data):
        return None
    try:
        aes_dec = AES.new(aes_key, AES.MODE_ECB).decrypt(data[offset : offset + aes_blocks])[:aes_size]
    except ValueError:
        return None
    mid_end = len(data) - xor_size
    if mid_end < offset + aes_blocks:
        return None
    mid = data[offset + aes_blocks : mid_end]
    xor_tail = data[mid_end:]
    out = aes_dec + mid + bytes(b ^ xor_key for b in xor_tail)
    return out if _is_image(out) else None


def decrypt_dat(path: Path, xml_aeskey: str = "") -> Optional[bytes]:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if _is_image(data):
        return data
    xor_guess = _xor_from_tail(data[-2:]) if len(data) >= 2 else 0x88
    for key in _aes_keys(xml_aeskey):
        for xor_key in (xor_guess, 0x88):
            plain = _v1_v2_decrypt(data, key, xor_key)
            if plain:
                return plain
    return None
