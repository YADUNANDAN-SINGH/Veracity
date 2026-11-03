# Replayed calls (judge mode / VERA_FAKE=1): the real rules on a scenario, through the real API.

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


def test_unknown_or_unsafe_scenarios_are_refused(api):
    assert api.post("/api/session/start", json={"scenario": "nope"}).status_code == 404
    assert api.post("/api/session/start", json={"scenario": "../main"}).status_code == 404


def test_only_a_replay_can_be_typed_into(api, monkeypatch):
    class LiveCall:
        active = True
    monkeypatch.setitem(session_routes.SESSIONS, "live1", LiveCall())
    assert api.post("/api/session/live1/say", json={"text": "hi"}).status_code == 409
