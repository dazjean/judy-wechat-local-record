from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from Crypto.PublicKey import ECC  # noqa: E402

from app.license import (  # noqa: E402
    evaluate,
    issue_license,
    parse_license_text,
)


def _keys():
    key = ECC.generate(curve="Ed25519")
    return key.export_key(format="PEM"), key.public_key().export_key(format="PEM")


def test_signed_license_matches_wxid(tmp_path: Path):
    priv, pub = _keys()
    text = issue_license(customer="庆总", wxids=["wxid_Alpha"], private_pem=priv)
    path = tmp_path / "license.dat"
    path.write_text(text, encoding="utf-8")
    payload = parse_license_text(text, pub)
    assert payload.customer == "庆总"
    assert "wxid_alpha" in payload.identifiers()
    status = evaluate(username="wxid_Alpha", path=path, public_pem=pub)
    assert status.ok
    assert status.mode == "licensed"


def test_folder_style_wxid_strips_device_suffix(tmp_path: Path):
    priv, pub = _keys()
    text = issue_license(customer="庆总", wxids=["wxid_ownerabc123_00de"], private_pem=priv)
    path = tmp_path / "license.dat"
    path.write_text(text, encoding="utf-8")
    payload = parse_license_text(text, pub)
    assert payload.identifiers() == {"wxid_ownerabc123"}
    status = evaluate(username="wxid_ownerabc123", path=path, public_pem=pub)
    assert status.ok


def test_folder_name_matches_license(tmp_path: Path):
    priv, pub = _keys()
    text = issue_license(customer="庆总", wxids=["nxss11_c6ad"], private_pem=priv)
    path = tmp_path / "license.dat"
    path.write_text(text, encoding="utf-8")
    status = evaluate(username="nxss11_c6ad", path=path, public_pem=pub)
    assert status.ok
    assert status.current_wxid == "nxss11_c6ad"


def test_custom_alias_does_not_match_license(tmp_path: Path):
    priv, pub = _keys()
    text = issue_license(customer="庆总", wxids=["my-shop"], private_pem=priv)
    path = tmp_path / "license.dat"
    path.write_text(text, encoding="utf-8")
    status = evaluate(username="wxid_other", path=path, public_pem=pub)
    assert not status.ok
    assert status.mode == "mismatch"


def test_copied_package_rejects_other_wechat(tmp_path: Path):
    priv, pub = _keys()
    text = issue_license(customer="庆总", wxids=["wxid_owner"], private_pem=priv)
    path = tmp_path / "license.dat"
    path.write_text(text, encoding="utf-8")
    status = evaluate(username="wxid_reseller", path=path, public_pem=pub)
    assert not status.ok
    assert status.mode == "mismatch"


def test_tampered_payload_is_rejected():
    import base64
    import json

    priv, pub = _keys()
    text = issue_license(customer="庆总", wxids=["wxid_owner"], private_pem=priv)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    payload = json.loads(base64.b64decode(lines[1]))
    payload["wxids"] = ["wxid_thief"]
    lines[1] = base64.b64encode(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).decode("ascii")
    tampered = "\n".join(lines) + "\n"
    try:
        parse_license_text(tampered, pub)
        raise AssertionError("tampered license should not parse")
    except Exception as exc:
        assert "无效" in str(exc)


def test_expired_license(tmp_path: Path):
    priv, pub = _keys()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    text = issue_license(
        customer="庆总",
        wxids=["wxid_owner"],
        private_pem=priv,
        expires_at=yesterday,
    )
    path = tmp_path / "license.dat"
    path.write_text(text, encoding="utf-8")
    status = evaluate(username="wxid_owner", path=path, public_pem=pub)
    assert not status.ok
    assert status.mode == "expired"
    assert status.kind == "paid"
    assert "过期" in status.message


def test_legacy_license_without_kind_is_paid():
    priv, pub = _keys()
    text = issue_license(customer="庆总", wxids=["wxid_owner"], private_pem=priv)
    payload = parse_license_text(text, pub)
    assert payload.kind == "paid"


