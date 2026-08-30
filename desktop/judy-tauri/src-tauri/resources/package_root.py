#!/usr/bin/env python3
"""Resolve the unzipped Judy package root for Judy.app (same idea as 灵犀 SKILL_ROOT).

Priority:
  1. JUDY_ROOT / SKILL_ROOT environment variable
  2. JUDY_ROOT marker file beside the .app (one line, absolute path)
  3. Parent of the .app, then walk upward
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

MARKER_NAME = "JUDY_ROOT"


def _looks_like_package_root(path: Path) -> bool:
    if not path.is_dir():
        return False
    app = path / "Judy.app"
    if app.is_dir():
        res = app / "Contents" / "Resources"
        if (res / "backend").is_dir() and (res / "web").is_dir():
            return True
        if (path / "install.sh").is_file() or (path / "使用说明.md").is_file():
            return True
    return (path / "backend").is_dir() and (
        (path / "web").is_dir() or (path / "frontend").is_dir()
    )


def _app_bundle_candidates(bundle: Path) -> list[Path]:
    bundle = bundle.expanduser().resolve()
    candidates: list[Path] = []
    seen: set[Path] = set()

    def add(raw: Path) -> None:
        key = raw.expanduser()
        if key in seen:
            return
        seen.add(key)
        candidates.append(key)

    marker = bundle.parent / MARKER_NAME
    if marker.is_file():
        line = marker.read_text(encoding="utf-8").strip().splitlines()[0].strip()
        if line:
            add(Path(line))

    add(bundle)
    current = bundle.parent
    for _ in range(24):
        add(current)
        if current.parent == current:
            break
        current = current.parent
    return candidates


def resolve_package_root(
    *,
    env_root: str | None = None,
    app_bundle: Path | None = None,
) -> Path:
    candidates: list[Path] = []
    if env_root:
        candidates.append(Path(env_root).expanduser())
    if app_bundle is not None:
        candidates.extend(_app_bundle_candidates(app_bundle))

    for raw in candidates:
        path = raw.resolve()
        if _looks_like_package_root(path):
            return path

    tried = ", ".join(str(p) for p in candidates) or "(none)"
    raise FileNotFoundError(
        f"无法定位 Judy 安装目录（需含 Judy.app）。已尝试: {tried}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resolve package root for Judy.app")
    parser.add_argument("--app-bundle", type=Path, default=None)
    parser.add_argument("--print", action="store_true")
    args = parser.parse_args(argv)
    env_root = os.environ.get("JUDY_ROOT") or os.environ.get("SKILL_ROOT")
    try:
        root = resolve_package_root(env_root=env_root, app_bundle=args.app_bundle)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1
    if args.print:
        print(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
