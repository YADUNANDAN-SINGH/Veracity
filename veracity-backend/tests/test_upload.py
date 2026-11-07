# Uploaded call recordings (the full judge build) through the real API: the
# file is decoded by ffmpeg and runs through the same Session pipeline as a live
# call. The voice model and Whisper are stand-ins, as in test_replay.py, so no
# torch or model download is needed; everything after them is real.

import io
import shutil
import tempfile
import threading
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy.io import wavfile

import main
from app.feature import file_capture, payment_gate, paypal_client, transcriber, upload, voice
from app.routes import health as health_routes
from app.routes import session as session_routes
from tests.fake_paypal import FakePayPal

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg isn't installed")

LINES = [
    "Grandma, it's me, Jake. I'm in jail and I need bail money right now.",
    "Don't tell Mom. Send it on PayPal, please.",
]


class FakeDetector:
    """Stands in for Spectra-0: every window sounds AI-generated."""

    def p_fake(self, x16k):
        return 0.9


@pytest.fixture
def upload_dir(tmp_path, monkeypatch):
    """Where the route writes its temp copy of the upload, so the test can check it's gone."""
    d = tmp_path / "tmp"
    d.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(d))
    return d


@pytest.fixture
def api(tmp_path, monkeypatch, upload_dir):
    monkeypatch.setenv("VERA_DB", str(tmp_path / "test.db"))
    monkeypatch.setattr(main, "JUDGE_MODE", True)
    monkeypatch.setattr(upload, "ENABLED", True)
    monkeypatch.setattr(upload, "models_installed", lambda: True)
    monkeypatch.setattr(upload, "ffmpeg_found", lambda: True)
    monkeypatch.setattr(voice, "_detector", FakeDetector())
    monkeypatch.setattr(transcriber, "_model", object())
    lines = iter(LINES)
    monkeypatch.setattr(transcriber, "transcribe", lambda audio: next(lines, ""))
    monkeypatch.setattr(file_capture, "SPEED", 50.0)  # a 14 s recording in about 0.3 s
    with TestClient(main.app) as client:
        yield client
    for s in list(session_routes.SESSIONS.values()):  # don't leave a recording playing into the next test
        if s.active:
            s.stop()


def wav_bytes(seconds=14.0, silence=(7.0, 8.0), sr=44_100, amplitude=0.1):
    """A tone with one pause in it, so the recording is cut into two transcript chunks."""
    t = np.arange(int(seconds * sr)) / sr
    x = amplitude * np.sin(2 * np.pi * 440 * t)
    if silence:
        x[int(silence[0] * sr):int(silence[1] * sr)] = 0
    buf = io.BytesIO()
    wavfile.write(buf, sr, (x * 32767).astype(np.int16))
    return buf.getvalue()


def post(api, data=None, name="call.wav", caller_number=None):
    files = {"file": (name, data if data is not None else wav_bytes(), "audio/wav")}
    form = {"caller_number": caller_number} if caller_number else {}
    return api.post("/api/session/upload", files=files, data=form)


def upload_ok(api, **kwargs):
    res = post(api, **kwargs)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["upload"] is True and body["replay"] is False
    return body


def events_until(ws, kind, limit=2000):
    seen = []
    for _ in range(limit):
        seen.append(ws.receive_json())
        if seen[-1]["type"] == kind:
            return seen
    raise AssertionError(f"no {kind} event")


