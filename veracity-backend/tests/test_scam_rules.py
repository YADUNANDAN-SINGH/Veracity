# The scam rules on US English calls, and that everyday sentences stay quiet.

import pytest

from app.feature import scam_rules
from app.feature.replay import load_scenario


def script_score_of(lines: list[str]) -> tuple[int, set[str]]:
    """Run lines through the rules the way a live call does (same duplicate check, 3 flags per category)."""
    flags: list[dict] = []
    for line in lines:
        for hit in scam_rules.scan(line):
            if scam_rules.is_duplicate(hit["evidence"], flags):
                continue
            if sum(f["category"] == hit["category"] for f in flags) >= 3:
                continue
            flags.append(hit)
    categories = {f["category"] for f in flags}
    return scam_rules.script_score(categories), categories


def test_grandparent_scam_scores_as_a_strong_scam_signal():
    score, categories = script_score_of([line["text"] for line in load_scenario("grandparent_us")["lines"]])
    assert score >= 80
    assert {"FAMILY_EMERGENCY", "SECRECY", "PAYMENT_PRESSURE"} <= categories


def test_a_real_grandson_asking_for_money_stays_low():
    score, _ = script_score_of([line["text"] for line in load_scenario("family_ok_us")["lines"]])
    assert score < 40


@pytest.mark.parametrize("line, category", [
    ("I know I sound different, I broke my nose.", "FAMILY_EMERGENCY"),
    ("They said I have to post bail tonight.", "FAMILY_EMERGENCY"),
    ("Please don't tell Mom and Dad about this.", "SECRECY"),
    ("Keep this between us, okay?", "SECRECY"),
    ("Do not hang up or you will be arrested.", "SECRECY"),
    ("Can you send it on PayPal?", "PAYMENT_PRESSURE"),
    ("Just wire the money to this account.", "PAYMENT_PRESSURE"),
    ("I need $2,400 for the lawyer.", "PAYMENT_PRESSURE"),
    ("A courier will pick up the cash at your door.", "PAYMENT_PRESSURE"),
    ("Go buy Target gift cards and read me the numbers.", "PAYMENT_PRESSURE"),
    ("This is Officer Davis with the county sheriff.", "AUTHORITY_IMPERSONATION"),
    ("I'm calling from the IRS about unpaid taxes.", "AUTHORITY_IMPERSONATION"),
    ("This is the fraud department at your bank.", "AUTHORITY_IMPERSONATION"),
    ("We noticed suspicious activity on your card.", "KYC_ACCOUNT_BLOCK"),
    ("Read me the code we just texted you.", "OTP_PIN_REQUEST"),
    ("Install this app so I can get remote access.", "REMOTE_ACCESS"),
    ("You have to do it as soon as possible.", "URGENCY"),
    ("Kisi ko mat batana. Do not disconnect this call.", "SECRECY"),
])
def test_us_scam_phrases(line, category):
    assert category in {hit["category"] for hit in scam_rules.scan(line)}


@pytest.mark.parametrize("line", [
    "Hi Grandma, it's Jake! I passed my driving test today.",
    "Mom says we're all coming over for dinner on Sunday.",
    "The weather is lovely, we walked to the park after lunch.",
    "Your prescription is ready for pickup at the pharmacy.",
    "मेरे सारे पैसे खर्च हो गए",  # "I spent all my money": no transfer word, so no payment flag
])
def test_everyday_sentences_raise_no_flags(line):
    assert scam_rules.scan(line) == []
