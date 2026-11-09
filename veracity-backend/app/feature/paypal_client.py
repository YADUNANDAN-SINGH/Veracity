# PayPal REST client for the payment gate. Sandbox only: this is a prototype
# and must never move real money.
#
#   OAuth 2.0     POST /v1/oauth2/token                           client-credentials token, cached
#   Orders v2     POST /v2/checkout/orders                        intent AUTHORIZE: money is held, not sent
#                 POST /v2/checkout/orders/{id}/authorize         after the payer approves in PayPal
#   Payments v2   POST /v2/payments/authorizations/{id}/capture   release the held money
#                 POST /v2/payments/authorizations/{id}/void      cancel: the money never moves
#                 GET  /v2/payments/authorizations/{id}           reconcile after an error
#   Payouts v1    POST /v1/payments/payouts                       optional: forward a release to the recipient
#   Webhooks      POST /v1/notifications/verify-webhook-signature
#
# Every POST that changes money carries a PayPal-Request-Id, so a retried
# request can't authorize, capture or void twice. Each call returns the
# response body and a short record of the call (method, path, status,
# PayPal debug id, time), which the gate keeps as the payment's audit trail.
#
# Without sandbox keys, VERA_PAYPAL_STANDIN=1 (the Docker judge build) answers
# these same calls in memory (app/feature/paypal_standin.py); keys always win.

import json
import logging
import os
import threading
import time
from dataclasses import dataclass

import httpx

log = logging.getLogger("veracity.paypal")

SANDBOX_BASE = "https://api-m.sandbox.paypal.com"
STANDIN_PREFIX = "STANDIN-"  # every id the stand-in makes up starts with this
TOKEN_MARGIN_S = 60  # refresh the token a minute before PayPal says it expires


class PayPalError(RuntimeError):
    """A failed PayPal call. `issue` is PayPal's specific reason, e.g. AUTHORIZATION_ALREADY_CAPTURED."""

    def __init__(self, status: int | None, name: str, message: str, issue: str | None = None,
                 debug_id: str | None = None, call: dict | None = None):
        super().__init__(f"{name}: {message}")
        self.status = status
        self.name = name
        self.message = message
        self.issue = issue
        self.debug_id = debug_id
        self.call = call


class PayPalNotConfigured(RuntimeError):
    """PAYPAL_CLIENT_ID or PAYPAL_CLIENT_SECRET is missing."""


@dataclass
class Result:
    body: dict
    call: dict  # {method, path, status, debug_id, ms}


