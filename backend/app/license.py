"""微信绑定授权。签发用 Ed25519 私钥；运行时只验证公钥，并把首次激活封存到本机。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa

from app.license_key import PUBLIC_KEY_PEM
from app.product import PRODUCT_CODE, PRODUCT_NAME, PRODUCT_VERSION

LICENSE_MAGIC = "LXCS1"
BIND_MAGIC = "LXBIND1"
LICENSE_BLOCKED = "license_blocked"


class LicenseError(Exception):
    def __init__(self, message: str, *, code: str = LICENSE_BLOCKED):
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass(frozen=True)
class LicensePayload:
    product: str
    customer: str
    wxids: tuple[str, ...]
    bind_mode: str
    issued_at: str
    expires_at: str
    instance_id: str

    def identifiers(self) -> set[str]:
        return {_norm(x) for x in self.wxids if _norm(x)}


@dataclass
class LicenseStatus:
    ok: bool
    mode: str
    customer: str = ""
    bound_wxids: list[str] = field(default_factory=list)
    current_wxid: str = ""
    message: str = ""
    product: str = PRODUCT_NAME
    version: str = PRODUCT_VERSION
    bind_mode: str = ""
    instance_id: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "customer": self.customer,
            "bound_wxids": self.bound_wxids,
            "current_wxid": self.current_wxid,
            "message": self.message,
            "product": self.product,
            "version": self.version,
            "bind_mode": self.bind_mode,
            "instance_id": self.instance_id,
        }


def _norm(value: str) -> str:
    text = (value or "").strip().lower()
    if not text:
        return ""
    from app.ingest.media.self_account import username_from_folder

    folder = username_from_folder(text)
    return (folder or text).lower()


def _canonical(obj: dict) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def _public_key(pem: str | None = None) -> ECC.EccKey:
    return ECC.import_key((pem or PUBLIC_KEY_PEM).strip())


def _private_key(pem: str) -> ECC.EccKey:
    return ECC.import_key(pem.strip())


def sign_payload(payload: dict, private_pem: str) -> bytes:
    signer = eddsa.new(_private_key(private_pem), "rfc8032")
    return signer.sign(_canonical(payload))


def verify_payload(payload: dict, signature: bytes, public_pem: str | None = None) -> None:
    verifier = eddsa.new(_public_key(public_pem), "rfc8032")
    verifier.verify(_canonical(payload), signature)


def encode_license(payload: dict, signature: bytes) -> str:
    return f"{LICENSE_MAGIC}\n{_b64(_canonical(payload))}\n{_b64(signature)}\n"


def parse_license_text(text: str, public_pem: str | None = None) -> LicensePayload:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if len(lines) < 3 or lines[0] != LICENSE_MAGIC:
        raise LicenseError("授权文件无效")
    raw = _b64d(lines[1])
    signature = _b64d(lines[2])
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LicenseError("授权文件无效") from exc
    if _canonical(payload) != raw:
        raise LicenseError("授权文件无效")
    try:
        verify_payload(payload, signature, public_pem)
    except ValueError as exc:
        raise LicenseError("授权文件无效") from exc
    if not isinstance(payload, dict):
        raise LicenseError("授权文件无效")
    product = str(payload.get("product") or "").strip()
    if product and product != PRODUCT_CODE:
        raise LicenseError("授权与当前产品不匹配")
    wxids = payload.get("wxids") or []
    if isinstance(wxids, str):
        wxids = [wxids]
    if not isinstance(wxids, list):
        raise LicenseError("授权文件无效")
    bind_mode = str(payload.get("bind_mode") or "wxid").strip() or "wxid"
    if bind_mode not in {"wxid", "first_use"}:
        raise LicenseError("授权文件无效")
    cleaned = tuple(_norm(str(x)) for x in wxids if _norm(str(x)))
    if bind_mode == "wxid" and not cleaned:
        raise LicenseError("授权未绑定微信")
    return LicensePayload(
        product=product or PRODUCT_CODE,
        customer=str(payload.get("customer") or "").strip(),
        wxids=cleaned,
        bind_mode=bind_mode,
        issued_at=str(payload.get("issued_at") or "").strip(),
        expires_at=str(payload.get("expires_at") or "").strip(),
        instance_id=str(payload.get("instance_id") or "").strip(),
    )


def issue_license(
    *,
    customer: str,
    wxids: list[str],
    private_pem: str,
    bind_mode: str = "wxid",
    expires_at: str = "",
    instance_id: str = "",
) -> str:
    cleaned = [_norm(x) for x in wxids if _norm(x)]
    if bind_mode not in {"wxid", "first_use"}:
        raise ValueError("bind_mode 无效")
    if bind_mode == "wxid" and not cleaned:
        raise ValueError("必须指定至少一个 wxid")
    payload = {
        "product": PRODUCT_CODE,
        "customer": (customer or "").strip(),
        "wxids": cleaned,
        "bind_mode": bind_mode,
        "issued_at": date.today().isoformat(),
        "expires_at": (expires_at or "").strip(),
        "instance_id": instance_id or str(uuid4()),
    }
    return encode_license(payload, sign_payload(payload, private_pem))


def license_path() -> Path:
    from app.config import settings

    return settings.license_path


def bind_paths(payload: LicensePayload, *, license_file: Path | None = None) -> list[Path]:
    from app.config import settings

    name = f".license-bind-{payload.instance_id or 'default'}"
    if license_file:
        return [license_file.parent / name, license_file.parent / "data" / name]
    return [settings.root / name, settings.data_dir / name]


def _hmac_key(instance_id: str, public_pem: str | None = None) -> bytes:
    material = (public_pem or PUBLIC_KEY_PEM).strip().encode("utf-8")
    material += b"|" + instance_id.encode("utf-8") + b"|" + f"{PRODUCT_CODE}-bind".encode("utf-8")
    return hashlib.sha256(material).digest()


def encode_bind(payload: dict, instance_id: str, public_pem: str | None = None) -> str:
    raw = _canonical(payload)
    digest = hmac.new(_hmac_key(instance_id, public_pem), raw, hashlib.sha256).digest()
    return f"{BIND_MAGIC}\n{_b64(raw)}\n{_b64(digest)}\n"


def parse_bind_text(text: str, instance_id: str, public_pem: str | None = None) -> dict:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if len(lines) < 3 or lines[0] != BIND_MAGIC:
        raise LicenseError("本机绑定损坏")
    raw = _b64d(lines[1])
    digest = _b64d(lines[2])
    expect = hmac.new(_hmac_key(instance_id, public_pem), raw, hashlib.sha256).digest()
    if not hmac.compare_digest(digest, expect):
        raise LicenseError("本机绑定损坏")
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise LicenseError("本机绑定损坏")
    return data


def read_bind(
    payload: LicensePayload,
    public_pem: str | None = None,
    *,
    license_file: Path | None = None,
) -> dict | None:
    for path in bind_paths(payload, license_file=license_file):
        if not path.is_file():
            continue
        try:
            data = parse_bind_text(path.read_text(encoding="utf-8"), payload.instance_id, public_pem)
        except (OSError, LicenseError, json.JSONDecodeError, ValueError):
            continue
        if data:
            return data
    return None


def write_bind(
    payload: LicensePayload,
    wxids: list[str],
    public_pem: str | None = None,
    *,
    license_file: Path | None = None,
) -> None:
    from app.config import settings

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    body = encode_bind(
        {
            "wxids": [_norm(x) for x in wxids if _norm(x)],
            "bound_at": datetime.now().isoformat(timespec="seconds"),
            "instance_id": payload.instance_id,
        },
        payload.instance_id,
        public_pem,
    )
    for path in bind_paths(payload, license_file=license_file):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        except OSError:
            continue


def load_payload(path: Path | None = None, public_pem: str | None = None) -> LicensePayload:
    target = path or license_path()
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise LicenseError("未找到授权文件") from exc
    return parse_license_text(text, public_pem)


def _expired(expires_at: str) -> bool:
    text = (expires_at or "").strip()
    if not text:
        return False
    try:
        return date.fromisoformat(text[:10]) < date.today()
    except ValueError:
        return True


def profile_ids(username: str = "") -> set[str]:
    ident = _norm(username)
    return {ident} if ident else set()


def development_mode() -> bool:
    if os.environ.get("LINGXI_LICENSE_SKIP") == "1":
        return True
    from app.config import frozen

    if frozen():
        return False
    return not license_path().is_file()


def evaluate(
    *,
    username: str = "",
    path: Path | None = None,
    public_pem: str | None = None,
    persist_bind: bool = True,
) -> LicenseStatus:
    if development_mode() and path is None:
        return LicenseStatus(
            ok=True,
            mode="development",
            message="开发模式，未启用授权校验",
        )
    try:
        payload = load_payload(path, public_pem)
    except LicenseError as exc:
        return LicenseStatus(ok=False, mode="missing" if "未找到" in exc.message else "invalid", message=exc.message)
    if _expired(payload.expires_at):
        return LicenseStatus(
            ok=False,
            mode="expired",
            customer=payload.customer,
            message="授权已过期，请联系实施人员续期",
            bind_mode=payload.bind_mode,
            instance_id=payload.instance_id,
        )
    bound = set(payload.identifiers())
    license_file = path or license_path()
    seal = read_bind(payload, public_pem, license_file=license_file)
    if seal:
        bound |= {_norm(x) for x in (seal.get("wxids") or []) if _norm(str(x))}
    current = profile_ids(username)
    current_label = _norm(username)
    if payload.bind_mode == "first_use" and not bound:
        if not current:
            return LicenseStatus(
                ok=False,
                mode="pending_wechat",
                customer=payload.customer,
                current_wxid=current_label,
                message="请使用本机微信完成读取初始化，系统将绑定当前微信系统号",
                bind_mode=payload.bind_mode,
                instance_id=payload.instance_id,
            )
        if persist_bind:
            write_bind(payload, sorted(current), public_pem, license_file=license_file)
        return LicenseStatus(
            ok=True,
            mode="licensed",
            customer=payload.customer,
            bound_wxids=sorted(current),
            current_wxid=current_label,
            message="已绑定当前微信",
            bind_mode=payload.bind_mode,
            instance_id=payload.instance_id,
        )
    if not current:
        return LicenseStatus(
            ok=False,
            mode="pending_wechat",
            customer=payload.customer,
            bound_wxids=sorted(bound),
            message="请登录授权的微信并完成读取初始化",
            bind_mode=payload.bind_mode,
            instance_id=payload.instance_id,
        )
    if current & bound:
        return LicenseStatus(
            ok=True,
            mode="licensed",
            customer=payload.customer,
            bound_wxids=sorted(bound),
            current_wxid=current_label,
            message="授权有效",
            bind_mode=payload.bind_mode,
            instance_id=payload.instance_id,
        )
    return LicenseStatus(
        ok=False,
        mode="mismatch",
        customer=payload.customer,
        bound_wxids=sorted(bound),
        current_wxid=current_label,
        message="本套软件已绑定其他微信，无法复制给其他人使用",
        bind_mode=payload.bind_mode,
        instance_id=payload.instance_id,
    )


def current_status(username: str = "") -> LicenseStatus:
    return evaluate(username=username)


def runtime_wxid() -> str:
    try:
        from app.ingest.media.self_account import current_folder_wxid

        return current_folder_wxid()
    except Exception:
        return ""


def status_from_runtime() -> LicenseStatus:
    return current_status(runtime_wxid())


def require_license(username: str = "") -> LicenseStatus:
    status = current_status(username) if username else status_from_runtime()
    if not status.ok:
        raise LicenseError(status.message)
    return status
