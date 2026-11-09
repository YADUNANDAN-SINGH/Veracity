# PayPal fails at the moment a call ends. The real API, gate and client on a real replay;
# only PayPal's answers are taken away. Ending a call must still give its report, the money
# must stay held, and the release must happen by itself, exactly once, when PayPal is back.

import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

import main
from app.feature import payment_gate, payments_db, paypal_client, replay
from tests.fake_paypal import FakePayPal


class FlakyPayPal(FakePayPal):
    def __init__(self):
        super().__init__()
        self.down = False  # nothing gets through
        self.capture_status: int | None = None  # PayPal answers every capture with this
        self.lose_capture_answer = False  # PayPal does the capture, and the answer never arrives
        self.failing_auths: set[str] = set()  # only these authorizations are unreachable

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "oauth2" not in path and (self.down or any(a in path for a in self.failing_auths)):
            raise httpx.ConnectError("PayPal is unreachable")
        if self.capture_status and path.endswith("/capture"):
            return httpx.Response(self.capture_status, json={"name": "INTERNAL_SERVER_ERROR", "message": "Try later."})
        response = super().handle(request)
        if self.lose_capture_answer and path.endswith("/capture"):
            self.lose_capture_answer = False
            self.down = True
            raise httpx.ReadTimeout("the answer never arrived")
        return response

    def captures(self) -> list:
        return [path for method, path, _ in self.requests if path.endswith("/capture")]


@pytest.fixture
def paypal():
    fake = FlakyPayPal()
    paypal_client.set_client(fake.client())
    yield fake
    paypal_client.set_client(None)