def wait_for(check, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if result := check():
            return result
        time.sleep(0.05)
    raise AssertionError("timed out")


@needs_ffmpeg
def test_an_upload_runs_through_the_live_pipeline(api, upload_dir):
    body = upload_ok(api, caller_number="+12025550143")
    assert body["duration_s"] == 14.0
    sid = body["session_id"]
    with api.websocket_connect(f"/ws/live/{sid}") as ws:
        events = events_until(ws, "audio_done")
    first = events[0]
    assert first["type"] == "mode" and first["upload"] is True and first["replay"] is False
    assert first["filename"] == "call.wav" and first["duration_s"] == 14.0 and first["region"]
    kinds = {e["type"] for e in events}
    assert {"level", "voice", "flag", "script"} <= kinds
    assert any(e["type"] == "voice" and e["speech"] and e["p_ai"] == 0.9 for e in events)
    assert not any(e["type"] == "alert" and e["kind"] == "audio" for e in events)
    assert events[-1] == {"type": "audio_done", "t": 14.0}

    # The recording ran out, but the call is still on until the user ends it
    session = session_routes.SESSIONS[sid]
    assert session.active
    wait_for(lambda: len(session.transcript) == 2)  # the last chunk was cut at the end of the file

    report = api.post(f"/api/session/{sid}/stop").json()
    assert report["call"]["capture_method"] == "upload_file" and report["call"]["audio_device"] is None
    assert report["voice"]["final_state"] == "LIKELY_AI" and report["voice"]["windows"]
    assert {f["category"] for f in report["script"]["red_flags"]} >= {"IDENTITY_CLAIM", "PAYMENT_PRESSURE", "SECRECY"}
    assert report["script"]["llm_used"] is False  # no Ollama in the tests: rules only, and the report says so
    assert report["evidence"]["audio_saved"] is False
    assert report["overall"]["risk_level"] == "HIGH"
    assert list(upload_dir.glob("veracity-upload-*")) == []  # the upload wasn't kept


@needs_ffmpeg
def test_a_silent_upload_doesnt_blame_blackhole(api):
    sid = upload_ok(api, data=wav_bytes(seconds=8.0, silence=(0.0, 8.0)))["session_id"]
    with api.websocket_connect(f"/ws/live/{sid}") as ws:
        events = events_until(ws, "audio_done")
    assert not any(e["type"] == "alert" for e in events)
    api.post(f"/api/session/{sid}/stop")


@needs_ffmpeg
def test_protected_send_during_an_upload_goes_through_the_gate(api, monkeypatch):
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "client-id")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "secret")
    monkeypatch.setattr(payment_gate, "PAYOUTS_ENABLED", False)
    fake = FakePayPal()
    paypal_client.set_client(fake.client())
    try:
        monkeypatch.setattr(file_capture, "SPEED", 10.0)  # still playing while the payer pays
        sid = upload_ok(api)["session_id"]
        created = api.post("/api/payment/orders", json={
            "amount": "2400", "currency": "USD", "recipient_name": "Jake", "contact_name": "Jake",
            "contact_number": "+12025550172", "session_id": sid,
        })
        assert created.status_code == 201, created.text
        order_id = created.json()["paypal"]["order_id"]
        fake.approve(order_id)
        payment = api.post(f"/api/payment/orders/{order_id}/authorize").json()
        assert payment["status"] == "HELD" and payment["hold_reason"] == "call_active"

        # The rest of the recording turns the call into a likely scam; ending it decides the hold again
        wait_for(lambda: api.get(f"/api/session/{sid}/risk").json()["level"] == "HIGH")
        report = api.post(f"/api/session/{sid}/stop").json()
        held = report["payments"][0]
        assert held["status"] == "HELD" and held["hold_reason"] != "call_active"
        assert ("POST", f"/v2/checkout/orders/{order_id}/authorize") in [(m, p) for m, p, _ in fake.requests]
    finally:
        paypal_client.set_client(None)


@needs_ffmpeg
def test_one_upload_at_a_time(api, monkeypatch):
    monkeypatch.setattr(file_capture, "SPEED", 1.0)  # the first one keeps playing
    sid = upload_ok(api)["session_id"]
    res = post(api)
    assert res.status_code == 409 and "End that call first" in res.json()["detail"]
    api.post(f"/api/session/{sid}/stop")
    upload_ok(api)  # free again once the first call has ended


