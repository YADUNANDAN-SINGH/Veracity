#!/usr/bin/env python3
"""Measure the AI-voice model on your own recordings, the way a live call scores them.

    cd veracity-backend && source venv/bin/activate
    python ../eval/voice_eval.py --real recordings/real --ai recordings/ai [--telephone]

Put WAV files of real people in --real and of cloned or synthetic voices in --ai
(same speakers in both if you can, e.g. your own voice and a clone of it, with
consent). Each file is scored like a call: a 4 s window every second, calibrated
with VERA_VOICE_T, silence skipped, then the live smoother decides whether the
call would have turned "Likely AI". --telephone first sends the audio through a
simple phone channel (300-3400 Hz band, 8 kHz, mu-law), closer to what a call
carries; real phone-line recordings (Save audio on) are better still.

Writes eval/voice_results.md. Needs the ML requirements (requirements-ml.txt).
"""

import argparse
import math
import sys
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, resample_poly, sosfiltfilt
from scipy.stats import rankdata

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "veracity-backend"))

from app.feature import voice  # noqa: E402
from app.feature.audio_capture import TARGET_SR, rms_dbfs, to_mono_16k  # noqa: E402

OUT = ROOT / "eval" / "voice_results.md"


def load(path: Path, telephone: bool) -> np.ndarray:
    sr, x = wavfile.read(path)
    if np.issubdtype(x.dtype, np.integer):
        x = x.astype(np.float32) / np.iinfo(x.dtype).max
    x = to_mono_16k(x.astype(np.float32), sr)
    return phone_channel(x) if telephone else x


def phone_channel(x: np.ndarray) -> np.ndarray:
    """300-3400 Hz band, down to 8 kHz with mu-law (8 bit), back up to 16 kHz."""
    band = sosfiltfilt(butter(6, [300, 3400], btype="band", fs=TARGET_SR, output="sos"), x)
    x8 = resample_poly(band, 1, 2)
    mu = 255.0
    y = np.sign(x8) * np.log1p(mu * np.clip(np.abs(x8), 0, 1)) / math.log1p(mu)
    y = np.round(y * 127) / 127  # 8-bit companded samples
    x8 = np.sign(y) * (np.power(1 + mu, np.abs(y)) - 1) / mu
    return resample_poly(x8, 2, 1).astype(np.float32)


def score_file(x: np.ndarray, detector) -> list[float]:
    """Calibrated p(AI) for each 4 s window, one per second of speech (as Session._score_voice does)."""
    win, hop = int(voice.WINDOW_S * TARGET_SR), TARGET_SR
    scores = []
    for end in range(TARGET_SR, len(x) + 1, hop):
        window = x[max(0, end - win):end]
        if rms_dbfs(window) < voice.SILENCE_DBFS:
            continue
        scores.append(voice.calibrate(detector.p_fake(window)))
    return scores


def turns_ai(scores: list[float]) -> bool:
    smoother = voice.VerdictSmoother()
    return any(smoother.update(p).state == "LIKELY_AI" for p in scores)


def roc(real: np.ndarray, ai: np.ndarray) -> tuple[float, float]:
    """(AUC, EER) for windows, AI as the positive class; ties count half, as they should."""
    ranks = rankdata(np.concatenate([real, ai]))  # average ranks for ties
    n_real, n_ai = len(real), len(ai)
    auc = (ranks[n_real:].sum() - n_ai * (n_ai + 1) / 2) / (n_real * n_ai)
    best = (2.0, 1.0)
    for th in np.unique(np.concatenate([real, ai, [np.inf]])):
        fpr, fnr = float(np.mean(real >= th)), float(np.mean(ai < th))
        best = min(best, (abs(fpr - fnr), (fpr + fnr) / 2))
    return float(auc), best[1]


def run(real_dir: Path, ai_dir: Path, telephone: bool, detector=None) -> str:
    detector = detector or voice.load_detector()
    rows, windows = [], {"real": [], "ai": []}
    for label, folder in (("real", real_dir), ("ai", ai_dir)):
        for path in sorted(folder.glob("*.wav")):
            scores = score_file(load(path, telephone), detector)
            windows[label] += scores
            rows.append((label, path.name, len(scores), max(scores, default=0.0), turns_ai(scores)))
    real, ai = np.array(windows["real"]), np.array(windows["ai"])
    if len(real) == 0 or len(ai) == 0:
        raise SystemExit("Need at least one scored WAV in both --real and --ai.")
    auc, eer = roc(real, ai)
    files = {lab: [r for r in rows if r[0] == lab] for lab in ("real", "ai")}

    md = [
        "# AI-voice model: evaluation on recordings",
        "",
        f"Model `{voice.VOICE_MODEL}`, calibration T = {voice.CALIBRATION_T}, AI threshold {voice.T_AI}. "
        f"Audio: {'simulated phone channel (300-3400 Hz, 8 kHz mu-law)' if telephone else 'as recorded'}.",
        "",
        "| | Real voices | AI voices |",
        "| --- | ---: | ---: |",
        f"| Files | {len(files['real'])} | {len(files['ai'])} |",
        f"| 4 s windows scored | {len(real)} | {len(ai)} |",
        f"| Windows ≥ {voice.T_AI} | {np.mean(real >= voice.T_AI):.0%} (false alarms) | {np.mean(ai >= voice.T_AI):.0%} (caught) |",
        f"| Calls that turned *Likely AI* | {np.mean([r[4] for r in files['real']]):.0%} | {np.mean([r[4] for r in files['ai']]):.0%} |",
        "",
        f"Window-level ROC AUC **{auc:.3f}**, equal error rate **{eer:.1%}**.",
        "",
        "| File | Label | Windows | Peak p(AI) | Turned Likely AI |",
        "| --- | --- | ---: | ---: | --- |",
        *[f"| `{name}` | {lab} | {n} | {peak:.2f} | {'yes' if flag else 'no'} |" for lab, name, n, peak, flag in rows],
        "",
        "Small sets swing a lot: report the file counts with any number you quote.",
        "",
    ]
    return "\n".join(md)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--real", type=Path, required=True, help="folder of WAVs of real voices")
    parser.add_argument("--ai", type=Path, required=True, help="folder of WAVs of cloned or synthetic voices")
    parser.add_argument("--telephone", action="store_true", help="simulate a phone channel first")
    args = parser.parse_args()
    report = run(args.real, args.ai, args.telephone)
    OUT.write_text(report, encoding="utf-8")
    print(report)
    print(f"wrote {OUT.relative_to(ROOT)}")