class PayPalClient:
    def __init__(self, client_id: str, client_secret: str, *, base_url: str = SANDBOX_BASE,
                 transport: httpx.BaseTransport | None = None, timeout: float = 20.0):
        self.client_id = client_id
        self._secret = client_secret
        self._http = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)
        self._token: str | None = None
        self._token_expires = 0.0
        self._lock = threading.Lock()

    # ----- auth -----

    def _access_token(self, refresh: bool = False) -> str:
        with self._lock:
            if not refresh and self._token and time.monotonic() < self._token_expires:
                return self._token
            try:
                resp = self._http.post(
                    "/v1/oauth2/token",
                    auth=(self.client_id, self._secret),
                    data={"grant_type": "client_credentials"},
                    headers={"Accept": "application/json"},
                )
            except httpx.HTTPError as e:
                raise PayPalError(None, "NETWORK_ERROR", f"Couldn't reach PayPal: {e}") from e
            if resp.status_code != 200:
                body = _json(resp)
                raise PayPalError(
                    resp.status_code, body.get("error", "AUTHENTICATION_FAILURE"),
                    body.get("error_description", "PayPal rejected the app credentials"),
                    debug_id=resp.headers.get("paypal-debug-id"),
                )
            body = resp.json()
            self._token = body["access_token"]
            self._token_expires = time.monotonic() + max(0, int(body.get("expires_in", 0)) - TOKEN_MARGIN_S)
            return self._token

    # ----- one request -----

    def _request(self, method: str, path: str, *, body: dict | None = None, raw: str | None = None,
                 request_id: str | None = None, retry_auth: bool = True) -> Result:
        headers = {
            "Authorization": f"Bearer {self._access_token()}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",  # void and capture answer with the object, not 204
        }
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        content = raw if raw is not None else (json.dumps(body) if body is not None else None)

        started = time.monotonic()
        try:
            resp = self._http.request(method, path, content=content, headers=headers)
        except httpx.HTTPError as e:
            call = {"method": method, "path": path, "status": None, "debug_id": None, "ms": _ms(started)}
            raise PayPalError(None, "NETWORK_ERROR", f"Couldn't reach PayPal: {e}", call=call) from e

        call = {
            "method": method, "path": path, "status": resp.status_code,
            "debug_id": resp.headers.get("paypal-debug-id"), "ms": _ms(started),
        }
        if resp.status_code == 401 and retry_auth:  # token revoked or expired early
            self._access_token(refresh=True)
            return self._request(method, path, body=body, raw=raw, request_id=request_id, retry_auth=False)
        if resp.status_code >= 400:
            err = _json(resp)
            details = err.get("details") or [{}]
            issue = details[0].get("issue")
            message = details[0].get("description") or err.get("message") or f"HTTP {resp.status_code}"
            raise PayPalError(resp.status_code, err.get("name", "PAYPAL_ERROR"), message, issue=issue,
                              debug_id=err.get("debug_id") or call["debug_id"], call=call)
        return Result(body=_json(resp), call=call)

    # ----- Orders v2 -----

    def create_order(self, *, amount: str, currency: str, reference_id: str, custom_id: str,
                     description: str, request_id: str) -> Result:
        """An order with intent AUTHORIZE: the payer approves, then funds are only reserved."""
        return self._request("POST", "/v2/checkout/orders", request_id=request_id, body={
            "intent": "AUTHORIZE",
            "purchase_units": [{
                "reference_id": reference_id,
                "custom_id": custom_id[:127],
                "description": description[:127],
                "amount": {"currency_code": currency, "value": amount},
            }],
            "payment_source": {"paypal": {"experience_context": {
                "brand_name": "Veracity Protected Send",
                "shipping_preference": "NO_SHIPPING",
                "user_action": "CONTINUE",
            }}},
        })

    def authorize_order(self, order_id: str, *, request_id: str) -> Result:
        return self._request("POST", f"/v2/checkout/orders/{order_id}/authorize", body={}, request_id=request_id)

    def get_order(self, order_id: str) -> Result:
        return self._request("GET", f"/v2/checkout/orders/{order_id}")

    # ----- Payments v2 -----

    def capture_authorization(self, authorization_id: str, *, request_id: str) -> Result:
        return self._request(
            "POST", f"/v2/payments/authorizations/{authorization_id}/capture",
            body={"final_capture": True}, request_id=request_id,
        )

    def void_authorization(self, authorization_id: str, *, request_id: str) -> Result:
        return self._request("POST", f"/v2/payments/authorizations/{authorization_id}/void", body={},
                             request_id=request_id)

    def get_authorization(self, authorization_id: str) -> Result:
        return self._request("GET", f"/v2/payments/authorizations/{authorization_id}")

    # ----- Payouts v1 -----

    def create_payout(self, *, sender_batch_id: str, receiver_email: str, amount: str, currency: str,
                      note: str) -> Result:
        return self._request("POST", "/v1/payments/payouts", request_id=sender_batch_id, body={
            "sender_batch_header": {
                "sender_batch_id": sender_batch_id,
                "email_subject": "You received a payment held by Veracity",
                "email_message": note[:1000],
            },
            "items": [{
                "recipient_type": "EMAIL",
                "receiver": receiver_email,
                "amount": {"value": amount, "currency": currency},
                "note": note[:4000],
                "sender_item_id": sender_batch_id,
            }],
        })

    # ----- Webhooks -----

    def verify_webhook_signature(self, headers: dict[str, str], raw_body: str, webhook_id: str) -> bool:
        """Ask PayPal whether this webhook really came from it.

        The event goes in exactly as received: re-serialising the JSON changes its
        bytes and makes PayPal's check fail, so the request body is built by hand.
        """
        h = {k.lower(): v for k, v in headers.items()}
        fields = {
            "auth_algo": h.get("paypal-auth-algo", ""),
            "cert_url": h.get("paypal-cert-url", ""),
            "transmission_id": h.get("paypal-transmission-id", ""),
            "transmission_sig": h.get("paypal-transmission-sig", ""),
            "transmission_time": h.get("paypal-transmission-time", ""),
            "webhook_id": webhook_id,
        }
        if not all(fields.values()):
            return False
        raw = json.dumps(fields)[:-1] + f', "webhook_event": {raw_body}}}'
        result = self._request("POST", "/v1/notifications/verify-webhook-signature", raw=raw)
        return result.body.get("verification_status") == "SUCCESS"


def _json(resp: httpx.Response) -> dict:
    try:
        body = resp.json()
        return body if isinstance(body, dict) else {}
    except ValueError:
        return {}


def _ms(started: float) -> int:
    return round((time.monotonic() - started) * 1000)


# ----- the app's one client -----

_client: PayPalClient | None = None
_client_lock = threading.Lock()


def configured() -> bool:
    return bool(os.environ.get("PAYPAL_CLIENT_ID") and os.environ.get("PAYPAL_CLIENT_SECRET"))


def standin_active() -> bool:
    """No sandbox keys, and this build answers PayPal's calls with the in-memory stand-in."""
    return os.environ.get("VERA_PAYPAL_STANDIN") == "1" and not configured()


def environment_of(order_id: str | None) -> str:
    """Who answered for this order: "standin" or the PayPal "sandbox". The report keeps it, so nobody mistakes one for the other."""
    return "standin" if (order_id or "").startswith(STANDIN_PREFIX) else "sandbox"


def get_client() -> PayPalClient:
    """The sandbox client built from PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET, or the stand-in without them."""
    global _client
    with _client_lock:
        if _client is None:
            if standin_active():
                from app.feature import paypal_standin

                log.warning("No PayPal sandbox keys: Protected Send uses the in-memory stand-in, not PayPal")
                _client = paypal_standin.shared().client()
                return _client
            if not configured():
                raise PayPalNotConfigured(
                    "PayPal isn't set up: put PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET from a sandbox app in .env"
                )
            if os.environ.get("PAYPAL_ENV", "sandbox") != "sandbox":
                log.warning("PAYPAL_ENV=%s ignored: Veracity only talks to the PayPal sandbox", os.environ["PAYPAL_ENV"])
            _client = PayPalClient(os.environ["PAYPAL_CLIENT_ID"], os.environ["PAYPAL_CLIENT_SECRET"])
        return _client


def set_client(client: PayPalClient | None) -> None:
    """Swap the client (tests use one with a mock transport)."""
    global _client
    with _client_lock:
        _client = client
