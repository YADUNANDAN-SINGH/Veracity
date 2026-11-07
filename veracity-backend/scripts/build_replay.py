#!/usr/bin/env python3
"""Turn a recorded call into a replay scenario that carries the real models' output.

    cd veracity-backend && source venv/bin/activate
    python scripts/build_replay.py app/data/audio/<session>.wav --base grandparent_us \\
        --out app/scenarios/grandparent_us_recorded.json

The recording goes through the same steps as a live call:
  voice       a 4 s window every second, calibrated with VERA_VOICE_T, silence not scored
  transcript  chunks of 6 to 12 s cut at pauses, each through Whisper (VERA_WHISPER_MODEL)
  levels      the input level every 0.1 s, for the meter and the waveform
The result is a copy of the --base scenario (its region, caller number and Protected
Send payment) with source "recorded", the transcript, the voice scores and the
recording's SHA-256, so anyone holding the WAV can check where the scores came from.
The judge build replays it with no models: every voice score on screen is the real
model's output on this recording, not a made-up number.

Only use recordings you have consent for: your own voice, or a clone of it that you
made yourself. Needs the ML requirements (requirements-ml.txt).
"""

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.feature import transcriber, voice  # noqa: E402
from app.feature.audio_capture import BLOCK_S, TARGET_SR, rms_dbfs, to_mono_16k  # noqa: E402
from app.feature.replay import load_scenario  # noqa: E402
from app.feature.session import CHUNK_MAX_S, CHUNK_MIN_S, PAUSE_DB  # noqa: E402

LANGUAGE_FOR_REGION = {"US": "en", "IN": "hi"}


def load_wav(path: Path) -> np.ndarray:
    sr, x = wavfile.read(path)
    if np.issubdtype(x.dtype, np.integer):
        x = x.astype(np.float32) / np.iinfo(x.dtype).max
    return to_mono_16k(x.astype(np.float32), sr)


def levels(x: np.ndarray) -> list[dict]:
    """The level event a live call sends after each 0.1 s block."""
    block = int(BLOCK_S * TARGET_SR)
    return [
        {"t": round((i + block) / TARGET_SR, 1), "dbfs": round(rms_dbfs(x[i:i + block]), 1)}
        for i in range(0, len(x) - block + 1, block)
    ]


def voice_windows(x: np.ndarray, detector) -> list[dict]:
    """One calibrated p(AI) per second of speech, scored exactly as Session._score_voice does."""
    win = int(voice.WINDOW_S * TARGET_SR)
    out = []
    for second in range(1, len(x) // TARGET_SR + 1):
        window = x[max(0, second * TARGET_SR - win):second * TARGET_SR]
        if not voice.scorable(window):
            continue  # the call's first seconds, or a pause: the replay keeps the verdict and draws a gap, like a live call
        out.append({"t": second, "p_ai": round(voice.calibrate(detector.p_fake(window)), 4)})
    return out


def chunks(x: np.ndarray) -> list[tuple[float, np.ndarray]]:
    """(start time, audio) for each transcription chunk, cut where Session._run_audio cuts them."""
    block = int(BLOCK_S * TARGET_SR)
    out, chunk, start, peak = [], [], 0.0, -120.0
    for i in range(0, len(x) - block + 1, block):
        b = x[i:i + block]
        t = round((i + block) / TARGET_SR, 1)
        dbfs = rms_dbfs(b)
        chunk.append(b)
        peak = max(peak, dbfs)
        chunk_s = len(chunk) * block / TARGET_SR
        pause = dbfs < voice.SILENCE_DBFS or dbfs < peak - PAUSE_DB
        if chunk_s >= CHUNK_MAX_S or (chunk_s >= CHUNK_MIN_S and pause):
            out.append((start, np.concatenate(chunk)))
            chunk, start, peak = [], t, -120.0
    if len(chunk) * block >= TARGET_SR:  # the last second or more still counts
        out.append((start, np.concatenate(chunk)))
    return out


def transcript(x: np.ndarray, transcribe) -> list[dict]:
    lines = []
    for start, audio in chunks(x):
        if rms_dbfs(audio) < voice.SILENCE_DBFS:
            continue
        text = transcribe(audio)
        if text:
            lines.append({"t": round(start, 1), "text": text})
    return lines


def build(wav: Path, base_id: str, *, detector=None, transcribe=None, title: str | None = None,
          description: str | None = None) -> dict:
    base = load_scenario(base_id)
    base.pop("id", None)
    x = load_wav(wav)
    seconds = round(len(x) / TARGET_SR, 1)
    lines = transcript(x, transcribe or transcriber.transcribe)
    if not lines:
        raise SystemExit(f"Whisper heard no speech in {wav}.")
    return {
        **base,
        "title": title or f"{base['title']} (recorded)",
        "description": description or (
            f"A {seconds:.0f} s recording of this call. The transcript is Whisper's and the voice scores are "
            "the real model's, both run on the recording; the scam rules run live as it replays."
        ),
        "order": base.get("order", 99) - 0.5,  # just before the scripted version in the picker
        "source": "recorded",
        "lines": lines,
        "voice": {
            "model_id": voice.VOICE_MODEL,
            "calibration_t": voice.CALIBRATION_T,
            "whisper_model": transcriber.WHISPER_SIZE,
            "language": transcriber.LANGUAGE or "auto",
            "recording_sha256": hashlib.sha256(wav.read_bytes()).hexdigest(),
            "recording_seconds": seconds,
            "built_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "windows": voice_windows(x, detector or voice.load_detector()),
            "levels": levels(x),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("wav", type=Path, help="the recorded call (Save audio on: app/data/audio/<id>.wav)")
    parser.add_argument("--base", required=True, help="scenario to copy region, caller and payment from")
    parser.add_argument("--out", type=Path, required=True, help="where to write the new scenario")
    parser.add_argument("--language", help="Whisper language: en, hi or auto (default: from the base's region)")
    parser.add_argument("--title", help="title in the sample-call picker")
    parser.add_argument("--description", help="one or two sentences for the picker")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9_]{1,40}", args.out.stem):
        raise SystemExit("--out must be named <id>.json, where <id> is lowercase letters, digits and _.")

    region = load_scenario(args.base).get("region", "IN")
    language = args.language or LANGUAGE_FOR_REGION.get(region, "auto")
    transcriber.LANGUAGE = None if language == "auto" else language

    scenario = build(args.wav, args.base, title=args.title, description=args.description)
    args.out.write_text(json.dumps(scenario, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    windows = scenario["voice"]["windows"]
    peak = max((w["p_ai"] for w in windows), default=0.0)
    smoother = voice.VerdictSmoother()
    states = {smoother.update(w["p_ai"]).state for w in windows}
    print(f"wrote {args.out}: {len(scenario['lines'])} transcript lines, {len(windows)} voice windows, "
          f"peak p(AI) {peak:.2f}, {'turns Likely AI' if 'LIKELY_AI' in states else 'never turns Likely AI'}")
    print(f"replay it with VERA_SCENARIO={args.out.stem} (judge mode) or pick it in Step 2.")


if __name__ == "__main__":
    main()
