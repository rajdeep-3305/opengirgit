#!/usr/bin/env python3
"""Live smoke test for the local STT pipeline.

Two modes, both exercising exactly the code the app runs (``dsp`` ->
``AudioCapture``/file reader -> ``stt.LocalWhisperEngine``):

* ``--wav FILE`` / ``--pcm FILE``
    Replays an audio file through the same downmix + resample + segmentation
    chain used for live capture. Any sample rate / channel count is accepted
    (16-bit PCM); the script resamples to 16 kHz mono itself.

* ``--capture SECONDS``
    Captures from a real device for N seconds and transcribes it. On Windows
    ``--source system`` uses WASAPI loopback (the same path the app uses to
    hear the interviewer); ``--source microphone`` uses the input device.

Requires the client dependencies plus ``faster-whisper`` (see
``client/requirements.txt``). The model is downloaded on first use.

Examples
--------
::

    # file replay, assert a phrase is present
    python tests/e2e/stt_smoke.py --wav speech.wav --expect "hello"

    # measure real latency: real-time replay + the silence gate you intend to use
    python tests/e2e/stt_smoke.py --wav speech.wav --realtime --model tiny.en --silence 0.4

    # live loopback capture on Windows (play audio while it runs)
    python tests/e2e/stt_smoke.py --capture 8 --source system

    # live microphone capture, explicit device
    python tests/e2e/stt_smoke.py --capture 8 --source microphone --device input:3

Exit code is 0 when a transcript was produced (and ``--expect`` matched, if
given), 1 otherwise.
"""

from __future__ import annotations

import argparse
import sys
import time
import wave
from pathlib import Path

CLIENT_DIR = Path(__file__).resolve().parents[2] / "client"
if str(CLIENT_DIR) not in sys.path:
    sys.path.insert(0, str(CLIENT_DIR))

from opengirgit.audio import AudioCapture, default_device_id, list_devices  # noqa: E402
from opengirgit.config import AppSettings  # noqa: E402
from opengirgit.dsp import StreamResampler, float32_to_pcm16, to_mono_float32  # noqa: E402
from opengirgit.stt import LocalWhisperEngine, describe_engine  # noqa: E402
from PySide6.QtCore import QCoreApplication, QTimer  # noqa: E402

BLOCK_FRAMES = 1024
REPORT_GRACE_MS = 400  # let queued worker signals drain before reporting


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--wav", type=Path, help="16-bit PCM WAV file to replay")
    source.add_argument("--pcm", type=Path, help="raw PCM file to replay (needs --rate/--channels)")
    source.add_argument(
        "--capture", type=float, metavar="SECONDS", help="capture live audio for N seconds"
    )

    parser.add_argument(
        "--rate", type=int, default=16000, help="sample rate of --pcm input (default 16000)"
    )
    parser.add_argument(
        "--channels",
        type=int,
        default=1,
        help="channel count of --pcm input (default 1; use 2 for stereo)",
    )
    parser.add_argument("--source", choices=("system", "microphone"), default="system")
    parser.add_argument(
        "--device", default="", help="device id override, e.g. input:3 or loopback:7"
    )
    parser.add_argument("--model", default="base.en", help="whisper model name (default base.en)")
    parser.add_argument("--language", default="en", help="language code (default en)")
    parser.add_argument(
        "--silence",
        type=float,
        default=0.9,
        help="utterance silence gate in seconds (default 0.9, lower = snappier)",
    )
    parser.add_argument(
        "--realtime",
        action="store_true",
        help="replay files at real-time pace and report end-of-audio -> final latency",
    )
    parser.add_argument(
        "--expect", default="", help="require this substring (case-insensitive) in the transcript"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="seconds to wait for transcription (default 300)",
    )
    return parser.parse_args()


def settings_from_args(args: argparse.Namespace) -> AppSettings:
    overrides: dict[str, object] = {
        "whisper_model": args.model,
        "language": args.language,
        "silence_seconds": args.silence,
    }
    if args.device:
        overrides["audio_device"] = args.device
    return AppSettings.from_dict(overrides)  # type: ignore[arg-type]


