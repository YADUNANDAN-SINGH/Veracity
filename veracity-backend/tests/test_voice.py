# The AI-voice pieces that don't need the model: the smoother's verdict, which windows
# get scored, and the window preparation Spectra-0 was trained with.

import numpy as np
import pytest

from app.feature import voice


def run(ps):
    smoother = voice.VerdictSmoother()
    states = [smoother.update(p).state for p in ps]
    return smoother, states


def test_three_ai_windows_in_a_row_make_it_likely_ai():
    _, states = run([0.9, 0.9, 0.2, 0.9, 0.9, 0.9])
    assert states[:5] == ["UNCERTAIN"] * 5
    assert states[5] == "LIKELY_AI"


def test_the_call_verdict_stays_likely_ai_after_a_human_speaks():
    smoother, states = run([0.95] * 4 + [0.05] * 8)
    assert states[3] == "LIKELY_AI"
    assert smoother.state == "LIKELY_HUMAN"  # the live meter follows whoever speaks now
    assert smoother.verdict == "LIKELY_AI"  # the gate and the report remember the AI voice


def test_a_human_call_never_gets_an_ai_verdict():
    smoother, _ = run([0.1, 0.8, 0.8, 0.1, 0.8, 0.05])  # never three in a row
    assert smoother.verdict != "LIKELY_AI"


def test_silent_windows_keep_the_verdict():
    smoother, _ = run([0.95, 0.95, 0.95])
    smoother.update(None)
    assert smoother.state == smoother.verdict == "LIKELY_AI"


def test_a_call_is_scored_from_its_third_second():
    speech = (0.1 * np.sin(np.arange(16_000 * 4) / 7)).astype(np.float32)
    assert not voice.scorable(speech[:16_000])  # 1 s repeated to fill 4 s sounds synthetic to the model
    assert not voice.scorable(speech[:32_000])
    assert voice.scorable(speech[:48_000])
    assert voice.scorable(speech)
    assert not voice.scorable(np.zeros(64_000, dtype=np.float32))  # silence


def test_prepare_matches_the_training_window():
    pytest.importorskip("torch")
    from app.feature import spectra0

    x = np.random.default_rng(0).standard_normal(16_000 * 5).astype(np.float32)
    long = spectra0.prepare(x)
    assert long.shape == (spectra0.N_SAMPLES,) and long.dtype == np.float32
    emphasised = np.concatenate([x[:1], x[1:] - 0.97 * x[:-1]])
    assert np.allclose(long, emphasised[-spectra0.N_SAMPLES:])  # the most recent samples

    short = spectra0.prepare(x[:48_000])  # a call's third second
    assert short.shape == (spectra0.N_SAMPLES,)
    assert np.allclose(short[:48_000], emphasised[:48_000])  # repeated from its start
    assert np.allclose(short[48_000:], emphasised[:spectra0.N_SAMPLES - 48_000])
