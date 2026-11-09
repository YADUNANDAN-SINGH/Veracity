# Protected Send: the PayPal payment gate (app/feature/payment_gate.py).
#
#   GET  /api/payment/config                       PayPal client id for the browser, policy numbers
#   POST /api/payment/orders                       { amount, currency, recipient_name, ... session_id }
#                                                  → PayPal order with intent AUTHORIZE
#   POST /api/payment/orders/{order_id}/standin-approve  the PayPal stand-in only: what the pop-up does
#   POST /api/payment/orders/{order_id}/authorize  after the payer approves in PayPal → held or released
#   GET  /api/payment/{id}                         the payment, its policy and its PayPal audit trail
#   POST /api/payment/{id}/verify                  { outcome: "confirmed" | "denied" } after a callback
#   POST /api/payment/{id}/cancel                  void the authorization
#   GET  /api/payment?session_id=…                 the payments made during one call
#   POST /api/paypal/webhook                       PayPal events, signature-verified

import json
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.feature import payment_gate, payments_db, paypal_client, paypal_standin, reports_db
from app.feature.payment_gate import GateError
from app.feature.paypal_client import PayPalError, PayPalNotConfigured
from app.routes.session import SESSIONS

router = APIRouter(tags=["payment"])


def _live_risk(session_id: str) -> dict | None:
    """The call's risk right now: from the live session, or from its saved report once it has ended."""
    session = SESSIONS.get(session_id)
    if session is not None:
        if session.active or session.report is None:
            return session.risk_snapshot()
        return payment_gate.risk_from_report(session.report)
    report = reports_db.get_report(session_id)
    return payment_gate.risk_from_report(report) if report else None


payment_gate.set_risk_provider(_live_risk)


class CreatePayment(BaseModel):
    amount: str = Field(..., max_length=16, examples=["2400.00"])
    currency: str = Field("USD", min_length=3, max_length=3)
    recipient_name: str = Field(..., min_length=1, max_length=80, examples=["Jake (grandson)"])
    recipient_email: str | None = Field(None, max_length=254)
    contact_name: str | None = Field(None, max_length=80, examples=["Jake"])
    contact_number: str | None = Field(None, max_length=32, examples=["+1 213 555 0172"])
    note: str | None = Field(None, max_length=200)
    session_id: str | None = Field(None, max_length=64)


class VerifyRequest(BaseModel):
    outcome: str = Field(..., examples=["confirmed", "denied"])


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except GateError as e:
        raise HTTPException(status_code=e.status, detail=e.message) from e
    except PayPalNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except PayPalError as e:
        raise HTTPException(status_code=502, detail=f"PayPal: {e.message}") from e


@router.get("/api/payment/config")
def payment_config():
    configured, standin = paypal_client.configured(), paypal_client.standin_active()
    return {
        "enabled": configured or standin,
        "standin": standin,  # no PayPal button: the dashboard approves through the route below
        "environment": "standin" if standin else "sandbox",
        "client_id": os.environ.get("PAYPAL_CLIENT_ID") if configured else None,  # public by design
        "currency": os.environ.get("VERA_CURRENCY", "USD"),
        "currencies": sorted(payment_gate.CURRENCIES),
        "payouts": payment_gate.PAYOUTS_ENABLED,
        "webhooks": bool(os.environ.get("PAYPAL_WEBHOOK_ID")),
        "hold_hours": payment_gate.HOLD_HOURS,
        "cool_off_min": payment_gate.COOL_OFF_MIN,
    }


@router.post("/api/payment/orders", status_code=201)
def create_order(body: CreatePayment):
    payment = _run(payment_gate.create, **body.model_dump())
    return payment_gate.view(payment)


@router.post("/api/payment/orders/{order_id}/standin-approve")
def standin_approve(order_id: str):
    """What the payer does in PayPal's pop-up. Only exists while the stand-in is answering for PayPal."""
    if not paypal_client.standin_active() or not paypal_standin.shared().approve(order_id):
        raise HTTPException(status_code=404, detail="No stand-in order with that id.")
    return {"approved": True}


@router.post("/api/payment/orders/{order_id}/authorize")
def authorize_order(order_id: str):
    payment = payments_db.find_by_order(order_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="No payment for that PayPal order.")
    return payment_gate.view(_run(payment_gate.authorize, payment["payment_id"]))


@router.get("/api/payment")
def list_payments(session_id: str | None = None):
    payments = [_run(payment_gate.refresh, p["payment_id"]) for p in payments_db.list_payments(session_id)]
    return [payment_gate.view(p) for p in payments]


@router.get("/api/payment/{payment_id}")
def get_payment(payment_id: str):
    return payment_gate.view(_run(payment_gate.refresh, payment_id))


@router.post("/api/payment/{payment_id}/verify")
def verify_payment(payment_id: str, body: VerifyRequest):
    return payment_gate.view(_run(payment_gate.verify, payment_id, body.outcome))


@router.post("/api/payment/{payment_id}/cancel")
def cancel_payment(payment_id: str):
    return payment_gate.view(_run(payment_gate.cancel, payment_id))


@router.post("/api/paypal/webhook")
async def paypal_webhook(request: Request):
    webhook_id = os.environ.get("PAYPAL_WEBHOOK_ID")
    if not webhook_id:
        raise HTTPException(status_code=503, detail="Webhooks aren't set up (PAYPAL_WEBHOOK_ID).")
    raw = (await request.body()).decode("utf-8")
    try:
        client = paypal_client.get_client()
        verified = await run_in_threadpool(client.verify_webhook_signature, dict(request.headers), raw, webhook_id)
    except (PayPalError, PayPalNotConfigured) as e:
        raise HTTPException(status_code=502, detail=f"Couldn't verify the webhook: {e}") from e
    if not verified:
        raise HTTPException(status_code=400, detail="Webhook signature didn't verify.")
    try:
        event = json.loads(raw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Webhook body isn't JSON.") from e
    payment = await run_in_threadpool(payment_gate.apply_webhook, event)
    return {"handled": payment is not None}
