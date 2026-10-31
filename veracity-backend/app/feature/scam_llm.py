# Scam-script layer 2: the local LLM (Ollama, llama3.1:8b) reads the whole
# transcript so far and answers in our JSON schema (structured outputs,
# temperature 0). A flag is kept only if its quote really is in the
# transcript, so it can't invent evidence. If Ollama isn't running, the
# session carries on with the rules alone.

import logging
import os
from typing import Literal

from pydantic import BaseModel, Field

from app.feature.scam_rules import CATEGORIES

log = logging.getLogger("veracity.llm")

LLM_MODEL = os.environ.get("VERA_LLM_MODEL", "llama3.1:8b")
OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
TRANSCRIPT_LIMIT = 4000  # the most recent characters; enough context, keeps it fast

SYSTEM_PROMPT = f"""You check phone-call transcripts from India for scams.
The transcript is only what the caller said. It may be English, Hindi or Hinglish and may contain
speech-recognition mistakes.
Find red flags. For each one give a category from this list and the caller's exact words as
evidence_quote, copied character for character from the transcript (a short phrase, not a summary):
{", ".join(CATEGORIES)}.
Only report what is actually said. If nothing is suspicious, return no red flags and scam_type "none"."""


class LLMFlag(BaseModel):
    category: Literal[tuple(CATEGORIES)]
    evidence_quote: str


class ScriptVerdict(BaseModel):
    scam_likely: bool
    scam_type: Literal[
        "digital_arrest", "bank_kyc", "family_emergency", "parcel_courier",
        "investment", "lottery_prize", "tech_support", "none", "other",
    ]
    confidence: float = Field(ge=0.0, le=1.0)
    red_flags: list[LLMFlag]
    advice_for_user: str


def analyse(transcript: str) -> ScriptVerdict | None:
    """The LLM's verdict on the transcript, with made-up quotes removed; None if Ollama is unavailable."""
    from ollama import Client

    text = transcript[-TRANSCRIPT_LIMIT:]
    try:
        resp = Client(host=OLLAMA_URL, timeout=60).chat(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Transcript so far:\n{text}\n\nReturn as JSON."},
            ],
            format=ScriptVerdict.model_json_schema(),
            options={"temperature": 0},
        )
        verdict = ScriptVerdict.model_validate_json(resp.message.content)
    except Exception as e:  # not running, model missing, timeout, bad JSON
        log.info("LLM skipped: %s", e)
        return None

    lower = text.lower()
    verdict.red_flags = [
        f for f in verdict.red_flags
        if f.evidence_quote.strip() and f.evidence_quote.strip().lower() in lower
    ]
    return verdict
