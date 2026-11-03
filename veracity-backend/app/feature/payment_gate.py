# The payment gate: PayPal holds the money, and the call decides where it goes.
#
#   create()            Orders v2 with intent AUTHORIZE for a Protected Send started during or after a call
#   authorize()         after the payer approves in PayPal: funds are reserved, nothing has moved yet,
#                       then decide() with the call's risk at that moment
#   verify()            the user called the person back on a saved number: confirmed → release, denied → void
#   cancel()            void: the money never leaves the payer
#   refresh()           on every read: escalate a hold if the call got riskier, release once a
#                       cooling-off ends, void a hold that has run out
#   on_session_ended()  holds that were waiting for the call to end are decided with the final report
#   apply_webhook()     PayPal is the source of truth for captures, voids and payouts
#
# Release = capture the authorization (and, with PAYPAL_PAYOUTS=1, forward it to the
# recipient's PayPal with Payouts). Cancel = void the authorization.
# Holds are voided after HOLD_HOURS, inside PayPal's 3-day honor period.

import json
import logging
import os
import re
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from app.feature import payments_db
from app.feature.paypal_client import PayPalError, get_client

log = logging.getLogger("veracity.gate")

HOLD_HOURS = float(os.environ.get("VERA_HOLD_HOURS", "72"))
COOL_OFF_MIN = float(os.environ.get("VERA_COOL_OFF_MIN", "15"))
PAYOUTS_ENABLED = os.environ.get("PAYPAL_PAYOUTS") == "1"
CURRENCIES = {"USD", "GBP", "EUR", "CAD", "AUD"}
MAX_AMOUNT = Decimal("10000.00")

# Why a payment is held, in the words the user sees ({contact} and {minutes} are filled in)
POLICY = {
    "call_active": (
        "Held while the call is still going on. Scammers push for money mid-call, so Veracity "
        "decides once you hang up."
    ),
    "verify": (
        "Held until you call {contact} back on the number saved in your phone, not the number that "
        "called you."
    ),
    "likely_scam": (
        "Held: this call matched a known scam. Call {contact} back on a saved number. Even if they "
        "confirm, the money waits {minutes} minutes before it is released."
    ),
}

# Look up the live risk of a call by session id; set by app/routes/payment.py
RiskProvider = Callable[[str], dict | None]
_risk_provider: RiskProvider = lambda _session_id: None  # noqa: E731

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


class GateError(RuntimeError):
    """A request the gate can't carry out; `status` is the HTTP status to answer with."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def set_risk_provider(provider: RiskProvider) -> None:
    global _risk_provider
    _risk_provider = provider


def _lock(payment_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(payment_id, threading.Lock())


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(ts: str | None) -> datetime | None:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) if ts else None


# ----- the decision -----

def gate_level(risk: dict) -> tuple[str, str]:
    """(level, why) the gate acts on: the call's fused level, raised by any one strong sign.

    The fused score weighs number, voice and script together, so a scam told by a
    real person with an ordinary number can fuse to LOW. Money gets a stricter
    rule: some scam signs in the script (≥ 40) are enough to ask for a callback.
    On eval/transcripts.jsonl that holds 21 of 24 test scams and none of 24
    ordinary calls (eval/results.md).
    """
    level, score, script = risk.get("level", "LOW"), risk.get("score", 0), risk.get("script_score", 0)
    if level == "HIGH":
        return "HIGH", f"The call is high risk ({score}/100)."
    if risk.get("voice_state") == "LIKELY_AI":
        return "HIGH", "The caller's voice sounded AI-generated."
    if script >= 80:
        return "HIGH", f"The caller's words match a known scam script ({script}/100)."
    if level == "MEDIUM":
        return "MEDIUM", f"The call is medium risk ({score}/100)."
    if script >= 40:
        return "MEDIUM", f"The caller's words show scam signs ({script}/100)."
    return "LOW", f"The call is low risk ({score}/100)."


def decide(risk: dict | None) -> tuple[str, str | None, str]:
    """(status, hold_reason, why) for a payment that was just authorized."""
    if risk is None:
        return "CAPTURED", None, "No call is linked to this payment, so it was released."
    level, why = gate_level(risk)
    if level == "HIGH":
        return "HELD", "likely_scam", why
    if risk.get("active"):
        return "HELD", "call_active", "The call is still going on."
    if level == "MEDIUM":
        return "HELD", "verify", why
    return "CAPTURED", None, why


def _with_gate(risk: dict | None) -> str | None:
    """The risk snapshot as stored with the payment, with the level the gate acted on."""
    if risk is None:
        return None
    level, why = gate_level(risk)
    return json.dumps({**risk, "gate_level": level, "gate_why": why})


def risk_from_report(report: dict) -> dict:
    """The same shape as Session.risk_snapshot(), from a finished call's report."""
    flags = sorted(report["script"]["red_flags"], key=lambda f: (-f["severity"], f["t"]))[:5]
    return {
        "session_id": report["report_id"],
        "active": False,
        "score": report["overall"]["score"],
        "level": report["overall"]["risk_level"],
        "reasons": report["overall"]["top_reasons"],
        "voice_state": report["voice"]["final_state"],
        "voice_peak": round(report["voice"]["max_p_ai"] * 100),
        "script_score": report["script"]["script_score"],
        "flags": [{k: f[k] for k in ("category", "severity", "evidence", "t")} for f in flags],
    }


