from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.restart import restart_spec  # noqa: E402


def test_restart_spec_dev(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("app.restart.frozen", lambda: False)
    monkeypatch.setattr("app.restart.deployed", lambda: False)
    monkeypatch.setenv("JUDY_ROOT", str(tmp_path))
    cmd, cwd, env = restart_spec()
    assert "-m" in cmd
    assert "app.boot" in cmd
    assert "backend" in env.get("PYTHONPATH", "")
    assert cwd == str(tmp_path.resolve())


def test_restart_spec_deployed(monkeypatch, tmp_path: Path):
    script = (
        tmp_path
        / "Judy.app"
        / "Contents"
        / "Resources"
        / "scripts"
        / "start_api.sh"
    )
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/bash\n", encoding="utf-8")
    monkeypatch.setattr("app.restart.frozen", lambda: False)
    monkeypatch.setattr("app.restart.deployed", lambda: True)
    monkeypatch.setenv("JUDY_ROOT", str(tmp_path))
    cmd, cwd, env = restart_spec()
    assert cmd[0] == "bash"
    assert Path(cmd[1]) == script
    assert env.get("JUDY_DEPLOY") == "1"
    assert env.get("JUDY_RESTART") == "1"
    assert cwd == str(tmp_path.resolve())


def test_restart_spec_frozen(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("app.restart.frozen", lambda: True)
    monkeypatch.setattr("app.restart.deployed", lambda: False)
    exe = tmp_path / "Judy"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(exe))
    cmd, cwd, env = restart_spec()
    assert cmd == [str(exe.resolve())]
    assert cwd == str(tmp_path.resolve())
