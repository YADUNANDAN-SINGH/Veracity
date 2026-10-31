# Step 3 (Live call):
#   POST /api/session/start      { caller_number, save_audio } → { session_id }
#   POST /api/session/{id}/stop  → the JSON report
#   WS   /ws/live/{id}           the call's events; late joiners get the history replayed

import asyncio

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.feature.audio_capture import AudioDeviceError
from app.feature.session import Session

router = APIRouter(tags=["session"])

# Finished sessions stay so their report and history can still be read
SESSIONS: dict[str, Session] = {}


class StartRequest(BaseModel):
    caller_number: str | None = Field(None, max_length=32, examples=["+919876543210"])
    save_audio: bool = False


class StartResponse(BaseModel):
    session_id: str


@router.post("/api/session/start", response_model=StartResponse)
async def start_session(body: StartRequest):
    # There is one phone and one audio input: a new call ends any call still running
    # (e.g. the dashboard was reloaded mid-call)
    for old in [s for s in SESSIONS.values() if s.active]:
        await run_in_threadpool(old.stop)

    loop = asyncio.get_running_loop()
    try:
        session = Session(body.caller_number, body.save_audio, loop)
        await run_in_threadpool(session.start)
    except AudioDeviceError as e:
        raise HTTPException(status_code=503, detail=str(e))
    SESSIONS[session.id] = session
    return {"session_id": session.id}


@router.post("/api/session/{session_id}/stop")
def stop_session(session_id: str):
    session = SESSIONS.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="No session with that id.")
    return session.stop()


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