# ----- create and authorize -----

def create(*, amount: str, currency: str, recipient_name: str, recipient_email: str | None,
           contact_name: str | None, contact_number: str | None, note: str | None,
           session_id: str | None) -> dict:
    """Create the PayPal order (intent AUTHORIZE). The browser then asks the payer to approve it."""
    value = _validate_amount(amount)
    currency = currency.upper()
    if currency not in CURRENCIES:
        raise GateError(422, f"Currency must be one of {', '.join(sorted(CURRENCIES))}.")
    if recipient_email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", recipient_email):
        raise GateError(422, "That recipient email doesn't look right.")

    payment_id = uuid.uuid4().hex
    who = recipient_name.strip() or "someone"
    try:
        result = get_client().create_order(
            amount=value, currency=currency, reference_id=payment_id, custom_id=session_id or payment_id,
            description=f"Protected Send to {who}, held by Veracity until the call is checked",
            request_id=f"{payment_id}-create",
        )
    except PayPalError as e:
        raise GateError(502, f"PayPal didn't create the order: {e.message}") from e

    payment = payments_db.create_payment({
        "payment_id": payment_id,
        "session_id": session_id,
        "order_id": result.body["id"],
        "amount": value,
        "currency": currency,
        "recipient_name": who,
        "recipient_email": recipient_email or None,
        "contact_name": (contact_name or "").strip() or who,
        "contact_number": contact_number or None,
        "note": (note or "").strip() or None,
        "status": "CREATED",
    })
    payments_db.add_event(payment_id, "paypal_api", "Order created (intent AUTHORIZE)", {
        **result.call, "order_id": result.body["id"], "order_status": result.body.get("status"),
    })
    return payment


def authorize(payment_id: str) -> dict:
    """The payer approved in PayPal: reserve the funds, then let the call decide."""
    with _lock(payment_id):
        payment = _get(payment_id)
        if payment["status"] != "CREATED":
            return payment  # approved twice (double click, retried request): nothing more to do
        try:
            result = get_client().authorize_order(payment["order_id"], request_id=f"{payment_id}-authorize")
        except PayPalError as e:
            payments_db.add_event(payment_id, "paypal_api", "Authorization failed", _error_detail(e))
            raise GateError(502, f"PayPal didn't authorize the payment: {e.message}") from e

        auth = result.body["purchase_units"][0]["payments"]["authorizations"][0]
        payments_db.add_event(payment_id, "paypal_api", "Payment authorized: funds held, nothing sent", {
            **result.call, "authorization_id": auth["id"], "authorization_status": auth.get("status"),
            "expiration_time": auth.get("expiration_time"),
        })
        if auth.get("status") == "DENIED":
            return payments_db.update_payment(payment_id, status="FAILED", authorization_id=auth["id"])

        risk = _risk_provider(payment["session_id"]) if payment["session_id"] else None
        status, reason, why = decide(risk)
        payment = payments_db.update_payment(
            payment_id, authorization_id=auth["id"], status="HELD", hold_reason=reason,
            risk_json=_with_gate(risk), expires_at=_iso(_now() + timedelta(hours=HOLD_HOURS)),
        )
        payments_db.add_event(payment_id, "veracity", "Decision", {
            "outcome": "release" if status == "CAPTURED" else "hold", "hold_reason": reason, "why": why,
            "risk_level": risk.get("level") if risk else None, "risk_score": risk.get("score") if risk else None,
        })
        if status == "CAPTURED":
            payment = _release(payment, why)
        return payment