def test_trial_expires_on_seven_days():
    from app.license import trial_expires_on

    assert trial_expires_on(7, today=date(2026, 9, 1)) == "2026-09-08"


def test_trial_license_valid_before_expiry(tmp_path: Path, monkeypatch):
    priv, pub = _keys()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    text = issue_license(
        customer="试用客户",
        wxids=["wxid_owner"],
        private_pem=priv,
        expires_at=tomorrow,
        kind="trial",
        instance_id="trial-ok",
    )
    path = tmp_path / "license.dat"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("JUDY_LICENSE_CLOCK_DIR", str(tmp_path / "clock"))
    status = evaluate(username="wxid_owner", path=path, public_pem=pub)
    assert status.ok
    assert status.kind == "trial"
    assert status.expires_at == tomorrow
    assert "试用" in status.message
    assert status.as_dict()["kind"] == "trial"
    assert status.as_dict()["trial_ends_on"] == tomorrow


def test_trial_expired_uses_trial_copy(tmp_path: Path, monkeypatch):
    priv, pub = _keys()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    text = issue_license(
        customer="试用客户",
        wxids=["wxid_owner"],
        private_pem=priv,
        expires_at=yesterday,
        kind="trial",
        instance_id="trial-exp",
    )
    path = tmp_path / "license.dat"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("JUDY_LICENSE_CLOCK_DIR", str(tmp_path / "clock"))
    status = evaluate(username="wxid_owner", path=path, public_pem=pub)
    assert not status.ok
    assert status.mode == "expired"
    assert status.kind == "trial"
    assert "试用已结束" in status.message


def test_trial_clock_rollback_expires(tmp_path: Path, monkeypatch):
    priv, pub = _keys()
    day0 = date.today()
    text = issue_license(
        customer="试用客户",
        wxids=["wxid_owner"],
        private_pem=priv,
        expires_at=(day0 + timedelta(days=1)).isoformat(),
        kind="trial",
        instance_id="trial-clock-1",
    )
    path = tmp_path / "license.dat"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("JUDY_LICENSE_CLOCK_DIR", str(tmp_path / "clock"))
    first = evaluate(username="wxid_owner", path=path, public_pem=pub, today=day0)
    assert first.ok
    second = evaluate(username="wxid_owner", path=path, public_pem=pub, today=day0 + timedelta(days=1))
    assert second.ok
    rolled = evaluate(username="wxid_owner", path=path, public_pem=pub, today=day0)
    assert not rolled.ok
    assert rolled.mode == "expired"
    assert "试用已结束" in rolled.message


def test_first_use_binds_then_rejects_other_account(tmp_path: Path):
    priv, pub = _keys()
    text = issue_license(customer="庆总", wxids=[], private_pem=priv, bind_mode="first_use")
    path = tmp_path / "license.dat"
    path.write_text(text, encoding="utf-8")
    first = evaluate(username="wxid_first", path=path, public_pem=pub)
    assert first.ok
    assert "wxid_first" in first.bound_wxids
    second = evaluate(username="wxid_other", path=path, public_pem=pub)
    assert not second.ok
    assert second.mode == "mismatch"


def test_pending_until_wechat_identity(tmp_path: Path):
    priv, pub = _keys()
    text = issue_license(customer="庆总", wxids=["wxid_owner"], private_pem=priv)
    path = tmp_path / "license.dat"
    path.write_text(text, encoding="utf-8")
    status = evaluate(path=path, public_pem=pub)
    assert not status.ok
    assert status.mode == "pending_wechat"


def test_source_run_without_license_file_is_development(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("LINGXI_LICENSE_SKIP", raising=False)
    monkeypatch.delenv("JUDY_DEPLOY", raising=False)
    monkeypatch.setattr("app.config.frozen", lambda: False)
    monkeypatch.setattr("app.config.deployed", lambda: False)
    monkeypatch.setattr("app.license.license_path", lambda: tmp_path / "license.dat")
    status = evaluate()
    assert status.ok
    assert status.mode == "development"
