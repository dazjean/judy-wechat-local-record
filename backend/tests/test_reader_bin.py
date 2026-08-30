from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.config import bundled_vendor_dirs  # noqa: E402
from app.ingest.wechat_cli.runner import resolve_reader_bin  # noqa: E402


def test_bundled_vendor_inside_judy_app(monkeypatch, tmp_path: Path):
    vendor = tmp_path / "Judy.app" / "Contents" / "Resources" / "vendor"
    vendor.mkdir(parents=True)
    (vendor / "wechat-cli").write_text("", encoding="utf-8")
    py = tmp_path / "Judy.app" / "Contents" / "Resources" / "python" / "bin" / "python3"
    py.parent.mkdir(parents=True)
    py.write_text("", encoding="utf-8")
    monkeypatch.setenv("JUDY_ROOT", str(tmp_path))
    monkeypatch.setattr(sys, "executable", str(py))
    dirs = bundled_vendor_dirs()
    assert vendor in dirs or vendor.resolve() in dirs


def test_resolve_reader_prefers_app_bundle(monkeypatch, tmp_path: Path):
    vendor = tmp_path / "Judy.app" / "Contents" / "Resources" / "vendor"
    vendor.mkdir(parents=True)
    bin_path = vendor / "wechat-cli"
    bin_path.write_text("", encoding="utf-8")
    py = tmp_path / "Judy.app" / "Contents" / "Resources" / "python" / "bin" / "python3"
    py.parent.mkdir(parents=True)
    py.write_text("", encoding="utf-8")
    visible = tmp_path / "vendor"
    visible.mkdir()
    (visible / "wechat-cli").write_text("no", encoding="utf-8")
    monkeypatch.setenv("JUDY_ROOT", str(tmp_path))
    monkeypatch.setattr(sys, "executable", str(py))
    found = resolve_reader_bin()
    assert found == bin_path