class SmokeRun:
    """Feeds PCM into the engine and reports the emitted transcript."""

    def __init__(self, settings: AppSettings, label: str, expect: str, timeout: float) -> None:
        self.settings = settings
        self.label = label
        self.expect = expect.lower()
        self.timeout = timeout
        self.finals: list[str] = []
        self.statuses: list[str] = []
        self.errors: list[str] = []
        self.started = time.time()
        self.t_final: float | None = None
        self.t_last_audio: float | None = None
        self.listening = False
        self.measure_latency = False

        self.engine = LocalWhisperEngine(settings)
        self.engine.final.connect(self._on_final)
        self.engine.status.connect(self._on_status)
        self.engine.error.connect(self.errors.append)

        self._feeder = None  # set by subclasses
        self._capture: AudioCapture | None = None
        self._deadline = time.time() + timeout

    def _on_status(self, text: str) -> None:
        if text == "listening":
            self.listening = True
        self.statuses.append(text)

    def _on_final(self, text: str) -> None:
        self.t_final = time.time()
        self.finals.append(text)

    # -- lifecycle --------------------------------------------------------- #

    def _start(self) -> None:
        print(f"mode: {self.label}")
        print(f"engine: {describe_engine(self.settings)}")
        self.engine.start()

    def _poll_finished(self) -> None:
        if time.time() > self._deadline:
            self.errors.append(f"timed out after {self.timeout:.0f}s waiting for transcription")
            self._report()
            return
        if self.engine.isFinished() and self._capture_done():
            QTimer.singleShot(REPORT_GRACE_MS, self._report)
        else:
            QTimer.singleShot(50, self._poll_finished)

    def _capture_done(self) -> bool:
        return self._capture is None or self._capture.isFinished()

    def _shutdown(self) -> None:
        self.engine.stop_engine()
        self._poll_finished()

    def _await_final_then_shutdown(self, grace: float) -> None:
        """Let the engine finish any utterance (grace seconds), then stop it."""
        started = time.time()

        def check() -> None:
            if self.t_final is not None or time.time() - started > grace:
                self._shutdown()
            else:
                QTimer.singleShot(50, check)

        check()

    def _wait_listening(self, then) -> None:  # noqa: ANN001 - simple callback
        """Run ``then`` once the engine reports it is listening (model loaded)."""
        if self.listening:
            then()
        elif self.errors or time.time() > self._deadline:
            print("errors:", self.errors or "(engine never became ready)")
            print("RESULT: FAIL")
            app.exit(1)
        else:
            QTimer.singleShot(50, lambda: self._wait_listening(then))

    # -- reporting ---------------------------------------------------------- #

    def _report(self) -> None:
        transcript = " ".join(self.finals).strip()
        print("statuses:", self.statuses or "(none)")
        if self.errors:
            print("errors:", self.errors)
        print(f"elapsed: {time.time() - self.started:.1f}s")
        if self.measure_latency and self.t_last_audio is not None and self.t_final is not None:
            gate = self.settings.silence_seconds
            latency = self.t_final - self.t_last_audio
            print(
                f"latency (last audio -> final): {latency:.2f}s "
                f"(gate {gate:.1f}s + transcribe ~{max(0.0, latency - gate):.2f}s)"
            )
        print("transcript:", transcript or "(nothing)")
        ok = bool(transcript)
        if self.expect:
            ok = ok and self.expect in transcript.lower()
            print(
                f"expected substring: {self.expect!r} -> {'found' if self.expect in transcript.lower() else 'MISSING'}"
            )
        print("RESULT:", "PASS" if ok else "FAIL")
        app.exit(0 if ok else 1)


