"""Audio device helpers (skipped without PySide6)."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opengirgit import audio  # noqa: E402


def test_missing_device_hint_points_at_pyaudiowpatch():
    assert "PyAudioWPatch" in audio.missing_device_hint("system")
    assert "PyAudioWPatch" in audio.missing_device_hint("loopback")
    assert "microphone" in audio.missing_device_hint("microphone")