# ----- the user's decision after calling back -----

def verify(payment_id: str, outcome: str) -> dict:
    """outcome "confirmed": the person said they asked for the money; "denied": they didn't."""
    if outcome not in ("confirmed", "denied"):
        raise GateError(422, 'outcome must be "confirmed" or "denied".')
    refresh(payment_id)
    with _lock(payment_id):
        payment = _get(payment_id)
        if payment["status"] != "HELD":
            raise GateError(409, f"This payment is {payment['status'].lower()}, not held.")
        contact = payment["contact_name"]
        if outcome == "denied":
            payments_db.update_payment(payment_id, verification="denied")
            payments_db.add_event(payment_id, "veracity", "Callback: they didn't ask for this money", {"contact": contact})
            return _cancel_held(_get(payment_id), f"{contact} said they didn't ask for this money.")

        if payment["hold_reason"] == "call_active":
            raise GateError(409, f"End the call first, then call {contact} back on a number saved in your phone.")
        payments_db.add_event(payment_id, "veracity", "Callback: confirmed", {"contact": contact})
        if payment["hold_reason"] == "likely_scam" and COOL_OFF_MIN > 0:
            release_at = _now() + timedelta(minutes=COOL_OFF_MIN)
            payments_db.add_event(payment_id, "veracity", "Cooling-off started", {"release_at": _iso(release_at)})
            return payments_db.update_payment(payment_id, verification="confirmed", release_at=_iso(release_at))
        payment = payments_db.update_payment(payment_id, verification="confirmed")
        return _release(payment, f"{contact} confirmed on a callback.")


def cancel(payment_id: str) -> dict:
    with _lock(payment_id):
        payment = _get(payment_id)
        if payment["status"] == "CREATED":  # never approved: the order simply expires at PayPal
            payments_db.add_event(payment_id, "veracity", "Cancelled before approval: nothing was authorized")
            return payments_db.update_payment(payment_id, status="VOIDED", hold_reason=None)
        if payment["status"] != "HELD":
            raise GateError(409, f"This payment is {payment['status'].lower()} and can't be cancelled.")
        return _cancel_held(payment, "Cancelled by the payer.")


# ----- things that happen on their own -----

def refresh(payment_id: str) -> dict:
    """Bring a held payment up to date: expiry, end of a cooling-off, or a call that got riskier."""
    with _lock(payment_id):
        payment = _get(payment_id)
        if payment["status"] != "HELD":
            return payment
        now = _now()
        expires = _parse(payment["expires_at"])
        if expires and now >= expires:
            return _cancel_held(payment, f"The hold ran out after {HOLD_HOURS:g} hours without being released.")
        release_at = _parse(payment["release_at"])
        if payment["verification"] == "confirmed" and release_at and now >= release_at:
            return _release(payment, "Confirmed on a callback and the cooling-off is over.")
        if payment["hold_reason"] == "call_active" and payment["session_id"]:
            risk = _risk_provider(payment["session_id"])
            if risk and gate_level(risk)[0] == "HIGH":
                payments_db.add_event(payment_id, "veracity", "Escalated: the call became high risk", {
                    "risk_score": risk.get("score"), "why": gate_level(risk)[1],
                })
                return payments_db.update_payment(payment_id, hold_reason="likely_scam", risk_json=_with_gate(risk))
        return payment


def on_session_ended(session_id: str, report: dict) -> list[dict]:
    """Decide the holds that were waiting for this call to end; returns the call's payments."""
    risk = risk_from_report(report)
    for payment in payments_db.list_payments(session_id):
        if payment["status"] != "HELD" or payment["hold_reason"] != "call_active":
            continue
        with _lock(payment["payment_id"]):
            status, reason, why = decide(risk)
            payments_db.add_event(payment["payment_id"], "veracity", "Decision after the call", {
                "outcome": "release" if status == "CAPTURED" else "hold", "hold_reason": reason, "why": why,
                "risk_level": risk["level"], "risk_score": risk["score"],
            })
            if status == "CAPTURED":
                _release(payments_db.update_payment(payment["payment_id"], risk_json=_with_gate(risk)), why)
            else:
                payments_db.update_payment(payment["payment_id"], hold_reason=reason, risk_json=_with_gate(risk))
    return [view(p) for p in payments_db.list_payments(session_id)]


