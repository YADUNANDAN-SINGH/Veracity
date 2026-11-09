# A PayPal stand-in for trying Protected Send without sandbox keys. On with
# VERA_PAYPAL_STANDIN=1 (the Docker judge build's default); sandbox keys always win.
#
# It plugs into the real PayPalClient through httpx.MockTransport, so the payment
# gate makes exactly the same calls as against the sandbox and only the answers are
# local. It keeps the parts of PayPal's behaviour the gate relies on: orders must be
# approved before they can be authorized, an authorization can be captured or voided
# once, and PayPal-Request-Id makes a retry return the first answer.
#
# This is not PayPal. Nothing leaves the machine, state lives in memory, there is no
# pop-up or buyer login, and the ids and debug ids are made up: every one starts with
# STANDIN- or standin-, and the dashboard and the report say so.

import json
import threading
import uuid
from datetime import datetime, timedelta, timezone

import httpx

from app.feature.paypal_client import STANDIN_PREFIX, PayPalClient


class PayPalStandIn:
    def __init__(self):
        self.orders: dict[str, dict] = {}
        self.auths: dict[str, dict] = {}
        self.requests: list[tuple[str, str, str | None]] = []  # (method, path, PayPal-Request-Id)
        self._idempotent: dict[str, httpx.Response] = {}

    def client(self) -> PayPalClient:
        return PayPalClient("standin-client", "standin-secret", transport=httpx.MockTransport(self.handle))

    # ----- what a payer does in the PayPal pop-up -----

    def approve(self, order_id: str) -> bool:
        order = self.orders.get(order_id)
        if order is None:
            return False
        order["status"] = "APPROVED"
        return True

    # ----- made-up ids -----

    def _new_id(self, kind: str) -> str:
        return f"{STANDIN_PREFIX}{kind}-{uuid.uuid4().hex[:12].upper()}"

    def _debug_id(self) -> str:
        return f"{STANDIN_PREFIX.lower()}{uuid.uuid4().hex[:13]}"

    # ----- the HTTP side -----

    def handle(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        request_id = request.headers.get("paypal-request-id")
        self.requests.append((method, path, request_id))
        if path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "A21-test", "expires_in": 32400})
        if request.headers.get("authorization") != "Bearer A21-test":
            return httpx.Response(401, json={"name": "AUTHENTICATION_FAILURE", "message": "no token"})
        if request_id and request_id in self._idempotent:
            return self._idempotent[request_id]

        response = self._route(method, path, json.loads(request.content) if request.content else {})
        # PayPal puts a debug id on every answer, and the audit trail shows it
        response.headers.setdefault("paypal-debug-id", self._debug_id())
        if request_id and response.status_code < 400:
            self._idempotent[request_id] = response
        return response

    def _route(self, method: str, path: str, body: dict) -> httpx.Response:
        parts = path.strip("/").split("/")
        if method == "POST" and path == "/v2/checkout/orders":
            if body.get("intent") != "AUTHORIZE":
                return self._error(422, "INVALID_INTENT", "Veracity only ever creates AUTHORIZE orders.")
            order_id = self._new_id("ORDER")
            self.orders[order_id] = {"id": order_id, "status": "CREATED", "body": body}
            return httpx.Response(201, json={"id": order_id, "status": "CREATED"})
        if method == "POST" and parts[:3] == ["v2", "checkout", "orders"] and parts[-1] == "authorize":
            order = self.orders.get(parts[3])
            if order is None:
                return self._not_found(path)
            if order["status"] != "APPROVED":
                return self._error(422, "ORDER_NOT_APPROVED", "Payer has not yet approved the Order for payment.")
            auth_id = self._new_id("AUTH")
            self.auths[auth_id] = {"id": auth_id, "status": "CREATED", "order_id": order["id"]}
            order["status"] = "COMPLETED"
            expires = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
            return httpx.Response(201, json={"id": order["id"], "status": "COMPLETED", "purchase_units": [{
                "payments": {"authorizations": [{"id": auth_id, "status": "CREATED", "expiration_time": expires}]},
            }]})
        if parts[:3] == ["v2", "payments", "authorizations"]:
            auth = self.auths.get(parts[3])
            if auth is None:  # state is in memory: a payment from before a restart isn't known any more
                return self._not_found(path)
            if method == "GET":
                return httpx.Response(200, json={"id": auth["id"], "status": auth["status"]})
            if parts[-1] == "capture":
                if auth["status"] != "CREATED":
                    issue = "AUTHORIZATION_ALREADY_CAPTURED" if auth["status"] == "CAPTURED" else "AUTHORIZATION_VOIDED"
                    return self._error(422, issue, f"Authorization is {auth['status']}.")
                auth["status"] = "CAPTURED"
                return httpx.Response(201, json={"id": self._new_id("CAPTURE"), "status": "COMPLETED"})
            if parts[-1] == "void":
                if auth["status"] != "CREATED":
                    issue = "PREVIOUSLY_CAPTURED" if auth["status"] == "CAPTURED" else "PREVIOUSLY_VOIDED"
                    return self._error(422, issue, f"Authorization is {auth['status']}.")
                auth["status"] = "VOIDED"
                return httpx.Response(200, json={"id": auth["id"], "status": "VOIDED"})
        if method == "POST" and path == "/v1/payments/payouts":
            return httpx.Response(201, json={"batch_header": {
                "payout_batch_id": self._new_id("BATCH"), "batch_status": "PENDING",
            }})
        if method == "POST" and path == "/v1/notifications/verify-webhook-signature":
            return httpx.Response(200, json={"verification_status": "FAILURE"})  # nothing real ever signs one
        return self._not_found(f"{method} {path}")

    def _not_found(self, what: str) -> httpx.Response:
        return self._error(404, "RESOURCE_NOT_FOUND", f"The PayPal stand-in has no {what}.")

    def _error(self, status: int, issue: str, description: str) -> httpx.Response:
        debug_id = self._debug_id()
        return httpx.Response(status, headers={"paypal-debug-id": debug_id}, json={
            "name": "UNPROCESSABLE_ENTITY" if status == 422 else "ERROR",
            "message": "The requested action could not be performed.",
            "debug_id": debug_id,
            "details": [{"issue": issue, "description": description}],
        })


_shared: PayPalStandIn | None = None
_shared_lock = threading.Lock()


def shared() -> PayPalStandIn:
    """The app's one stand-in: orders made through the client are approved through the same object."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = PayPalStandIn()
        return _shared
