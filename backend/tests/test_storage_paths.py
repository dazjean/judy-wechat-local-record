from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import pytest

from app.storage_paths import (  # noqa: E402
    default_data_dir,
    override_source,
    reset_startup_cache,
    resolve_data_dir,
    save_data_dir,
    validate_data_dir,
)


def test_default_when_empty(tmp_path: Path):
    reset_startup_cache()
    assert resolve_data_dir(tmp_path) == tmp_path / "data"
    assert override_source(tmp_path) == "default"


def test_file_override(tmp_path: Path):
    reset_startup_cache()
    custom = tmp_path / "store"
    save_data_dir(str(custom), root=tmp_path)
    assert (tmp_path / "data-dir.txt").read_text(encoding="utf-8").strip() == str(custom.resolve())
    assert resolve_data_dir(tmp_path) == custom.resolve()
    assert override_source(tmp_path) == "file"


def test_reset_to_default_removes_file(tmp_path: Path):
    reset_startup_cache()
    save_data_dir(str(tmp_path / "store"), root=tmp_path)
    save_data_dir("", root=tmp_path)
    assert not (tmp_path / "data-dir.txt").exists()
    assert resolve_data_dir(tmp_path) == default_data_dir(tmp_path)


def test_rejects_wechat_folder(tmp_path: Path):
    reset_startup_cache()
    wechat = tmp_path / "xwechat_files" / "nxss11_c6ad"
    wechat.mkdir(parents=True)
    with pytest.raises(ValueError, match="微信"):
        validate_data_dir(str(wechat), root=tmp_path)


def test_rejects_install_root(tmp_path: Path):
    reset_startup_cache()
    with pytest.raises(ValueError, match="安装目录"):
        validate_data_dir(str(tmp_path), root=tmp_path)


def test_env_wins_over_file(tmp_path: Path, monkeypatch):
    reset_startup_cache()
    save_data_dir(str(tmp_path / "from-file"), root=tmp_path)
    env_dir = tmp_path / "from-env"
    env_dir.mkdir()
    monkeypatch.setenv("JUDY_DATA_DIR", str(env_dir))
    assert resolve_data_dir(tmp_path, env_value=str(env_dir)) == env_dir.resolve()
    assert override_source(tmp_path, env_value=str(env_dir)) == "env"
    monkeypatch.delenv("JUDY_DATA_DIR", raising=False)
