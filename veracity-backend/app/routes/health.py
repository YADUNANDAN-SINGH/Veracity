# GET /api/health: the system check behind Step 1 (Check setup) on the frontend.
# Response shape is documented in veracity-frontend/veracity/src/api/health.js.
#
# Everything is really checked: adb, scrcpy, the audio input device, and
# whether each model has been downloaded. Run with VERA_FAKE=1 to use
# simulation mode and continue past Step 1 without the hardware.

import json
import os
import shutil # it checks for the existence of a command in PATH
import subprocess # this lets run python commands and capture their output;
import sys
import urllib.request
from pathlib import Path

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api", tags=["health"])

# The input Python records from; VERA_AUDIO_DEVICE overrides it for the
# speakerphone fallback (e.g. "MacBook Air Microphone")
AUDIO_DEVICE = os.environ.get("VERA_AUDIO_DEVICE", "BlackHole 2ch")

VOICE_MODEL = os.environ.get("VERA_VOICE_MODEL", "Gustking/wav2vec2-large-xlsr-deepfake-audio-classification")  # same default as app/feature/voice.py
WHISPER_SIZE = os.environ.get("VERA_WHISPER_MODEL", "large-v3-turbo")  # same default as app/feature/transcriber.py
# Where faster-whisper downloads each size from
WHISPER_REPOS = {"large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo"}
LLM_MODEL = os.environ.get("VERA_LLM_MODEL", "llama3.1:8b")
OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434")


def _run(cmd: list[str]) -> str | None:
    """Run a quick command and return its stdout, or None if it fails."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return None


def _adb_device_count() -> int:
    out = _run(["adb", "devices"]) or ""
    # Lines after the header look like "<serial>\tdevice"; skip "unauthorized" / "offline"
    return sum(1 for line in out.splitlines()[1:] if line.strip().endswith("\tdevice"))


def _scrcpy_version() -> str | None:
    out = _run(["scrcpy", "--version"]) or ""
    first = out.splitlines()[0].split() if out else []
    # First line is e.g. "scrcpy 3.1 <https://github.com/Genymobile/scrcpy>"
    return first[1] if len(first) > 1 else None


# Lists audio devices as JSON. Run in a fresh Python each time: a new process
# always sees devices added since start-up, and re-initialising PortAudio
# inside the server (once per health check, from several threads) crashed it.
_LIST_DEVICES = (
    "import json, sounddevice as sd; "
    "print(json.dumps([[d['name'], d['max_input_channels'], d['default_samplerate']] "
    "for d in sd.query_devices()]))"
)


def _audio_input() -> tuple[str | None, int | None]:
    """Name and sample rate of the AUDIO_DEVICE input, or (None, None) if absent."""
    try:
        result = subprocess.run(
            [sys.executable, "-c", _LIST_DEVICES], capture_output=True, text=True, timeout=5
        )
        devices = json.loads(result.stdout) if result.returncode == 0 else []
    except (OSError, subprocess.SubprocessError, ValueError):
        # PortAudio missing (e.g. the Docker image) or the scan hung
        return None, None
    for name, input_channels, sample_rate in devices:
        if name == AUDIO_DEVICE and input_channels > 0:
            return name, int(sample_rate)
    return None, None


def _hf_cached(repo_id: str, filename: str) -> bool:
    """True if a Hugging Face repo's file is in the local cache (no download, no torch import)."""
    hub = os.environ.get("HF_HUB_CACHE") or os.path.join(
        os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"), "hub"
    )
    snapshots = Path(hub) / f"models--{repo_id.replace('/', '--')}" / "snapshots"
    return any(snapshots.glob(f"*/{filename}"))


def _ollama_has(model: str) -> bool:
    """True if Ollama is running and has pulled `model`."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=1) as resp:
            names = {m["name"] for m in json.load(resp).get("models", [])}
    except (OSError, ValueError):
        return False  # Ollama not running: the scam rules still work without it
    # "llama3.1" is stored as "llama3.1:latest"
    return model in names or f"{model}:latest" in names


@router.get("/health")
def health(request: Request):
    adb_found = shutil.which("adb") is not None
    scrcpy_found = shutil.which("scrcpy") is not None
    audio_device, audio_sample_rate = _audio_input()

    return {
        "status": "ok",
        "fake_mode": os.environ.get("VERA_FAKE") == "1",
        "port": request.url.port or 8000,
        "adb_found": adb_found,
        "adb_devices": _adb_device_count() if adb_found else 0,
        "scrcpy_found": scrcpy_found,
        "scrcpy_version": _scrcpy_version() if scrcpy_found else None,
        "audio_device": audio_device,
        "audio_sample_rate": audio_sample_rate,
        "models": {
            "voice": {"id": VOICE_MODEL, "ready": _hf_cached(VOICE_MODEL, "model.safetensors")},
            "whisper": {
                "id": WHISPER_SIZE,
                "ready": _hf_cached(
                    WHISPER_REPOS.get(WHISPER_SIZE, f"Systran/faster-whisper-{WHISPER_SIZE}"), "model.bin"
                ),
            },
            "llm": {"id": LLM_MODEL, "ready": _ollama_has(LLM_MODEL)},
        },
    }
