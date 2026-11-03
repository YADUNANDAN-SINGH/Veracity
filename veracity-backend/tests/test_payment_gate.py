# The PayPal payment gate, end to end through the API, against tests/fake_paypal.py.
# Run from veracity-backend/: venv/bin/python -m pytest

import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.feature import payment_gate, paypal_client
from app.routes import session as session_routes
from main import app
from tests.fake_paypal import FakePayPal

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("VERA_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "client-id")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "secret")
    monkeypatch.setattr(payment_gate, "PAYOUTS_ENABLED", False)
    monkeypatch.setattr(payment_gate, "COOL_OFF_MIN", 15.0)


@pytest.fixture
def fake():
    fake = FakePayPal()
    paypal_client.set_client(fake.client())
    yield fake
    paypal_client.set_client(None)


class StubCall:
    """Stands in for a live Session: the gate only asks it for its risk."""

    def __init__(self, sid: str, level: str, score: int, active: bool = True):
        self.id, self.level, self.score, self._active, self.report = sid, level, score, active, None

    @property
    def active(self):
        return self._active

    def risk_snapshot(self):
        return {
            "session_id": self.id, "active": self._active, "score": self.score, "level": self.level, "reasons": [],
            "voice_state": "LIKELY_HUMAN", "voice_peak": 12, "script_score": self.score,
            "flags": [{"category": "PAYMENT_PRESSURE", "severity": 3, "evidence": "send it on PayPal", "t": 35.0}],
        }


def call_report(sid: str, level: str, score: int) -> dict:
    """The parts of a finished call's report that the gate reads."""
    return {
        "report_id": sid,
        "overall": {"score": score, "risk_level": level, "top_reasons": []},
        "voice": {"final_state": "LIKELY_HUMAN", "max_p_ai": 0.1},
        "script": {"script_score": score, "red_flags": []},
    }


def start_call(monkeypatch, level, score, active=True, sid="call1"):
    call = StubCall(sid, level, score, active)
    monkeypatch.setitem(session_routes.SESSIONS, sid, call)
    return call


def pay(fake, session_id=None, **overrides):
    """Create the order, approve it as the payer would in PayPal, then authorize it."""
    body = {"amount": "2,400", "currency": "usd", "recipient_name": "Jake (grandson)", "contact_name": "Jake",
            "contact_number": "+12025550172", "session_id": session_id, **overrides}
    created = client.post("/api/payment/orders", json=body)
    assert created.status_code == 201, created.text
    order_id = created.json()["paypal"]["order_id"]
    fake.approve(order_id)
    res = client.post(f"/api/payment/orders/{order_id}/authorize")
    assert res.status_code == 200, res.text
    return res.json()


# --- creating the order ---

def test_order_is_created_with_intent_authorize(fake):
    res = client.post("/api/payment/orders", json={"amount": "49.5", "currency": "USD", "recipient_name": "Jake"})
    assert res.status_code == 201
    payment = res.json()
    assert payment["status"] == "CREATED" and payment["amount"] == "49.50"
    order = fake.orders[payment["paypal"]["order_id"]]["body"]
    assert order["intent"] == "AUTHORIZE"
    assert order["purchase_units"][0]["amount"] == {"currency_code": "USD", "value": "49.50"}
    # Every money-moving request carries an idempotency key
    assert all(rid for method, path, rid in fake.requests if method == "POST" and "oauth2" not in path)


@pytest.mark.parametrize("body, message", [
    ({"amount": "abc"}, "must be a number"),
    ({"amount": "0"}, "more than 0"),
    ({"amount": "50000"}, "at most"),
    ({"currency": "INR"}, "Currency"),
    ({"recipient_email": "not-an-email"}, "email"),
])
def test_bad_orders_are_refused(fake, body, message):
    res = client.post("/api/payment/orders", json={"amount": "10", "currency": "USD", "recipient_name": "Jake", **body})
    assert res.status_code == 422 and message in res.json()["detail"]


def test_without_paypal_keys_the_api_says_so(monkeypatch):
    paypal_client.set_client(None)
    monkeypatch.delenv("PAYPAL_CLIENT_ID")
    assert client.get("/api/payment/config").json()["enabled"] is False
    res = client.post("/api/payment/orders", json={"amount": "10", "recipient_name": "Jake"})
    assert res.status_code == 503 and "PAYPAL_CLIENT_ID" in res.json()["detail"]


# --- the decision ---

@pytest.mark.parametrize("risk, expected", [
    (None, ("CAPTURED", None)),
    ({"level": "LOW", "active": False, "score": 10}, ("CAPTURED", None)),
    ({"level": "LOW", "active": True, "score": 10}, ("HELD", "call_active")),
    ({"level": "MEDIUM", "active": True, "score": 50}, ("HELD", "call_active")),
    ({"level": "MEDIUM", "active": False, "score": 50}, ("HELD", "verify")),
    ({"level": "HIGH", "active": True, "score": 100}, ("HELD", "likely_scam")),
    ({"level": "HIGH", "active": False, "score": 100}, ("HELD", "likely_scam")),
    # A scam told by a real person can fuse to LOW; for money, scam signs in the words are enough
    ({"level": "LOW", "active": False, "score": 24, "script_score": 68}, ("HELD", "verify")),
    ({"level": "LOW", "active": False, "score": 34, "script_score": 85}, ("HELD", "likely_scam")),
    ({"level": "LOW", "active": True, "score": 30, "voice_state": "LIKELY_AI"}, ("HELD", "likely_scam")),
    ({"level": "LOW", "active": False, "score": 8, "script_score": 24}, ("CAPTURED", None)),
])
def test_policy(risk, expected):
    status, reason, _why = payment_gate.decide(risk)
    assert (status, reason) == expected


def test_payment_with_no_call_is_released(fake):
    payment = pay(fake)
    assert payment["status"] == "CAPTURED"
    assert payment["paypal"]["capture_id"].startswith("CAPTURE")
    kinds = [e["kind"] for e in payment["events"]]
    assert kinds == ["Order created (intent AUTHORIZE)", "Payment authorized: funds held, nothing sent",
                     "Decision", "Released: authorization captured"]


def test_scam_call_holds_the_money_and_a_denied_callback_voids_it(fake, monkeypatch):
    start_call(monkeypatch, "HIGH", 100)
    payment = pay(fake, session_id="call1")
    assert (payment["status"], payment["hold_reason"]) == ("HELD", "likely_scam")
    assert "Jake" in payment["policy"] and "15 minutes" in payment["policy"]
    assert payment["risk"]["flags"][0]["evidence"] == "send it on PayPal"  # the held screen quotes the caller
    assert fake.auths[payment["paypal"]["authorization_id"]]["status"] == "CREATED"  # held, not moved

    res = client.post(f"/api/payment/{payment['payment_id']}/verify", json={"outcome": "denied"})
    assert res.json()["status"] == "VOIDED" and res.json()["verification"] == "denied"
    assert fake.auths[payment["paypal"]["authorization_id"]]["status"] == "VOIDED"
    # Nothing left to do: a second cancel is refused, not sent to PayPal again
    assert client.post(f"/api/payment/{payment['payment_id']}/cancel").status_code == 409


def test_nobody_can_confirm_while_the_caller_is_on_the_line(fake, monkeypatch):
    call = start_call(monkeypatch, "HIGH", 100)
    payment = pay(fake, session_id="call1")
    pid = payment["payment_id"]
    assert payment["call_live"] is True and payment["can_verify"] is False and payment["can_cancel"] is True
    res = client.post(f"/api/payment/{pid}/verify", json={"outcome": "confirmed"})
    assert res.status_code == 409 and "End the call" in res.json()["detail"]

    call._active = False  # hung up: now the callback can confirm (and the cooling-off still applies)
    assert client.get(f"/api/payment/{pid}").json()["can_verify"] is True
    held = client.post(f"/api/payment/{pid}/verify", json={"outcome": "confirmed"}).json()
    assert held["status"] == "HELD" and held["release_at"]


def test_high_risk_release_waits_for_the_cooling_off(fake, monkeypatch):
    start_call(monkeypatch, "HIGH", 95, active=False)
    payment = pay(fake, session_id="call1")
    pid = payment["payment_id"]
    held = client.post(f"/api/payment/{pid}/verify", json={"outcome": "confirmed"}).json()
    assert held["status"] == "HELD" and held["release_at"] and held["can_verify"] is False

    now = payment_gate._now()
    monkeypatch.setattr(payment_gate, "_now", lambda: now + timedelta(minutes=16))
    released = client.get(f"/api/payment/{pid}").json()
    assert released["status"] == "CAPTURED"
    assert fake.auths[payment["paypal"]["authorization_id"]]["status"] == "CAPTURED"


def test_payment_during_a_call_waits_for_the_call_to_end(fake, monkeypatch):
    call = start_call(monkeypatch, "MEDIUM", 52)
    payment = pay(fake, session_id="call1")
    pid = payment["payment_id"]
    assert payment["hold_reason"] == "call_active" and payment["can_verify"] is False

    # The scammer is still on the line: no "confirmed" until the call is over
    res = client.post(f"/api/payment/{pid}/verify", json={"outcome": "confirmed"})
    assert res.status_code == 409 and "End the call" in res.json()["detail"]

    call._active = False
    views = payment_gate.on_session_ended("call1", call_report("call1", "MEDIUM", 52))
    assert views[0]["hold_reason"] == "verify"
    res = client.post(f"/api/payment/{pid}/verify", json={"outcome": "confirmed"})
    assert res.json()["status"] == "CAPTURED"


def test_low_risk_call_releases_the_payment_when_it_ends(fake, monkeypatch):
    call = start_call(monkeypatch, "LOW", 8)
    payment = pay(fake, session_id="call1", amount="40")
    assert payment["status"] == "HELD"
    call._active = False
    views = payment_gate.on_session_ended("call1", call_report("call1", "LOW", 8))
    assert views[0]["status"] == "CAPTURED"


def test_a_call_that_turns_into_a_scam_escalates_the_hold(fake, monkeypatch):
    call = start_call(monkeypatch, "LOW", 8)
    payment = pay(fake, session_id="call1")
    assert payment["hold_reason"] == "call_active"
    call.level, call.score = "HIGH", 100
    assert client.get(f"/api/payment/{payment['payment_id']}").json()["hold_reason"] == "likely_scam"


def test_a_hold_that_runs_out_is_voided(fake, monkeypatch):
    start_call(monkeypatch, "MEDIUM", 50, active=False)
    payment = pay(fake, session_id="call1")
    now = payment_gate._now()
    monkeypatch.setattr(payment_gate, "_now", lambda: now + timedelta(hours=73))
    assert client.get(f"/api/payment/{payment['payment_id']}").json()["status"] == "VOIDED"


def test_the_sweeper_voids_a_hold_nobody_looks_at(fake, monkeypatch):
    start_call(monkeypatch, "MEDIUM", 50, active=False)
    held = pay(fake, session_id="call1")
    pay(fake, amount="40")  # no call: released at once, so the sweeper has nothing to do with it
    assert payment_gate.sweep() == 0
    now = payment_gate._now()
    monkeypatch.setattr(payment_gate, "_now", lambda: now + timedelta(hours=73))
    assert payment_gate.sweep() == 1
    assert fake.auths[held["paypal"]["authorization_id"]]["status"] == "VOIDED"


def test_a_failed_capture_is_reconciled_with_paypal(fake, monkeypatch):
    start_call(monkeypatch, "MEDIUM", 50, active=False)
    payment = pay(fake, session_id="call1")
    fake.auths[payment["paypal"]["authorization_id"]]["status"] = "VOIDED"  # voided elsewhere, e.g. in the dashboard
    res = client.post(f"/api/payment/{payment['payment_id']}/verify", json={"outcome": "confirmed"})
    assert res.json()["status"] == "VOIDED"
    kinds = [e["kind"] for e in res.json()["events"]]
    assert "Capture failed" in kinds and "Checked the authorization at PayPal" in kinds


def test_approving_twice_doesnt_authorize_twice(fake):
    created = client.post("/api/payment/orders", json={"amount": "10", "recipient_name": "Jake"}).json()
    order_id = created["paypal"]["order_id"]
    fake.approve(order_id)
    first = client.post(f"/api/payment/orders/{order_id}/authorize").json()
    second = client.post(f"/api/payment/orders/{order_id}/authorize").json()
    assert first["paypal"]["authorization_id"] == second["paypal"]["authorization_id"]
    assert sum(path.endswith("/authorize") for _, path, _ in fake.requests) == 1


def test_cancel_before_approval_needs_no_paypal_call(fake):
    created = client.post("/api/payment/orders", json={"amount": "10", "recipient_name": "Jake"}).json()
    before = len(fake.requests)
    assert client.post(f"/api/payment/{created['payment_id']}/cancel").json()["status"] == "VOIDED"
    assert len(fake.requests) == before


def test_payouts_forward_a_release_to_the_recipient(fake, monkeypatch):
    monkeypatch.setattr(payment_gate, "PAYOUTS_ENABLED", True)
    payment = pay(fake, recipient_email="jake@example.com")
    assert payment["status"] == "PAID_OUT" and payment["paypal"]["payout_batch_id"].startswith("BATCH")


# --- webhooks ---

WEBHOOK_HEADERS = {
    "PAYPAL-AUTH-ALGO": "SHA256withRSA", "PAYPAL-CERT-URL": "https://api.sandbox.paypal.com/cert.pem",
    "PAYPAL-TRANSMISSION-ID": "t-1", "PAYPAL-TRANSMISSION-TIME": "2026-11-05T10:00:00Z",
}


def test_verified_webhook_updates_the_payment(fake, monkeypatch):
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "WH-1")
    start_call(monkeypatch, "HIGH", 100)
    payment = pay(fake, session_id="call1")
    auth_id = payment["paypal"]["authorization_id"]
    event = {"id": "WH-EVT-1", "event_type": "PAYMENT.AUTHORIZATION.VOIDED", "resource": {"id": auth_id, "status": "VOIDED"}}
    raw = json.dumps(event, indent=1)  # odd formatting on purpose: it must reach PayPal byte for byte

    bad = client.post("/api/paypal/webhook", content=raw, headers={**WEBHOOK_HEADERS, "PAYPAL-TRANSMISSION-SIG": "forged"})
    assert bad.status_code == 400

    headers = {**WEBHOOK_HEADERS, "PAYPAL-TRANSMISSION-SIG": "good-signature"}
    assert client.post("/api/paypal/webhook", content=raw, headers=headers).json() == {"handled": True}
    assert fake.verify_bodies[-1]["webhook_id"] == "WH-1" and fake.verify_bodies[-1]["webhook_event"] == event
    assert client.get(f"/api/payment/{payment['payment_id']}").json()["status"] == "VOIDED"
    # PayPal retries deliveries; the same event is applied once
    assert client.post("/api/paypal/webhook", content=raw, headers=headers).json() == {"handled": False}


def test_webhooks_are_off_without_a_webhook_id(fake, monkeypatch):
    monkeypatch.delenv("PAYPAL_WEBHOOK_ID", raising=False)
    assert client.post("/api/paypal/webhook", content="{}").status_code == 503
