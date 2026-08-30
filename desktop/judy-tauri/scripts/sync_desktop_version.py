#!/usr/bin/env python3
"""把仓库根 VERSION 写入 Tauri / Cargo / npm，供 Info.plist 与 exe 属性在构建时对齐。"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
_CARGO_PKG_VERSION = re.compile(
    r'(?m)^(?P<pre>version\s*=\s*")(?P<ver>[^"]*)(?P<post>"[^\n]*)'
)


def desktop_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def repo_root() -> Path:
    return desktop_dir().parent.parent


def read_semver(version_file: Path) -> str:
    raw = version_file.read_text(encoding="utf-8").strip()
    if raw.startswith("v"):
        raw = raw[1:]
    if not _SEMVER.fullmatch(raw):
        raise RuntimeError(f"VERSION 非法（期望 x.y.z）: {raw!r}")
    return raw


_JSON_VERSION = re.compile(r'("version"\s*:\s*")[^"]*(")')


def stamp_json_version(text: str, version: str) -> str:
    data = json.loads(text)
    if not isinstance(data, dict) or "version" not in data:
        raise RuntimeError("JSON 根对象缺少 version")
    new, n = _JSON_VERSION.subn(rf"\g<1>{version}\g<2>", text, count=1)
    if n != 1:
        raise RuntimeError("JSON 未找到 version 字段")
    return new


def stamp_cargo_toml(text: str, version: str) -> str:
    lines = text.splitlines(keepends=True)
    in_package = False
    replaced = False
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_package = stripped == "[package]"
        if in_package and not replaced:
            m = _CARGO_PKG_VERSION.match(line)
            if m:
                newline = "\n" if line.endswith("\n") else ""
                line = f'{m.group("pre")}{version}{m.group("post")}' + newline
                replaced = True
        out.append(line)
    if not replaced:
        raise RuntimeError("Cargo.toml 未找到 [package] version")
    return "".join(out)


def apply_version(tauri_dir: Path, version: str) -> list[Path]:
    targets = [
        (tauri_dir / "package.json", stamp_json_version),
        (tauri_dir / "src-tauri" / "tauri.conf.json", stamp_json_version),
        (tauri_dir / "src-tauri" / "Cargo.toml", stamp_cargo_toml),
    ]
    written: list[Path] = []
    for path, stamp in targets:
        if not path.is_file():
            raise RuntimeError(f"缺少 {path}")
        new = stamp(path.read_text(encoding="utf-8"), version)
        if new != path.read_text(encoding="utf-8"):
            path.write_text(new, encoding="utf-8")
        written.append(path)
    return written


def sync(root: Path | None = None, tauri_dir: Path | None = None) -> str:
    root = (root or repo_root()).resolve()
    tauri_dir = (tauri_dir or desktop_dir()).resolve()
    version = read_semver(root / "VERSION")
    apply_version(tauri_dir, version)
    return version


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    root = None
    tauri = None
    i = 0
    while i < len(argv):
        if argv[i] == "--root" and i + 1 < len(argv):
            root = Path(argv[i + 1])
            i += 2
            continue
        if argv[i] == "--tauri-dir" and i + 1 < len(argv):
            tauri = Path(argv[i + 1])
            i += 2
            continue
        print(f"未知参数: {argv[i]}", file=sys.stderr)
        return 2
    version = sync(root=root, tauri_dir=tauri)
    print(f"desktop version ← {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
