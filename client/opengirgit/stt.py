"""Speech-to-text engines.

Two interchangeable engines, both consuming 16 kHz mono int16 PCM:

* :class:`LocalWhisperEngine` — fully offline transcription with
  ``faster-whisper`` (default). Simple energy-based utterance segmentation.
* :class:`DeepgramEngine` — streaming over a direct WebSocket to Deepgram,
  authenticated with a short-lived token minted by *your* server (the audio
  never passes through the server, matching the original architecture).
"""

from __future__ import annotations

import json
import queue
import time
from collections.abc import Callable

import numpy as np
from PySide6.QtCore import QThread, Signal

from .api import ApiClient, ApiError
from .config import AppSettings
from .dsp import rms, to_mono_float32

TARGET_RATE = 16_000
QUEUE_MAX_CHUNKS = 400  # ~25 s of 1024-frame chunks at 16 kHz


class SttEngine(QThread):
    """Base class: ``feed()`` PCM in, ``final``/``partial`` text out."""

    partial = Signal(str)
    final = Signal(str)
    error = Signal(str)
    status = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=QUEUE_MAX_CHUNKS)
        self._stop_flag = False

    # -- public API --------------------------------------------------------- #

    def feed(self, pcm: bytes) -> None:
        if not pcm:
            return
        try:
            self._queue.put_nowait(pcm)
        except queue.Full:
            try:
                self._queue.get_nowait()  # drop oldest, keep listening live
                self._queue.put_nowait(pcm)
            except queue.Empty:
                pass

    def stop_engine(self) -> None:
        self._stop_flag = True

    def _next_chunk(self, timeout: float = 0.2) -> bytes | None:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None


# --------------------------------------------------------------------------- #
# Local faster-whisper
# --------------------------------------------------------------------------- #


