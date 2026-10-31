# Feature 4: the JSON red-flag report (Project Document §1.7) and the fusion
# that turns number + voice + script into one risk level (§3.3).
#
# build_report() is called once per call, by Session.stop(). The field names
# match what the frontend's ReportPage reads.

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"
APP_VERSION = "0.1.0"

# Fusion weights and thresholds; agree on them as a team and show them on a slide
WEIGHTS = {"number": 0.25, "voice": 0.40, "script": 0.35}
VOICE_ALONE = 85   # a voice peak this high is enough on its own
SCRIPT_ALONE = 80  # so is a script score this high
HIGH, MEDIUM = 70, 40

TRANSCRIPT_LIMIT = 2000

NEXT_STEPS = [
    "Lost money? Call 1930 now and file a complaint at https://cybercrime.gov.in. Attach this file.",
    "No money lost? Report the number on Chakshu (https://sancharsaathi.gov.in/sfc/) within 30 days of the call.",
]
DISCLAIMER = (
    "This report is evidence, not proof. The AI-voice % is a calibrated model estimate, "
    "and red flags are matched from the transcript, which can contain mistakes."
)

VoiceState = Literal["LIKELY_HUMAN", "UNCERTAIN", "LIKELY_AI"]
RiskLevel = Literal["LOW", "MEDIUM", "HIGH"]


class CallInfo(BaseModel):
    caller_number: str | None
    started_at: datetime
    ended_at: datetime
    duration_s: float
    # "scrcpy_voice_call_downlink", "laptop_mic_speakerphone", ...
    capture_method: str
    audio_device: str | None = None


class NumberSection(BaseModel):
    e164: str
    valid: bool
    type: str
    series: str
    country: str | None
    location: str | None
    original_carrier: str | None
    community_reports: int
    reports_7d: int
    rule_score: int
    reasons: list[str]
    # Filled in once the number model exists
    ml_probability: float | None = None
    ml_trained_on: str | None = None


class VoiceWindow(BaseModel):
    t_start: float
    t_end: float
    p_ai: float = Field(ge=0, le=1)


class VoiceSection(BaseModel):
    model_id: str
    calibration_t: float | None
    threshold: float
    windows: list[VoiceWindow]
    max_p_ai: float
    mean_p_ai: float
    final_state: VoiceState | None  # None when no speech was scored


class RedFlag(BaseModel):
    category: str
    severity: int = Field(ge=1, le=3)
    evidence: str
    t: float
    source: Literal["rule", "llm"]


class ScriptSection(BaseModel):
    script_score: int = Field(ge=0, le=100)
    red_flags: list[RedFlag]
    scam_type: str | None
    transcript_excerpt: str = Field(max_length=TRANSCRIPT_LIMIT)


class Overall(BaseModel):
    risk_level: RiskLevel
    score: int = Field(ge=0, le=100)
    top_reasons: list[str]


class Evidence(BaseModel):
    audio_saved: bool
    audio_sha256: str | None


class Report(BaseModel):
    schema_version: str
    report_id: str
    generated_at: datetime
    app_version: str
    call: CallInfo
    number: NumberSection | None
    voice: VoiceSection
    script: ScriptSection
    overall: Overall
    evidence: Evidence
    next_steps: list[str]
    disclaimer: str


def risk_level(score: int) -> RiskLevel:
    return "HIGH" if score >= HIGH else "MEDIUM" if score >= MEDIUM else "LOW"


def fuse(number_score: int | None, voice_peak: int, script_score: int) -> tuple[int, RiskLevel]:
    """Weighted score, raised to any single signal that is strong enough on its own."""
    score = round(
        WEIGHTS["number"] * (number_score or 0)
        + WEIGHTS["voice"] * voice_peak
        + WEIGHTS["script"] * script_score
    )
    if voice_peak >= VOICE_ALONE:
        score = max(score, voice_peak)
    if script_score >= SCRIPT_ALONE:
        score = max(score, script_score)
    score = min(100, score)
    return score, risk_level(score)


def top_reasons(number: NumberSection | None, voice_peak: int, script: ScriptSection, limit: int = 3) -> list[str]:
    """Plain-language reasons, biggest contribution to the score first."""
    candidates: list[tuple[float, str]] = []
    if voice_peak >= 75:
        candidates.append((WEIGHTS["voice"] * voice_peak, f"Voice sounded synthetic (peak {voice_peak}%)"))
    elif voice_peak >= 40:
        candidates.append((WEIGHTS["voice"] * voice_peak, f"Voice may be synthetic (peak {voice_peak}%)"))
    if script.script_score > 0:
        candidates.append(
            (WEIGHTS["script"] * script.script_score, f"Scam-script red flags (score {script.script_score})")
        )
    if number and number.rule_score > 0 and number.reasons:
        candidates.append((WEIGHTS["number"] * number.rule_score, f"Number: {number.reasons[0]}"))
    candidates.sort(key=lambda c: c[0], reverse=True)
    return [reason for _, reason in candidates[:limit]]


def build_report(
    *,
    report_id: str | None = None,
    caller_number: str | None,
    started_at: datetime,
    ended_at: datetime,
    capture_method: str,
    audio_device: str | None = None,
    number: dict | None,
    model_id: str,
    calibration_t: float | None,
    threshold: float,
    windows: list[dict],
    final_state: VoiceState | None,
    red_flags: list[dict],
    script_score: int,
    scam_type: str | None,
    transcript: str,
    audio_sha256: str | None = None,
) -> Report:
    """Assemble the report. `number` is analyse_number()'s output, or None if the caller was unknown."""
    number_section = None
    if number:
        number_section = NumberSection(
            e164=number["e164_format"],
            valid=number["valid"],
            type=number["number_type"],
            series=number["series"],
            country=number["country"],
            location=number["location"],
            original_carrier=number["original_carrier"],
            community_reports=number["community_reports"],
            reports_7d=number["reports_7d"],
            rule_score=number["rule_score"],
            reasons=number["rule_reasons"],
        )

    p_ais = [w["p_ai"] for w in windows]
    voice = VoiceSection(
        model_id=model_id,
        calibration_t=calibration_t,
        threshold=threshold,
        windows=[VoiceWindow(**w) for w in windows],
        max_p_ai=round(max(p_ais, default=0.0), 4),
        mean_p_ai=round(sum(p_ais) / len(p_ais), 4) if p_ais else 0.0,
        final_state=final_state if p_ais else None,
    )
    script = ScriptSection(
        script_score=script_score,
        red_flags=[RedFlag(**f) for f in red_flags],
        scam_type=scam_type,
        transcript_excerpt=transcript[:TRANSCRIPT_LIMIT],
    )

    voice_peak = round(voice.max_p_ai * 100)
    score, level = fuse(number_section.rule_score if number_section else None, voice_peak, script_score)

    return Report(
        schema_version=SCHEMA_VERSION,
        report_id=report_id or uuid.uuid4().hex,
        generated_at=ended_at,
        app_version=APP_VERSION,
        call=CallInfo(
            caller_number=caller_number,
            started_at=started_at,
            ended_at=ended_at,
            duration_s=round((ended_at - started_at).total_seconds(), 1),
            capture_method=capture_method,
            audio_device=audio_device,
        ),
        number=number_section,
        voice=voice,
        script=script,
        overall=Overall(risk_level=level, score=score, top_reasons=top_reasons(number_section, voice_peak, script)),
        evidence=Evidence(audio_saved=audio_sha256 is not None, audio_sha256=audio_sha256),
        next_steps=NEXT_STEPS,
        disclaimer=DISCLAIMER,
    )
