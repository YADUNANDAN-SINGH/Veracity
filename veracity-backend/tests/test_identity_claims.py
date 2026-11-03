# The voice-clone opener: "it's me, your grandson". Weak alone, but with a
# money request the payment is never released before a call-back.

import pytest

from app.feature import scam_rules
from app.feature.payment_gate import gate_level, risk_from_report
from app.feature.report import fuse


def cats(*lines):
    return {h["category"] for line in lines for h in scam_rules.scan(line)}


def live_risk(*lines, voice_peak=10):
    """What Session.risk_snapshot() says for a human-sounding voice and no number."""
    c = cats(*lines)
    script = scam_rules.script_score(c)
    score, level = fuse(None, voice_peak, script)
    return {"level": level, "score": score, "script_score": script, "voice_state": "LIKELY_HUMAN",
            "categories": sorted(c)}


@pytest.mark.parametrize("line, evidence", [
    ("Grandma, it's me, your grandson. I had an accident.", "it's me, your grandson"),
    ("Hi Mum, it's me. Mine died.", "it's me"),
    ("I'm your nephew from Leeds.", "I'm your nephew"),
    ("Don't you recognise my voice?", "Don't you recognise my voice"),
    ("Main tumhara bhatija bol raha hoon, pehchana?", "Main tumhara bhatija bol raha"),
])
def test_identity_claims_are_flagged_with_their_words(line, evidence):
    hits = {h["category"]: h["evidence"] for h in scam_rules.scan(line)}
    assert hits["IDENTITY_CLAIM"] == evidence


@pytest.mark.parametrize("line", [
    "Hey, it's Arjun. Are we still on for dinner tonight?",
    "Hi, this is your bank's fraud team.",
    "I paid 30 dollars for the tickets yesterday.",
])
def test_ordinary_lines_are_not_identity_claims(line):
    assert "IDENTITY_CLAIM" not in cats(line)


@pytest.mark.parametrize("line", ["Can you send me 60 pounds for a taxi?", "Just send £60 now", "Wire 200 euros today"])
def test_uk_and_eu_money_requests(line):
    assert "PAYMENT_PRESSURE" in cats(line)


def test_identity_alone_does_not_hold_a_payment():
    assert gate_level(live_risk("Hi Mum, it's me."))[0] == "LOW"


def test_someone_you_know_asking_for_money_is_held_for_a_callback():
    risk = live_risk("Hi Mum, it's me. My phone died.", "Can you send me 60 pounds for a taxi home?")
    assert scam_rules.verify_first(risk["categories"])
    level, why = gate_level(risk)
    assert level == "MEDIUM" and "call them back" in why


def test_a_finished_calls_report_keeps_the_rule():
    report = {
        "report_id": "r1", "overall": {"score": 12, "risk_level": "LOW", "top_reasons": []},
        "voice": {"final_state": "LIKELY_HUMAN", "max_p_ai": 0.1, "smoothed_peak": 0.1},
        "script": {"script_score": 30, "red_flags": [
            {"category": "IDENTITY_CLAIM", "severity": 1, "evidence": "it's me", "t": 2.0},
            {"category": "PAYMENT_PRESSURE", "severity": 3, "evidence": "send me 60 pounds", "t": 9.0},
        ]},
    }
    assert gate_level(risk_from_report(report))[0] == "MEDIUM"
