from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.ingest.media.msg_index import NativeMedia, take_native  # noqa: E402
from app.ingest.media.store import resolve_media_path, sniff_mime  # noqa: E402
from app.ingest.wechat_cli.parse import parse_history_lines  # noqa: E402


def test_parse_file_and_voice_types():
    lines = [
        "[2026-08-01 10:00] 家长: [文件] 作业.pdf",
        "[2026-08-01 10:01] 家长: [语音] <msg><voicemsg length=\"22266\" /></msg>",
    ]
    parsed = parse_history_lines(lines, "wxid_demo")
    assert parsed[0].msg_type == "file"
    assert parsed[0].content.startswith("[文件]")
    assert parsed[1].msg_type == "voice"
    assert parsed[1].content.startswith("[语音]")


def test_take_native_pairs_same_minute():
    rows = [
        NativeMedia(kind="voice", create_time=1787960313, local_id=1, silk_length=5334),
        NativeMedia(kind="voice", create_time=1787960450, local_id=2, silk_length=22266),
        NativeMedia(kind="image", create_time=1787960274, local_id=3, xml_length=78803),
    ]
    voice_at = datetime.fromtimestamp(1787960400)
    hit = take_native(rows, "voice", voice_at)
    assert hit is not None
    assert hit.silk_length == 22266
    leftover = take_native(rows, "voice", voice_at)
    assert leftover is not None
    assert leftover.silk_length == 5334
    assert leftover.local_id != hit.local_id
    assert take_native(rows, "voice", voice_at) is None


def test_sniff_silk_and_png():
    mime, ext = sniff_mime(b"\x02#!SILK_V3" + b"\x00" * 8, "voice.silk")
    assert mime == "audio/silk"
    assert ext == "silk"
    mime, ext = sniff_mime(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8, "a.png")
    assert mime == "image/png"
    mime, ext = sniff_mime(b"ID3" + b"\x00" * 8, "voice.mp3")
    assert mime == "audio/mpeg"
    assert ext == "mp3"


def test_silk_to_mp3_roundtrip():
    from io import BytesIO

    import pysilk
    from app.ingest.media.silk_mp3 import ffmpeg_bin, silk_to_mp3

    if not ffmpeg_bin():
        return
    pcm = BytesIO(b"\x00\x00" * 4800)
    silk_buf = BytesIO()
    pysilk.encode(pcm, silk_buf, 24000, 25000)
    encoded = silk_buf.getvalue()
    mp3 = silk_to_mp3(encoded) or silk_to_mp3(b"\x02" + encoded)
    assert mp3
    assert mp3.startswith(b"ID3") or mp3[0] == 0xFF


def test_silk_payload_strips_wechat_prefix():
    from app.ingest.media.silk_mp3 import silk_payload

    raw = b"\x02#!SILK_V3" + b"\x00" * 4
    assert silk_payload(raw).startswith(b"#!SILK")
    assert silk_payload(b"#!SILK_V3xxxx").startswith(b"#!SILK")


def test_resolve_media_rejects_traversal(tmp_path, monkeypatch):
    from app.ingest.media import store as media_store

    media = tmp_path / "media"
    media.mkdir()
    (media / "image").mkdir()
    target = media / "image" / "ok.png"
    target.write_bytes(b"\x89PNG\r\n\x1a\n")
    fake = type("S", (), {"media_dir": media})()
    monkeypatch.setattr(media_store, "settings", fake)
    assert resolve_media_path("image/ok.png") == target.resolve()
    assert resolve_media_path("../ok.png") is None
    assert resolve_media_path("image/../../etc/passwd") is None


def test_find_downloaded_file_by_name(tmp_path, monkeypatch):
    from app.ingest.media import extract as media_extract
    from app.ingest.media.msg_index import NativeMedia

    ts = 1787960400
    month = tmp_path / "msg" / "file" / datetime.fromtimestamp(ts).strftime("%Y-%m")
    month.mkdir(parents=True)
    target = month / "作业.pdf"
    target.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(media_extract, "wechat_account_root", lambda: tmp_path)
    hit = media_extract._find_downloaded_file(
        NativeMedia(kind="file", create_time=ts, local_id=1, file_name="作业.pdf")
    )
    assert hit == target