class FileRun(SmokeRun):
    """Replays a PCM buffer through the app's capture pipeline."""

    def __init__(
        self,
        settings: AppSettings,
        pcm: bytes,
        rate: int,
        channels: int,
        realtime: bool = False,
        **kw,
    ) -> None:
        super().__init__(
            settings,
            label=f"file replay ({rate} Hz, {channels}ch, {len(pcm) / 2 / channels / rate:.1f}s"
            + (", real-time)" if realtime else ")"),
            **kw,
        )
        self._pcm = pcm + b"\x00" * int(rate * channels * 2 * 1.5)  # trailing silence
        self._speech_bytes = len(pcm)
        self._rate = rate
        self._channels = channels
        self._offset = 0
        self._realtime = realtime
        self.measure_latency = realtime
        self._resampler = StreamResampler(rate, 16000)

    def start(self) -> None:
        self._start()
        self._wait_listening(lambda: QTimer.singleShot(0, self._feed_block))

    def _feed_block(self) -> None:
        block_bytes = BLOCK_FRAMES * self._channels * 2
        if self._offset >= len(self._pcm):
            if self.t_last_audio is None:
                self.t_last_audio = time.time()
            # the trailing silence triggers the natural silence-gate final;
            # stop the engine only if it never comes (engine failure)
            self._await_final_then_shutdown(30.0)
            return
        block = self._pcm[self._offset : self._offset + block_bytes]
        self._offset += block_bytes
        mono = to_mono_float32(block, self._channels)
        resampled = self._resampler.process(mono)
        if resampled.size:
            self.engine.feed(float32_to_pcm16(resampled))
        if self._realtime and self._offset >= self._speech_bytes and self.t_last_audio is None:
            self.t_last_audio = time.time()  # end of speech; silence keeps streaming
        # one block is BLOCK_FRAMES frames of source audio (64 ms at 16 kHz)
        interval = max(1, int(1000 * BLOCK_FRAMES / self._rate)) if self._realtime else 2
        QTimer.singleShot(interval, self._feed_block)


class CaptureRun(SmokeRun):
    """Captures live audio from a device (WASAPI loopback on Windows)."""

    def __init__(self, settings: AppSettings, seconds: float, device_id: str, **kw) -> None:
        super().__init__(
            settings, label=f"live capture ({seconds:.0f}s from {device_id or 'default'})", **kw
        )
        self._seconds = seconds
        self._capture = AudioCapture(device_id)
        self._capture.frame.connect(self.engine.feed)
        self._capture.error.connect(self.errors.append)
        self._capture.started_ok.connect(lambda rate: print(f"capture: native rate {rate} Hz"))

    def start(self) -> None:
        self._start()
        print(f"capture: recording {self._seconds:.0f}s — play some audio now")
        self._capture.start()
        QTimer.singleShot(int(self._seconds * 1000), self._stop_capture)

    def _stop_capture(self) -> None:
        if self._capture is not None:
            self._capture.stop_capture()
        self.t_last_audio = time.time()
        self.measure_latency = True
        self._await_final_then_shutdown(15.0)


def load_pcm(path: Path, rate: int, channels: int) -> tuple[bytes, int, int]:
    if path.suffix.lower() == ".wav":
        with wave.open(str(path), "rb") as wav:
            if wav.getsampwidth() != 2:
                raise SystemExit(
                    f"{path} is not 16-bit PCM; convert it first, e.g.:\n"
                    f"  ffmpeg -i {path} -ac 1 -ar 16000 -c:a pcm_s16le out.wav"
                )
            return wav.readframes(wav.getnframes()), wav.getframerate(), wav.getnchannels()
    return path.read_bytes(), rate, channels


def resolve_device(args: argparse.Namespace, settings: AppSettings) -> str:
    if args.device:
        return args.device
    kind = "loopback" if args.source == "system" else "input"
    device_id = default_device_id(kind)
    if not device_id:
        known = ", ".join(f"{d.id} ({d.name})" for d in list_devices()) or "none found"
        raise SystemExit(f"no {kind} device found. Known devices: {known}")
    return device_id


def main() -> int:
    args = parse_args()
    settings = settings_from_args(args)

    if args.capture is not None:
        if args.capture <= 0:
            raise SystemExit("--capture seconds must be positive")
        device_id = resolve_device(args, settings)
        run: SmokeRun = CaptureRun(
            settings,
            seconds=args.capture,
            device_id=device_id,
            expect=args.expect,
            timeout=args.timeout,
        )
    else:
        path: Path = args.wav or args.pcm
        if not path.is_file():
            raise SystemExit(f"file not found: {path}")
        pcm, rate, channels = load_pcm(path, args.rate, args.channels)
        run = FileRun(
            settings,
            pcm,
            rate,
            channels,
            realtime=args.realtime,
            expect=args.expect,
            timeout=args.timeout,
        )

    run.start()
    return app.exec()


app = QCoreApplication(sys.argv)

if __name__ == "__main__":
    raise SystemExit(main())
