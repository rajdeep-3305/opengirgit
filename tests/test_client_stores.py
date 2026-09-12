"""Local stores: bounded history, atomic writes, credentials fallback."""

from __future__ import annotations

from opengirgit import stores


def test_conversation_store_bounds_and_persists(tmp_path, monkeypatch):
    path = tmp_path / "conversations.json"
    monkeypatch.setattr(stores, "CONVERSATIONS_PATH", path)

    store = stores.ConversationStore()
    store.start_session("first")
    store.add_item("q1", "a1")
    store.add_item("q2", "a2")

    reloaded = stores.ConversationStore()
    sessions = reloaded.sessions()
    assert len(sessions) == 1
    assert [item["question"] for item in sessions[0]["items"]] == ["q1", "a2".replace("a2", "q2")]
    assert sessions[0]["items"][0]["answer"] == "a1"


def test_conversation_store_caps_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(stores, "CONVERSATIONS_PATH", tmp_path / "c.json")
    store = stores.ConversationStore()
    for index in range(stores.MAX_SESSIONS + 5):
        store.start_session(f"session {index}")
    assert len(store.sessions()) == stores.MAX_SESSIONS
    # newest first
    assert store.sessions()[0]["title"] == f"session {stores.MAX_SESSIONS + 4}"


def test_context_store_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(stores, "CONTEXT_PATH", tmp_path / "context.json")
    context = stores.ContextStore()
    assert context.load()["company"] == ""
    context.save({"company": "Acme", "resume": {"name": "Ada"}})
    assert context.load()["company"] == "Acme"


def test_credentials_file_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(stores, "CREDENTIALS_PATH", tmp_path / "credentials.json")
    store = stores.CredentialsStore()
    store._keyring = None  # force the file fallback
    store.save("a@b.c", "token-123", "http://127.0.0.1:8000")
    loaded = store.load()
    assert loaded["email"] == "a@b.c"
    assert loaded["access_token"] == "token-123"
    store.clear()
    assert store.load() == {}
