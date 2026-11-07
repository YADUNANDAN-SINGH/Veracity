#!/usr/bin/env python3
"""Measure the AI-voice model on recordings, the way a live call scores them.

    cd veracity-backend && source venv/bin/activate
    python ../eval/voice_eval.py --real DIR [DIR ...] --ai DIR [DIR ...] [--channels clean,phone_wb,replay]

Put recordings of real people in the --real folders and of cloned or synthetic voices
in the --ai folders, one source per folder (your own voice and a clone of it, with
consent, are the best pair). WAV works as is; MP3, M4A, MP4 and other formats need
ffmpeg (brew install ffmpeg), which the phone channels need too.

Each file is brought to a phone-like speech level, sent through each channel, and
scored like a call: a 4 s window every second from the third second on, silence
skipped, calibrated with VERA_VOICE_T, then the live smoother decides whether the
call would have turned "Likely AI". Channels:
  clean     as recorded
  phone_nb  300-3400 Hz, 8 kHz G.711 mu-law, then AAC (a 2G/3G call through scrcpy)
  phone_wb  16 kbit/s Opus at 16 kHz, then AAC (close to a VoLTE call)
  replay    played from a small loudspeaker into a phone in a room, then phone_wb
Real phone-line recordings (Save audio on) are better than any simulation.

Writes eval/voice_eval_results.md (or --out). Needs the ML requirements (requirements-ml.txt).
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, fftconvolve, lfilter, sosfilt
from scipy.stats import rankdata

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "veracity-backend"))

from app.feature import voice  # noqa: E402
from app.feature.audio_capture import TARGET_SR, to_mono_16k  # noqa: E402

OUT = ROOT / "eval" / "voice_eval_results.md"
SR = TARGET_SR
CHANNELS = ("clean", "phone_nb", "phone_wb", "replay")
AUDIO = {".wav", ".flac", ".mp3", ".m4a", ".mp4", ".mov", ".ogg", ".opus", ".aac", ".webm"}


# ---------- audio ----------

def _ffmpeg(args: list[str], data: bytes = b"") -> bytes:
    r = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", *args], input=data, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode(errors="replace")[-400:])
    return r.stdout


def load(path: Path) -> np.ndarray:
    """Any audio or video file → 16 kHz mono float32, at a phone-like speech level."""
    if path.suffix.lower() == ".wav" and not shutil.which("ffmpeg"):
        sr, x = wavfile.read(path)
        x = x.astype(np.float32) / np.iinfo(x.dtype).max if np.issubdtype(x.dtype, np.integer) else x.astype(np.float32)
        x = to_mono_16k(x, sr)
    else:
        x = np.frombuffer(_ffmpeg(["-i", str(path), "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "pipe:1"]), dtype=np.float32)
    return level(x)


def level(x: np.ndarray, dbfs: float = -24.0) -> np.ndarray:
    """The same speech level for every file, so loudness can't give the answer away."""
    rms = float(np.sqrt(np.mean(x.astype(np.float64) ** 2)) + 1e-9)
    y = x * (10 ** (dbfs / 20) / rms)
    peak = float(np.abs(y).max() + 1e-9)
    return (y / peak * 0.99 if peak > 0.99 else y).astype(np.float32)


def speaker_room(x: np.ndarray, seed: int) -> np.ndarray:
    """A small loudspeaker (180 Hz-7.5 kHz, presence bump) in a room (RT60 0.2-0.6 s,
    direct-to-reverb 0-8 dB) with background noise (20-35 dB SNR), heard by a phone."""
    rng = np.random.default_rng(seed)
    y = sosfilt(butter(2, [180, 7500], btype="band", fs=SR, output="sos"), x)
    b, a = butter(2, [2000, 3200], btype="band", fs=SR)
    y = y + 0.4 * lfilter(b, a, y)
    rt60, drr_db, snr_db = rng.uniform(0.2, 0.6), rng.uniform(0, 8), rng.uniform(20, 35)
    t = np.arange(int(rt60 * SR * 1.2)) / SR
    tail = rng.standard_normal(len(t)) * np.exp(-6.9 * t / rt60)
    tail[: int(0.003 * SR)] = 0
    h = tail / np.sqrt(np.sum(tail ** 2)) * 10 ** (-drr_db / 20)
    h[0] = 1.0
    y = fftconvolve(y, h)[: len(y)]
    noise = lfilter([1], [1, -0.95], rng.standard_normal(len(y)))
    y = y + noise / (np.sqrt(np.mean(noise ** 2)) + 1e-9) * (np.sqrt(np.mean(y ** 2)) + 1e-9) * 10 ** (-snr_db / 20)
    return level(y.astype(np.float32))


def channel(x: np.ndarray, cond: str, seed: int = 0) -> np.ndarray:
    """The audio as a call would carry it: the codec, then scrcpy's AAC."""
    if cond == "clean":
        return x
    if cond == "replay":
        return channel(speaker_room(x, seed), "phone_wb")
    raw = x.astype(np.float32).tobytes()
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        if cond == "phone_nb":
            coded = _ffmpeg(["-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "pipe:0", "-af", "highpass=f=300,lowpass=f=3400",
                             "-ar", "8000", "-c:a", "pcm_mulaw", "-f", "mulaw", "pipe:1"], raw)
            pcm48 = _ffmpeg(["-f", "mulaw", "-ar", "8000", "-ac", "1", "-i", "pipe:0", "-ar", "48000", "-f", "f32le", "pipe:1"], coded)
        elif cond == "phone_wb":
            (td / "in.raw").write_bytes(raw)
            _ffmpeg(["-y", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", str(td / "in.raw"), "-c:a", "libopus", "-b:a", "16k",
                     "-application", "voip", "-ar", "16000", str(td / "c.opus")])
            pcm48 = _ffmpeg(["-i", str(td / "c.opus"), "-ar", "48000", "-ac", "1", "-f", "f32le", "pipe:1"])
        else:
            raise ValueError(f"unknown channel {cond!r}")
        (td / "p48.raw").write_bytes(pcm48)
        _ffmpeg(["-y", "-f", "f32le", "-ar", "48000", "-ac", "1", "-i", str(td / "p48.raw"), "-c:a", "aac", "-b:a", "128k", str(td / "a.m4a")])
        y = np.frombuffer(_ffmpeg(["-i", str(td / "a.m4a"), "-ar", str(SR), "-ac", "1", "-f", "f32le", "pipe:1"]), dtype=np.float32)
    return y[: len(x)].copy() if len(y) >= len(x) else np.pad(y, (0, len(x) - len(y)))


