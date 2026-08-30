#!/usr/bin/env python3
"""生产打包：与灵犀商用部署包同一口径。

前端构建 + 微信授权 + Nuitka 业务模块 + Tauri Judy.app（内嵌 Python）。
客户目录不含业务源码。
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.product import EXE_NAME, PRODUCT_NAME, PRODUCT_VERSION  # noqa: E402

SOURCE_MARKERS = (".py", ".vue", ".ts", ".tsx", ".md")
KEEP_MD_NAMES = {"使用说明.md"}
STUB_MARKER = "AUTO-GENERATED DEPLOY STUB"
RUNTIME_REQUIREMENTS = BACKEND / "requirements-runtime.txt"


def _run(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(cmd))
    merged = os.environ.copy()
    if env:
        merged.update(env)
    subprocess.run(cmd, cwd=str(cwd or ROOT), check=True, env=merged)


def _py() -> str:
    venv = ROOT / ".venv" / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")
    return str(venv if venv.is_file() else sys.executable)


def _os_tag() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "darwin":
        return f"macos-{machine}"
    if system == "windows":
        return f"win-{machine}"
    return f"{system}-{machine}"


def _build_frontend() -> Path:
    npm = shutil.which("npm")
    if not npm:
        raise SystemExit("需要 npm 才能构建前端")
    frontend = ROOT / "frontend"
    if not (frontend / "node_modules").is_dir():
        _run([npm, "install"], cwd=frontend)
    _run([npm, "run", "build"], cwd=frontend)
    dist = frontend / "dist"
    if not (dist / "index.html").is_file():
        raise SystemExit("前端构建失败，没有 dist/index.html")
    return dist


def _issue_license(customer: str, wxids: list[str], first_use: bool, expires: str, dest: Path) -> None:
    cmd = [_py(), str(ROOT / "scripts" / "issue_license.py"), "--customer", customer, "--out", str(dest)]
    for wxid in wxids:
        cmd.extend(["--wxid", wxid])
    if first_use:
        cmd.append("--bind-on-first-use")
    if expires:
        cmd.extend(["--expires", expires])
    _run(cmd)


def _copy_tree(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


def _write_mac_app(out_dir: Path, name: str, bundle_id: str, body: str) -> None:
    """osacompile 小程序。Finder 不会启动以 shell 脚本为入口的 .app。"""
    app = out_dir / f"{name}.app"
    if app.exists():
        shutil.rmtree(app)
    src = out_dir / f".{bundle_id}.applescript"
    src.write_text(
        "on run\n"
        '  set sh to POSIX path of (path to me) & "Contents/Resources/run.sh"\n'
        "  try\n"
        "    do shell script quoted form of sh\n"
        "  on error errMsg\n"
        '    display dialog errMsg with title "Judy" buttons {"好"} default button "好"\n'
        "  end try\n"
        "end run\n",
        encoding="utf-8",
    )
    subprocess.run(["osacompile", "-o", str(app), str(src)], check=True)
    src.unlink(missing_ok=True)
    res = app / "Contents" / "Resources"
    res.mkdir(parents=True, exist_ok=True)
    run = res / "run.sh"
    run.write_text(
        "#!/bin/bash\n"
        "set -u\n"
        'APP="$(cd "$(dirname "$0")/../.." && pwd)"\n'
        'ROOT="$(cd "$APP/.." && pwd)"\n'
        'cd "$ROOT"\n'
        "mkdir -p logs\n" + body,
        encoding="utf-8",
    )
    run.chmod(0o755)
    plist = str(app / "Contents" / "Info.plist")
    pb = "/usr/libexec/PlistBuddy"
    subprocess.run([pb, "-c", f"Add :CFBundleIdentifier string {bundle_id}", plist], check=False)
    subprocess.run([pb, "-c", f"Set :CFBundleIdentifier {bundle_id}", plist], check=False)
    subprocess.run([pb, "-c", f"Set :CFBundleName {name}", plist], check=False)
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)], check=False)


def _payload_scripts(out_dir: Path) -> None:
    src = ROOT / "scripts" / "install.sh"
    dest = out_dir / "install.sh"
    shutil.copy2(src, dest)
    dest.chmod(0o755)
    if os.name == "nt":
        (out_dir / "启动.bat").write_text(
            '@echo off\r\ncd /d "%~dp0"\r\nstart "" "Judy.exe"\r\n',
            encoding="gbk",
        )
        return
    _write_mac_app(
        out_dir,
        "微信读取初始化",
        "local.judy.wechat-init",
        "echo 正在初始化微信读取，请保持微信已登录…\n"
        "BIN=\"\"\n"
        "for p in \\\n"
        "  Judy.app/Contents/Resources/vendor/wechat-cli \\\n"
        "  vendor/wechat-cli\n"
        "do\n"
        "  if [ -x \"$p\" ]; then BIN=\"$p\"; break; fi\n"
        "done\n"
        "if [ -z \"$BIN\" ]; then osascript -e 'display dialog \"微信读取组件未就绪，请重新安装本系统。\" with title \"Judy\" buttons {\"好\"}'; exit 1; fi\n"
        "\"$BIN\" init\n"
        "osascript -e 'display dialog \"微信读取初始化完成。请双击 Judy。\" with title \"Judy\" buttons {\"好\"}'\n",
    )


def seal_payload_into_mac_app(staging: Path) -> None:
    """把 backend / web / license 收进 Judy.app，解压根目录只留客户要看见的文件。"""
    res = staging / "Judy.app" / "Contents" / "Resources"
    res.mkdir(parents=True, exist_ok=True)
    for name in ("backend", "web"):
        src = staging / name
        dest = res / name
        if not src.is_dir():
            raise SystemExit(f"缺少 {name}，无法打进 Judy.app")
        if dest.exists():
            shutil.rmtree(dest)
        shutil.move(str(src), str(dest))
    license_src = staging / "license.dat"
    if not license_src.is_file():
        raise SystemExit("缺少 license.dat，无法打进 Judy.app")
    shutil.move(str(license_src), str(res / "license.dat"))
    for name in (".edition", ".deploy-format"):
        src = staging / name
        if src.is_file():
            shutil.move(str(src), str(res / name))
    print("已收纳 backend / web / license.dat → Judy.app")


def embed_runtime_scripts_into_mac_app(staging: Path) -> None:
    dest_dir = staging / "Judy.app" / "Contents" / "Resources" / "scripts"
    dest_dir.mkdir(parents=True, exist_ok=True)
    for name in ("start_api.sh", "stop_api.sh", "stop_all.sh"):
        src = ROOT / "scripts" / name
        dest = dest_dir / name
        shutil.copy2(src, dest)
        dest.chmod(0o755)
    print("已内嵌运行脚本 → Judy.app/Contents/Resources/scripts/")


def _reader_source() -> Path | None:
    name = "wechat-cli.exe" if os.name == "nt" else "wechat-cli"
    for cand in (ROOT / "vendor" / name,):
        if cand.is_file():
            return cand
    return None


def embed_reader_into_mac_app(staging: Path) -> None:
    src = _reader_source()
    if src is None:
        raise SystemExit("未找到 vendor/wechat-cli，无法打进 Judy.app")
    dest_dir = staging / "Judy.app" / "Contents" / "Resources" / "vendor"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    shutil.copy2(src, dest)
    dest.chmod(0o755)
    print(f"已内嵌读取组件 → Judy.app/Contents/Resources/vendor/{src.name}")


def _stage_backend(dest: Path) -> None:
    app_src = BACKEND / "app"
    app_dest = dest / "backend" / "app"
    _copy_tree(app_src, app_dest)
    for junk in app_dest.rglob("__pycache__"):
        if junk.is_dir():
            shutil.rmtree(junk, ignore_errors=True)
    shutil.copy2(RUNTIME_REQUIREMENTS, dest / "backend" / "requirements-runtime.txt")


def _nuitka_compile_app(staging: Path) -> None:
    compiler_abi_tag()
    app_dir = staging / "backend" / "app"
    if not app_dir.is_dir():
        raise SystemExit("暂存目录缺少 backend/app")
    _run([_py(), "-m", "pip", "install", "-q", "nuitka", "ordered-set", "zstandard"])
    cmd = [
        _py(),
        "-m",
        "nuitka",
        "--module",
        "--include-package=app",
        "--nofollow-import-to=fastapi",
        "--nofollow-import-to=starlette",
        "--nofollow-import-to=uvicorn",
        "--nofollow-import-to=sqlalchemy",
        "--nofollow-import-to=pydantic",
        "--nofollow-import-to=pydantic_settings",
        "--nofollow-import-to=httpx",
        "--nofollow-import-to=webview",
        "--nofollow-import-to=Crypto",
        "--nofollow-import-to=openpyxl",
        "--assume-yes-for-downloads",
        "--remove-output",
        "--output-dir=.",
        "app",
    ]
    env = {
        "PYTHONPATH": str(staging / "backend"),
        "CI": "1",
    }
    _run(cmd, cwd=staging / "backend", env=env)
    produced = list((staging / "backend").glob("app*.so")) + list((staging / "backend").glob("app*.pyd"))
    if not produced:
        inner = list(app_dir.glob("*.so")) + list(app_dir.glob("*.pyd"))
        if not inner:
            raise SystemExit("Nuitka 未产出 app 扩展模块")
    if app_dir.is_dir() and produced:
        shutil.rmtree(app_dir)
    else:
        for py in app_dir.rglob("*.py"):
            rel = py.relative_to(staging).as_posix()
            py.write_text(
                f'"""{STUB_MARKER} — {rel}"""\n',
                encoding="utf-8",
            )


def compiler_abi_tag() -> str:
    result = subprocess.run(
        [_py(), "-c", "import sys; print(f'{sys.version_info.major}{sys.version_info.minor}')"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    tag = (result.stdout or "").strip()
    if tag != "312":
        raise SystemExit(
            f"商用包须用 CPython 3.12 编译 Nuitka 以匹配内嵌 3.12.12，当前是 {_py()} ({tag})"
        )
    return tag


def parse_abi_tag_from_name(name: str) -> str | None:
    match = re.search(r"cpython-(\d+)", name, re.I)
    if match:
        return match.group(1)
    match = re.search(r"[.]cp(\d{2,3})[-.]", name, re.I)
    if match:
        return match.group(1)
    return None


def extension_module_paths(staging: Path) -> list[Path]:
    out: list[Path] = []
    for path in staging.rglob("*"):
        if not path.is_file() or path.suffix not in {".so", ".pyd"}:
            continue
        rel = path.relative_to(staging).as_posix()
        if "Contents/Resources/python/" in rel or rel.startswith("python/"):
            continue
        out.append(path)
    return out


def bundled_python_exe(staging: Path) -> Path | None:
    mac = staging / "Judy.app" / "Contents" / "Resources" / "python" / "bin" / "python3"
    if mac.is_file():
        return mac
    win = staging / "python" / "python.exe"
    if win.is_file():
        return win
    return None


def _read_python_abi(exe: Path) -> str:
    result = subprocess.run(
        [str(exe), "-c", "import sys; print(f'{sys.version_info.major}{sys.version_info.minor}')"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    tag = (result.stdout or "").strip()
    if not re.fullmatch(r"\d{2,3}", tag):
        raise SystemExit(f"无法读取解释器 ABI: {exe} -> {tag!r}")
    return tag


def verify_extension_abi(staging: Path, *, skip_nuitka: bool) -> None:
    if skip_nuitka:
        return
    mods = extension_module_paths(staging)
    if not mods:
        raise SystemExit("Nuitka 未产出业务 .so/.pyd")
    file_tags = {tag for path in mods if (tag := parse_abi_tag_from_name(path.name))}
    compiler = compiler_abi_tag()
    if file_tags and file_tags != {compiler}:
        raise SystemExit(f"Nuitka ABI {sorted(file_tags)} 与编译解释器 {compiler} 不一致")
    bundled = bundled_python_exe(staging)
    if bundled is None:
        return
    bundled_tag = _read_python_abi(bundled)
    if bundled_tag != compiler:
        raise SystemExit(f"内嵌 Python ABI {bundled_tag} 与 Nuitka 编译器 {compiler} 不一致")
    if file_tags and file_tags != {bundled_tag}:
        raise SystemExit(f"扩展模块 ABI {sorted(file_tags)} 与内嵌 Python {bundled_tag} 不一致")


def _pip_into_bundled_python(staging: Path) -> None:
    exe = bundled_python_exe(staging)
    if exe is None:
        raise SystemExit("没有内嵌 Python，无法安装运行依赖")
    req = staging / "backend" / "requirements-runtime.txt"
    _run([str(exe), "-m", "pip", "install", "-q", "-r", str(req)])


def _reuse_python_cache_env() -> dict[str, str]:
    env: dict[str, str] = {}
    lingxi = (
        Path.home()
        / ".openclaw"
        / "skills"
        / "wechat-automation"
        / "desktop"
        / "lingxi-tauri"
        / ".cache"
        / "python-standalone"
    )
    if any(lingxi.glob("*/python/bin/python3")):
        env["JUDY_PYTHON_CACHE"] = str(lingxi)
    return env


def build_mac_desktop_app(staging: Path) -> None:
    if sys.platform != "darwin":
        raise SystemExit("macos 交付包必须在 Mac 上构建 Judy.app")
    out_app = staging / "Judy.app"
    script = ROOT / "desktop" / "judy-tauri" / "build-app.sh"
    if not script.is_file():
        raise SystemExit(f"缺少 Tauri 构建脚本: {script}")
    fetch = ROOT / "desktop" / "judy-tauri" / "scripts" / "fetch-bundled-python.sh"
    env = _reuse_python_cache_env()
    env["JUDY_REQUIRE_BUNDLED_PYTHON"] = "1"
    env["LINGXI_REQUIRE_BUNDLED_PYTHON"] = "1"
    if fetch.is_file():
        print("预热内嵌 Python 缓存…")
        _run(["bash", str(fetch)], env=env)
    _run(["bash", str(script), str(out_app)], env=env)
    py = out_app / "Contents" / "Resources" / "python" / "bin" / "python3"
    if not py.is_file():
        raise SystemExit("Judy.app 缺少内嵌 Python")


def verify_mac_desktop(staging: Path) -> None:
    app = staging / "Judy.app" / "Contents" / "MacOS"
    if not app.is_dir():
        raise SystemExit("缺少 Judy.app")
    py = staging / "Judy.app" / "Contents" / "Resources" / "python" / "bin" / "python3"
    if not py.is_file() or not os.access(py, os.X_OK):
        raise SystemExit("Judy.app 内嵌 python3 不可用")


def adhoc_sign_macos_deploy(staging: Path) -> None:
    if sys.platform != "darwin":
        return
    subprocess.run(["xattr", "-cr", str(staging)], check=False)
    backends = (
        staging / "backend",
        staging / "Judy.app" / "Contents" / "Resources" / "backend",
    )
    for backend in backends:
        if not backend.is_dir():
            continue
        for so in backend.rglob("*.so"):
            subprocess.run(
                ["codesign", "--force", "--sign", "-", "--timestamp=none", str(so)],
                check=False,
                capture_output=True,
            )
    app = staging / "Judy.app"
    if not app.is_dir():
        return
    result = subprocess.run(
        ["codesign", "--force", "--deep", "--sign", "-", "--timestamp=none", str(app)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"codesign Judy.app 失败: {(result.stderr or result.stdout or '').strip()}")
    print("ad-hoc signed Judy.app")


def _forbid_source(root: Path) -> None:
    bad: list[Path] = []
    skip_dirs = {"_internal", "python"}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part.endswith(".app") or part in skip_dirs for part in path.parts):
            continue
        if path.name in KEEP_MD_NAMES:
            continue
        if path.suffix.lower() in SOURCE_MARKERS:
            text = ""
            if path.suffix.lower() == ".py":
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    text = ""
                if STUB_MARKER in text and text.count("\n") <= 12:
                    continue
            bad.append(path)
    if bad:
        preview = "\n".join(str(p.relative_to(root)) for p in bad[:20])
        raise SystemExit(f"客户包里出现源码，已中止：\n{preview}")


def _zip_dir(src: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in src.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(src.parent))
    print(f"已打包 {zip_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=f"打包 {PRODUCT_NAME} 商用部署包（Nuitka + Tauri）")
    parser.add_argument("--customer", required=True)
    parser.add_argument("--wxid", action="append", default=[], help="绑定的系统 wxid，可重复")
    parser.add_argument("--bind-on-first-use", action="store_true")
    parser.add_argument("--expires", default="")
    parser.add_argument("--skip-nuitka", action="store_true", help="不编译业务模块（不可用于客户交付）")
    parser.add_argument("--skip-desktop", action="store_true", help="不构建 Judy.app（不可用于客户交付）")
    args = parser.parse_args()
    wxids = [x.strip() for x in args.wxid if x.strip()]
    if not wxids and not args.bind_on_first_use:
        print("正式交付必须 --wxid 绑定客户微信，或显式 --bind-on-first-use", file=sys.stderr)
        return 2
    if args.skip_nuitka or args.skip_desktop:
        print("警告：跳过 Nuitka 或桌面壳的结果不能发给客户。", file=sys.stderr)

    if not RUNTIME_REQUIREMENTS.is_file():
        raise SystemExit("缺少 backend/requirements-runtime.txt")

    web = _build_frontend()
    out_root = ROOT / "dist-release"
    folder_name = f"{EXE_NAME}-{PRODUCT_VERSION}-{_os_tag()}-{args.customer}"
    dest = out_root / folder_name
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    license_path = dest / "license.dat"
    _issue_license(args.customer, wxids, args.bind_on_first_use, args.expires, license_path)

    _stage_backend(dest)
    _copy_tree(web, dest / "web")
    if _reader_source() is None:
        print("警告：未找到 vendor/wechat-cli，客户将无法做微信读取初始化。")
    shutil.copy2(ROOT / "docs" / "使用说明.md", dest / "使用说明.md")
    _payload_scripts(dest)
    (dest / "data").mkdir(exist_ok=True)
    (dest / "logs").mkdir(exist_ok=True)
    (dest / ".edition").write_text("commercial-deploy\n", encoding="utf-8")
    (dest / ".deploy-format").write_text("nuitka-module\n", encoding="utf-8")

    if not args.skip_nuitka:
        _nuitka_compile_app(dest)
    else:
        print("跳过 Nuitka，backend/app 仍是明文。")

    if sys.platform == "darwin" and not args.skip_desktop:
        build_mac_desktop_app(dest)
        verify_mac_desktop(dest)
        embed_reader_into_mac_app(dest)
        embed_runtime_scripts_into_mac_app(dest)
        _pip_into_bundled_python(dest)
    elif sys.platform == "darwin":
        print("跳过 Judy.app。")
    elif sys.platform == "win32" and not args.skip_desktop:
        print("Windows 桌面壳请在 Windows 上构建（与灵犀相同，本机 Mac 不交叉编译）。")
    if not args.skip_nuitka:
        verify_extension_abi(dest, skip_nuitka=False)
        print("Nuitka ABI 已与内嵌/编译 Python 对齐")
    if sys.platform == "darwin" and not args.skip_desktop:
        seal_payload_into_mac_app(dest)
        adhoc_sign_macos_deploy(dest)
        res = dest / "Judy.app" / "Contents" / "Resources"
        for rel in (
            "vendor/wechat-cli",
            "scripts/start_api.sh",
            "backend",
            "web/index.html",
            "license.dat",
        ):
            path = res / rel
            if not path.exists():
                raise SystemExit(f"Judy.app 内缺少 {rel}，已中止")
        for leftover in ("backend", "web", "license.dat", "scripts", "vendor", ".edition", ".deploy-format"):
            if (dest / leftover).exists():
                raise SystemExit(f"解压根目录仍有 {leftover}，应收进 Judy.app")

    if not args.skip_nuitka:
        _forbid_source(dest)
    zip_path = out_root / f"{folder_name}.zip"
    _zip_dir(dest, zip_path)
    print(f"{PRODUCT_NAME} {PRODUCT_VERSION} 客户包：{dest}")
    print("不要把源码目录、.venv、packaging/keys 发给客户。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
