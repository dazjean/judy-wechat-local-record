#!/usr/bin/env python3
"""签发客户授权文件。私钥只留在实施机，不进入客户包。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from Crypto.PublicKey import ECC  # noqa: E402

from app.license import issue_license  # noqa: E402

KEY_DIR = ROOT / "packaging" / "keys"
PRIV_PATH = KEY_DIR / "ed25519.pem"
PUB_PATH = KEY_DIR / "ed25519.pub"
EMBED_PATH = BACKEND / "app" / "license_key.py"


def _ensure_keys() -> str:
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    if PRIV_PATH.is_file():
        priv = PRIV_PATH.read_text(encoding="utf-8")
        key = ECC.import_key(priv)
    else:
        key = ECC.generate(curve="Ed25519")
        priv = key.export_key(format="PEM")
        PRIV_PATH.write_text(priv, encoding="utf-8")
        print(f"已生成签发私钥 {PRIV_PATH}，请妥善保管，不要发给客户。")
    pub = key.public_key().export_key(format="PEM")
    PUB_PATH.write_text(pub, encoding="utf-8")
    embed = (
        '"""发行公钥。私钥只存在实施机 packaging/keys/ed25519.pem，不进入客户包。"""\n\n'
        f"PUBLIC_KEY_PEM = \"\"\"{pub.strip()}\n\"\"\"\n"
    )
    if EMBED_PATH.read_text(encoding="utf-8") != embed:
        EMBED_PATH.write_text(embed, encoding="utf-8")
        print(f"已更新运行时公钥 {EMBED_PATH}")
    return priv


def main() -> int:
    parser = argparse.ArgumentParser(description="签发 Judy 微信绑定授权")
    parser.add_argument("--customer", required=True, help="客户名称，仅用于展示")
    parser.add_argument("--wxid", action="append", default=[], help="绑定的系统 wxid，可重复")
    parser.add_argument("--bind-on-first-use", action="store_true", help="首次识别到的微信即永久绑定")
    parser.add_argument("--expires", default="", help="到期日 YYYY-MM-DD，可空")
    parser.add_argument("--out", default="", help="输出路径，默认 packaging/licenses/<customer>.dat")
    args = parser.parse_args()
    wxids = [x.strip() for x in args.wxid if x.strip()]
    bind_mode = "first_use" if args.bind_on_first_use else "wxid"
    if bind_mode == "wxid" and not wxids:
        print("必须用 --wxid 指定绑定的系统 wxid，或改用 --bind-on-first-use", file=sys.stderr)
        return 2
    priv = _ensure_keys()
    text = issue_license(
        customer=args.customer,
        wxids=wxids,
        private_pem=priv,
        bind_mode=bind_mode,
        expires_at=args.expires,
    )
    out = Path(args.out) if args.out else ROOT / "packaging" / "licenses" / f"{args.customer}.dat"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"已签发 {out}")
    if bind_mode == "first_use":
        print("警告：未使用前的安装包仍可被复制后首次绑定。正式交付请尽量指定 --wxid。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
