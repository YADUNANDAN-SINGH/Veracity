# Call audio from an uploaded recording, for the judge build: the same interface
# as LiveCapture (.sample_rate, .start(), .read(timeout), .close()), so a
# Session's audio loop runs on a file exactly as it runs on BlackHole.
#
# ffmpeg decodes the whole file up front (5 minutes of 16 kHz float32 is ~19 MB),
# which gives an exact duration and a clear error before the call starts; the
# upload is deleted as soon as it's decoded, so the audio is never stored.
# read() then hands out 0.1 s blocks at real time × VERA_UPLOAD_SPEED, so
# Protected Send can be used mid-recording the same way as on a live call.
# No sounddevice, no BlackHole.

import logging
import os
import subprocess
import time
from pathlib import Path

import numpy as np

from app.feature.audio_capture import BLOCK_S, TARGET_SR

log = logging.getLogger("veracity.upload")

SPEED = float(os.environ.get("VERA_UPLOAD_SPEED", "1"))  # 2 plays a recording twice as fast; the tests use more
# On CPU the models run slower than real time (a 60 s recording took ~2.2 min on an
# Apple M5 in Docker), so the default keeps a judge's wait to a few minutes
MAX_S = float(os.environ.get("VERA_UPLOAD_MAX_S", "120"))
DECODE_TIMEOUT_S = 120


class DecodeError(ValueError):
    """ffmpeg couldn't read the file, or it holds no audio."""


class TooLong(ValueError):
    """The recording is longer than MAX_S."""


def decode(path: str | Path, max_s: float | None = None) -> np.ndarray:
    """Any audio file ffmpeg reads → mono float32 at 16 kHz. Stops reading just past max_s."""
    max_s = MAX_S if max_s is None else max_s
    cmd = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-i", str(path),
        "-t", f"{max_s + 1:.1f}",  # enough to tell "too long" without decoding an hour
        "-vn", "-ac", "1", "-ar", str(TARGET_SR), "-f", "f32le", "pipe:1",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=DECODE_TIMEOUT_S)
    except FileNotFoundError as e:
        raise DecodeError("ffmpeg isn't installed") from e
    except subprocess.TimeoutExpired as e:
        raise DecodeError(f"ffmpeg took more than {DECODE_TIMEOUT_S} s to read the file") from e
    if result.returncode != 0:
        lines = result.stderr.decode(errors="replace").strip().splitlines()
        raise DecodeError(f"ffmpeg couldn't read the file ({lines[-1] if lines else f'exit {result.returncode}'})")

    pcm = np.frombuffer(result.stdout, dtype=np.float32).copy()
    if pcm.size == 0:
        raise DecodeError("the file has no audio track")
    if pcm.size / TARGET_SR > max_s:
        raise TooLong(f"the recording is longer than {max_s:g} s")
    return pcm


class FileCapture:
    """A decoded recording, read like a live input: 0.1 s blocks, paced at real time × speed."""

    def __init__(self, path: str | Path, speed: float | None = None, delete: bool = True):
        try:
            self._pcm = decode(path)
        finally:
            if delete:  # the upload is never kept, even if it couldn't be read
                Path(path).unlink(missing_ok=True)
        self.sample_rate = TARGET_SR
        self.duration_s = round(self._pcm.size / TARGET_SR, 1)
        self.speed = speed or SPEED
        self.finished = False  # every block has been read
        self._block = int(TARGET_SR * BLOCK_S)
        self._pos = 0
        self._t0: float | None = None

    def start(self) -> None:
        self._t0 = time.monotonic()

    def read(self, timeout: float = 0.5) -> np.ndarray | None:
        """The next block once it has "played", None while waiting or after the end (then .finished)."""
        if self._pos >= self._pcm.size:
            self.finished = True
            return None
        end = min(self._pos + self._block, self._pcm.size)
        # Due when the block's last sample has played, measured from start(), so the pace doesn't drift
        wait = self._t0 + end / self.sample_rate / self.speed - time.monotonic()
        if wait > timeout:
            time.sleep(timeout)
            return None
        if wait > 0:
            time.sleep(wait)
        block = self._pcm[self._pos:end]
        self._pos = end
        return block

    def close(self) -> None:
        # Finished sessions stay in memory for their report, so drop the audio now
        self._pcm = np.zeros(0, dtype=np.float32)
        self._pos = 0
