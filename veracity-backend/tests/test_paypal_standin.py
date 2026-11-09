# The in-memory PayPal stand-in (VERA_PAYPAL_STANDIN=1, the Docker judge build's
# default), through the real API and the real payment gate: the money's journey is
# the same as with PayPal's sandbox, and every answer says it wasn't PayPal.

import time

import pytest
from fastapi.testclient import TestClient

import main
from app.feature import payment_gate, paypal_client, paypal_standin, replay


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("VERA_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("VERA_PAYPAL_STANDIN", "1")
    monkeypatch.delenv("PAYPAL_CLIENT_ID", raising=False)
    monkeypatch.delenv("PAYPAL_CLIENT_SECRET", raising=False)
    monkeypatch.setattr(payment_gate, "PAYOUTS_ENABLED", False)
    monkeypatch.setattr(paypal_standin, "_shared", None)
    monkeypatch.setattr(replay, "SPEED", 40.0)
    monkeypatch.setattr(main, "JUDGE_MODE", True)
    paypal_client.set_client(None)
    with TestClient(main.app) as client:
        yield client
    paypal_client.set_client(None)


def wait_for(check, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if result := check():
            return result
        time.sleep(0.05)
    raise AssertionError("timed out")


def pay(api, session_id, amount="2400"):
    """What the dashboard's stand-in button does: create, approve, authorize."""
    created = api.post("/api/payment/orders", json={
        "amount": amount, "currency": "USD", "recipient_name": "Jake (grandson)", "contact_name": "Jake",
        "contact_number": "+12025550172", "session_id": session_id,
    })
    assert created.status_code == 201, created.text
    order_id = created.json()["paypal"]["order_id"]
    assert order_id.startswith("STANDIN-ORDER-")
    assert api.post(f"/api/payment/orders/{order_id}/standin-approve").json() == {"approved": True}
    held = api.post(f"/api/payment/orders/{order_id}/authorize")
    assert held.status_code == 200, held.text
    return held.json()


def trail(payment):
    return [e["detail"] for e in payment["events"] if e["source"] == "paypal_api"]


def test_config_and_health_say_its_a_stand_in(api):
    config = api.get("/api/payment/config").json()
    assert config["enabled"] is True and config["standin"] is True
    assert config["environment"] == "standin" and config["client_id"] is None
    assert api.get("/api/health").json()["paypal"]["standin"] is True


def test_scam_call_authorize_hold_then_void(api):
    sid = api.post("/api/session/start", json={"scenario": "grandparent_us"}).json()["session_id"]
    wait_for(lambda: api.get(f"/api/session/{sid}/risk").json()["level"] == "HIGH")
    payment = pay(api, sid)
    assert payment["status"] == "HELD" and payment["hold_reason"] == "likely_scam"
    assert payment["paypal"]["environment"] == "standin" and payment["paypal"]["authorization_id"].startswith("STANDIN-AUTH-")

    report = api.post(f"/api/session/{sid}/stop").json()
    assert report["payments"][0]["paypal"]["environment"] == "standin"  # the evidence file says it wasn't PayPal

    voided = api.post(f"/api/payment/{payment['payment_id']}/verify", json={"outcome": "denied"}).json()
    assert voided["status"] == "VOIDED"
    calls = [(c["method"], c["path"].replace(payment["paypal"]["authorization_id"], "{id}").replace(payment["paypal"]["order_id"], "{id}"), c["status"]) for c in trail(voided)]
    assert calls == [
        ("POST", "/v2/checkout/orders", 201),
        ("POST", "/v2/checkout/orders/{id}/authorize", 201),
        ("POST", "/v2/payments/authorizations/{id}/void", 200),
    ]
    assert all(c["debug_id"].startswith("standin-") for c in trail(voided))


def test_low_risk_birthday_cake_call_is_held_during_the_call_then_captured(api):
    sid = api.post("/api/session/start", json={"scenario": "birthday_cake_us"}).json()["session_id"]
    wait_for(lambda: len(api.get(f"/api/session/{sid}/risk").json()["flags"]) >= 1)
    payment = pay(api, sid, amount="50.00")
    assert payment["status"] == "HELD" and payment["hold_reason"] == "call_active"

    time.sleep(1.2)  # the rest of the 40 s call at 40× speed
    report = api.post(f"/api/session/{sid}/stop").json()
    assert report["overall"]["risk_level"] == "LOW"
    assert report["payments"][0]["status"] == "CAPTURED"
    captured = api.get(f"/api/payment/{payment['payment_id']}").json()
    assert any(c["path"].endswith("/capture") and c["status"] == 201 for c in trail(captured))


def test_an_order_cant_be_authorized_before_its_approved(api):
    created = api.post("/api/payment/orders", json={
        "amount": "10", "currency": "USD", "recipient_name": "Jake", "contact_number": "+12025550172",
    }).json()
    res = api.post(f"/api/payment/orders/{created['paypal']['order_id']}/authorize")
    assert res.status_code == 502 and "approved" in res.json()["detail"]


def test_approving_an_unknown_order_is_refused(api):
    assert api.post("/api/payment/orders/STANDIN-ORDER-NOPE/standin-approve").status_code == 404


def test_a_hold_from_before_a_restart_answers_with_an_error_not_a_crash(api, monkeypatch):
    sid = api.post("/api/session/start", json={"scenario": "grandparent_us"}).json()["session_id"]
    wait_for(lambda: api.get(f"/api/session/{sid}/risk").json()["level"] == "HIGH")
    payment = pay(api, sid)
    api.post(f"/api/session/{sid}/stop")
    # The container restarted: the database kept the payment, the stand-in's memory is gone
    monkeypatch.setattr(paypal_standin, "_shared", None)
    paypal_client.set_client(None)
    res = api.post(f"/api/payment/{payment['payment_id']}/cancel")
    assert res.status_code == 502 and "stand-in" in res.json()["detail"].lower()


def test_sandbox_keys_always_win(api, monkeypatch):
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "real-client-id")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "real-secret")
    paypal_client.set_client(None)
    config = api.get("/api/payment/config").json()
    assert config["standin"] is False and config["environment"] == "sandbox" and config["client_id"] == "real-client-id"
    assert api.post("/api/payment/orders/ANY/standin-approve").status_code == 404
    client = paypal_client.get_client()
    assert client.client_id == "real-client-id"
    paypal_client.set_client(None)


def test_off_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("VERA_DB", str(tmp_path / "test.db"))
    monkeypatch.delenv("VERA_PAYPAL_STANDIN", raising=False)
    monkeypatch.delenv("PAYPAL_CLIENT_ID", raising=False)
    monkeypatch.delenv("PAYPAL_CLIENT_SECRET", raising=False)
    monkeypatch.setattr(main, "JUDGE_MODE", True)
    paypal_client.set_client(None)
    with TestClient(main.app) as client:
        config = client.get("/api/payment/config").json()
        assert config["enabled"] is False and config["standin"] is False
        assert client.post("/api/payment/orders/ANY/standin-approve").status_code == 404
