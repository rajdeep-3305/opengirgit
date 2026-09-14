"""Audio DSP helpers — pure numpy, no Qt, fully unit-testable.

Everything works on float32 mono in [-1, 1] internally; ``pcm16`` bytes are the
wire format for the STT engines.
"""

from __future__ import annotations

import numpy as np

INT16_SCALE = 32768.0


def to_mono_float32(raw: bytes, channels: int) -> np.ndarray:
    """int16 interleaved PCM bytes -> float32 mono samples in [-1, 1]."""
    if channels < 1:
        raise ValueError("channels must be >= 1")
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    if samples.size == 0:
        return samples
    if channels > 1:
        usable = (samples.size // channels) * channels
        samples = samples[:usable].reshape(-1, channels).mean(axis=1)
    return samples / INT16_SCALE


def float32_to_pcm16(samples: np.ndarray) -> bytes:
    """float32 mono [-1, 1] -> int16 little-endian PCM bytes."""
    if samples.size == 0:
        return b""
    clipped = np.clip(samples, -1.0, 1.0)
    return (clipped * 32767.0).astype("<i2").tobytes()


def rms(samples: np.ndarray) -> float:
    """Root-mean-square level of a float32 buffer (0.0 when empty)."""
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))


class StreamResampler:
    """Stateful linear-interpolation resampler for a continuous sample stream.

    ``process`` may be called with arbitrarily sized chunks; the fractional
    sample position and the last input sample are carried over between calls so
    the output stream stays gapless.
    """

    def __init__(self, src_rate: int, dst_rate: int) -> None:
        if src_rate <= 0 or dst_rate <= 0:
            raise ValueError("sample rates must be positive")
        self.src_rate = int(src_rate)
        self.dst_rate = int(dst_rate)
        self.ratio = self.src_rate / self.dst_rate
        self._tail = np.zeros(1, dtype=np.float32)
        self._pos = 0.0

    @property
    def passthrough(self) -> bool:
        return abs(self.ratio - 1.0) < 1e-9

    def process(self, chunk: np.ndarray) -> np.ndarray:
        if chunk.size == 0:
            return np.empty(0, dtype=np.float32)
        chunk = np.asarray(chunk, dtype=np.float32)
        if self.passthrough:
            return chunk.copy()

        samples = np.concatenate((self._tail, chunk))
        last_index = samples.size - 1
        positions = np.arange(self._pos, last_index, self.ratio, dtype=np.float64)
        if positions.size == 0:
            self._tail = samples[-1:]
            self._pos = max(self._pos - last_index, 0.0)
            return np.empty(0, dtype=np.float32)

        idx = np.floor(positions).astype(np.int64)
        frac = (positions - idx).astype(np.float32)
        out = samples[idx] * (1.0 - frac) + samples[idx + 1] * frac

        self._pos = float(positions[-1] + self.ratio - last_index)
        if self._pos < 0.0:
            self._pos = 0.0
        self._tail = samples[-1:]
        return out
