from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time

import httpx
import uvicorn

from app.config import settings
from app.main import app
from app.product import PRODUCT_NAME, PRODUCT_TAGLINE, PRODUCT_VERSION


def _alert(message: str) -> None:
    if sys.platform != "darwin":
        print(message)
        return
    script = f'display dialog "{message}" with title "Judy" buttons {{"好"}} default button "好"'
    subprocess.run(["osascript", "-e", script], check=False)


def _wechat_init() -> None:
    from app.ingest.wechat_cli.runner import resolve_reader_bin

    bin_path = resolve_reader_bin()
    if not bin_path:
        _alert("微信读取组件未就绪，请重新安装本系统。")
        raise SystemExit(1)
    result = subprocess.run([str(bin_path), "init"])
    if result.returncode == 0:
        _alert("微信读取初始化完成。请双击 Judy。")
        return
    _alert("尚未完成微信读取初始化，或当前微信版本不兼容。")
    raise SystemExit(result.returncode or 1)


def _port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((host, port)) == 0


def _wait_health(url: str, tries: int = 80) -> bool:
    health = url.rstrip("/") + "/api/health"
    for _ in range(tries):
        try:
            response = httpx.get(health, timeout=0.4)
            if response.status_code < 500:
                return True
        except Exception:
            time.sleep(0.1)
    return False


def _start_server(host: str, port: int) -> None:
    uvicorn.run(app, host=host, port=port, log_level="warning")


def _run_desktop(url: str) -> None:
    import webview

    try:
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False
    except Exception:
        pass
    window = webview.create_window(
        f"{PRODUCT_NAME} · {PRODUCT_TAGLINE}",
        url,
        width=1400,
        height=900,
        min_size=(960, 640),
        text_select=True,
    )

    def _closed() -> None:
        os._exit(0)

    try:
        window.events.closed += _closed
    except Exception:
        pass
    webview.start()
    os._exit(0)


def main() -> int:
    if "--wechat-init" in sys.argv:
        _wechat_init()
        return 0

    host = settings.app_host
    port = int(settings.app_port)
    url = f"http://{host}:{port}"
    owned = False
    if not _port_open(host, port):
        threading.Thread(target=_start_server, args=(host, port), daemon=True).start()
        owned = True
    if not _wait_health(url):
        _alert("Judy 未能启动本机服务，请先退出 Judy 后再打开。")
        raise SystemExit(1)
    print(f"{PRODUCT_NAME} {PRODUCT_VERSION}  {url}")
    if os.environ.get("JUDY_NO_WINDOW") == "1":
        if owned:
            threading.Event().wait()
        return 0
    _run_desktop(url)
    return 0


if __name__ == "__main__":
    main()
