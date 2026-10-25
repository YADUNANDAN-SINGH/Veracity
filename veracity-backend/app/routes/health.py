# GET /api/health: the system check behind Step 1 (Check setup) on the frontend.
# Response shape is documented in veracity-frontend/veracity/src/api/health.js.
#
# Basic version: adb and scrcpy are really checked; the audio device and the
# models aren't wired up yet, so they're reported as missing. Run with
# VERA_FAKE=1 to use simulation mode and continue past Step 1 meanwhile.

import os
import shutil
import subprocess

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api", tags=["health"])


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


@router.get("/health")
def health(request: Request):
    adb_found = shutil.which("adb") is not None
    scrcpy_found = shutil.which("scrcpy") is not None

    return {
        "status": "ok",
        "fake_mode": os.environ.get("VERA_FAKE") == "1",
        "port": request.url.port or 8000,
        "adb_found": adb_found,
        "adb_devices": _adb_device_count() if adb_found else 0,
        "scrcpy_found": scrcpy_found,
        "scrcpy_version": _scrcpy_version() if scrcpy_found else None,
        # TODO: detect the BlackHole input device and its sample rate
        "audio_device": None,
        "audio_sample_rate": None,
        # TODO: report whether each model is downloaded
        "models": {
            "voice": {"id": "mo-thecreator/Deepfake-audio-detection", "ready": False},
            "whisper": {"id": "small", "ready": False},
            "llm": {"id": "llama3.1:8b", "ready": False},
        },
    }
