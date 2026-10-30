# GET /api/call/state: polled by Step 2 (Check number) so an incoming cellular
# call fills in the caller's number automatically.

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.feature.call_state import PhoneNotConnectedError, get_call_state

router = APIRouter(prefix="/api/call", tags=["call"])


class CallStateResponse(BaseModel):
    connected: bool
    state: Literal["idle", "ringing", "in_call"]
    # None when there's no call, or the phone hides the number (common on Android 12+)
    number: str | None


@router.get("/state", response_model=CallStateResponse)
def call_state():
    try:
        return {"connected": True, **get_call_state()}
    except PhoneNotConnectedError:
        # Not an error for the dashboard: it just shows "phone not connected"
        return {"connected": False, "state": "idle", "number": None}