class LocalWhisperEngine(SttEngine):
    def __init__(self, settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._model = None
        self._buffer: list[np.ndarray] = []
        self._preroll: list[np.ndarray] = []
        self._speaking = False
        self._silence_frames = 0
        self._buffered_samples = 0
        self._last_partial_samples = 0
        self._last_partial_text = ""

    # -- tunables ----------------------------------------------------------- #

    RMS_THRESHOLD = 0.006
    SILENCE_SECONDS = 0.9
    MIN_UTTERANCE_SECONDS = 0.4
    MAX_UTTERANCE_SECONDS = 20.0
    PREROLL_SECONDS = 0.3
    #: While an utterance is in progress, re-transcribe at most this often and
    #: emit the text as a partial (live transcript). Disable via settings.partials.
    PARTIAL_INTERVAL_SECONDS = 1.2
    #: If a partial pass takes longer than this, back off (heavy models on CPU).
    PARTIAL_SLOW_SECONDS = 0.9
    #: Upper bound for the adaptive back-off factor.
    PARTIAL_MAX_BACKOFF = 4.0
    #: Partial passes only look at the most recent window, to bound CPU cost.
    PARTIAL_WINDOW_SECONDS = 15.0

    def run(self) -> None:  # noqa: D102
        try:
            self._load_model()
        except Exception as exc:  # noqa: BLE001
            self.error.emit(
                f"could not load the whisper model: {exc}. "
                "Check the model name in settings or install faster-whisper."
            )
            return

        self.status.emit("listening")
        frame_seconds = 1024 / TARGET_RATE
        silence_seconds = float(getattr(self._settings, "silence_seconds", self.SILENCE_SECONDS))
        silence_frames_needed = max(1, int(silence_seconds / frame_seconds))
        preroll_max = max(1, int(self.PREROLL_SECONDS / frame_seconds))
        max_samples = int(self.MAX_UTTERANCE_SECONDS * TARGET_RATE)
        partials_enabled = bool(getattr(self._settings, "partials", True))
        partial_step = int(self.PARTIAL_INTERVAL_SECONDS * TARGET_RATE)
        partial_backoff = 1.0

        while not self._stop_flag:
            pcm = self._next_chunk()
            if pcm is None:
                if self._speaking and self._silence_frames == 0:
                    continue
                if self._speaking:
                    self._finalise()
                continue

            chunk = to_mono_float32(pcm, 1)
            if chunk.size == 0:
                continue
            level = rms(chunk)

            if level >= self.RMS_THRESHOLD:
                if not self._speaking:
                    self._buffer = list(self._preroll)
                    self._buffered_samples = sum(part.size for part in self._buffer)
                    self._speaking = True
                    self._last_partial_samples = 0
                    self._last_partial_text = ""
                    self.status.emit("hearing speech…")
                self._buffer.append(chunk)
                self._buffered_samples += chunk.size
                self._silence_frames = 0
                if self._buffered_samples >= max_samples:
                    self._finalise()
                elif (
                    partials_enabled
                    and partial_backoff <= self.PARTIAL_MAX_BACKOFF
                    and self._buffered_samples - self._last_partial_samples
                    >= partial_step * partial_backoff
                ):
                    self._last_partial_samples = self._buffered_samples
                    started = time.monotonic()
                    self._emit_partial()
                    if time.monotonic() - started > self.PARTIAL_SLOW_SECONDS:
                        # the model cannot keep up with 1.2 s cadence — ease off
                        partial_backoff = min(self.PARTIAL_MAX_BACKOFF, partial_backoff * 2)
            else:
                self._preroll.append(chunk)
                if len(self._preroll) > preroll_max:
                    del self._preroll[0]
                if self._speaking:
                    self._buffer.append(chunk)
                    self._buffered_samples += chunk.size
                    self._silence_frames += 1
                    if self._silence_frames >= silence_frames_needed:
                        self._finalise()

        self._finalise()
        self.status.emit("stopped")

    # -- helpers ------------------------------------------------------------ #

    def _load_model(self) -> None:
        if self._model is not None:
            return
        self.status.emit(f"loading model {self._settings.whisper_model}…")
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "faster-whisper is not installed (pip install faster-whisper), "
                "or switch the STT engine to 'deepgram' in settings"
            ) from exc
        self._model = WhisperModel(
            self._settings.whisper_model,
            device="cpu",
            compute_type=self._settings.whisper_compute_type,
        )

    def _buffer_audio(self) -> np.ndarray:
        return np.concatenate(self._buffer) if self._buffer else np.empty(0, np.float32)

    def _transcribe(self, audio: np.ndarray) -> str:
        """Run the model on ``audio``; raises on failure."""
        segments, _info = self._model.transcribe(
            audio,
            language="en",
            beam_size=1,
            vad_filter=False,
            condition_on_previous_text=False,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()

    def _emit_partial(self) -> None:
        """Re-transcribe the in-progress utterance and emit it as a partial."""
        audio = self._buffer_audio()
        window = int(self.PARTIAL_WINDOW_SECONDS * TARGET_RATE)
        if audio.size > window:
            audio = audio[-window:]
        if audio.size / TARGET_RATE < self.MIN_UTTERANCE_SECONDS or self._model is None:
            return
        try:
            text = self._transcribe(audio)
        except Exception:  # noqa: BLE001 - partials are best-effort only
            return
        if text and text != self._last_partial_text:
            self._last_partial_text = text
            self.partial.emit(text)

    def _finalise(self) -> None:
        audio = self._buffer_audio()
        self._buffer = []
        self._preroll = []
        self._buffered_samples = 0
        self._speaking = False
        self._silence_frames = 0
        self._last_partial_samples = 0
        self._last_partial_text = ""

        duration = audio.size / TARGET_RATE
        if duration < self.MIN_UTTERANCE_SECONDS or self._model is None:
            return

        self.status.emit("transcribing…")
        try:
            text = self._transcribe(audio)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(f"transcription failed: {exc}")
            self.status.emit("listening")
            return

        self.status.emit("listening")
        if text:
            self.final.emit(text)


# --------------------------------------------------------------------------- #
# Deepgram direct WebSocket
# --------------------------------------------------------------------------- #


class DeepgramEngine(SttEngine):
    KEEPALIVE_SECONDS = 5.0
    MAX_RECONNECTS = 5
    SOCKET_TIMEOUT = 0.25

    def __init__(self, api: ApiClient, parent=None) -> None:
        super().__init__(parent)
        self._api = api
        self._reconnects = 0

    def run(self) -> None:  # noqa: D102
        try:
            from websockets.sync.client import connect  # noqa: F401
        except ImportError:
            self.error.emit("the 'websockets' package is required for Deepgram STT")
            return

        while not self._stop_flag and self._reconnects <= self.MAX_RECONNECTS:
            try:
                self._session()
                if self._stop_flag:
                    break
                raise ConnectionError("Deepgram connection closed")
            except Exception as exc:  # noqa: BLE001 - reconnect policy below
                if self._stop_flag:
                    break
                self._reconnects += 1
                if self._reconnects > self.MAX_RECONNECTS:
                    self.error.emit(f"Deepgram connection failed: {exc}")
                    break
                self.status.emit(f"reconnecting to Deepgram ({self._reconnects})…")
                time.sleep(min(1.5 * self._reconnects, 5.0))

        self.status.emit("stopped")

    # -- one connection ------------------------------------------------------ #

    def _session(self) -> None:  # pragma: no cover - network dependent
        from websockets.sync.client import connect

        self.status.emit("requesting STT token…")
        try:
            grant = self._api.get_stt_token()
        except ApiError as exc:
            raise RuntimeError(f"could not get an STT token: {exc}") from exc

        token = grant.get("token")
        url = grant.get("deepgram_url")
        if not token or not url:
            raise RuntimeError("server returned an incomplete STT grant")

        self.status.emit("connecting to Deepgram…")
        with connect(
            url,
            additional_headers={"Authorization": f"Token {token}"},
            open_timeout=5,
            close_timeout=2,
            max_size=2**21,
        ) as socket:
            self._reconnects = 0
            self.status.emit("listening (Deepgram)")

            last_send = time.monotonic()
            pending: list[bytes] = []
            while not self._stop_flag:
                pcm = self._next_chunk(timeout=self.SOCKET_TIMEOUT)
                if pcm is not None:
                    pending.append(pcm)

                while pending:
                    socket.send(pending.pop(0))
                    last_send = time.monotonic()

                try:
                    message = socket.recv(timeout=self.SOCKET_TIMEOUT)
                except TimeoutError:
                    message = None
                except Exception:
                    raise

                if message is not None:
                    self._handle_message(message)

                if time.monotonic() - last_send >= self.KEEPALIVE_SECONDS:
                    try:
                        socket.send(json.dumps({"type": "KeepAlive"}))
                    except Exception:
                        raise
                    last_send = time.monotonic()

            try:
                socket.send(json.dumps({"type": "CloseStream"}))
            except Exception:
                pass

    def _handle_message(self, raw: str | bytes) -> None:
        if isinstance(raw, bytes):
            return
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            return
        kind = message.get("type")
        if kind == "Results":
            alternatives = (message.get("channel") or {}).get("alternatives") or [{}]
            transcript = str(alternatives[0].get("transcript") or "").strip()
            if not transcript:
                return
            if message.get("is_final"):
                self.final.emit(transcript)
            else:
                self.partial.emit(transcript)
        elif kind == "Error":
            detail = message.get("description") or message.get("message") or "unknown error"
            self.error.emit(f"Deepgram error: {detail}")


def make_engine(settings: AppSettings, api: ApiClient, parent=None) -> SttEngine:
    """Factory driven by ``settings.stt_engine``."""
    if settings.stt_engine == "deepgram":
        return DeepgramEngine(api, parent)
    return LocalWhisperEngine(settings, parent)


def describe_engine(settings: AppSettings) -> str:
    if settings.stt_engine == "deepgram":
        return "Deepgram (cloud, direct WebSocket)"
    return f"faster-whisper '{settings.whisper_model}' (local)"


# Re-exported for callers that only need the type of the feed callback.
PcmFeed = Callable[[bytes], None]