# ---------- scoring ----------

def score_file(x: np.ndarray, detector) -> list[float]:
    """Calibrated p(AI) for each window a live call would score (as Session._score_voice does)."""
    win = int(voice.WINDOW_S * SR)
    windows = (x[max(0, end - win):end] for end in range(SR, len(x) + 1, SR))
    return [voice.calibrate(detector.p_fake(w)) for w in windows if voice.scorable(w)]


def turns_ai(scores: list[float]) -> bool:
    smoother = voice.VerdictSmoother()
    for p in scores:
        smoother.update(p)
    return smoother.verdict == "LIKELY_AI"


def roc(real: np.ndarray, ai: np.ndarray) -> tuple[float, float]:
    """(AUC, EER) for windows, AI as the positive class; ties count half."""
    ranks = rankdata(np.concatenate([real, ai]))
    n_real, n_ai = len(real), len(ai)
    auc = (ranks[n_real:].sum() - n_ai * (n_ai + 1) / 2) / (n_real * n_ai)
    best = (2.0, 1.0)
    for th in np.unique(np.concatenate([real, ai, [np.inf]])):
        fpr, fnr = float(np.mean(real >= th)), float(np.mean(ai < th))
        best = min(best, (abs(fpr - fnr), (fpr + fnr) / 2))
    return float(auc), best[1]


def run(real_dirs: list[Path], ai_dirs: list[Path], channels=("clean",), detector=None) -> str:
    detector = detector or voice.load_detector()
    folders = [(d, "real") for d in real_dirs] + [(d, "AI") for d in ai_dirs]
    results = {}  # (folder, channel) -> [(windows, turned)]
    for folder, label in folders:
        paths = sorted(p for p in folder.rglob("*") if p.suffix.lower() in AUDIO)
        if not paths:
            raise SystemExit(f"No audio files in {folder}")
        for path in paths:
            x = load(path)
            for cond in channels:
                s = score_file(channel(x, cond, seed=zlib.crc32(path.name.encode())), detector)
                results.setdefault((folder, cond), []).append((s, turns_ai(s)))
        print(f"{label:4} {folder}: {len(paths)} files", flush=True)

    md = [
        "# AI-voice model: evaluation on recordings", "",
        f"Model `{voice.VOICE_MODEL}`, calibration T = {voice.CALIBRATION_T}. A call turns *Likely AI* after "
        f"{voice.AI_RUN} windows in a row ≥ {voice.T_AI}; scoring starts {voice.MIN_WINDOW_S:.0f} s into a file.", "",
        "| Folder | Label | " + " | ".join(channels) + " |",
        "| --- | --- |" + " ---: |" * len(channels),
    ]
    for folder, label in folders:
        cells = []
        for cond in channels:
            r = results[(folder, cond)]
            cells.append(f"{sum(t for _, t in r)} of {len(r)} calls Likely AI")
        md.append(f"| `{folder.name}` | {label} | " + " | ".join(cells) + " |")
    md += ["", "| Channel | Windows (real / AI) | Window ROC AUC | Equal error rate |", "| --- | ---: | ---: | ---: |"]
    for cond in channels:
        real = np.concatenate([s for d, _ in folders[:len(real_dirs)] for s, _ in results[(d, cond)]] or [[]])
        ai = np.concatenate([s for d, _ in folders[len(real_dirs):] for s, _ in results[(d, cond)]] or [[]])
        if len(real) and len(ai):
            auc, eer = roc(real, ai)
            md.append(f"| {cond} | {len(real)} / {len(ai)} | {auc:.3f} | {eer:.1%} |")
    md += ["", "Small sets swing a lot: report the file counts with any number you quote.", ""]
    return "\n".join(md)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--real", type=Path, nargs="+", required=True, help="folders of real voices, one source each")
    parser.add_argument("--ai", type=Path, nargs="+", required=True, help="folders of cloned or synthetic voices")
    parser.add_argument("--channels", default="clean", help=f"comma-separated, from {', '.join(CHANNELS)} (default clean)")
    parser.add_argument("--telephone", action="store_true", help="same as --channels clean,phone_nb")
    parser.add_argument("--out", type=Path, default=OUT, help=f"where to write the table (default {OUT.relative_to(ROOT)})")
    args = parser.parse_args()
    chans = ["clean", "phone_nb"] if args.telephone else [c.strip() for c in args.channels.split(",") if c.strip()]
    if bad := [c for c in chans if c not in CHANNELS]:
        raise SystemExit(f"Unknown channel {bad[0]!r}; choose from {', '.join(CHANNELS)}")
    if any(c != "clean" for c in chans) and not shutil.which("ffmpeg"):
        raise SystemExit("The phone channels need ffmpeg: brew install ffmpeg")
    report = run(args.real, args.ai, chans)
    args.out.write_text(report, encoding="utf-8")
    print(report)
    print(f"wrote {args.out}")
