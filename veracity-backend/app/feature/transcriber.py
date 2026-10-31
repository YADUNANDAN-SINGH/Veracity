# Speech-to-text for the scam-script layer: faster-whisper on the CPU (int8).
# It doesn't resample NumPy arrays, so pass 16 kHz mono.
#
# Tuned for narrow-band Hindi/Hinglish call audio:
#   - language "hi" by default: detecting it per chunk picked Romanian and German
#     on real calls (VERA_LANGUAGE=auto turns detection back on, "en" forces English)
#   - temperature 0 with one small retry: Whisper's default retries up to 1.0,
#     which is slow and turns unclear audio into word salad
#   - no repeated 3-word phrases: temperature 0 alone can loop ("आपने आपने आपने …")
#   - segments Whisper itself thinks are not speech are dropped
#
# VERA_WHISPER_MODEL picks the size; VERA_WHISPER_THREADS the CPU threads.

import logging
import os
import threading

import numpy as np

log = logging.getLogger("veracity.transcriber")

# large-v3-turbo: on Hindi speech through a simulated phone channel it got 10% of
# characters wrong at 5.0 s per 8 s chunk; small got 22% (2.5 s), medium 21% (8.1 s,
# too slow to keep up). Use "small" on a slower Mac.
WHISPER_SIZE = os.environ.get("VERA_WHISPER_MODEL", "large-v3-turbo")
_language = os.environ.get("VERA_LANGUAGE", "hi")
LANGUAGE = None if _language == "auto" else _language
CPU_THREADS = int(os.environ.get("VERA_WHISPER_THREADS", min(8, os.cpu_count() or 4)))

# A segment is dropped when Whisper is both unsure there was speech and unsure of the words
NO_SPEECH_PROB = 0.6
LOW_LOGPROB = -1.0

_model = None
_lock = threading.Lock()


def load_model():
    global _model
    with _lock:
        if _model is None:
            from faster_whisper import WhisperModel

            _model = WhisperModel(WHISPER_SIZE, device="cpu", compute_type="int8", cpu_threads=CPU_THREADS)
            log.info("whisper %s loaded (%d threads, language %s)", WHISPER_SIZE, CPU_THREADS, LANGUAGE or "auto")
        return _model


def transcribe(x16k: np.ndarray) -> str:
    """One chunk of call audio → its text ("" if nobody spoke)."""
    segments, _info = load_model().transcribe(
        x16k,
        language=LANGUAGE,
        vad_filter=True,
        temperature=[0.0, 0.2],
        condition_on_previous_text=False,  # each chunk stands alone, so one bad chunk can't spoil the next
        no_repeat_ngram_size=3,
    )
    kept = [
        s.text.strip() for s in segments
        if not (s.no_speech_prob > NO_SPEECH_PROB and s.avg_logprob < LOW_LOGPROB)
    ]
    return " ".join(t for t in kept if t).strip()
