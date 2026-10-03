"""The optional WebSocket transport end to end (server side, in-process).

Uses ``fastapi.testclient`` so no network port is opened; the LLM upstream is
stubbed, everything else is the real application.
"""

from __future__ import annotations

import os
import tempfile

import pytest

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="opengirgit-ws-test-")
os.environ.setdefault("JWT_SECRET", "unit-test-secret-that-is-long-enough-for-hs256")
os.environ.setdefault("ALLOW_DEV_OTP_ECHO", "true")

from app import llm as llm_module  # noqa: E402
from app.config import get_settings  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

get_settings.cache_clear()

from app import main as main_module  # noqa: E402
from app.security import create_token  # noqa: E402

SETTINGS = get_settings()
TOKEN = create_token("candidate@example.com", SETTINGS.jwt_secret, expires_minutes=5)


@pytest.fixture()
def client():
    with TestClient(main_module.app) as test_client:
        yield test_client


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def _stub_stream(chunks: list[str], calls: list[dict] | None = None):
    async def stream(messages, model=None):  # noqa: ANN001, ANN202 - mirrors llm.stream_chat
        if calls is not None:
            calls.append({"messages": messages, "model": model})
        for chunk in chunks:
            yield chunk

    return stream


def test_websocket_requires_a_token(client):
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect("/api/llm/ws") as websocket:
            websocket.receive_text()
    assert excinfo.value.code == 4401


def test_websocket_rejects_a_garbage_token(client):
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect(
            "/api/llm/ws", headers={"Authorization": "Bearer junk"}
        ) as websocket:
            websocket.receive_text()
    assert excinfo.value.code == 4401


def test_websocket_streams_a_chat_answer(client, monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(
        main_module.llm, "stream_chat", _stub_stream(["Hello ", "world"], calls)
    )
    with client.websocket_connect("/api/llm/ws", headers=_auth_headers()) as websocket:
        websocket.send_json({"kind": "chat", "message": "hi", "context": "ctx"})
        assert websocket.receive_json() == {"chunk": "Hello "}
        assert websocket.receive_json() == {"chunk": "world"}
        assert websocket.receive_json() == {"done": True}
        # the connection stays open for the next question
        websocket.send_json({"kind": "chat", "message": "again"})
        assert websocket.receive_json() == {"chunk": "Hello "}
        assert websocket.receive_json() == {"chunk": "world"}
        assert websocket.receive_json() == {"done": True}
    assert [call["messages"][-1]["content"] for call in calls] == ["hi", "again"]
    assert "ctx" in calls[0]["messages"][0]["content"]


def test_websocket_streams_a_vision_answer(client, monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(main_module.llm, "stream_chat", _stub_stream(["seen"], calls))
    with client.websocket_connect("/api/llm/ws", headers=_auth_headers()) as websocket:
        websocket.send_json(
            {"kind": "vision", "prompt": "read it", "images": ["aW1n"], "context": ""}
        )
        assert websocket.receive_json() == {"chunk": "seen"}
        assert websocket.receive_json() == {"done": True}
    content = calls[0]["messages"][-1]["content"]
    assert isinstance(content, list)  # vision content is multimodal
    assert content[0]["text"] == "read it"
    assert content[1]["image_url"]["url"].endswith("aW1n")


def test_websocket_reports_llm_errors_as_frames(client, monkeypatch):
    async def broken(messages, model=None):  # noqa: ANN001, ANN202
        raise llm_module.LLMError("upstream 429")
        yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr(main_module.llm, "stream_chat", broken)
    with client.websocket_connect("/api/llm/ws", headers=_auth_headers()) as websocket:
        websocket.send_json({"kind": "chat", "message": "hi"})
        assert websocket.receive_json() == {"error": "upstream 429"}


def test_websocket_validates_payloads(client):
    with client.websocket_connect("/api/llm/ws", headers=_auth_headers()) as websocket:
        websocket.send_text("{not json")
        assert websocket.receive_json() == {"error": "invalid JSON"}
        websocket.send_json({"kind": "chat"})  # message is required
        assert "invalid request" in websocket.receive_json()["error"]
        websocket.send_json({"kind": "vision", "prompt": "x", "images": []})
        assert websocket.receive_json() == {"error": "no image supplied"}
        websocket.send_json({"kind": "vision", "prompt": "x", "images": ["too", "many", "images", "for", "cap", "six"]})
        assert "invalid request" in websocket.receive_json()["error"]
