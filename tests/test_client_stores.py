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


def test_session_and_history_export_markdown(tmp_path, monkeypatch):
    monkeypatch.setattr(stores, "CONVERSATIONS_PATH", tmp_path / "c.json")
    store = stores.ConversationStore()
    store.start_session("first session")
    store.add_item("what is a closure?", "A closure captures its environment.")
    store.add_item("screenshot q", "vision answer", kind="vision")
    store.start_session("second session")
    store.add_item("later q", "later a")

    sessions = store.sessions()  # newest first
    newest = store.session_markdown(sessions[0])
    assert newest.startswith("## second session")
    assert "**Q:** later q" in newest
    assert "later a" in newest

    older = store.session_markdown(sessions[1])
    assert "### Q1" in older and "### Q2 — screenshot" in older
    assert "what is a closure?" in older

    everything = store.export_markdown()
    assert everything.startswith("# OpenGirGit conversation export")
    # oldest first in a full export
    assert everything.index("## first session") < everything.index("## second session")
    assert "2 session(s)" in everything

    single = store.export_markdown(str(sessions[0]["id"]))
    assert "## second session" in single
    assert "## first session" not in single


def test_export_without_sessions_is_still_valid_markdown(tmp_path, monkeypatch):
    monkeypatch.setattr(stores, "CONVERSATIONS_PATH", tmp_path / "empty.json")
    store = stores.ConversationStore()
    export = store.export_markdown(None)
    assert export.startswith("# OpenGirGit conversation export")
    assert "No conversations stored yet." in export


def test_store_files_are_owner_only(tmp_path, monkeypatch):
    """credentials/context/history must not be world-readable on POSIX."""
    import os
    import stat

    if os.name != "posix":
        return  # chmod only flips the read-only bit on Windows
    target = tmp_path / "credentials.json"
    stores._atomic_write(target, {"access_token": "secret"})  # noqa: SLF001
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
