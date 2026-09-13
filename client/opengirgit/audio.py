"""Audio capture: WASAPI loopback (system audio) or a microphone.

Output is always 16 kHz mono int16 PCM, delivered through the ``frame`` signal.

* Windows **system audio** requires ``pyaudiowpatch`` and a ``loopback:<index>``
  device (use :func:`list_devices`).
* **Microphone** capture uses ``sounddevice`` and works on Windows, macOS and
  Linux (device id ``input:<index>``).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QThread, Signal

from .dsp import StreamResampler, float32_to_pcm16, rms, to_mono_float32

TARGET_RATE = 16_000
FRAMES_PER_BUFFER = 1024

IS_WINDOWS = sys.platform == "win32"


class AudioError(Exception):
    pass


@dataclass
class AudioDevice:
    id: str
    name: str
    kind: str  # "loopback" | "input"
    is_default: bool = False

    def label(self) -> str:
        tag = " [loopback]" if self.kind == "loopback" else ""
        return f"{self.name}{tag}"


def _pyaudio():  # pragma: no cover - windows only
    try:
        import pyaudiowpatch as pyaudio
    except ImportError as exc:
        raise AudioError(
            "pyaudiowpatch is not installed — system-audio capture needs it "
            "(pip install PyAudioWPatch), or switch to microphone mode."
        ) from exc
    return pyaudio


def _sounddevice():  # pragma: no cover - platform dependent
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise AudioError("sounddevice is not installed (pip install sounddevice)") from exc
    return sd


def list_devices() -> list[AudioDevice]:
    """Enumerate loopback (Windows) and microphone devices."""
    devices: list[AudioDevice] = []

    if IS_WINDOWS:
        try:  # pragma: no cover - windows only
            pyaudio = _pyaudio()
            with pyaudio.PyAudio() as p:
                default_index = -1
                try:
                    wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
                    default_out = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
                    if default_out.get("isLoopbackDevice"):
                        default_index = int(default_out["index"])
                    else:
                        for loopback in p.get_loopback_device_info_generator():
                            if default_out["name"] in loopback["name"]:
                                default_index = int(loopback["index"])
                                break
                except Exception:
                    pass
                for info in p.get_loopback_device_info_generator():
                    devices.append(
                        AudioDevice(
                            id=f"loopback:{int(info['index'])}",
                            name=str(info["name"]),
                            kind="loopback",
                            is_default=int(info["index"]) == default_index,
                        )
                    )
        except AudioError:
            pass

    try:  # pragma: no cover - platform dependent
        sd = _sounddevice()
        default_input = None
        try:
            default_input = sd.query_devices(kind="input")
        except Exception:
            pass
        for index, info in enumerate(sd.query_devices()):
            if int(info.get("max_input_channels", 0)) < 1:
                continue
            name = str(info.get("name", f"input {index}"))
            is_default = bool(
                default_input is not None and name == str(default_input.get("name", ""))
            )
            devices.append(
                AudioDevice(id=f"input:{index}", name=name, kind="input", is_default=is_default)
            )
    except AudioError:
        pass

    return devices


def default_device_id(source: str) -> str:
    devices = list_devices()
    for device in devices:
        if device.kind == source and device.is_default:
            return device.id
    for device in devices:
        if device.kind == source:
            return device.id
    return ""


class AudioCapture(QThread):
    """Streams 16 kHz mono int16 PCM frames until :meth:`stop_capture` is called."""

    frame = Signal(bytes)
    level = Signal(float)
    error = Signal(str)
    started_ok = Signal(int)  # native sample rate

    def __init__(self, device_id: str, parent=None) -> None:
        super().__init__(parent)
        self._device_id = device_id or ""
        self._stop = False
        self._stream = None

    def stop_capture(self) -> None:
        self._stop = True
        stream = self._stream
        if stream is not None:
            try:
                stream.stop_stream()  # unblocks read()
            except Exception:
                pass

    # -- thread ------------------------------------------------------------ #

    def run(self) -> None:  # noqa: D102
        try:
            if self._device_id.startswith("loopback:"):
                self._run_loopback(int(self._device_id.split(":", 1)[1]))
            else:
                self._run_input(self._device_id)
        except AudioError as exc:
            self.error.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            self.error.emit(f"audio capture failed: {exc}")
        finally:
            self._stream = None

    # -- backends ---------------------------------------------------------- #

    def _run_loopback(self, index: int) -> None:  # pragma: no cover - windows only
        pyaudio = _pyaudio()
        with pyaudio.PyAudio() as p:
            info = p.get_device_info_by_index(index)
            samplerate = int(info["defaultSampleRate"])
            channels = max(1, int(info["maxInputChannels"]))
            stream = p.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=samplerate,
                input=True,
                input_device_index=index,
                frames_per_buffer=FRAMES_PER_BUFFER,
            )
            self._stream = stream
            self.started_ok.emit(samplerate)
            self._pump(stream.read, samplerate, channels)

    def _run_input(self, device_id: str) -> None:
        sd = _sounddevice()
        index = None
        if device_id.startswith("input:"):
            suffix = device_id.split(":", 1)[1]
            if suffix.isdigit():
                index = int(suffix)

        info = sd.query_devices(index, "input") if index is not None else sd.query_devices(kind="input")
        samplerate = int(info.get("default_samplerate") or 48000)
        channels = 1

        stream = sd.RawInputStream(
            samplerate=samplerate,
            blocksize=FRAMES_PER_BUFFER,
            device=index,
            channels=channels,
            dtype="int16",
            callback=None,
        )
        stream.start()
        self._stream = stream
        self.started_ok.emit(samplerate)
        self._pump(stream.read, samplerate, channels)
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass

    # -- shared pump ------------------------------------------------------- #

    def _pump(self, read, samplerate: int, channels: int) -> None:
        resampler = StreamResampler(samplerate, TARGET_RATE)
        while not self._stop:
            raw = read(FRAMES_PER_BUFFER, exception_on_overflow=False)
            if isinstance(raw, tuple):  # sounddevice RawInputStream returns (bytes, overflowed)
                raw = raw[0]
            if not raw:
                continue
            mono = to_mono_float32(bytes(raw), channels)
            self.level.emit(rms(mono))
            resampled = resampler.process(mono)
            if resampled.size:
                self.frame.emit(float32_to_pcm16(resampled))
        try:
            stream = self._stream
            if stream is not None and hasattr(stream, "stop_stream"):
                stream.stop_stream()
                stream.close()
        except Exception:
            pass


def pcm16_duration_seconds(pcm: bytes) -> float:
    return len(pcm) / 2.0 / TARGET_RATE


def silence_ratio(pcm: bytes, threshold: float = 0.005) -> float:
    """Fraction of the buffer below ``threshold`` RMS (diagnostics helper)."""
    samples = to_mono_float32(pcm, 1)
    if samples.size == 0:
        return 1.0
    return float(np.mean(np.abs(samples) < threshold))
