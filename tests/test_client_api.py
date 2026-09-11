"""Client HTTP layer: SSE parsing, error mapping, cancellation (offline)."""

from __future__ import annotations

import json

import pytest
from opengirgit import api as api_module
from opengirgit.api import ApiClient, ApiError, Cancelled


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
