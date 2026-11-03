# Step 3 (Live call):
#   POST /api/session/start      { caller_number, save_audio, scenario? } → { session_id, replay }
#   POST /api/session/{id}/stop  → the JSON report, with the call's Protected Send payments
#   POST /api/session/{id}/say   { text } → a replayed call hears it as the caller's words
#   GET  /api/session/{id}/risk  → the call's fused risk so far
#   GET  /api/session/scenarios  → calls that can be replayed without a phone
#   WS   /ws/live/{id}           the call's events; late joiners get the history replayed
#
# Judge mode (VERA_MODE=judge) and VERA_FAKE=1 always replay a scenario
# (app/feature/replay.py); otherwise a call is replayed only if `scenario` is given.

import asyncio
import os

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.feature import payment_gate, reports_db
from app.feature.audio_capture import AudioDeviceError
from app.feature.number_intelligence import DEFAULT_REGION
from app.feature.replay import ReplaySession, ScenarioNotFound, list_scenarios, load_scenario
from app.feature.session import Session

router = APIRouter(tags=["session"])

JUDGE_MODE = os.environ.get("VERA_MODE") == "judge"
ALWAYS_REPLAY = JUDGE_MODE or os.environ.get("VERA_FAKE") == "1"
DEFAULT_SCENARIO = os.environ.get("VERA_SCENARIO") or ("grandparent_us" if DEFAULT_REGION == "US" else "digital_arrest_in")

# Finished sessions stay so their report and history can still be read
SESSIONS: dict[str, Session] = {}


class StartRequest(BaseModel):
    caller_number: str | None = Field(None, max_length=32, examples=["+919876543210"])
    save_audio: bool = False
    # Replay this scenario instead of listening to the phone (always on in judge mode)
    scenario: str | None = Field(None, max_length=40, examples=["grandparent_us"])


class StartResponse(BaseModel):
    session_id: str
    replay: bool


class SayRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=300)


def finish(session: Session) -> dict:
    """End a call, let the payment gate decide the payments that waited for it, and save the report."""
    report = session.stop()
    payments = payment_gate.on_session_ended(session.id, report)
    if payments:
        report = {**report, "payments": [payment_gate.summary(p) for p in payments]}
        reports_db.save_report(report)
        session.report = report
    return report


@router.get("/api/session/scenarios")
def scenarios():
    return {"default": DEFAULT_SCENARIO, "always_replay": ALWAYS_REPLAY, "scenarios": list_scenarios()}


@router.post("/api/session/start", response_model=StartResponse)
async def start_session(body: StartRequest):
    # There is one phone and one audio input: a new call ends any call still running
    # (e.g. the dashboard was reloaded mid-call)
    for old in [s for s in SESSIONS.values() if s.active]:
        await run_in_threadpool(finish, old)

    loop = asyncio.get_running_loop()
    scenario_id = body.scenario or (DEFAULT_SCENARIO if ALWAYS_REPLAY else None)
    try:
        if scenario_id:
            session = ReplaySession(load_scenario(scenario_id), loop, caller_number=body.caller_number)
        else:
            session = Session(body.caller_number, body.save_audio, loop)
        await run_in_threadpool(session.start)
    except ScenarioNotFound as e:
        raise HTTPException(status_code=404, detail=f"No scenario called “{scenario_id}”.") from e
    except AudioDeviceError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    SESSIONS[session.id] = session
    return {"session_id": session.id, "replay": scenario_id is not None}


@router.post("/api/session/{session_id}/stop")
def stop_session(session_id: str):
    return finish(_get(session_id))


@router.post("/api/session/{session_id}/say", status_code=202)
def say(session_id: str, body: SayRequest):
    session = _get(session_id)
    if not isinstance(session, ReplaySession):
        raise HTTPException(status_code=409, detail="Only a replayed call can be typed into.")
    if not session.active:
        raise HTTPException(status_code=409, detail="The call has ended.")
    session.say(body.text)
    return {"heard": True}


@router.get("/api/session/{session_id}/risk")
def risk(session_id: str):
    session = SESSIONS.get(session_id)
    if session is not None and (session.active or session.report is None):
        return session.risk_snapshot()
    report = session.report if session is not None else reports_db.get_report(session_id)
    if report is None:
        raise HTTPException(status_code=404, detail="No session with that id.")
    return payment_gate.risk_from_report(report)


@router.websocket("/ws/live/{session_id}")
async def live(ws: WebSocket, session_id: str):
    session = SESSIONS.get(session_id)
    await ws.accept()
    if session is None:
        await ws.close(code=4404)
        return
    q = session.subscribe()
    try:
        while True:
            event = await q.get()
            await ws.send_json(event)
            if event["type"] == "ended":
                break
    except WebSocketDisconnect:
        pass
    finally:
        if q in session.subscribers:
            session.subscribers.remove(q)


def _get(session_id: str) -> Session:
    session = SESSIONS.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="No session with that id.")
    return session