@pytest.fixture
def api(tmp_path, monkeypatch, paypal):
    monkeypatch.setenv("VERA_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "client-id")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "secret")
    monkeypatch.setattr(payment_gate, "PAYOUTS_ENABLED", False)
    monkeypatch.setattr(replay, "SPEED", 40.0)
    monkeypatch.setattr(main, "JUDGE_MODE", True)
    # raise_server_exceptions=False: a crash comes back as the 500 a browser would get
    with TestClient(main.app, raise_server_exceptions=False) as client:
        yield client


def low_risk_call(api):
    return api.post("/api/session/start", json={"scenario": "birthday_cake_us"}).json()["session_id"]


def pay(api, paypal, session_id):
    created = api.post("/api/payment/orders", json={
        "amount": "50", "currency": "USD", "recipient_name": "Jake (grandson)", "contact_name": "Jake",
        "contact_number": "+12025550172", "session_id": session_id,
    }).json()
    paypal.approve(created["paypal"]["order_id"])
    held = api.post(f"/api/payment/orders/{created['paypal']['order_id']}/authorize").json()
    assert held["status"] == "HELD" and held["hold_reason"] == "call_active"
    return held


def end_call_while_paypal_is_down(api, paypal):
    sid = low_risk_call(api)
    payment = pay(api, paypal, sid)
    paypal.down = True
    report = api.post(f"/api/session/{sid}/stop")
    assert report.status_code == 200, report.text
    return sid, payment["payment_id"], report.json()


def retry_is_due(payment_id):
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    payments_db.update_payment(payment_id, release_at=past)


def get(api, payment_id):
    return api.get(f"/api/payment/{payment_id}").json()


def test_paypal_unreachable_at_hang_up_still_gives_the_report_and_keeps_the_money_held(api, paypal):
    sid, pid, report = end_call_while_paypal_is_down(api, paypal)
    assert report["overall"]["risk_level"] == "LOW" and report["report_id"] == sid

    assert report["payments"][0]["status"] == "HELD" and report["payments"][0]["hold_reason"] == "release_pending"
    payment = get(api, pid)
    assert payment["status"] == "HELD" and payment["hold_reason"] == "release_pending"
    assert payment["call_live"] is False and payment["can_cancel"] is True
    assert payment["can_verify"] is False  # no callback to make: the call already checked out
    assert "No money has moved" in payment["policy"]
    assert "Release delayed: PayPal didn't complete it" in [e["kind"] for e in payment["events"]]


def test_a_paypal_error_answer_at_hang_up_is_handled_the_same_way(api, paypal):
    sid = low_risk_call(api)
    pid = pay(api, paypal, sid)["payment_id"]
    paypal.capture_status = 500
    report = api.post(f"/api/session/{sid}/stop")
    assert report.status_code == 200 and report.json()["payments"][0]["hold_reason"] == "release_pending"
    assert get(api, pid)["status"] == "HELD"


def test_the_release_happens_by_itself_when_paypal_is_back_and_only_when_its_due(api, paypal):
    _, pid, _ = end_call_while_paypal_is_down(api, paypal)
    attempts = len(paypal.captures())
    paypal.down = False

    assert get(api, pid)["status"] == "HELD"  # not due yet, so polling doesn't hammer PayPal
    assert len(paypal.captures()) == attempts

    retry_is_due(pid)
    payment = get(api, pid)
    assert payment["status"] == "CAPTURED" and payment["hold_reason"] is None and payment["paypal"]["capture_id"]
    assert get(api, pid)["status"] == "CAPTURED"
    assert len(paypal.captures()) == attempts + 1


def test_the_background_sweep_retries_with_nobody_on_the_page(api, paypal):
    _, pid, _ = end_call_while_paypal_is_down(api, paypal)
    paypal.down = False
    retry_is_due(pid)
    assert payment_gate.sweep() == 1
    assert payments_db.get_payment(pid)["status"] == "CAPTURED"


def test_each_failed_try_waits_longer(api, paypal):
    _, pid, _ = end_call_while_paypal_is_down(api, paypal)

    def wait_s():
        at = datetime.strptime(payments_db.get_payment(pid)["release_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return (at - datetime.now(timezone.utc)).total_seconds()

    assert wait_s() == pytest.approx(payment_gate.RELEASE_RETRY_FIRST_S, abs=3)
    retry_is_due(pid)
    assert get(api, pid)["hold_reason"] == "release_pending"
    assert wait_s() == pytest.approx(payment_gate.RELEASE_RETRY_FIRST_S * 2, abs=3)


def test_a_capture_whose_answer_was_lost_isnt_done_twice(api, paypal):
    sid = low_risk_call(api)
    payment = pay(api, paypal, sid)
    paypal.lose_capture_answer = True
    report = api.post(f"/api/session/{sid}/stop").json()
    assert report["payments"][0]["hold_reason"] == "release_pending"  # Veracity can't know yet that PayPal did it
    auth_id = payment["paypal"]["authorization_id"]
    assert paypal.auths[auth_id]["status"] == "CAPTURED"

    paypal.down = False
    retry_is_due(payment["payment_id"])
    assert get(api, payment["payment_id"])["status"] == "CAPTURED"
    # Both tries carried the same PayPal-Request-Id, so PayPal answers the retry with the first capture
    ids = {rid for method, path, rid in paypal.requests if path.endswith("/capture")}
    assert ids == {f"{payment['payment_id']}-capture"}
    assert sum(1 for a in paypal.auths.values() if a["status"] == "CAPTURED") == 1


def test_one_payment_failing_doesnt_stop_the_others_being_decided(api, paypal):
    sid = low_risk_call(api)
    first, second = pay(api, paypal, sid), pay(api, paypal, sid)
    paypal.failing_auths = {first["paypal"]["authorization_id"]}
    report = api.post(f"/api/session/{sid}/stop")
    assert report.status_code == 200
    status = {p["payment_id"]: p["status"] for p in report.json()["payments"]}
    assert status == {first["payment_id"]: "HELD", second["payment_id"]: "CAPTURED"}


def test_the_payer_can_cancel_while_its_waiting_for_paypal(api, paypal):
    _, pid, _ = end_call_while_paypal_is_down(api, paypal)
    paypal.down = False
    assert api.post(f"/api/payment/{pid}/cancel").json()["status"] == "VOIDED"


def test_a_release_that_never_succeeds_is_voided_when_the_hold_runs_out(api, paypal):
    _, pid, _ = end_call_while_paypal_is_down(api, paypal)
    paypal.down = False
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    payments_db.update_payment(pid, expires_at=past)
    assert get(api, pid)["status"] == "VOIDED"


def test_ending_the_call_again_is_safe(api, paypal):
    sid, pid, first = end_call_while_paypal_is_down(api, paypal)
    second = api.post(f"/api/session/{sid}/stop")
    assert second.status_code == 200 and second.json()["report_id"] == first["report_id"]
    paypal.down = False
    retry_is_due(pid)
    assert get(api, pid)["status"] == "CAPTURED"
    captures = len(paypal.captures())
    assert api.post(f"/api/session/{sid}/stop").status_code == 200
    assert len(paypal.captures()) == captures  # it's already released: ending the call again changes nothing
    assert sum(a["status"] == "CAPTURED" for a in paypal.auths.values()) == 1


def test_a_healthy_paypal_is_unaffected(api, paypal):
    sid = low_risk_call(api)
    pid = pay(api, paypal, sid)["payment_id"]
    time.sleep(0.2)
    report = api.post(f"/api/session/{sid}/stop").json()
    assert report["payments"][0]["status"] == "CAPTURED"
    payment = get(api, pid)
    assert not [e for e in payment["events"] if e["kind"].startswith("Release delayed")]
