# AI-voice scoring (Project Document §1.5): a 4 s window every second →
# p(fake) from the deepfake model → temperature calibration → EMA smoothing
# → LIKELY_HUMAN / UNCERTAIN / LIKELY_AI.
#
# 0.40, 0.75 and T = 1.0 are starting values; replace them with the ones
# calibrated on your own recordings (VERA_VOICE_T, VERA_T_AI, VERA_T_UNCERTAIN).

import logging
import math
import os
import threading
from dataclasses import dataclass

import numpy as np

log = logging.getLogger("veracity.voice")

# XLS-R (pretrained on 128 languages, Hindi included). On speech sent through a
# simulated phone channel (300–3400 Hz, mu-law, AAC) it put 1% of real-voice
# windows at ≥ 0.75 and 100% of synthetic ones; mo-thecreator/Deepfake-audio-detection,
# the first choice, put 26% of real voices there and flagged real calls as AI.
VOICE_MODEL = os.environ.get("VERA_VOICE_MODEL", "Gustking/wav2vec2-large-xlsr-deepfake-audio-classification")
CALIBRATION_T = float(os.environ.get("VERA_VOICE_T", "1.0"))
T_AI = float(os.environ.get("VERA_T_AI", "0.75"))
T_UNCERTAIN = float(os.environ.get("VERA_T_UNCERTAIN", "0.40"))
SMOOTH_ALPHA = 0.5
AI_RUN = 3  # windows in a row ≥ T_AI before LIKELY_AI

WINDOW_S = 4.0
SILENCE_DBFS = -45.0  # quieter windows aren't scored


class DeepfakeDetector:
    def __init__(self, model_id: str = VOICE_MODEL):
        import torch
        from transformers import pipeline

        device = "mps" if torch.backends.mps.is_available() else "cpu"
        self.clf = pipeline("audio-classification", model=model_id, device=device)
        log.info("voice model loaded on %s", device)

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


_detector: DeepfakeDetector | None = None
_lock = threading.Lock()


def load_detector() -> DeepfakeDetector:
    """Load once (several seconds); later calls return the same model."""
    global _detector
    with _lock:
        if _detector is None:
            _detector = DeepfakeDetector()
        return _detector


def detector_if_ready() -> DeepfakeDetector | None:
    """The model if it has finished loading, without waiting for it."""
    return _detector


def calibrate(p_raw: float, t: float = CALIBRATION_T) -> float:
    """sigmoid(logit(p) / T): T > 1 pulls overconfident scores toward 50%."""
    p = min(max(p_raw, 1e-6), 1 - 1e-6)
    return 1 / (1 + math.exp(-math.log(p / (1 - p)) / t))


@dataclass
class VoiceState:
    state: str
    smoothed: float
    changed: bool


class VerdictSmoother:
    """LIKELY_AI only after AI_RUN windows in a row ≥ T_AI; one weaker window doesn't flip it back."""

    def __init__(self):
        self.ema: float | None = None
        self.run = 0
        self.state = "LIKELY_HUMAN"

    def update(self, p: float | None) -> VoiceState:
        if p is None:  # silent window: keep the last verdict
            return VoiceState(self.state, round(self.ema or 0.0, 4), False)
        prev = self.state
        self.ema = p if self.ema is None else SMOOTH_ALPHA * p + (1 - SMOOTH_ALPHA) * self.ema
        self.run = self.run + 1 if p >= T_AI else 0
        if self.run >= AI_RUN:
            self.state = "LIKELY_AI"
        elif self.state == "LIKELY_AI" and self.ema >= T_UNCERTAIN:
            pass
        else:
            self.state = "UNCERTAIN" if self.ema >= T_UNCERTAIN else "LIKELY_HUMAN"
        return VoiceState(self.state, round(self.ema, 4), self.state != prev)
