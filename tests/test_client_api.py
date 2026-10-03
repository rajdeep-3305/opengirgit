"""Client HTTP layer: SSE parsing, error mapping, cancellation (offline)."""

from __future__ import annotations

import json

import pytest
from opengirgit import api as api_module
from opengirgit.api import ApiClient, ApiError, Cancelled

#: Captured before any fixture patches it, so WebSocket tests can opt back in.
_REAL_STREAM_WS = ApiClient._stream_ws


class _FakeResponse:
    def __init__(self, lines: list[str], status: int = 200) -> None:
        self._lines = lines
        self.status_code = status
        self.reason_phrase = "OK"
        self.text = "\n".join(lines)

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def iter_lines(self):
        yield from self._lines

    def read(self) -> bytes:
        return self.text.encode()

    def json(self):
        return json.loads(self.text)


class _FakeClient:
    """Minimal stand-in for httpx.Client used by :meth:`ApiClient._stream`."""

    lines: list[str] = []
    status = 200

    def __init__(self, *args, **kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def stream(self, method, url, json=None, headers=None, **kwargs):
        return _FakeResponse(type(self).lines, type(self).status)


@pytest.fixture(autouse=True)
def _patch_httpx(monkeypatch):
    monkeypatch.setattr(api_module.httpx, "Client", _FakeClient)


@pytest.fixture(autouse=True)
def _offline_websockets(monkeypatch):
    """Never dial a real socket: the SSE tests fall back deterministically."""

    def unavailable(self, kind, payload, on_chunk, cancel):
        raise api_module._WebSocketUnavailable("offline test")

    monkeypatch.setattr(ApiClient, "_stream_ws", unavailable)


def _sse(*events: dict) -> list[str]:
    return [f"data: {json.dumps(event)}" for event in events]


def test_stream_assembles_chunks_and_stops_on_done():
    _FakeClient.lines = [": open", ""] + _sse(
        {"chunk": "Hello "}, {"chunk": "world"}, {"done": True}, {"chunk": "ignored"}
    )
    seen: list[str] = []
    answer = ApiClient("http://x").chat_stream("hi", on_chunk=seen.append)
    assert answer == "Hello world"
    assert seen == ["Hello ", "world"]


def test_stream_without_done_returns_what_it_got():
    _FakeClient.lines = _sse({"chunk": "partial"})
    assert ApiClient("http://x").chat_stream("hi") == "partial"


def test_stream_error_event_raises_api_error():
    _FakeClient.lines = _sse({"chunk": "start"}, {"error": "upstream 429"})
    with pytest.raises(ApiError, match="upstream 429"):
        ApiClient("http://x").chat_stream("hi")


def test_stream_cancel_flag_raises_cancelled():
    _FakeClient.lines = _sse({"chunk": "a"}, {"chunk": "b"}, {"done": True})
    state = {"cancelled": False}

    def on_chunk(_text: str) -> None:
        state["cancelled"] = True

    with pytest.raises(Cancelled):
        ApiClient("http://x").chat_stream(
            "hi", on_chunk=on_chunk, cancel=lambda: state["cancelled"]
        )


def test_stream_malformed_lines_are_ignored():
    _FakeClient.lines = ["data: {not json}", "junk", ": comment", ""] + _sse(
        {"chunk": "ok"}, {"done": True}
    )
    assert ApiClient("http://x").chat_stream("hi") == "ok"


def test_base_url_normalisation():
    assert ApiClient("127.0.0.1:8000").base_url == "http://127.0.0.1:8000"
    assert ApiClient("http://a.b/").base_url == "http://a.b"
    assert ApiClient(" https://a.b/v1 ").base_url == "https://a.b/v1"


def test_stt_grant_is_forwarded():
    client = ApiClient("http://x")

    def fake_request(method, path, **kwargs):
        assert path == "/api/stt/token"
        return {"token": "t", "deepgram_url": "wss://d", "expires_in": 600}

    client._request = fake_request  # type: ignore[method-assign]
    grant = client.get_stt_token()
    assert grant["token"] == "t"


class _JsonResponse:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


def _no_sleep_client() -> ApiClient:
    client = ApiClient("http://x")
    client.retry_backoff = (0.0, 0.0, 0.0)
    return client


def test_send_otp_retries_transient_connect_errors(monkeypatch):
    calls = {"n": 0}

    def fake_request(method, url, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise api_module.httpx.ConnectError("connection refused")
        return _JsonResponse({"sent": True})

    monkeypatch.setattr(api_module.httpx, "request", fake_request)
    assert _no_sleep_client().send_otp("a@b.c") == {"sent": True}
    assert calls["n"] == 3


def test_send_otp_gives_up_after_backoff(monkeypatch):
    calls = {"n": 0}

    def fake_request(*args, **kwargs):
        calls["n"] += 1
        raise api_module.httpx.ConnectError("connection refused")

    monkeypatch.setattr(api_module.httpx, "request", fake_request)
    with pytest.raises(ApiError, match="cannot reach"):
        _no_sleep_client().send_otp("a@b.c")
    assert calls["n"] == 4  # first try + 3 retries


def test_verify_otp_is_not_retried(monkeypatch):
    calls = {"n": 0}

    def fake_request(*args, **kwargs):
        calls["n"] += 1
        raise api_module.httpx.ConnectError("connection refused")

    monkeypatch.setattr(api_module.httpx, "request", fake_request)
    with pytest.raises(ApiError):
        ApiClient("http://x").verify_otp("a@b.c", "123456")
    assert calls["n"] == 1  # a retried verify could burn OTP attempts


def test_http_error_response_is_never_retried(monkeypatch):
    calls = {"n": 0}

    def fake_request(method, url, **kwargs):
        calls["n"] += 1
        return _JsonResponse({"detail": "rate limited"}, status=429)

    monkeypatch.setattr(api_module.httpx, "request", fake_request)
    with pytest.raises(ApiError, match="rate limited"):
        _no_sleep_client().send_otp("a@b.c")
    assert calls["n"] == 1


def test_feedback_payload(monkeypatch):
    captured: dict = {}

    def fake_request(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return _JsonResponse({"success": True})

    monkeypatch.setattr(api_module.httpx, "request", fake_request)
    assert ApiClient("http://x").submit_feedback("hi", email="a@b.c", app_version="9.9")
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/api/feedback/submit")
    assert captured["json"] == {"message": "hi", "email": "a@b.c", "app_version": "9.9"}


# --------------------------------------------------------------------------- #
# WebSocket transport
# --------------------------------------------------------------------------- #


class _FakeWsConnection:
    """Minimal websockets.sync.client connection stand-in."""

    def __init__(self, frames: list) -> None:
        self._frames = list(frames)
        self.sent: list[str] = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        self.closed = True
        return False

    def send(self, data) -> None:
        self.sent.append(data)

    def recv(self, timeout=None):
        if not self._frames:
            raise TimeoutError()
        frame = self._frames.pop(0)
        if isinstance(frame, Exception):
            raise frame
        return frame


def _require_websockets():
    """The optional transport needs the ``websockets`` package (Deepgram dep)."""
    return pytest.importorskip("websockets.sync.client")


def _install_ws(monkeypatch, connection, *, fail_connect: Exception | None = None) -> None:
    """Restore the real ``_stream_ws`` and point ``websockets`` at a fake socket."""
    _require_websockets()
    import websockets.sync.client as ws_client

    def connect(url, **kwargs):
        if fail_connect is not None:
            raise fail_connect
        connection.url = url
        connection.headers = kwargs.get("additional_headers")
        return connection

    monkeypatch.setattr(ws_client, "connect", connect)
    monkeypatch.setattr(ApiClient, "_stream_ws", _REAL_STREAM_WS)


def test_websocket_url_mapping():
    assert api_module._websocket_url("http://127.0.0.1:8000") == "ws://127.0.0.1:8000"
    assert api_module._websocket_url("https://a.b") == "wss://a.b"
    assert api_module._websocket_url("a.b:1234") == "ws://a.b:1234"


def test_websocket_stream_assembles_chunks(monkeypatch):
    connection = _FakeWsConnection(
        [json.dumps({"chunk": "Hello "}), json.dumps({"chunk": "world"}), json.dumps({"done": True})]
    )
    _install_ws(monkeypatch, connection)
    seen: list[str] = []
    client = ApiClient("http://x", token="tok", transport="websocket")
    answer = client.chat_stream("hi", on_chunk=seen.append)
    assert answer == "Hello world"
    assert seen == ["Hello ", "world"]
    request = json.loads(connection.sent[0])
    assert request["kind"] == "chat" and request["message"] == "hi"
    assert connection.url.endswith("/api/llm/ws")
    assert connection.headers["Authorization"] == "Bearer tok"
    assert connection.closed is True


def test_websocket_vision_sets_kind(monkeypatch):
    connection = _FakeWsConnection([json.dumps({"chunk": "ok"}), json.dumps({"done": True})])
    _install_ws(monkeypatch, connection)
    answer = ApiClient("http://x", transport="websocket").vision_stream("read it", ["aW1n"])
    assert answer == "ok"
    request = json.loads(connection.sent[0])
    assert request["kind"] == "vision"
    assert request["images"] == ["aW1n"]


def test_websocket_error_frame_raises(monkeypatch):
    connection = _FakeWsConnection([json.dumps({"error": "upstream 429"})])
    _install_ws(monkeypatch, connection)
    with pytest.raises(ApiError, match="upstream 429"):
        ApiClient("http://x", transport="websocket").chat_stream("hi")


def test_websocket_cancel_raises(monkeypatch):
    connection = _FakeWsConnection([json.dumps({"chunk": "a"}), json.dumps({"done": True})])
    _install_ws(monkeypatch, connection)
    state = {"stop": False}

    def on_chunk(_text: str) -> None:
        state["stop"] = True

    with pytest.raises(Cancelled):
        ApiClient("http://x", transport="websocket").chat_stream(
            "hi", on_chunk=on_chunk, cancel=lambda: state["stop"]
        )


def test_websocket_unavailable_falls_back_to_sse(monkeypatch):
    _install_ws(monkeypatch, _FakeWsConnection([]), fail_connect=OSError("connection refused"))
    _FakeClient.lines = _sse({"chunk": "via sse"}, {"done": True})
    # 'auto' falls back, even though WS is broken
    assert ApiClient("http://x", transport="auto").chat_stream("hi") == "via sse"


def test_websocket_forced_transport_surfaces_the_failure(monkeypatch):
    _install_ws(monkeypatch, _FakeWsConnection([]), fail_connect=OSError("connection refused"))
    _FakeClient.lines = _sse({"chunk": "via sse"}, {"done": True})
    with pytest.raises(ApiError, match="websocket transport unavailable"):
        ApiClient("http://x", transport="websocket").chat_stream("hi")


def test_sse_transport_never_touches_the_socket(monkeypatch):
    _require_websockets()
    import websockets.sync.client as ws_client

    def explode(*args, **kwargs):
        raise AssertionError("the sse transport must not open a websocket")

    monkeypatch.setattr(ws_client, "connect", explode)
    _FakeClient.lines = _sse({"chunk": "plain"}, {"done": True})
    assert ApiClient("http://x", transport="sse").chat_stream("hi") == "plain"
