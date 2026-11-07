# FileCapture (uploaded recordings, judge build) and the two Session hooks it
# relies on, checked so the phone build's live loop behaves exactly as before.

import shutil
import time

import numpy as np
import pytest
from scipy.io import wavfile

from app.feature import file_capture
from app.feature.audio_capture import LiveCapture
from app.feature.file_capture import DecodeError, FileCapture, TooLong
from app.feature.session import Session

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg isn't installed")


def write_wav(path, seconds, sr=44_100, channels=2, amplitude=0.1):
    """A 440 Hz tone, stereo int16, like a typical phone recording export."""
    t = np.arange(int(seconds * sr)) / sr
    x = (amplitude * np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
    wavfile.write(path, sr, np.stack([x] * channels, axis=1) if channels > 1 else x)
    return path


def read_all(capture):
    blocks = []
    while (block := capture.read(timeout=0.5)) is not None or not capture.finished:
        if block is not None:
            blocks.append(block)
    return blocks


@needs_ffmpeg
def test_decodes_to_mono_16k_blocks_and_deletes_the_upload(tmp_path):
    path = write_wav(tmp_path / "call.wav", 2.5)
    capture = FileCapture(path, speed=1000)
    assert not path.exists()  # deleted as soon as it was decoded
    assert capture.sample_rate == 16_000 and capture.duration_s == 2.5

    capture.start()
    blocks = read_all(capture)
    assert all(b.ndim == 1 and b.dtype == np.float32 for b in blocks)
    assert {len(b) for b in blocks[:-1]} == {1600}  # 0.1 s blocks, the last one may be shorter
    assert sum(len(b) for b in blocks) == 40_000
    assert capture.finished and capture.read() is None


@needs_ffmpeg
def test_blocks_are_paced_at_real_time_times_the_speed(tmp_path):
    capture = FileCapture(write_wav(tmp_path / "call.wav", 2.0), speed=20)
    capture.start()
    t0 = time.monotonic()
    first = capture.read(timeout=0.5)
    assert first is not None and time.monotonic() - t0 >= 0.1 / 20 * 0.9  # not handed out before it has "played"
    read_all(capture)
    elapsed = time.monotonic() - t0
    assert 2.0 / 20 * 0.9 <= elapsed < 2.0 / 20 + 0.5


@needs_ffmpeg
def test_read_waits_at_most_the_timeout(tmp_path):
    capture = FileCapture(write_wav(tmp_path / "call.wav", 1.0), speed=0.1)  # a block every second
    capture.start()
    t0 = time.monotonic()
    assert capture.read(timeout=0.05) is None and not capture.finished
    assert time.monotonic() - t0 < 0.5


@needs_ffmpeg
def test_too_long_and_unreadable_files_are_refused_and_still_deleted(tmp_path, monkeypatch):
    monkeypatch.setattr(file_capture, "MAX_S", 1.0)
    long = write_wav(tmp_path / "long.wav", 2.5)
    with pytest.raises(TooLong):
        FileCapture(long)
    assert not long.exists()

    junk = tmp_path / "junk.mp3"
    junk.write_bytes(b"this is not audio" * 100)
    with pytest.raises(DecodeError):
        FileCapture(junk)
    assert not junk.exists()


# ----- the phone build's loop is unchanged -----

class SilentLiveInput:
    """Stands in for LiveCapture on a call that isn't routed to BlackHole: exact zeros, then nothing."""

    finished = False

    def __init__(self, blocks=70, sr=48_000):
        self.sample_rate = sr
        self._left = blocks
        self.reads_after_end = 0

    def read(self, timeout=0.5):
        if self._left == 0:
            self.reads_after_end += 1
            time.sleep(0.01)
            return None
        self._left -= 1
        return np.zeros(int(self.sample_rate * 0.1), dtype=np.float32)

    def close(self):
        pass


def test_live_input_never_reports_finished():
    assert LiveCapture.finished is False


def test_a_live_session_still_alerts_on_no_audio_and_keeps_listening(monkeypatch):
    session = Session(None, save_audio=False, loop=None)
    events = []
    monkeypatch.setattr(session, "_publish", events.append)
    session.capture = SilentLiveInput(blocks=70)  # 7 s of digital silence, then no blocks at all
    session._audio_thread.start()

    deadline = time.monotonic() + 5
    while session.capture.reads_after_end < 20 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert [e["kind"] for e in events if e["type"] == "alert"] == ["audio"]
    assert session._audio_thread.is_alive()  # no blocks for a while doesn't end a live call

    session._stop.set()
    session._audio_thread.join(timeout=2)
    assert not session._audio_thread.is_alive()
    assert not any(e["type"] == "audio_done" for e in events)


def test_the_audio_loop_ends_when_a_recording_runs_out(monkeypatch):
    session = Session(None, save_audio=False, loop=None)
    monkeypatch.setattr(session, "_publish", lambda e: None)
    capture = SilentLiveInput(blocks=5)
    capture.finished = True  # as FileCapture says once its last block is read
    session.capture = capture
    session._audio_thread.start()
    session._audio_thread.join(timeout=2)
    assert not session._audio_thread.is_alive()
    assert session._chunks.get_nowait() is None  # the transcriber is told the audio is over
