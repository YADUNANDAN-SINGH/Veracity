# PayPal for the tests: the app's in-memory stand-in (app/feature/paypal_standin.py)
# with short, predictable ids, and webhook signatures that a test can get right.

from itertools import count

import httpx

from app.feature.paypal_standin import PayPalStandIn


class FakePayPal(PayPalStandIn):
    def __init__(self):
        super().__init__()
        self.verify_bodies: list[dict] = []
        self._ids = count(1)

    def _new_id(self, kind: str) -> str:
        return f"{kind}{next(self._ids)}"

    def _debug_id(self) -> str:
        return "debug123"

    def _route(self, method: str, path: str, body: dict) -> httpx.Response:
        if method == "POST" and path == "/v1/notifications/verify-webhook-signature":
            self.verify_bodies.append(body)
            ok = body.get("transmission_sig") == "good-signature" and isinstance(body.get("webhook_event"), dict)
            return httpx.Response(200, json={"verification_status": "SUCCESS" if ok else "FAILURE"})
        return super()._route(method, path, body)
