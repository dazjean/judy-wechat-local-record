from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "desktop" / "shared"))

from package_root import resolve_package_root  # noqa: E402


def test_resolve_package_root_beside_app(tmp_path: Path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "web").mkdir()
    app = tmp_path / "Judy.app"
    app.mkdir()
    assert resolve_package_root(app_bundle=app) == tmp_path.resolve()


def test_resolve_package_root_env(tmp_path: Path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "web").mkdir()
    assert resolve_package_root(env_root=str(tmp_path)) == tmp_path.resolve()


def test_resolve_package_root_sealed_into_app(tmp_path: Path):
    res = tmp_path / "Judy.app" / "Contents" / "Resources"
    (res / "backend").mkdir(parents=True)
    (res / "web").mkdir()
    (tmp_path / "install.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    app = tmp_path / "Judy.app"
    assert resolve_package_root(app_bundle=app) == tmp_path.resolve()
    assert not (tmp_path / "backend").exists()
    assert not (tmp_path / "web").exists()