def apply_webhook(event: dict) -> dict | None:
    """Update a payment from a verified PayPal webhook; returns the payment, or None if it isn't ours."""
    if not payments_db.mark_webhook_seen(event.get("id", ""), event.get("event_type", "")):
        return None  # PayPal retried a delivery we already handled
    kind = event.get("event_type", "")
    resource = event.get("resource") or {}
    related = (resource.get("supplementary_data") or {}).get("related_ids") or {}

    payment = None
    if kind.startswith("PAYMENT.AUTHORIZATION."):
        payment = payments_db.find_by_authorization(resource.get("id", ""))
    elif kind.startswith("PAYMENT.CAPTURE."):
        payment = payments_db.find_by_authorization(related.get("authorization_id", ""))
    elif kind.startswith("CHECKOUT.ORDER."):
        payment = payments_db.find_by_order(resource.get("id", ""))
    elif kind.startswith("PAYMENT.PAYOUTSBATCH."):
        payment = payments_db.find_by_payout((resource.get("batch_header") or {}).get("payout_batch_id", ""))
    elif kind.startswith("PAYMENT.PAYOUTS-ITEM."):
        payment = payments_db.find_by_payout(resource.get("payout_batch_id", ""))
    if payment is None and related.get("order_id"):
        payment = payments_db.find_by_order(related["order_id"])
    if payment is None:
        return None

    pid = payment["payment_id"]
    with _lock(pid):
        payment = _get(pid)
        payments_db.add_event(pid, "webhook", kind, {"event_id": event.get("id"), "resource_id": resource.get("id"),
                                                     "resource_status": resource.get("status")})
        if kind == "PAYMENT.AUTHORIZATION.VOIDED" and payment["status"] in ("CREATED", "HELD"):
            payment = payments_db.update_payment(pid, status="VOIDED")
        elif kind == "PAYMENT.CAPTURE.COMPLETED" and payment["status"] in ("CREATED", "HELD"):
            payment = payments_db.update_payment(pid, status="CAPTURED", capture_id=resource.get("id"))
        elif kind in ("PAYMENT.CAPTURE.DENIED", "PAYMENT.CAPTURE.DECLINED"):
            payment = payments_db.update_payment(pid, status="FAILED")
    return payment


# ----- releasing and cancelling (call with the payment's lock held) -----

def _release(payment: dict, why: str) -> dict:
    pid = payment["payment_id"]
    try:
        result = get_client().capture_authorization(payment["authorization_id"], request_id=f"{pid}-capture")
    except PayPalError as e:
        return _reconcile(payment, e, wanted="CAPTURED")
    payments_db.add_event(pid, "paypal_api", "Released: authorization captured", {
        **result.call, "capture_id": result.body.get("id"), "capture_status": result.body.get("status"), "why": why,
    })
    payment = payments_db.update_payment(pid, status="CAPTURED", capture_id=result.body.get("id"), hold_reason=None)
    if PAYOUTS_ENABLED and payment["recipient_email"]:
        payment = _payout(payment)
    return payment


def _payout(payment: dict) -> dict:
    pid = payment["payment_id"]
    try:
        result = get_client().create_payout(
            sender_batch_id=f"{pid}-payout", receiver_email=payment["recipient_email"],
            amount=payment["amount"], currency=payment["currency"],
            note=f"Released by Veracity for {payment['recipient_name']}.",
        )
    except PayPalError as e:
        payments_db.add_event(pid, "paypal_api", "Payout failed: the money is captured but not forwarded",
                              _error_detail(e))
        return payment
    batch = result.body.get("batch_header") or {}
    payments_db.add_event(pid, "paypal_api", "Payout sent to the recipient", {
        **result.call, "payout_batch_id": batch.get("payout_batch_id"), "batch_status": batch.get("batch_status"),
    })
    return payments_db.update_payment(pid, status="PAID_OUT", payout_batch_id=batch.get("payout_batch_id"))


