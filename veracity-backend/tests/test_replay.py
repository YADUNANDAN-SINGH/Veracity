# Replayed calls (judge mode / VERA_FAKE=1): the real rules on a scenario, through the real API.

import hashlib
import json
import time

import pytest
from fastapi.testclient import TestClient

import main
from app.feature import replay
from app.routes import session as session_routes


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("VERA_DB", str(tmp_path / "test.db"))
    monkeypatch.setattr(replay, "SPEED", 40.0)  # a 45 s call in about a second
    monkeypatch.setattr(main, "JUDGE_MODE", True)  # no models to warm up
    with TestClient(main.app) as client:  # one event loop for the whole test, like the real server
        yield client


def wait_for(check, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(0.05)
    raise AssertionError("timed out")


def start(api, scenario):
    res = api.post("/api/session/start", json={"scenario": scenario})
    assert res.status_code == 200, res.text
    assert res.json()["replay"] is True
    return res.json()["session_id"]


def test_scenarios_are_listed(api):
    body = api.get("/api/session/scenarios").json()
    ids = [s["id"] for s in body["scenarios"]]
    assert ids[:2] == ["grandparent_us", "family_ok_us"] and "digital_arrest_in" in ids
    grandparent = body["scenarios"][0]
    assert grandparent["voice_scored"] is False and grandparent["payment"]["amount"] == "2400.00"


def test_replayed_scam_is_caught_by_the_real_rules(api):
    sid = start(api, "grandparent_us")
    risk = wait_for(lambda: (r := api.get(f"/api/session/{sid}/risk").json())["level"] == "HIGH" and r)
    assert risk["active"] is True and risk["script_score"] >= 80
    assert {"SECRECY", "PAYMENT_PRESSURE"} <= {f["category"] for f in risk["flags"]} | {"SECRECY"}

    report = api.post(f"/api/session/{sid}/stop").json()
    assert report["call"]["capture_method"] == "replay_scripted"
    assert report["overall"]["risk_level"] == "HIGH"
    assert report["voice"]["final_state"] is None  # a scripted call has no voice score, and none is invented
    assert report["region"] == "US" and "reportfraud.ftc.gov" in report["next_steps"][0]
    assert {link["label"] for link in report["report_links"]} >= {"ReportFraud.ftc.gov"}


def test_websocket_streams_the_replay(api):
    sid = start(api, "grandparent_us")
    with api.websocket_connect(f"/ws/live/{sid}") as ws:
        first = ws.receive_json()
        assert first["type"] == "mode" and first["replay"] is True and first["voice_scored"] is False
        kinds = set()
        while "script" not in kinds:
            kinds.add(ws.receive_json()["type"])
        assert {"transcript", "flag", "script"} <= kinds
    api.post(f"/api/session/{sid}/stop")


def test_typed_lines_are_heard_as_the_callers_words(api):
    sid = start(api, "family_ok_us")
    res = api.post(f"/api/session/{sid}/say", json={"text": "Don't tell Mom. Go buy gift cards right now."})
    assert res.status_code == 202
    risk = wait_for(lambda: (r := api.get(f"/api/session/{sid}/risk").json())["flags"] and r)
    assert {"SECRECY", "PAYMENT_PRESSURE"} <= {f["category"] for f in risk["flags"]}
    api.post(f"/api/session/{sid}/stop")
    assert api.post(f"/api/session/{sid}/say", json={"text": "hello"}).status_code == 409


def test_recorded_scenario_replays_the_models_voice_scores(api, tmp_path, monkeypatch):
    scenario = {
        "title": "Recorded test call", "region": "US", "source": "recorded", "caller_number": "+12025550143",
        "lines": [{"t": 2, "text": "Hi, it's me."}],
        "voice": {"windows": [{"t": t, "p_ai": 0.93} for t in range(1, 7)],
                  "levels": [{"t": round(0.1 * i, 1), "dbfs": -30.0} for i in range(1, 70)]},
    }
    (tmp_path / "recorded_test.json").write_text(json.dumps(scenario))
    monkeypatch.setattr(replay, "SCENARIO_DIR", tmp_path)
    sid = start(api, "recorded_test")
    wait_for(lambda: api.get(f"/api/session/{sid}/risk").json()["voice_state"] == "LIKELY_AI")
    report = api.post(f"/api/session/{sid}/stop").json()
    assert report["call"]["capture_method"] == "replay_recorded"
    assert report["voice"]["final_state"] == "LIKELY_AI" and report["voice"]["max_p_ai"] == 0.93


def test_an_ai_voice_keeps_the_call_likely_ai_after_a_human_speaks(api, tmp_path, monkeypatch):
    # A cloned voice for 6 s, then a real person for 8 s: the meter goes back to human,
    # but the payment gate and the report still see a call that had an AI voice
    windows = [{"t": t, "p_ai": 0.95} for t in range(1, 7)] + [{"t": t, "p_ai": 0.03} for t in range(7, 15)]
    scenario = {
        "title": "Clone then human", "region": "US", "source": "recorded", "caller_number": "+12025550143",
        "lines": [{"t": 2, "text": "Hi, it's me."}],
        "voice": {"windows": windows, "levels": [{"t": round(0.1 * i, 1), "dbfs": -30.0} for i in range(1, 150)]},
    }
    (tmp_path / "clone_then_human.json").write_text(json.dumps(scenario))
    monkeypatch.setattr(replay, "SCENARIO_DIR", tmp_path)
    sid = start(api, "clone_then_human")
    session = session_routes.SESSIONS[sid]
    wait_for(lambda: len(session.windows) == len(windows))
    assert session.smoother.state == "LIKELY_HUMAN"
    assert api.get(f"/api/session/{sid}/risk").json()["voice_state"] == "LIKELY_AI"
    report = api.post(f"/api/session/{sid}/stop").json()
    assert report["voice"]["final_state"] == "LIKELY_AI"


def test_unknown_or_unsafe_scenarios_are_refused(api):
    assert api.post("/api/session/start", json={"scenario": "nope"}).status_code == 404
    assert api.post("/api/session/start", json={"scenario": "../main"}).status_code == 404


def test_only_a_replay_can_be_typed_into(api, monkeypatch):
    class LiveCall:
        active = True
    monkeypatch.setitem(session_routes.SESSIONS, "live1", LiveCall())
    assert api.post("/api/session/live1/say", json={"text": "hi"}).status_code == 409


def test_voice_events_keep_the_latched_verdict_and_peak_after_the_voice_stops(api, tmp_path, monkeypatch):
    # Likely AI, then quiet windows scored as human, then a pause before the end of the recording
    windows = [{"t": t, "p_ai": 0.95} for t in range(3, 9)] + [{"t": t, "p_ai": 0.02} for t in range(9, 13)]
    scenario = {
        "title": "Trailing silence", "region": "US", "source": "recorded", "caller_number": None,
        "lines": [{"t": 2, "text": "Hi, it's me."}],
        "voice": {"windows": windows, "levels": [{"t": round(0.1 * i, 1), "dbfs": -30.0} for i in range(1, 170)]},
    }
    (tmp_path / "trailing_silence.json").write_text(json.dumps(scenario))
    monkeypatch.setattr(replay, "SCENARIO_DIR", tmp_path)
    sid = start(api, "trailing_silence")
    with api.websocket_connect(f"/ws/live/{sid}") as ws:
        voices, event = [], ws.receive_json()
        while event["type"] != "audio_done":
            if event["type"] == "voice":
                voices.append(event)
            event = ws.receive_json()
    api.post(f"/api/session/{sid}/stop")

    assert voices[-1]["speech"] is False and voices[-1]["p_ai"] is None  # the pause at the end
    assert voices[-1]["state"] == "LIKELY_HUMAN" and voices[-1]["smoothed"] < 0.40  # what the voice is doing now
    assert voices[-1]["verdict"] == "LIKELY_AI" and voices[-1]["peak"] == pytest.approx(0.95)  # what the call was


def test_a_scripted_call_has_no_recording_to_run_out(api):
    sid = start(api, "family_ok_us")
    with api.websocket_connect(f"/ws/live/{sid}") as ws:
        kinds = set()
        while "script" not in kinds:
            kinds.add(ws.receive_json()["type"])
    api.post(f"/api/session/{sid}/stop")
    assert "audio_done" not in kinds


def test_the_elevenlabs_sample_replays_the_real_models_output_on_its_real_recording(api):
    sample = next(s for s in api.get("/api/session/scenarios").json()["scenarios"] if s["id"] == "elevenlabs_scam_us")
    assert sample["source"] == "recorded" and sample["voice_scored"] is True and sample["duration_s"] == 44.0

    # The scores come from this exact file: the scenario holds its SHA-256
    scenario = replay.load_scenario("elevenlabs_scam_us")
    recording = api.get(sample["audio_url"])
    assert recording.status_code == 200 and recording.headers["content-type"] == "audio/mpeg"
    assert hashlib.sha256(recording.content).hexdigest() == scenario["voice"]["recording_sha256"]
    assert scenario["voice"]["model_id"] == "lab260/spectra_0"

    # The browser seeks to where the replay has got to
    part = api.get(sample["audio_url"], headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and len(part.content) == 100

    sid = start(api, "elevenlabs_scam_us")
    with api.websocket_connect(f"/ws/live/{sid}") as ws:
        mode = ws.receive_json()
        assert mode["voice_scored"] is True and mode["audio_url"] == sample["audio_url"]
        events, event = [], ws.receive_json()
        while event["type"] != "audio_done":
            events.append(event)
            event = ws.receive_json()
    assert any(e["type"] == "alert" and e["kind"] == "voice" for e in events)
    assert any(e["type"] == "transcript" for e in events)
    report = api.post(f"/api/session/{sid}/stop").json()
    assert report["call"]["capture_method"] == "replay_recorded"
    assert report["voice"]["final_state"] == "LIKELY_AI" and report["voice"]["smoothed_peak"] > 0.9
    assert report["overall"]["risk_level"] == "HIGH" and report["script"]["script_score"] >= 80


def test_a_scenario_without_a_recording_has_no_audio_to_fetch(api):
    sample = next(s for s in api.get("/api/session/scenarios").json()["scenarios"] if s["id"] == "grandparent_us")
    assert sample["audio_url"] is None
    assert api.get("/api/session/scenarios/grandparent_us/audio").status_code == 404
    assert api.get("/api/session/scenarios/nope/audio").status_code == 404
    assert api.get("/api/session/scenarios/..%2F..%2Fmain/audio").status_code == 404


def test_a_missing_recording_hides_the_player_but_not_the_replay(api, tmp_path, monkeypatch):
    monkeypatch.setattr(replay, "SAMPLE_AUDIO_DIR", tmp_path)  # a build without docs/Audio
    sample = next(s for s in api.get("/api/session/scenarios").json()["scenarios"] if s["id"] == "elevenlabs_scam_us")
    assert sample["audio_url"] is None and sample["voice_scored"] is True
    assert api.get("/api/session/scenarios/elevenlabs_scam_us/audio").status_code == 404


def test_a_scenario_cant_point_its_recording_outside_the_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(replay, "SAMPLE_AUDIO_DIR", tmp_path / "audio")
    (tmp_path / "audio").mkdir()
    (tmp_path / "secret.mp3").write_bytes(b"x")
    assert replay.audio_path({"audio_file": "../secret.mp3"}) is None


def test_the_real_voice_sample_replays_as_a_low_risk_human_call_with_its_own_audio(api):
    sample = next(s for s in api.get("/api/session/scenarios").json()["scenarios"] if s["id"] == "real_voice_no_scam_us")
    assert sample["source"] == "recorded" and sample["voice_scored"] is True and sample["payment"]["amount"] == "50.00"

    scenario = replay.load_scenario("real_voice_no_scam_us")
    recording = api.get(sample["audio_url"])
    assert recording.status_code == 200 and hashlib.sha256(recording.content).hexdigest() == scenario["voice"]["recording_sha256"]
    assert recording.headers["content-type"] == "audio/mp4"  # AAC in MP4, even though the file is called .mp3

    sid = start(api, "real_voice_no_scam_us")
    wait_for(lambda: len(session_routes.SESSIONS[sid].windows) == len(scenario["voice"]["windows"]))
    report = api.post(f"/api/session/{sid}/stop").json()
    assert report["voice"]["final_state"] == "LIKELY_HUMAN" and report["voice"]["smoothed_peak"] < 0.40
    assert report["overall"]["risk_level"] == "LOW"
    assert not any(e["type"] == "alert" for e in session_routes.SESSIONS[sid].history)
