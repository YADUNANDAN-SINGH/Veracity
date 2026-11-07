# scripts/build_replay.py: a recording becomes a scenario that replays the real model's scores.
# The models are stubbed here; the script's own steps (windows, chunks, levels, hashing) are real.

import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy.io import wavfile

import main
from app.feature import replay

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import build_replay  # noqa: E402


class AlwaysAI:
    """Stands in for the deepfake model: every window it's given sounds cloned."""

    def p_fake(self, x16k):
        return 0.95


def recording(path: Path) -> Path:
    """17 s at 48 kHz stereo: 1 s quiet, 8 s of 'speech', 1 s pause, 6 s of 'speech', 1 s quiet."""
    sr = 48_000
    t = np.arange(17 * sr) / sr
    on = ((t >= 1) & (t < 9)) | ((t >= 10) & (t < 16))
    mono = np.where(on, 0.3 * np.sin(2 * np.pi * 220 * t), 0.0)
    wavfile.write(path, sr, (np.stack([mono, mono], axis=1) * 32767).astype(np.int16))
    return path


def test_a_recording_becomes_a_scenario(tmp_path):
    wav = recording(tmp_path / "call.wav")
    said = iter(["Grandma, it's me. Don't tell Mom, okay?", "I need $2,400 for bail. Send it on PayPal right now."])
    scenario = build_replay.build(wav, "grandparent_us", detector=AlwaysAI(), transcribe=lambda audio: next(said))

    assert scenario["source"] == "recorded" and scenario["region"] == "US"
    assert scenario["payment"]["amount"] == "2400.00"  # Protected Send is pre-filled from the base scenario
    # Two chunks, cut at the pause, each stamped with when it started (as a live call stamps them)
    assert [line["t"] for line in scenario["lines"]] == [0.0, 9.1]
    v = scenario["voice"]
    assert v["recording_sha256"] == hashlib.sha256(wav.read_bytes()).hexdigest()
    assert len(v["levels"]) == 170 and v["levels"][0] == {"t": 0.1, "dbfs": -120.0}
    seconds = [w["t"] for w in v["windows"]]
    assert seconds[0] == 3 and seconds[-1] == 17  # scored from the call's third second, as a live call is
    assert {w["p_ai"] for w in v["windows"]} == {0.95}


def test_the_recorded_scenario_replays_its_real_scores(tmp_path, monkeypatch):
    wav = recording(tmp_path / "call.wav")
    said = iter(["Grandma, it's me. Don't tell Mom, okay?", "I need $2,400 for bail. Send it on PayPal right now."])
    scenario = build_replay.build(wav, "grandparent_us", detector=AlwaysAI(), transcribe=lambda audio: next(said))
    (tmp_path / "grandparent_us_recorded.json").write_text(json.dumps(scenario), encoding="utf-8")

    monkeypatch.setattr(replay, "SCENARIO_DIR", tmp_path)
    monkeypatch.setattr(replay, "SPEED", 40.0)
    monkeypatch.setattr(main, "JUDGE_MODE", True)
    monkeypatch.setenv("VERA_DB", str(tmp_path / "test.db"))
    with TestClient(main.app) as api:
        sid = api.post("/api/session/start", json={"scenario": "grandparent_us_recorded"}).json()["session_id"]
        deadline = time.monotonic() + 8
        while api.get(f"/api/session/{sid}/risk").json()["voice_state"] != "LIKELY_AI":
            assert time.monotonic() < deadline, "the voice never turned Likely AI"
            time.sleep(0.05)
        report = api.post(f"/api/session/{sid}/stop").json()

    assert report["call"]["capture_method"] == "replay_recorded"
    assert report["voice"]["final_state"] == "LIKELY_AI" and report["voice"]["max_p_ai"] == pytest.approx(0.95)
    assert report["overall"]["risk_level"] == "HIGH"