def _cancel_held(payment: dict, why: str) -> dict:
    pid = payment["payment_id"]
    try:
        result = get_client().void_authorization(payment["authorization_id"], request_id=f"{pid}-void")
    except PayPalError as e:
        return _reconcile(payment, e, wanted="VOIDED")
    payments_db.add_event(pid, "paypal_api", "Cancelled: authorization voided, no money moved", {
        **result.call, "authorization_status": result.body.get("status"), "why": why,
    })
    return payments_db.update_payment(pid, status="VOIDED", hold_reason=None)


def _reconcile(payment: dict, error: PayPalError, *, wanted: str) -> dict:
    """A capture or void failed: ask PayPal what state the authorization is really in."""
    pid = payment["payment_id"]
    payments_db.add_event(pid, "paypal_api", f"{'Capture' if wanted == 'CAPTURED' else 'Void'} failed", _error_detail(error))
    try:
        auth = get_client().get_authorization(payment["authorization_id"])
    except PayPalError as e:
        raise GateError(502, f"PayPal didn't answer: {e.message}") from e
    status = auth.body.get("status")
    payments_db.add_event(pid, "paypal_api", "Checked the authorization at PayPal", {**auth.call, "authorization_status": status})
    if status in ("CAPTURED", "PARTIALLY_CAPTURED"):
        return payments_db.update_payment(pid, status="CAPTURED", hold_reason=None)
    if status in ("VOIDED", "EXPIRED"):
        return payments_db.update_payment(pid, status="VOIDED", hold_reason=None)
    if status == "DENIED":
        return payments_db.update_payment(pid, status="FAILED", hold_reason=None)
    raise GateError(502, f"PayPal refused: {error.message}")


# ----- reading -----

def view(payment: dict) -> dict:
    """The payment as the API returns it, with the policy text and the audit trail."""
    reason = payment["hold_reason"]
    policy = POLICY.get(reason, "").format(contact=payment["contact_name"], minutes=f"{COOL_OFF_MIN:g}") if reason else None
    held = payment["status"] == "HELD"
    return {
        "payment_id": payment["payment_id"],
        "session_id": payment["session_id"],
        "status": payment["status"],
        "hold_reason": reason,
        "policy": policy,
        "amount": payment["amount"],
        "currency": payment["currency"],
        "recipient_name": payment["recipient_name"],
        "recipient_email": payment["recipient_email"],
        "contact_name": payment["contact_name"],
        "contact_number": payment["contact_number"],
        "note": payment["note"],
        "paypal": {
            "order_id": payment["order_id"],
            "authorization_id": payment["authorization_id"],
            "capture_id": payment["capture_id"],
            "payout_batch_id": payment["payout_batch_id"],
        },
        "risk": json.loads(payment["risk_json"]) if payment["risk_json"] else None,
        "verification": payment["verification"],
        "release_at": payment["release_at"],
        "expires_at": payment["expires_at"],
        "created_at": payment["created_at"],
        "updated_at": payment["updated_at"],
        "can_verify": held and reason != "call_active" and payment["verification"] != "confirmed",
        "can_cancel": payment["status"] in ("CREATED", "HELD"),
        "events": payments_db.list_events(payment["payment_id"]),
    }


def summary(payment_view: dict) -> dict:
    """The short form kept in the call's evidence report."""
    keys = ("payment_id", "status", "hold_reason", "amount", "currency", "recipient_name", "verification")
    return {**{k: payment_view[k] for k in keys}, "paypal": payment_view["paypal"]}


def _get(payment_id: str) -> dict:
    payment = payments_db.get_payment(payment_id)
    if payment is None:
        raise GateError(404, "No payment with that id.")
    return payment


def _validate_amount(amount: str) -> str:
    try:
        value = Decimal(str(amount).replace(",", "").strip()).quantize(Decimal("0.01"))
    except InvalidOperation:
        raise GateError(422, "The amount must be a number, like 2400 or 49.99.") from None
    if value <= 0 or value > MAX_AMOUNT:
        raise GateError(422, f"The amount must be more than 0 and at most {MAX_AMOUNT}.")
    return f"{value:.2f}"


def _error_detail(e: PayPalError) -> dict:
    return {**(e.call or {}), "error": e.name, "issue": e.issue, "message": e.message, "debug_id": e.debug_id}
