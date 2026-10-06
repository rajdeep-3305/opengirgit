"""Audio device discovery helpers: PulseAudio/PipeWire parsing (offline)."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opengirgit import audio  # noqa: E402

PACTL_LIST_SHORT = "\n".join(
    [
        "46\talsa_output.pci-0000_00_1f.3.analog-stereo.monitor\tPipeWire\ts16le 2ch 48000Hz\tSUSPENDED",
        "47\talsa_input.pci-0000_00_1f.3.analog-stereo\tPipeWire\ts16le 2ch 48000Hz\tSUSPENDED",
        "52\tbluez_output.AC_12_2F_9E_00_11.a2dp-sink.monitor\tPipeWire\ts16le 2ch 48000Hz\tIDLE",
        "garbage line without tabs",
    ]
)


def test_parse_pactl_sources_keeps_only_monitors():
    monitors = audio.parse_pactl_sources(PACTL_LIST_SHORT)
    names = [name for name, _default in monitors]
    assert names == [
        "alsa_output.pci-0000_00_1f.3.analog-stereo.monitor",
        "bluez_output.AC_12_2F_9E_00_11.a2dp-sink.monitor",
    ]
    assert not any(default for _name, default in monitors)


def test_parse_pactl_sources_flags_the_default_sink_monitor_first():
    monitors = audio.parse_pactl_sources(
        PACTL_LIST_SHORT, "bluez_output.AC_12_2F_9E_00_11.a2dp-sink"
    )
    assert monitors[0][0] == "bluez_output.AC_12_2F_9E_00_11.a2dp-sink.monitor"
    assert monitors[0][1] is True
    assert monitors[1][1] is False


def test_parse_pactl_sources_tolerates_empty_output():
    assert audio.parse_pactl_sources("") == []
    assert audio.parse_pactl_sources("no tabs here") == []


def test_linux_loopback_devices_builds_parec_ids(monkeypatch):
    def fake_pactl(*args):
        if args == ("list", "short", "sources"):
            return PACTL_LIST_SHORT
        if args == ("get-default-sink",):
            return "alsa_output.pci-0000_00_1f.3.analog-stereo\n"
        return None

    monkeypatch.setattr(audio, "_run_pactl", fake_pactl)
    devices = audio.linux_loopback_devices()
    assert [device.kind for device in devices] == ["loopback", "loopback"]
    assert devices[0].id == "parec:alsa_output.pci-0000_00_1f.3.analog-stereo.monitor"
    assert devices[0].is_default is True
    assert devices[0].label().endswith("[loopback]")


def test_linux_loopback_devices_empty_without_pactl(monkeypatch):
    monkeypatch.setattr(audio, "_run_pactl", lambda *args: None)
    assert audio.linux_loopback_devices() == []


def test_missing_device_hints_are_platform_specific(monkeypatch):
    monkeypatch.setattr(audio, "IS_WINDOWS", False)
    monkeypatch.setattr(audio, "IS_LINUX", True)
    assert "pulseaudio-utils" in audio.missing_device_hint("system")
    monkeypatch.setattr(audio, "IS_LINUX", False)
    assert "BlackHole" in audio.missing_device_hint("system")
    assert "microphone" in audio.missing_device_hint("microphone")
