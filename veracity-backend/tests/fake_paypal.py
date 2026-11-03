# A small in-memory stand-in for the PayPal sandbox, plugged into PayPalClient
# through httpx.MockTransport. It keeps the parts of PayPal's behaviour the gate
# relies on: orders must be approved before they can be authorized, an
# authorization can be captured or voided once, PayPal-Request-Id makes a retry
# return the first answer, and webhook signatures are checked.

import json
from itertools import count

import httpx

from app.feature.paypal_client import PayPalClient


class FakePayPal:
    def __init__(self):
        self.orders: dict[str, dict] = {}
        self.auths: dict[str, dict] = {}
        self.requests: list[tuple[str, str, str | None]] = []  # (method, path, PayPal-Request-Id)
        self.verify_bodies: list[dict] = []
        self._ids = count(1)
        self._idempotent: dict[str, httpx.Response] = {}

    def client(self) -> PayPalClient:
        return PayPalClient("client-id", "secret", transport=httpx.MockTransport(self.handle))

    # ----- what a payer does in the PayPal pop-up -----

    def approve(self, order_id: str) -> None:
        self.orders[order_id]["status"] = "APPROVED"

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
        if request_id and response.status_code < 400:
            self._idempotent[request_id] = response
        return response

    def _route(self, method: str, path: str, body: dict) -> httpx.Response:
        parts = path.strip("/").split("/")
        if method == "POST" and path == "/v2/checkout/orders":
            assert body["intent"] == "AUTHORIZE"
            order_id = f"ORDER{next(self._ids)}"
            self.orders[order_id] = {"id": order_id, "status": "CREATED", "body": body}
            return httpx.Response(201, json={"id": order_id, "status": "CREATED"})
        if method == "POST" and parts[:3] == ["v2", "checkout", "orders"] and parts[-1] == "authorize":
            order = self.orders[parts[3]]
            if order["status"] != "APPROVED":
                return _error(422, "ORDER_NOT_APPROVED", "Payer has not yet approved the Order for payment.")
            auth_id = f"AUTH{next(self._ids)}"
            self.auths[auth_id] = {"id": auth_id, "status": "CREATED", "order_id": order["id"]}
            order["status"] = "COMPLETED"
            return httpx.Response(201, json={"id": order["id"], "status": "COMPLETED", "purchase_units": [{
                "payments": {"authorizations": [{"id": auth_id, "status": "CREATED",
                                                 "expiration_time": "2026-12-02T10:00:00Z"}]},
            }]})
        if parts[:3] == ["v2", "payments", "authorizations"]:
            auth = self.auths[parts[3]]
            if method == "GET":
                return httpx.Response(200, json={"id": auth["id"], "status": auth["status"]})
            if parts[-1] == "capture":
                if auth["status"] != "CREATED":
                    issue = "AUTHORIZATION_ALREADY_CAPTURED" if auth["status"] == "CAPTURED" else "AUTHORIZATION_VOIDED"
                    return _error(422, issue, f"Authorization is {auth['status']}.")
                auth["status"] = "CAPTURED"
                return httpx.Response(201, json={"id": f"CAPTURE{next(self._ids)}", "status": "COMPLETED"})
            if parts[-1] == "void":
                if auth["status"] != "CREATED":
                    issue = "PREVIOUSLY_CAPTURED" if auth["status"] == "CAPTURED" else "PREVIOUSLY_VOIDED"
                    return _error(422, issue, f"Authorization is {auth['status']}.")
                auth["status"] = "VOIDED"
                return httpx.Response(200, json={"id": auth["id"], "status": "VOIDED"})
        if method == "POST" and path == "/v1/payments/payouts":
            return httpx.Response(201, json={"batch_header": {
                "payout_batch_id": f"BATCH{next(self._ids)}", "batch_status": "PENDING",
            }})
        if method == "POST" and path == "/v1/notifications/verify-webhook-signature":
            self.verify_bodies.append(body)
            ok = body.get("transmission_sig") == "good-signature" and isinstance(body.get("webhook_event"), dict)
            return httpx.Response(200, json={"verification_status": "SUCCESS" if ok else "FAILURE"})
        return _error(404, "RESOURCE_NOT_FOUND", f"No fake for {method} {path}")


def _error(status: int, issue: str, description: str) -> httpx.Response:
    return httpx.Response(status, headers={"paypal-debug-id": "debug123"}, json={
        "name": "UNPROCESSABLE_ENTITY" if status == 422 else "ERROR",
        "message": "The requested action could not be performed.",
        "debug_id": "debug123",
        "details": [{"issue": issue, "description": description}],
    })
