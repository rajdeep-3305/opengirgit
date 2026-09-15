"""Stream resampler / DSP helpers (numpy only, no Qt)."""

from __future__ import annotations

import numpy as np
import pytest
from opengirgit.dsp import (
    StreamResampler,
    float32_to_pcm16,
    rms,
    to_mono_float32,
)

numpy = pytest.importorskip("numpy")


def _sine(rate: int, seconds: float, freq: float = 440.0) -> np.ndarray:
    t = np.arange(int(rate * seconds), dtype=np.float32) / rate
    return np.sin(2 * np.pi * freq * t, dtype=np.float32)


def test_passthrough_returns_same_length():
    resampler = StreamResampler(16000, 16000)
    assert resampler.passthrough
    chunk = _sine(16000, 0.1)
    assert resampler.process(chunk).shape == chunk.shape


def test_downsample_48k_to_16k_length():
    resampler = StreamResampler(48000, 16000)
    out = resampler.process(_sine(48000, 1.0))
    # allow the one-sample interpolation tail
    assert abs(out.size - 16000) <= 2


def test_streaming_chunks_match_single_pass():
    source = _sine(48000, 0.5)
    single = StreamResampler(48000, 16000)
    reference = single.process(source)

    chunked = StreamResampler(48000, 16000)
    pieces = [chunked.process(part) for part in np.array_split(source, 20)]
    streamed = np.concatenate(pieces)

    assert streamed.size == reference.size
    assert np.allclose(streamed, reference, atol=1e-6)


def test_downmix_stereo_to_mono():
    left = np.array([1000, -1000, 1000, -1000], dtype=np.int16)
    right = -left
    interleaved = np.empty(left.size * 2, dtype=np.int16)
    interleaved[0::2] = left
    interleaved[1::2] = right
    mono = to_mono_float32(interleaved.tobytes(), 2)
    assert mono.size == 4
    assert np.allclose(mono, 0.0, atol=1e-6)


def test_to_mono_and_back_round_trip():
    samples = np.array([0.0, 0.5, -0.5, 1.0, -1.0], dtype=np.float32)
    raw = float32_to_pcm16(samples)
    restored = to_mono_float32(raw, 1)
    assert np.allclose(restored, samples, atol=1e-3)


def test_rms_levels():
    assert rms(np.empty(0, dtype=np.float32)) == 0.0
    assert rms(np.zeros(64, dtype=np.float32)) == 0.0
    assert rms(np.ones(64, dtype=np.float32)) == pytest.approx(1.0)


def test_invalid_rates_rejected():
    with pytest.raises(ValueError):
        StreamResampler(0, 16000)
    with pytest.raises(ValueError):
        to_mono_float32(b"\x00\x00", 0)
