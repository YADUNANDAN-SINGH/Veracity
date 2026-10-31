# Call audio for a live session (Project Document §1.3):
#   scrcpy pulls the caller's voice over USB and plays it on the Mac; a
#   Multi-Output Device sends it to the speakers and to BlackHole 2ch; Python
#   reads BlackHole like a microphone in 0.1 s blocks, then makes it mono 16 kHz.
#
# The session starts scrcpy itself unless one is already running.

import logging
import math
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import time

import numpy as np
from scipy.signal import resample_poly

log = logging.getLogger("veracity.audio")

AUDIO_DEVICE = os.environ.get("VERA_AUDIO_DEVICE", "BlackHole 2ch")
# "voice-call-downlink" is the caller only; "voice-call" mixes both sides
AUDIO_SOURCE = os.environ.get("VERA_AUDIO_SOURCE", "voice-call-downlink")
# "laptop_mic_speakerphone" for the speakerphone fallback, which needs no scrcpy
CAPTURE_METHOD = os.environ.get("VERA_CAPTURE_METHOD", "scrcpy_" + AUDIO_SOURCE.replace("-", "_"))

TARGET_SR = 16_000
BLOCK_S = 0.1
SCRCPY_LOG = os.path.join(tempfile.gettempdir(), "veracity-scrcpy.log")


class AudioDeviceError(RuntimeError):
    """The input device is missing, or macOS wouldn't open it."""


def to_mono_16k(block: np.ndarray, sr: int) -> np.ndarray:
    """(frames, channels) float32 at `sr` → mono float32 at 16 kHz (48 kHz is exactly 1:3)."""
    x = block.mean(axis=1) if block.ndim == 2 else block
    g = math.gcd(sr, TARGET_SR)
    return resample_poly(x, TARGET_SR // g, sr // g).astype(np.float32)


def rms_dbfs(x: np.ndarray) -> float:
    """Loudness in dBFS: 0 is full scale, digital silence is clamped to −120."""
    if x.size == 0:
        return -120.0
    rms = float(np.sqrt(np.mean(np.square(x, dtype=np.float64))))
    return max(-120.0, 20 * math.log10(rms + 1e-12))


class LiveCapture:
    """Reads AUDIO_DEVICE in 0.1 s blocks on PortAudio's thread; read() hands them out."""

    def __init__(self, device_name: str = AUDIO_DEVICE):
        import sounddevice as sd  # imported here so the server runs without PortAudio (Docker)

        self._sd = sd
        matches = [
            (i, d) for i, d in enumerate(sd.query_devices())
            if d["name"] == device_name and d["max_input_channels"] > 0
        ]
        if not matches:
            raise AudioDeviceError(f"Audio input “{device_name}” isn't available")
        self.device, info = matches[0]
        self.sample_rate = int(info["default_samplerate"])
        self.channels = min(2, info["max_input_channels"])
        self._blocks: queue.Queue[np.ndarray] = queue.Queue()
        self._stream = None

    def start(self) -> None:
        def on_block(indata, frames, time_info, status):
            if status:
                log.debug("audio status: %s", status)  # e.g. input overflow
            self._blocks.put(indata.copy())

        try:
            self._stream = self._sd.InputStream(
                device=self.device,
                samplerate=self.sample_rate,
                channels=self.channels,
                blocksize=int(self.sample_rate * BLOCK_S),
                dtype="float32",
                callback=on_block,
            )
            self._stream.start()
        except Exception as e:  # PortAudioError; macOS also lands here if mic access is denied
            raise AudioDeviceError(f"Couldn't open “{AUDIO_DEVICE}”: {e}") from e

    def read(self, timeout: float = 0.5) -> np.ndarray | None:
        try:
            return self._blocks.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


def default_output_name() -> str | None:
    """The Mac's current sound output, e.g. "MacBook Air Speakers" (None if it can't tell).

    Asked in a fresh Python: this process's PortAudio only knows the devices from start-up.
    """
    try:
        result = subprocess.run(
            [sys.executable, "-c", "import sounddevice as sd; print(sd.query_devices(kind='output')['name'])"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None if result.returncode == 0 else None


def _scrcpy_running() -> bool:
    return subprocess.run(["pgrep", "-x", "scrcpy"], capture_output=True).returncode == 0


def start_scrcpy() -> subprocess.Popen | None:
    """Start scrcpy's audio-only mirror, or return None if it's running already or can't run."""
    if not CAPTURE_METHOD.startswith("scrcpy") or shutil.which("scrcpy") is None:
        return None
    if _scrcpy_running():
        log.info("scrcpy is already running; using its audio")
        return None
    with open(SCRCPY_LOG, "w") as out:
        proc = subprocess.Popen(
            [
                "scrcpy", "--no-video", "--no-control", "--require-audio",
                f"--audio-source={AUDIO_SOURCE}", "--audio-codec=aac", "--audio-buffer=200",
            ],
            stdout=out, stderr=subprocess.STDOUT,
        )
    time.sleep(1.5)  # most failures (no phone, no call audio) show up straight away
    if proc.poll() is not None:
        with open(SCRCPY_LOG) as f:
            log.warning("scrcpy exited (%s):\n%s", proc.returncode, f.read()[-2000:])
        return None
    return proc


def stop_scrcpy(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
