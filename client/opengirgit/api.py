"""HTTP client for the OpenGirGit server (sync; used from worker threads)."""

from __future__ import annotations

import json
import socket
import ssl
import time
from collections.abc import Callable
from typing import Any

import httpx

try:  # pulled in by httpx, but imported directly for the trust-store fallback
    import certifi
except ImportError:  # pragma: no cover - certifi is an httpx dependency
    certifi = None  # type: ignore[assignment]

DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0)
STREAM_TIMEOUT = httpx.Timeout(connect=10.0, read=180.0, write=30.0, pool=10.0)

#: Delays (seconds) between retries of transient transport failures.
DEFAULT_RETRY_BACKOFF = (0.6, 1.5, 3.0)


class ApiError(Exception):
    """Any non-2xx response or transport failure, with a human message."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class Cancelled(Exception):
    """Raised inside a stream when the caller cancels."""


class _WebSocketUnavailable(Exception):
    """The server (or this install) cannot stream over WebSocket — use SSE."""


def _normalise_base_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if url and not url.startswith(("http://", "https://")):
        url = "http://" + url
    return url


def _websocket_url(base_url: str) -> str:
    """http(s)://host → ws(s)://host (the API path is appended by the caller)."""
    if base_url.startswith("https://"):
        return "wss://" + base_url[len("https://") :]
    if base_url.startswith("http://"):
        return "ws://" + base_url[len("http://") :]
    return "ws://" + base_url


_TRUST_CONTEXT: ssl.SSLContext | None = None


def _error_chain(exc: BaseException) -> str:
    """Every message in an exception's cause/context chain, newest first."""
    parts: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        parts.append(str(current))
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return "\n".join(parts)


