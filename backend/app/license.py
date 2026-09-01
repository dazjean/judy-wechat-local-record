"""微信绑定授权。签发用 Ed25519 私钥；运行时只验证公钥，并把首次激活封存到本机。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
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
LICENSE_KINDS = ("trial", "paid")
DEFAULT_TRIAL_DAYS = 7


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
    kind: str = "paid"

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
    expires_at: str = ""
    kind: str = ""
    trial_ends_on: str = ""

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
            "expires_at": self.expires_at,
            "kind": self.kind,
            "trial_ends_on": self.trial_ends_on,
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


def normalize_license_kind(kind: str) -> str:
    k = (kind or "").strip().lower()
    return k if k in LICENSE_KINDS else "paid"


def trial_expires_on(days: int = DEFAULT_TRIAL_DAYS, *, today: date | None = None) -> str:
    """到期日 = 签发日 + N 天；到期当天仍可用。"""
    try:
        n = int(days)
    except (TypeError, ValueError):
        n = DEFAULT_TRIAL_DAYS
    n = max(1, n)
    clock = today or date.today()
    return (clock + timedelta(days=n)).isoformat()


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
        kind=normalize_license_kind(str(payload.get("kind") or "")),
    )


def issue_license(
    *,
    customer: str,
    wxids: list[str],
    private_pem: str,
    bind_mode: str = "wxid",
    expires_at: str = "",
    instance_id: str = "",
    kind: str = "paid",
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
        "kind": normalize_license_kind(kind),
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


def _expired(expires_at: str, today: date | None = None) -> bool:
    parsed = _parse_iso_date(expires_at)
    if parsed is None:
        return bool((expires_at or "").strip())
    return parsed < (today or date.today())


def _parse_iso_date(text: str) -> date | None:
    raw = (text or "").strip()[:10]
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _app_support_dir() -> Path:
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "Judy"
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(home / "AppData" / "Roaming")
        return Path(base) / "Judy"
    return home / ".local" / "share" / "judy"


def trial_clock_paths() -> list[Path]:
    override = (os.environ.get("JUDY_LICENSE_CLOCK_DIR") or "").strip()
    if override:
        root = Path(override).expanduser()
        return [root / "clock.json", root / "clock.bak.json"]
    try:
        from app.config import settings

        data = settings.data_dir / ".license_clock.json"
    except Exception:
        data = Path(".license_clock.json")
    return [data, _app_support_dir() / "license_clock.json"]


def _read_clock_file(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _merge_trial_record(instance_id: str) -> dict[str, str]:
    first: date | None = None
    last: date | None = None
    for path in trial_clock_paths():
        records = _read_clock_file(path).get("records")
        if not isinstance(records, dict):
            continue
        rec = records.get(instance_id)
        if not isinstance(rec, dict):
            continue
        fs = _parse_iso_date(str(rec.get("first_seen") or ""))
        ls = _parse_iso_date(str(rec.get("last_seen") or ""))
        if fs and (first is None or fs < first):
            first = fs
        if ls and (last is None or ls > last):
            last = ls
    out: dict[str, str] = {}
    if first:
        out["first_seen"] = first.isoformat()
    if last:
        out["last_seen"] = last.isoformat()
    return out


def _write_trial_record(instance_id: str, first_seen: str, last_seen: str) -> None:
    patch = {"first_seen": first_seen, "last_seen": last_seen}
    for path in trial_clock_paths():
        try:
            data = _read_clock_file(path)
            records = data.get("records")
            if not isinstance(records, dict):
                records = {}
            records[instance_id] = patch
            data["records"] = records
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        except OSError:
            continue


def _trial_duration_days(payload: LicensePayload) -> int:
    issued = _parse_iso_date(payload.issued_at)
    expires = _parse_iso_date(payload.expires_at)
    if issued and expires:
        return max(1, (expires - issued).days)
    return DEFAULT_TRIAL_DAYS


def trial_end_date(payload: LicensePayload, today: date | None = None) -> str:
    """试用结束日：日历到期与首次打开窗口取较早；当天仍可用。"""
    if payload.kind != "trial":
        return ""
    clock = today or date.today()
    expires = _parse_iso_date(payload.expires_at)
    rec = _merge_trial_record(payload.instance_id) if payload.instance_id else {}
    first = _parse_iso_date(rec.get("first_seen") or "") or clock
    ends = first + timedelta(days=_trial_duration_days(payload))
    if expires and expires < ends:
        ends = expires
    return ends.isoformat()


def trial_clock_blocked(payload: LicensePayload, today: date | None = None) -> bool:
    """试用：拨回系统日期、或超过首次打开后的窗口 → 结束。"""
    if payload.kind != "trial":
        return False
    clock = today or date.today()
    issued = _parse_iso_date(payload.issued_at)
    if issued and clock < issued:
        return True
    instance_id = (payload.instance_id or "").strip()
    rec = _merge_trial_record(instance_id) if instance_id else {}
    first = _parse_iso_date(rec.get("first_seen") or "")
    last = _parse_iso_date(rec.get("last_seen") or "")
    if last and clock < last:
        return True
    if first and clock < first:
        return True
    if first is None:
        first = clock
    last_seen = last if last and last > clock else clock
    end = first + timedelta(days=_trial_duration_days(payload))
    if clock > end:
        return True
    if instance_id:
        _write_trial_record(instance_id, first.isoformat(), last_seen.isoformat())
    return False


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
    today: date | None = None,
) -> LicenseStatus:
    clock = today or date.today()
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
    trial = payload.kind == "trial"
    clock_blocked = trial_clock_blocked(payload, clock)
    calendar_expired = _expired(payload.expires_at, clock)
    trial_ends = trial_end_date(payload, clock)
    extra = dict(
        bind_mode=payload.bind_mode,
        instance_id=payload.instance_id,
        expires_at=payload.expires_at,
        kind=payload.kind,
        trial_ends_on=trial_ends,
    )
    if clock_blocked or calendar_expired:
        return LicenseStatus(
            ok=False,
            mode="expired",
            customer=payload.customer,
            message="试用已结束，付款后可继续使用" if trial else "授权已过期，请联系实施人员续期",
            **extra,
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
                **extra,
            )
        if persist_bind:
            write_bind(payload, sorted(current), public_pem, license_file=license_file)
        return LicenseStatus(
            ok=True,
            mode="licensed",
            customer=payload.customer,
            bound_wxids=sorted(current),
            current_wxid=current_label,
            message="试用有效" if trial else "已绑定当前微信",
            **extra,
        )
    if not current:
        return LicenseStatus(
            ok=False,
            mode="pending_wechat",
            customer=payload.customer,
            bound_wxids=sorted(bound),
            message="请登录授权的微信并完成读取初始化",
            **extra,
        )
    if current & bound:
        return LicenseStatus(
            ok=True,
            mode="licensed",
            customer=payload.customer,
            bound_wxids=sorted(bound),
            current_wxid=current_label,
            message="试用有效" if trial else "授权有效",
            **extra,
        )
    return LicenseStatus(
        ok=False,
        mode="mismatch",
        customer=payload.customer,
        bound_wxids=sorted(bound),
        current_wxid=current_label,
        message="本套软件已绑定其他微信，无法复制给其他人使用",
        **extra,
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
