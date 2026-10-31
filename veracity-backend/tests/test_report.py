# Step 4: number rule score, fusion, the report schema, and the two endpoints.
# Run from veracity-backend/: venv/bin/python -m pytest

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.feature import reports_db
from app.feature.number_intelligence import analyse_number, rule_score
from app.feature.report import build_report, fuse
from main import app


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("VERA_DB", str(tmp_path / "test.db"))


client = TestClient(app)

START = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)


def make_report(number="+919876543210", p_ai=0.97, script_score=100):
    # The same shapes Session collects during a call
    return build_report(
        caller_number=number,
        started_at=START,
        ended_at=START + timedelta(seconds=33),
        capture_method="scrcpy_voice_call_downlink",
        audio_device="BlackHole 2ch",
        number=analyse_number(number) if number else None,
        model_id="Gustking/wav2vec2-large-xlsr-deepfake-audio-classification",
        calibration_t=1.0,
        threshold=0.75,
        windows=[{"t_start": 0.0, "t_end": 4.0, "p_ai": 0.2}, {"t_start": 29.0, "t_end": 33.0, "p_ai": p_ai}],
        final_state="LIKELY_AI",
        red_flags=[{
            "category": "THREAT_ARREST", "severity": 3, "t": 8.0, "source": "rule",
            "evidence": "digital arrest",
        }],
        script_score=script_score,
        scam_type="digital_arrest",
        transcript="A parcel in your name has drugs. " * 100,
    )


# --- number rule score (§1.4 table) ---

@pytest.mark.parametrize("raw, series, score", [
    ("77799988881", "invalid", 40),
    ("9999999999", "mobile", 0),
    ("1600123456", "1600_regulated", 0),
    ("1401234567", "140_telemarketing", 5),
    ("+855 12345678", "international", 25),
])
def test_rule_score_matches_document(raw, series, score):
    n = analyse_number(raw)
    assert (n["series"], n["rule_score"]) == (series, score)


def test_community_points_are_capped():
    assert rule_score("mobile", 1, 0)[0] == 10
    assert rule_score("mobile", 3, 3)[0] == 30  # 20 + 10 for the last 7 days
    assert rule_score("mobile", 100, 0)[0] == 30


# --- fusion (§3.3) ---

def test_fusion_weights_and_levels():
    assert fuse(20, 50, 40) == (39, "LOW")   # 5 + 20 + 14
    assert fuse(None, 60, 60) == (45, "MEDIUM")


def test_one_strong_signal_is_enough():
    assert fuse(0, 90, 0) == (90, "HIGH")
    assert fuse(0, 0, 80) == (80, "HIGH")
    assert fuse(0, 84, 79) == (61, "MEDIUM")  # neither is strong enough alone


# --- report ---

def test_report_shape():
    report = make_report().model_dump(mode="json")
    assert report["overall"] == {
        "risk_level": "HIGH", "score": 100,
        "top_reasons": ["Voice sounded synthetic (peak 97%)", "Scam-script red flags (score 100)"],
    }
    assert report["voice"]["max_p_ai"] == 0.97
    assert report["voice"]["mean_p_ai"] == 0.585
    assert report["call"]["duration_s"] == 33.0
    assert report["generated_at"] == "2026-10-31T12:00:33Z"
    assert len(report["script"]["transcript_excerpt"]) == 2000
    assert report["evidence"] == {"audio_saved": False, "audio_sha256": None}
    assert report["next_steps"] and report["disclaimer"]


def test_report_without_a_number_or_speech():
    report = build_report(
        caller_number=None, started_at=START, ended_at=START + timedelta(seconds=5),
        capture_method="scrcpy_voice_call_downlink", number=None, model_id="m", calibration_t=1.0,
        threshold=0.75, windows=[], final_state="LIKELY_HUMAN", red_flags=[], script_score=0,
        scam_type=None, transcript="",
    )
    assert report.number is None
    assert report.voice.final_state is None  # nothing was scored
    assert report.overall.risk_level == "LOW"
    assert report.overall.top_reasons == []


# --- endpoints ---

def test_report_is_saved_and_served():
    report = make_report().model_dump(mode="json")
    reports_db.save_report(report)

    res = client.get(f"/api/report/{report['report_id']}")
    assert res.status_code == 200
    assert res.json() == report

    res = client.get(f"/api/report/{report['report_id']}?download=1")
    assert "attachment" in res.headers["content-disposition"]

    assert client.get("/api/report/nope").status_code == 404


def test_community_report_raises_the_number_score():
    before = client.post("/api/number/check", json={"number": "98765 43210"}).json()
    assert before["community_reports"] == 0

    res = client.post("/api/number/report", json={"number": "+91 98765 43210", "category": "digital_arrest", "note": " Said CBI "})
    assert res.status_code == 201
    assert res.json()["e164"] == "+919876543210"
    assert res.json()["community_reports"] == 1

    after = client.post("/api/number/check", json={"number": "9876543210"}).json()
    assert after["rule_score"] == before["rule_score"] + 20  # +10 reported once, +10 in the last 7 days
    assert "Reported once by the community (+10)" in after["rule_reasons"]


def test_community_report_validates_input():
    assert client.post("/api/number/report", json={"number": "hello", "category": "other"}).status_code == 422
    assert client.post("/api/number/report", json={"number": "9876543210", "category": "spam"}).status_code == 422
