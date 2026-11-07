# The live stream's resampling: BlackHole's 0.1 s blocks must come out as if the whole
# call had been resampled at once. Block-by-block resampling clicked at every edge and
# hid a cloned voice from the AI-voice model.

import numpy as np
import pytest

from app.feature.audio_capture import StreamResampler, to_mono_16k


@pytest.mark.parametrize("sr", [48_000, 44_100, 96_000, 16_000])
def test_streaming_matches_resampling_the_whole_call(sr):
    x = np.random.default_rng(0).standard_normal((sr * 2, 2)).astype(np.float32) * 0.1
    rs = StreamResampler(sr)
    out = np.concatenate([rs(x[i:i + sr // 10]) for i in range(0, len(x), sr // 10)])
    whole = to_mono_16k(x, sr)
    assert len(whole) - len(out) <= 160  # at most 10 ms held back for the next block
    assert np.allclose(out, whole[:len(out)], atol=1e-6)


def test_irregular_blocks_change_nothing():
    sr = 48_000
    x = np.random.default_rng(1).standard_normal(sr * 2).astype(np.float32) * 0.1
    sizes = np.random.default_rng(2).integers(1, 9_000, 400)
    rs, out, i = StreamResampler(sr), [], 0
    for n in sizes:
        out.append(rs(x[i:i + n]))
        i += n
    out = np.concatenate(out)
    assert np.allclose(out, to_mono_16k(x[:i], sr)[:len(out)], atol=1e-6)


def test_no_clicks_at_block_edges():
    sr = 48_000
    t = np.arange(sr * 2) / sr
    tone = (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    rs = StreamResampler(sr)
    out = np.concatenate([rs(tone[i:i + 4800]) for i in range(0, len(tone), 4800)])
    ref = (0.3 * np.sin(2 * np.pi * 440 * np.arange(len(out)) / 16_000)).astype(np.float32)
    err = np.abs(out - ref)[1600:]  # past the start, where a one-go resample has its own ramp
    assert err.max() < 1e-3
