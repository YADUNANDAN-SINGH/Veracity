# AI-voice scoring (Project Document §1.5): a 4 s window every second →
# p(AI) from the detector → temperature calibration → EMA smoothing
# → LIKELY_HUMAN / UNCERTAIN / LIKELY_AI.
#
# The detector is Spectra-0 (app/feature/spectra0.py), an XLS-R anti-spoofing
# network. The wav2vec2 classifier it replaces scored speech from newer
# generators (ElevenLabs, Google Veo, AI podcasts) as human: on 7 Nov 2026 a Veo
# narration played into a call stayed "Likely human" at 7-22%. Measured on
# recordings, phone codecs and a loudspeaker in eval/voice_results.md.
#
# VERA_VOICE_MODEL can name any Hugging Face audio-classification model instead
# (scored with the transformers pipeline). T, the thresholds and the run length
# are starting values; recalibrate them on your own recordings.

import logging
import math
import os
import threading
from dataclasses import dataclass

import numpy as np

log = logging.getLogger("veracity.voice")

# app/feature/spectra0.py needs torch, so it's imported only when the model loads:
# the light judge build has no torch and never scores a voice
SPECTRA0 = "lab260/spectra_0"
VOICE_MODEL = os.environ.get("VERA_VOICE_MODEL", SPECTRA0)
CALIBRATION_T = float(os.environ.get("VERA_VOICE_T", "1.0"))
T_AI = float(os.environ.get("VERA_T_AI", "0.75"))
T_UNCERTAIN = float(os.environ.get("VERA_T_UNCERTAIN", "0.40"))
SMOOTH_ALPHA = 0.5
AI_RUN = 3  # windows in a row ≥ T_AI before LIKELY_AI

WINDOW_S = 4.0
# The model wants 4 s, so a shorter window is repeated to fill it. One second
# repeated four times sounds synthetic to it (8% of human starts scored ≥ T_AI,
# against ~1% from 3 s on), so a call is scored from its third second.
MIN_WINDOW_S = 3.0
SILENCE_DBFS = -45.0  # quieter windows aren't scored


class Spectra0Detector:
    def __init__(self):
        import torch

        from app.feature import spectra0

        self._torch, self._spectra0 = torch, spectra0
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        self.net = spectra0.load(self.device)
        log.info("voice model %s loaded on %s", spectra0.REPO, self.device)

    def p_fake(self, x16k: np.ndarray) -> float:
        x = self._torch.from_numpy(self._spectra0.prepare(x16k)).unsqueeze(0).to(self.device)
        logits = self.net.score(x)
        z = float(logits[0, 0] - logits[0, 1])  # spoof minus bona fide: softmax(logits)[spoof]
        return 1 / (1 + math.exp(-z)) if z >= 0 else math.exp(z) / (1 + math.exp(z))


class PipelineDetector:
    """Any transformers audio-classification model (VERA_VOICE_MODEL)."""

    def __init__(self, model_id: str):
        import torch
        from transformers import pipeline

        device = "mps" if torch.backends.mps.is_available() else "cpu"
        self.clf = pipeline("audio-classification", model=model_id, device=device)
        log.info("voice model %s loaded on %s", model_id, device)

    def p_fake(self, x16k: np.ndarray) -> float:
        # Pass 16 kHz explicitly, otherwise the pipeline wants torchaudio to resample
        out = self.clf({"raw": x16k, "sampling_rate": 16_000}, top_k=None)
        scores = {d["label"].lower(): d["score"] for d in out}
        # Models name the classes differently: fake/real, spoof/bonafide, ...
        for label in ("fake", "spoof", "aivoice"):
            if label in scores:
                return float(scores[label])
        for label in ("real", "bonafide", "humanvoice"):
            if label in scores:
                return float(1 - scores[label])
        raise ValueError(f"Can't tell which label means AI voice: {sorted(scores)}")


_detector: Spectra0Detector | PipelineDetector | None = None
_lock = threading.Lock()


def load_detector() -> Spectra0Detector | PipelineDetector:
    """Load once (several seconds); later calls return the same model."""
    global _detector
    with _lock:
        if _detector is None:
            _detector = Spectra0Detector() if VOICE_MODEL == SPECTRA0 else PipelineDetector(VOICE_MODEL)
        return _detector


def detector_if_ready() -> Spectra0Detector | PipelineDetector | None:
    """The model if it has finished loading, without waiting for it."""
    return _detector


def scorable(window: np.ndarray) -> bool:
    """Long enough for the model and loud enough to be speech (16 kHz audio)."""
    from app.feature.audio_capture import TARGET_SR, rms_dbfs

    return len(window) >= MIN_WINDOW_S * TARGET_SR and rms_dbfs(window) >= SILENCE_DBFS


def calibrate(p_raw: float, t: float = CALIBRATION_T) -> float:
    """sigmoid(logit(p) / T): T > 1 pulls overconfident scores toward 50%."""
    p = min(max(p_raw, 1e-6), 1 - 1e-6)
    return 1 / (1 + math.exp(-math.log(p / (1 - p)) / t))


@dataclass
class VoiceState:
    state: str  # the voice right now (the timeline)
    smoothed: float
    changed: bool
    verdict: str = "LIKELY_HUMAN"  # the call's verdict: once Likely AI, it stays Likely AI
    peak: float = 0.0  # the highest smoothed score so far: the call's headline once it's Likely AI


class VerdictSmoother:
    """LIKELY_AI only after AI_RUN windows in a row ≥ T_AI; one weaker window doesn't flip it back.

    `state` follows the voice as it is now (the timeline); `verdict` is the call's:
    once a voice has been Likely AI, the call stays Likely AI even if someone else
    speaks, or the recording trails off into silence, afterwards (the headline meter,
    the payment gate and the report read this).
    """

    def __init__(self):
        self.ema: float | None = None
        self.run = 0
        self.state = "LIKELY_HUMAN"
        self.was_ai = False
        self.peak = 0.0  # the same number as smoothed_peak() over the windows so far

    @property
    def verdict(self) -> str:
        return "LIKELY_AI" if self.was_ai else self.state

    def update(self, p: float | None) -> VoiceState:
        if p is None:  # silent window: keep the last verdict
            return VoiceState(self.state, round(self.ema or 0.0, 4), False, self.verdict, round(self.peak, 4))
        prev = self.state
        self.ema = p if self.ema is None else SMOOTH_ALPHA * p + (1 - SMOOTH_ALPHA) * self.ema
        self.run = self.run + 1 if p >= T_AI else 0
        if self.run >= AI_RUN:
            self.state = "LIKELY_AI"
        elif self.state == "LIKELY_AI" and self.ema >= T_UNCERTAIN:
            pass
        else:
            self.state = "UNCERTAIN" if self.ema >= T_UNCERTAIN else "LIKELY_HUMAN"
        self.was_ai = self.was_ai or self.state == "LIKELY_AI"
        self.peak = max(self.peak, self.ema)
        return VoiceState(self.state, round(self.ema, 4), self.state != prev, self.verdict, round(self.peak, 4))


def smoothed_peak(p_ais) -> float:
    """Highest smoothed AI probability over a call's speech windows (what the gate and report fuse)."""
    ema, peak = None, 0.0
    for p in p_ais:
        ema = p if ema is None else SMOOTH_ALPHA * p + (1 - SMOOTH_ALPHA) * ema
        peak = max(peak, ema)
    return peak
