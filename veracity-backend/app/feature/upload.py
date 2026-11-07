# An uploaded call recording, for the judge build (Dockerfile.judge): the file
# goes through the same Session pipeline as a live call (the real Spectra-0
# voice model, Whisper, the scam rules, the local LLM if one is running, risk
# fusion, the payment gate and the report), read from FileCapture instead of
# BlackHole.
#
# Differences from a live call:
#   - no scrcpy and no audio-device check, and no "nothing is reaching BlackHole" alert
#   - an `audio_done` event when the file runs out; the call doesn't end by itself, so
#     payments are still decided by the user's "End call & build report" (finish())
#   - stop() waits longer for Whisper to finish the queued chunks: a judge's CPU in
#     Docker is slower than the Mac this was tuned on
#   - the audio is never saved, and the upload is deleted as soon as it's decoded
#
# Uploads are on with VERA_UPLOAD=1, when torch and faster-whisper are installed
# and ffmpeg is on PATH. The light judge build (the root Dockerfile) has none of them.

import importlib.util
import logging
import os
import shutil
import threading

from app.feature import scam_llm, transcriber, voice
from app.feature.file_capture import FileCapture
from app.feature.session import Session, warm_models

log = logging.getLogger("veracity.upload")

ENABLED = os.environ.get("VERA_UPLOAD") == "1"
MAX_MB = float(os.environ.get("VERA_UPLOAD_MAX_MB", "20"))
EXTENSIONS = ("wav", "mp3", "m4a", "ogg", "flac", "webm")
DRAIN_S = 90.0  # how long stop() waits for Whisper to finish the chunks still queued
CAPTURE_METHOD = "upload_file"

NEEDS_FULL_BUILD = "needs the full judge build"
NO_FFMPEG = "ffmpeg not found"
LOADING = "models still loading"
LOAD_FAILED = "the models failed to load (see the server log)"

_warmed = threading.Event()  # set once warm() has finished, whether the models loaded or not


def models_installed() -> bool:
    """torch and faster-whisper are importable (checked without importing them: torch takes seconds)."""
    return all(importlib.util.find_spec(name) is not None for name in ("torch", "faster_whisper"))


def models_loaded() -> bool:
    return voice.detector_if_ready() is not None and transcriber.model_if_ready() is not None


def warm() -> None:
    """Load the voice model and Whisper at start-up, then note that loading is over."""
    warm_models()
    _warmed.set()


def ffmpeg_found() -> bool:
    return shutil.which("ffmpeg") is not None


def availability() -> tuple[bool, str | None]:
    """(available, reason): whether this server can analyse an uploaded recording right now."""
    if not ENABLED or not models_installed():
        return False, NEEDS_FULL_BUILD
    if not ffmpeg_found():
        return False, NO_FFMPEG
    if not models_loaded():
        return False, LOAD_FAILED if _warmed.is_set() else LOADING
    return True, None


class UploadSession(Session):
    watch_routing = False  # the audio comes from a file, not BlackHole

    def __init__(self, capture: FileCapture, filename: str, loop, caller_number: str | None = None):
        super().__init__(caller_number, save_audio=False, loop=loop)
        self.capture = capture
        self.filename = filename
        self.capture_method = CAPTURE_METHOD
        self.audio_device = None

    def start(self) -> None:
        self._publish({
            "type": "mode", "replay": False, "upload": True, "filename": self.filename,
            "duration_s": self.capture.duration_s, "region": self.region, "llm": scam_llm.available(),
        })
        self.capture.start()
        self._audio_thread.start()
        self._text_thread.start()

    def _run_audio(self) -> None:
        super()._run_audio()  # returns when the file runs out, or when the call is ended early
        if self.capture.finished:
            self._publish({"type": "audio_done", "t": self.capture.duration_s})

    def stop(self) -> dict:
        if self.report is not None:
            return self.report
        self._stop.set()
        self._audio_thread.join(timeout=5)
        self._text_thread.join(timeout=DRAIN_S)
        if self._text_thread.is_alive():
            log.warning("whisper still busy after %.0f s; the report has the transcript so far", DRAIN_S)
        return super().stop()  # its joins return at once now; it builds and publishes the report
