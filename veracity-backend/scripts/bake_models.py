#!/usr/bin/env python3
"""The judge image's models: bake them in, then prove the image works without a network.

    python bake_models.py download <spectra0 revision> <whisper size>
        Dockerfile.judge, before the app is copied in. A cold clone's build shouldn't
        die on one failed request or a rate limit, so each download is retried.

    python scripts/bake_models.py verify
        Dockerfile.judge, last step, with HF_HUB_OFFLINE=1. Runs the real models on the
        first seconds of the built-in recording, so an image that would fail on a
        judge's machine fails its build here instead.
"""

import hashlib
import os
import shutil
import sys
import time
from pathlib import Path

ATTEMPTS = 5
FIRST_WAIT_S = 15
SAMPLE = "elevenlabs_scam_us"


def with_retries(what: str, fetch) -> None:
    for attempt in range(1, ATTEMPTS + 1):
        try:
            fetch()
            print(f"{what}: in the image", flush=True)
            return
        except Exception as e:  # noqa: BLE001  rate limits, resets and timeouts all look different
            if attempt == ATTEMPTS:
                raise
            wait = FIRST_WAIT_S * 2 ** (attempt - 1)
            print(f"{what}: attempt {attempt} of {ATTEMPTS} failed ({e}); trying again in {wait} s", flush=True)
            time.sleep(wait)


def download(spectra0_revision: str, whisper_size: str) -> None:
    from faster_whisper import WhisperModel
    from huggingface_hub import hf_hub_download

    with_retries("Spectra-0", lambda: hf_hub_download("lab260/spectra_0", "model.safetensors", revision=spectra0_revision))
    with_retries(f"Whisper {whisper_size}", lambda: WhisperModel(whisper_size, device="cpu", compute_type="int8"))


def verify() -> None:
    if os.environ.get("HF_HUB_OFFLINE") != "1":
        raise SystemExit("verify runs with HF_HUB_OFFLINE=1, to prove nothing needs the network")
    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg isn't in the image")

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app.feature import file_capture, replay, transcriber, voice
    from app.feature.audio_capture import TARGET_SR

    for listed in replay.list_scenarios():
        scenario = replay.load_scenario(listed["id"])
        if scenario.get("audio_file") is None:
            continue
        recording = replay.audio_path(scenario)
        if recording is None:
            raise SystemExit(f"{listed['id']}'s recording isn't in {replay.SAMPLE_AUDIO_DIR}")
        if hashlib.sha256(recording.read_bytes()).hexdigest() != scenario["voice"]["recording_sha256"]:
            raise SystemExit(f"{recording} isn't the file {listed['id']}'s scores were computed on: run scripts/build_replay.py again")

    audio = file_capture.decode(replay.audio_path(replay.load_scenario(SAMPLE)))[:8 * TARGET_SR]
    started = time.monotonic()
    p_ai = voice.calibrate(voice.load_detector().p_fake(audio[-int(voice.WINDOW_S * TARGET_SR):]))
    text = transcriber.transcribe(audio)
    if not 0.0 <= p_ai <= 1.0 or not text:
        raise SystemExit(f"The models ran but gave nothing usable: p(AI) {p_ai}, transcript {text!r}")
    print(f"verified offline in {time.monotonic() - started:.0f} s: {voice.VOICE_MODEL} p(AI) {p_ai:.2f}; "
          f"Whisper {transcriber.WHISPER_SIZE}: {text[:60]!r}", flush=True)


if __name__ == "__main__":
    if sys.argv[1:2] == ["download"] and len(sys.argv) == 4:
        download(sys.argv[2], sys.argv[3])
    elif sys.argv[1:] == ["verify"]:
        verify()
    else:
        raise SystemExit(__doc__)
