# Step 3 (Live call):
#   POST /api/session/start      { caller_number, save_audio, scenario? } → { session_id, replay }
#   POST /api/session/upload     multipart: file, caller_number? → { session_id, replay, upload, duration_s }
#   POST /api/session/{id}/stop  → the JSON report, with the call's Protected Send payments
#   POST /api/session/{id}/say   { text } → a replayed call hears it as the caller's words
#   GET  /api/session/{id}/risk  → the call's fused risk so far
#   GET  /api/session/scenarios  → calls that can be replayed without a phone
#   GET  /api/session/scenarios/{id}/audio  → a recorded scenario's audio file, to play along with its replay
#   WS   /ws/live/{id}           the call's events; late joiners get the history replayed
#
# Judge mode (VERA_MODE=judge) and VERA_FAKE=1 always replay a scenario
# (app/feature/replay.py); otherwise a call is replayed only if `scenario` is given.
# An upload runs a recording through the real models (app/feature/upload.py) and
# needs the full judge build (Dockerfile.judge).

import asyncio
import os
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.feature import payment_gate, reports_db, upload
from app.feature.audio_capture import AudioDeviceError
from app.feature import file_capture
from app.feature.file_capture import DecodeError, FileCapture, TooLong
from app.feature.number_intelligence import DEFAULT_REGION
from app.feature.replay import ReplaySession, ScenarioNotFound, audio_path, audio_type, list_scenarios, load_scenario
from app.feature.session import Session

router = APIRouter(tags=["session"])

JUDGE_MODE = os.environ.get("VERA_MODE") == "judge"
ALWAYS_REPLAY = JUDGE_MODE or os.environ.get("VERA_FAKE") == "1"
DEFAULT_SCENARIO = os.environ.get("VERA_SCENARIO") or ("grandparent_us" if DEFAULT_REGION == "US" else "digital_arrest_in")

# Finished sessions stay so their report and history can still be read
SESSIONS: dict[str, Session] = {}

# One upload at a time: two Whisper jobs at once would slow a judge's laptop to a crawl
_upload_lock = asyncio.Lock()


class StartRequest(BaseModel):
    caller_number: str | None = Field(None, max_length=32, examples=["+919876543210"])
    save_audio: bool = False
    # Replay this scenario instead of listening to the phone (always on in judge mode)
    scenario: str | None = Field(None, max_length=40, examples=["grandparent_us"])


class StartResponse(BaseModel):
    session_id: str
    replay: bool


class UploadResponse(StartResponse):
    upload: bool
    duration_s: float


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


@router.get("/api/session/scenarios/{scenario_id}/audio")
def scenario_audio(scenario_id: str):
    try:
        path = audio_path(load_scenario(scenario_id))
    except ScenarioNotFound as e:
        raise HTTPException(status_code=404, detail="No scenario with that id.") from e
    if path is None:
        raise HTTPException(status_code=404, detail="This scenario has no recording here.")
    # Answers Range requests, so the browser can seek to the replay's position
    return FileResponse(path, media_type=audio_type(path))


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


@router.post("/api/session/upload", response_model=UploadResponse)
async def upload_session(request: Request):
    """An uploaded call recording, analysed like a live call: multipart `file` and an optional `caller_number`."""
    available, reason = upload.availability()
    if not available:
        detail = (
            "Uploading a recording needs the full judge build: docker compose --profile judge up --build judge."
            if reason == upload.NEEDS_FULL_BUILD else f"Uploads aren't available right now: {reason}."
        )
        raise HTTPException(status_code=503, detail=detail)
    if _upload_lock.locked() or any(isinstance(s, upload.UploadSession) and s.active for s in SESSIONS.values()):
        raise HTTPException(status_code=409, detail=BUSY)
    max_bytes = int(upload.MAX_MB * 1024 * 1024)
    # Refuse an oversized upload before it is read, when the browser says how big it is
    if int(request.headers.get("content-length") or 0) > max_bytes + 64 * 1024:
        raise HTTPException(status_code=413, detail=_too_big(upload.MAX_MB))

    async with _upload_lock:
        saved = await _save_upload(request, max_bytes)
        try:
            capture = await run_in_threadpool(FileCapture, saved["path"])  # decodes, then deletes the file
        except TooLong as e:
            raise HTTPException(status_code=422, detail=f"Recordings can be up to {_max_length()} long: {e}.") from e
        except DecodeError as e:
            raise HTTPException(status_code=422, detail=f"Couldn't read this audio file: {e}.") from e
        finally:
            Path(saved["path"]).unlink(missing_ok=True)  # already gone unless decoding never started

        # Like /start: a new call ends any call still running (a replay left open in another tab)
        for old in [s for s in SESSIONS.values() if s.active]:
            await run_in_threadpool(finish, old)
        session = upload.UploadSession(capture, saved["filename"], asyncio.get_running_loop(),
                                       caller_number=saved["caller_number"])
        await run_in_threadpool(session.start)
        SESSIONS[session.id] = session
    return {"session_id": session.id, "replay": False, "upload": True, "duration_s": capture.duration_s}


BUSY = "Another uploaded recording is still being analysed. End that call first, then upload again."


def _too_big(max_mb: float) -> str:
    return f"The file is too big: uploads can be up to {max_mb:g} MB."


def _max_length() -> str:
    max_s = file_capture.MAX_S
    return f"{max_s / 60:g} minutes" if max_s >= 60 else f"{max_s:g} s"


async def _save_upload(request: Request, max_bytes: int) -> dict:
    """The multipart form → the file in a temp file of our own (ffmpeg needs a seekable file for m4a)."""
    try:
        form = await request.form(max_files=1, max_fields=4)
    except Exception as e:  # not multipart, or python-multipart isn't installed
        raise HTTPException(status_code=400, detail="Send the recording as a multipart form with a `file` field.") from e
    try:
        file = form.get("file")
        if file is None or isinstance(file, str) or not file.filename:
            raise HTTPException(status_code=422, detail="Choose an audio file to upload.")
        ext = Path(file.filename).suffix.lower().lstrip(".")
        if ext not in upload.EXTENSIONS:
            allowed = ", ".join(upload.EXTENSIONS[:-1]) + " or " + upload.EXTENSIONS[-1]
            raise HTTPException(status_code=415, detail=f"Upload a {allowed} file; “.{ext or '?'}” isn't supported.")
        if file.size is not None and file.size > max_bytes:
            raise HTTPException(status_code=413, detail=_too_big(upload.MAX_MB))
        number = form.get("caller_number")
        number = number.strip()[:32] if isinstance(number, str) and number.strip() else None

        fd, tmp = tempfile.mkstemp(prefix="veracity-upload-", suffix=f".{ext}")
        with os.fdopen(fd, "wb") as out:
            await run_in_threadpool(shutil.copyfileobj, file.file, out)
        if os.path.getsize(tmp) > max_bytes:  # no size from the browser: checked once it's here
            Path(tmp).unlink(missing_ok=True)
            raise HTTPException(status_code=413, detail=_too_big(upload.MAX_MB))
        return {"path": tmp, "filename": Path(file.filename).name[:120], "caller_number": number}
    finally:
        await form.close()


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
