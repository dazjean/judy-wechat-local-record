from __future__ import annotations

import os
import sys
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def deployed() -> bool:
    if os.environ.get("JUDY_DEPLOY") == "1":
        return True
    exe = Path(sys.executable).resolve()
    return any(parent.suffix == ".app" and parent.name.startswith("Judy") for parent in exe.parents)


def _env_root() -> Path | None:
    raw = (os.environ.get("JUDY_ROOT") or os.environ.get("SKILL_ROOT") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    try:
        return path.resolve()
    except OSError:
        return path


def _root_from_app_bundle() -> Path | None:
    exe = Path(sys.executable).resolve()
    for parent in exe.parents:
        if parent.suffix == ".app":
            return parent.parent
    return None


def _root_from_file() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if parent.suffix == ".app":
            return parent.parent
    if here.suffix.lower() in {".so", ".pyd"}:
        if here.parent.name == "backend":
            return here.parent.parent
        return here.parent
    return here.parents[2]


def project_root() -> Path:
    env = _env_root()
    if env is not None:
        return env
    bundled = _root_from_app_bundle()
    if bundled is not None:
        return bundled
    if frozen():
        exe = Path(sys.executable).resolve()
        for parent in exe.parents:
            if parent.suffix == ".app":
                return parent.parent
        return exe.parent
    return _root_from_file()


def bundle_root() -> Path:
    if frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return project_root()


def _first_dir(*candidates: Path) -> Path:
    for path in candidates:
        if path.is_dir():
            return path
    return candidates[0]


def bundled_vendor_dirs() -> list[Path]:
    """交付包里读取组件在 Judy.app/Contents/Resources/vendor/，开发机才用仓库 vendor/。"""
    dirs: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        if path in seen:
            return
        seen.add(path)
        dirs.append(path)

    exe = Path(sys.executable).resolve()
    for parent in exe.parents:
        if parent.suffix == ".app":
            add(parent / "Contents" / "Resources" / "vendor")
        if parent.name == "Resources":
            add(parent / "vendor")
    root = project_root()
    add(root / "Judy.app" / "Contents" / "Resources" / "vendor")
    add(root / "vendor")
    add(bundle_root() / "vendor")
    return dirs


def app_resources() -> Path | None:
    exe = Path(sys.executable).resolve()
    for parent in exe.parents:
        if parent.suffix == ".app":
            res = parent / "Contents" / "Resources"
            return res if res.is_dir() else None
    if not deployed():
        return None
    root = project_root()
    res = root / "Judy.app" / "Contents" / "Resources"
    return res if res.is_dir() else None


def runtime_backend() -> Path:
    res = app_resources()
    if res is not None and (res / "backend").is_dir():
        return res / "backend"
    return project_root() / "backend"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(project_root() / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=(),
    )

    app_host: str = "127.0.0.1"
    app_port: int = 8090
    model_base_url: str = ""
    model_name: str = ""
    model_api_key: str = ""
    timeout_seconds: int = 180
    session_gap_hours: int = 12
    sync_include_groups: bool = False
    sync_exclude_names: str = ""
    sync_include_names: str = ""
    sync_limit_people_enabled: bool = True
    sync_limit_people: int = 20
    sync_limit_per_contact: int = 1000
    sync_limit_per_group: int = 1000
    sync_limit_covered: int = 1000
    sync_limit_group_covered: int = 1000
    sync_days: int = 14
    sync_auto_enabled: bool = False
    sync_auto_minutes: int = 15
    sync_watch_enabled: bool = False
    sync_covered_from: str = ""

    judy_data_dir: str = ""

    @property
    def root(self) -> Path:
        return project_root()

    @property
    def data_dir(self) -> Path:
        from app.storage_paths import startup_data_dir

        return startup_data_dir(env_value=self.judy_data_dir)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "lingxi.db"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def exports_dir(self) -> Path:
        return self.root / "exports"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def media_cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def vendor_dir(self) -> Path:
        return _first_dir(*bundled_vendor_dirs())

    @property
    def frontend_dist(self) -> Path:
        res = app_resources()
        bundled_web = (res / "web") if res is not None else self.root / "web"
        return _first_dir(
            bundled_web,
            self.root / "web",
            bundle_root() / "web",
            self.root / "frontend" / "dist",
            bundle_root() / "frontend" / "dist",
        )

    @property
    def license_path(self) -> Path:
        override = self.root / "license.dat"
        if override.is_file():
            return override
        res = app_resources()
        if res is not None:
            bundled = res / "license.dat"
            if bundled.is_file():
                return bundled
        return self.root / "license.dat"


settings = Settings()
