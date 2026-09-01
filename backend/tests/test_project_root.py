from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.config import Settings, project_root  # noqa: E402


def test_project_root_inside_app_bundle(monkeypatch, tmp_path: Path):
    macos = tmp_path / "Judy.app" / "Contents" / "MacOS"
    macos.mkdir(parents=True)
    exe = macos / "Judy"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr("app.config.frozen", lambda: True)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.delenv("JUDY_ROOT", raising=False)
    monkeypatch.delenv("SKILL_ROOT", raising=False)
    assert project_root() == tmp_path


def test_project_root_bundled_python(monkeypatch, tmp_path: Path):
    py = tmp_path / "Judy.app" / "Contents" / "Resources" / "python" / "bin" / "python3"
    py.parent.mkdir(parents=True)
    py.write_text("", encoding="utf-8")
    monkeypatch.setattr("app.config.frozen", lambda: False)
    monkeypatch.setattr(sys, "executable", str(py))
    monkeypatch.delenv("JUDY_ROOT", raising=False)
    monkeypatch.delenv("SKILL_ROOT", raising=False)
    assert project_root() == tmp_path


def test_project_root_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("JUDY_ROOT", str(tmp_path))
    monkeypatch.setattr("app.config.frozen", lambda: False)
    assert project_root() == tmp_path.resolve()


def test_license_and_web_inside_app(monkeypatch, tmp_path: Path):
    res = tmp_path / "Judy.app" / "Contents" / "Resources"
    (res / "web").mkdir(parents=True)
    (res / "web" / "index.html").write_text("ok", encoding="utf-8")
    (res / "license.dat").write_text("lic", encoding="utf-8")
    py = res / "python" / "bin" / "python3"
    py.parent.mkdir(parents=True)
    py.write_text("", encoding="utf-8")
    monkeypatch.setenv("JUDY_ROOT", str(tmp_path))
    monkeypatch.setattr("app.config.frozen", lambda: False)
    monkeypatch.setattr(sys, "executable", str(py))
    settings = Settings()
    assert settings.license_path == res / "license.dat"
    assert settings.frontend_dist == res / "web"


def test_source_python_ignores_sibling_app_license(monkeypatch, tmp_path: Path):
    res = tmp_path / "Judy.app" / "Contents" / "Resources"
    (res / "web").mkdir(parents=True)
    (res / "license.dat").write_text("lic", encoding="utf-8")
    py = tmp_path / ".venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text("", encoding="utf-8")
    monkeypatch.setenv("JUDY_ROOT", str(tmp_path))
    monkeypatch.delenv("JUDY_DEPLOY", raising=False)
    monkeypatch.setattr("app.config.frozen", lambda: False)
    monkeypatch.setattr(sys, "executable", str(py))
    settings = Settings()
    assert settings.license_path == tmp_path / "license.dat"
    assert not settings.license_path.is_file()


def test_project_root_onedir(monkeypatch, tmp_path: Path):
    exe = tmp_path / "Judy"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr("app.config.frozen", lambda: True)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.delenv("JUDY_ROOT", raising=False)
    monkeypatch.delenv("SKILL_ROOT", raising=False)
    assert project_root() == tmp_path
