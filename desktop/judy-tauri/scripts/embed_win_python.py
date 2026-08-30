#!/usr/bin/env python3
"""Download python-build-standalone (Windows) into <dest>/python/python.exe.

Used by O36-Win portable zip (exe 同级 python\\). Same release tag as Mac fetch script.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

RELEASE_TAG = os.environ.get("LINGXI_PYTHON_RELEASE", "20251010")
PY_VER = os.environ.get("LINGXI_PYTHON_VERSION", "3.12.12")
TRIPLE = "x86_64-pc-windows-msvc"
ASSET = f"cpython-{PY_VER}+{RELEASE_TAG}-{TRIPLE}-install_only_stripped.tar.gz"
URL = (
    "https://github.com/astral-sh/python-build-standalone/releases/download/"
    f"{RELEASE_TAG}/{ASSET}"
)


def cache_dir() -> Path:
    override = os.environ.get("LINGXI_PYTHON_CACHE")
    if override:
        return Path(override)
    here = Path(__file__).resolve().parent.parent
    return here / ".cache" / "python-standalone"


def ensure_cached_windows_python() -> Path:
    """Return extracted prefix containing python/python.exe."""
    cache = cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    tarball = cache / ASSET
    extracted = cache / f"{TRIPLE}-{PY_VER}"
    exe = extracted / "python" / "python.exe"
    if exe.is_file():
        return extracted / "python"
    if not tarball.is_file():
        print(f"📥 download {ASSET} …")
        partial = tarball.with_suffix(tarball.suffix + ".partial")
        urllib.request.urlretrieve(URL, partial)
        partial.replace(tarball)
    if extracted.exists():
        shutil.rmtree(extracted)
    extracted.mkdir(parents=True)
    print(f"📦 extract {tarball} …")
    with tarfile.open(tarball, "r:gz") as tf:
        tf.extractall(extracted)
    if not exe.is_file():
        raise RuntimeError(f"extract missing {exe}")
    return extracted / "python"


def embed_into_zip_root(dest_root: Path) -> Path:
    src = ensure_cached_windows_python()
    dest = Path(dest_root) / "python"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    exe = dest / "python.exe"
    if not exe.is_file():
        raise RuntimeError(f"embed missing {exe}")
    if sys.platform == "win32":
        subprocess.run(
            [str(exe), "-m", "pip", "install", "--quiet", "zstandard"],
            check=True,
        )
    print(f"✅ windows python → {exe}")
    return exe


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dest_root", type=Path, help="zip/staging root (writes python/)")
    args = parser.parse_args(argv)
    embed_into_zip_root(args.dest_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