def _ssl_cause(exc: BaseException) -> ssl.SSLError | None:
    """The ``ssl`` error buried in a transport exception, if there is one."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, ssl.SSLError):
            return current
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return None


def _is_certificate_error(exc: BaseException) -> bool:
    if isinstance(_ssl_cause(exc), ssl.SSLCertVerificationError):
        return True
    return "certificate verify failed" in _error_chain(exc).lower()


def trust_store_context() -> ssl.SSLContext:
    """Trust roots from the OS store plus certifi (built once, then cached).

    ``httpx`` verifies against the certifi bundle alone, so a proxy or
    antivirus that injects its own root *the OS trusts* still fails; this
    context is the union used for one rescue retry.
    """
    global _TRUST_CONTEXT
    if _TRUST_CONTEXT is None:
        context = ssl.create_default_context()  # the OS trust store
        if certifi is not None:
            try:
                context.load_verify_locations(certifi.where())
            except Exception:  # pragma: no cover - defensive
                pass
        _TRUST_CONTEXT = context
    return _TRUST_CONTEXT


def _connect_error_message(exc: BaseException, base_url: str) -> str:
    """A classified, human-readable story for a connection failure."""
    text = _error_chain(exc).lower()
    if _is_certificate_error(exc):
        return (
            f"TLS certificate for {base_url} is not trusted — even the OS trust "
            "store does not know it; a proxy or antivirus may be intercepting HTTPS"
        )
    if _ssl_cause(exc) is not None:
        return f"TLS handshake with {base_url} failed — is the address right (http vs https)?"
    if isinstance(exc.__cause__, socket.gaierror) or "getaddrinfo" in text:
        return f"cannot resolve {base_url} — check the address and DNS"
    if isinstance(exc.__cause__, ConnectionRefusedError) or "connection refused" in text:
        return f"connection refused by {base_url} — is the server running?"
    if "timed out" in text:
        return f"{base_url} did not answer in time"
    return f"cannot reach {base_url} — is the server running?"


class ApiClient:
    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        *,
        timeout: httpx.Timeout | float | None = None,
        transport: str = "auto",
    ) -> None:
        self.base_url = _normalise_base_url(base_url)
        self.token = token
        self.timeout = timeout or DEFAULT_TIMEOUT
        self.retry_backoff = DEFAULT_RETRY_BACKOFF
        #: "auto" (WebSocket, SSE fallback) | "sse" | "websocket"
        self.transport = transport or "auto"

    # -- plumbing --------------------------------------------------------- #

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        timeout: httpx.Timeout | float | None = None,
        retries: int = 0,
    ) -> dict[str, Any]:
        """One JSON round-trip; transient transport failures retried ``retries`` times.

        Only connection/timeout errors are retried — HTTP responses (including
        errors) are returned or raised immediately, so a request that reached
        the server is never replayed.
        """
        url = f"{self.base_url}{path}"
        attempt = 0
        verify: ssl.SSLContext | None = None
        while True:
            request_kwargs: dict[str, Any] = {
                "json": payload,
                "headers": self._headers(),
                "timeout": timeout or self.timeout,
            }
            if verify is not None:
                request_kwargs["verify"] = verify
            try:
                response = httpx.request(method, url, **request_kwargs)
                break
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                if _is_certificate_error(exc):
                    if verify is None:
                        # certifi and the OS trust store disagree (proxy/AV
                        # roots): retry once against their union. A cert error
                        # is deterministic, so backoff retries are pointless.
                        verify = trust_store_context()
                        continue
                    raise ApiError(_connect_error_message(exc, self.base_url)) from exc
                if attempt < retries:
                    delay = self.retry_backoff[min(attempt, len(self.retry_backoff) - 1)]
                    time.sleep(delay)
                    attempt += 1
                    continue
                if isinstance(exc, httpx.TimeoutException):
                    raise ApiError("the server took too long to answer") from exc
                raise ApiError(_connect_error_message(exc, self.base_url)) from exc
            except httpx.HTTPError as exc:
                raise ApiError(f"network error: {exc}") from exc

        if response.status_code >= 400:
            raise ApiError(_error_message(response), status_code=response.status_code)
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise ApiError("the server returned malformed JSON") from exc

    # -- auth ------------------------------------------------------------- #

    def send_otp(self, email: str) -> dict[str, Any]:
        # Mail delivery occasionally fails to accept the connection; retry
        # transient network blips like the original client did. Only transport
        # errors are retried — HTTP responses (including rate limits) are not.
        return self._request(
            "POST",
            "/api/auth/otp/send",
            payload={"email": email},
            retries=len(DEFAULT_RETRY_BACKOFF),
        )

    def verify_otp(self, email: str, code: str) -> dict[str, Any]:
        return self._request(
            "POST", "/api/auth/otp/verify", payload={"email": email, "otp": code}
        )

    def refresh(self) -> dict[str, Any]:
        return self._request("POST", "/api/auth/refresh")

    def me(self) -> dict[str, Any]:
        return self._request("GET", "/api/auth/me")

    def save_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/auth/profile", payload={"profile": profile})

    def get_version(self) -> dict[str, Any]:
        return self._request("GET", "/api/version")

    def prewarm(self) -> None:
        """Best-effort warm-up of DNS/TLS and (optionally) the chat WebSocket.

        Runs on a background thread at startup so the first question does not
        pay connection setup. Never raises and never sends a completion — the
        health probe and a WebSocket handshake are all that happen here.
        """
        try:
            httpx.get(
                f"{self.base_url}/api/health", timeout=3.0, headers=self._headers()
            )
        except Exception:  # noqa: BLE001 - warm-up is best-effort by definition
            pass
        if not self.token or self.transport not in ("auto", "websocket"):
            return
        try:
            from websockets.sync.client import connect
        except ImportError:
            return
        try:
            with connect(
                f"{_websocket_url(self.base_url)}/api/llm/ws",
                additional_headers=self._headers(),
                open_timeout=4,
                close_timeout=1,
            ):
                pass  # handshake only: auth and framing are now warm
        except Exception:  # noqa: BLE001
            pass

    def parse_resume(self, resume_text: str) -> dict[str, Any]:
        data = self._request(
            "POST",
            "/api/resume/parse",
            payload={"resume_text": resume_text},
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0),
        )
        return data.get("resume") or {}

    def get_stt_token(self) -> dict[str, Any]:
        return self._request("POST", "/api/stt/token", timeout=DEFAULT_TIMEOUT)

    def submit_feedback(
        self,
        message: str,
        *,
        email: str | None = None,
        app_version: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/feedback/submit",
            payload={"message": message, "email": email, "app_version": app_version},
            retries=1,
        )

    # -- streaming completions -------------------------------------------- #

    def chat_stream(
        self,
        message: str,
        *,
        conversation_history: list[dict[str, str]] | None = None,
        context: str = "",
        on_chunk: Callable[[str], None] | None = None,
        cancel: Callable[[], bool] | None = None,
        model: str | None = None,
        transport: str | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "message": message,
            "conversation_history": conversation_history or [],
            "context": context,
        }
        if model:
            payload["model"] = model
        return self._stream("/api/llm/chat/stream", payload, on_chunk, cancel, transport=transport)

    def vision_stream(
        self,
        prompt: str,
        images_b64: list[str],
        *,
        conversation_history: list[dict[str, str]] | None = None,
        context: str = "",
        on_chunk: Callable[[str], None] | None = None,
        cancel: Callable[[], bool] | None = None,
        model: str | None = None,
        transport: str | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "prompt": prompt,
            "images": images_b64,
            "conversation_history": conversation_history or [],
            "context": context,
        }
        if model:
            payload["model"] = model
        return self._stream(
            "/api/llm/vision/stream",
            payload,
            on_chunk,
            cancel,
            transport=transport,
            kind="vision",
        )

    def _stream(
        self,
        path: str,
        payload: dict[str, Any],
        on_chunk: Callable[[str], None] | None,
        cancel: Callable[[], bool] | None,
        *,
        transport: str | None = None,
        kind: str = "chat",
    ) -> str:
        choice = (transport or self.transport or "sse").strip().lower()
        if choice == "websocket":
            try:
                return self._stream_ws(kind, payload, on_chunk, cancel)
            except _WebSocketUnavailable as exc:
                raise ApiError(f"websocket transport unavailable: {exc}") from exc
        if choice == "auto":
            try:
                return self._stream_ws(kind, payload, on_chunk, cancel)
            except _WebSocketUnavailable:
                pass  # older server or a proxy that blocks WS: plain SSE works too
        return self._stream_sse(path, payload, on_chunk, cancel)

    # -- SSE ---------------------------------------------------------------- #

    def _stream_sse(
        self,
        path: str,
        payload: dict[str, Any],
        on_chunk: Callable[[str], None] | None,
        cancel: Callable[[], bool] | None,
    ) -> str:
        url = f"{self.base_url}{path}"
        chunks: list[str] = []
        headers = {**self._headers(), "Accept": "text/event-stream"}
        verify: ssl.SSLContext | None = None
        while True:
            try:
                client_kwargs: dict[str, Any] = {"timeout": STREAM_TIMEOUT}
                if verify is not None:
                    client_kwargs["verify"] = verify
                with httpx.Client(**client_kwargs) as client:
                    with client.stream("POST", url, json=payload, headers=headers) as response:
                        if response.status_code >= 400:
                            response.read()
                            raise ApiError(_error_message(response), status_code=response.status_code)
                        for line in response.iter_lines():
                            if cancel is not None and cancel():
                                raise Cancelled()
                            if not line or not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if not data:
                                continue
                            try:
                                event = json.loads(data)
                            except json.JSONDecodeError:
                                continue
                            if event.get("error"):
                                raise ApiError(str(event["error"]))
                            text = event.get("chunk")
                            if isinstance(text, str) and text:
                                chunks.append(text)
                                if on_chunk is not None:
                                    on_chunk(text)
                            if event.get("done"):
                                return "".join(chunks)
                break  # the stream ended without a done frame
            except Cancelled:
                raise
            except ApiError:
                raise
            except httpx.ConnectError as exc:
                if verify is None and not chunks and _is_certificate_error(exc):
                    # certifi and the OS trust store disagree (proxy/AV roots):
                    # retry once against their union before giving up.
                    verify = trust_store_context()
                    continue
                raise ApiError(_connect_error_message(exc, self.base_url)) from exc
            except httpx.HTTPError as exc:
                raise ApiError(f"streaming failed: {exc}") from exc
        return "".join(chunks)

    # -- WebSocket ---------------------------------------------------------- #

    def _stream_ws(
        self,
        kind: str,
        payload: dict[str, Any],
        on_chunk: Callable[[str], None] | None,
        cancel: Callable[[], bool] | None,
    ) -> str:
        """Stream one completion over ``/api/llm/ws``.

        Raises ``_WebSocketUnavailable`` when the socket cannot be opened (so
        ``auto`` can fall back to SSE); anything after the request was sent is
        reported as ``ApiError`` — the question is never replayed twice.
        """
        try:
            from websockets.sync.client import connect
        except ImportError as exc:
            raise _WebSocketUnavailable("the 'websockets' package is not installed") from exc

        url = f"{_websocket_url(self.base_url)}/api/llm/ws"
        dial_kwargs: dict[str, Any] = {
            "additional_headers": self._headers(),
            "open_timeout": 10,
            "close_timeout": 2,
            "max_size": 2**22,
        }

        def dial() -> Any:
            return connect(url, **dial_kwargs)

        try:
            connection = dial()
        except Exception as exc:  # noqa: BLE001 - connect-level failure: SSE fallback
            if not _is_certificate_error(exc):
                raise _WebSocketUnavailable(str(exc)) from exc
            # certifi and the OS trust store disagree (proxy/AV roots): one
            # retry against their union before falling back to SSE.
            dial_kwargs["ssl"] = trust_store_context()
            try:
                connection = dial()
            except Exception as retry_exc:  # noqa: BLE001
                raise _WebSocketUnavailable(
                    _connect_error_message(retry_exc, self.base_url)
                ) from retry_exc

        chunks: list[str] = []
        with connection:
            try:
                connection.send(json.dumps({"kind": kind, **payload}, ensure_ascii=False))
            except Exception as exc:  # noqa: BLE001
                raise ApiError(f"websocket send failed: {exc}") from exc
            while True:
                if cancel is not None and cancel():
                    raise Cancelled()
                try:
                    raw = connection.recv(timeout=0.25)
                except TimeoutError:
                    continue
                except Cancelled:
                    raise
                except Exception as exc:  # noqa: BLE001 - mid-stream failure
                    raise ApiError(f"streaming failed: {exc}") from exc
                if isinstance(raw, (bytes, bytearray)):
                    raw = bytes(raw).decode("utf-8", "replace")
                try:
                    event = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get("error"):
                    raise ApiError(str(event["error"]))
                text = event.get("chunk")
                if isinstance(text, str) and text:
                    chunks.append(text)
                    if on_chunk is not None:
                        on_chunk(text)
                if event.get("done"):
                    return "".join(chunks)

    # -- helpers ----------------------------------------------------------- #

    @staticmethod
    def health(base_url: str) -> dict[str, Any]:
        url = f"{_normalise_base_url(base_url)}/api/health"
        try:
            response = httpx.get(url, timeout=5.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            raise ApiError(f"health check failed: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ApiError("server did not return JSON") from exc


def _error_message(response: httpx.Response) -> str:
    """Extract FastAPI's ``detail`` when possible."""
    try:
        body = response.json()
        if isinstance(body, dict) and body.get("detail"):
            return str(body["detail"])
    except Exception:
        pass
    text = response.text.strip()
    return text[:300] if text else f"HTTP {response.status_code}"