@needs_ffmpeg
def test_an_upload_ends_a_running_replay(api):
    replay = api.post("/api/session/start", json={"scenario": "grandparent_us"}).json()["session_id"]
    upload_ok(api)
    assert session_routes.SESSIONS[replay].active is False


@needs_ffmpeg
def test_too_long_and_unreadable_recordings_are_refused(api, monkeypatch, upload_dir):
    monkeypatch.setattr(file_capture, "MAX_S", 5.0)
    res = post(api)
    assert res.status_code == 422 and "up to 5 s long" in res.json()["detail"]
    res = post(api, data=b"not audio at all" * 200, name="call.mp3")
    assert res.status_code == 422 and "Couldn't read this audio file" in res.json()["detail"]
    assert list(upload_dir.glob("veracity-upload-*")) == []


def test_wrong_file_types_are_refused(api):
    res = post(api, data=b"hello", name="notes.txt")
    assert res.status_code == 415 and "wav, mp3, m4a, ogg, flac or webm" in res.json()["detail"]
    assert post(api, data=b"hello", name="noextension").status_code == 415


def test_a_missing_file_is_refused(api):
    res = api.post("/api/session/upload", data={"caller_number": "+12025550143"},
                   files={"other": ("x.txt", b"x", "text/plain")})
    assert res.status_code == 422 and "Choose an audio file" in res.json()["detail"]


def test_files_over_the_size_limit_are_refused(api, monkeypatch):
    monkeypatch.setattr(upload, "MAX_MB", 0.01)  # 10 KB
    res = post(api, data=b"\0" * 200_000)
    assert res.status_code == 413 and "0.01 MB" in res.json()["detail"]


def test_without_the_models_uploads_say_which_build_to_use(api, monkeypatch):
    monkeypatch.setattr(upload, "ENABLED", False)
    res = post(api)
    assert res.status_code == 503 and "full judge build" in res.json()["detail"]

    monkeypatch.setattr(upload, "ENABLED", True)
    monkeypatch.setattr(upload, "models_installed", lambda: False)  # the light build: no torch
    assert post(api).status_code == 503


def test_uploads_wait_for_the_models_to_load(api, monkeypatch):
    monkeypatch.setattr(transcriber, "_model", None)
    monkeypatch.setattr(upload, "_warmed", threading.Event())  # start-up is still loading them
    res = post(api)
    assert res.status_code == 503 and "models still loading" in res.json()["detail"]

    upload._warmed.set()  # loading is over and Whisper still isn't there
    assert "failed to load" in post(api).json()["detail"]


def test_health_has_the_upload_block_in_the_full_judge_build(api, monkeypatch):
    monkeypatch.setattr(health_routes, "MODE", "judge")
    block = api.get("/api/health").json()["upload"]
    assert block == {"available": True, "reason": None, "max_mb": upload.MAX_MB, "max_s": file_capture.MAX_S}

    monkeypatch.setattr(upload, "ffmpeg_found", lambda: False)
    assert api.get("/api/health").json()["upload"]["reason"] == "ffmpeg not found"


def test_health_has_the_upload_block_in_the_light_and_phone_builds(monkeypatch, tmp_path):
    monkeypatch.setenv("VERA_DB", str(tmp_path / "test.db"))
    monkeypatch.setattr(main, "JUDGE_MODE", True)
    monkeypatch.setattr(upload, "ENABLED", False)
    monkeypatch.setattr(health_routes, "_audio_input", lambda: (None, None))
    with TestClient(main.app) as client:
        for mode in ("judge", "local"):
            monkeypatch.setattr(health_routes, "MODE", mode)
            body = client.get("/api/health").json()
            assert body["upload"]["available"] is False and body["upload"]["reason"] == "needs the full judge build"
            assert body["upload"]["max_mb"] == 20 and body["upload"]["max_s"] == 300
            assert {"status", "mode", "region", "paypal", "sandbox_buyer", "fake_mode"} <= set(body)
