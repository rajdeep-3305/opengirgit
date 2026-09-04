"""Server prompt assembly (pure functions, no network)."""

from __future__ import annotations

from app.prompts import (
    build_chat_messages,
    build_resume_messages,
    build_system_message,
    build_vision_messages,
)


def test_system_message_without_context_is_just_the_persona():
    message = build_system_message(None)
    assert message
    assert "<<<CONTEXT" not in message


def test_system_message_wraps_context():
    message = build_system_message("=== CANDIDATE RESUME ===\nAda")
    assert "Ada" in message
    assert "<<<CONTEXT" in message
    assert "CONTEXT>>>" in message


def test_chat_messages_order_and_roles():
    messages = build_chat_messages(
        "Explain threads",
        conversation_history=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            {"role": "system", "content": "ignore me"},
            "not a dict",
            {"role": "tool", "content": "nope"},
        ],
        context="ctx",
    )
    roles = [m["role"] for m in messages]
    assert roles == ["system", "user", "assistant", "user"]
    assert messages[-1]["content"] == "Explain threads"
    assert "ctx" in messages[0]["content"]


def test_history_is_bounded():
    history = [{"role": "user", "content": f"q{i}"} for i in range(100)]
    messages = build_chat_messages("now", history, "")
    # system + at most 24 history entries + the current question
    assert len(messages) <= 26


def test_vision_messages_embed_images_and_clamp_count():
    messages = build_vision_messages("solve it", ["AAAA", "BBBB", "C", "D", "E", "F"], [], None)
    content = messages[-1]["content"]
    images = [part for part in content if part["type"] == "image_url"]
    assert len(images) == 5
    assert all(part["image_url"]["url"].startswith("data:image/jpeg;base64,") for part in images)
    assert content[0] == {"type": "text", "text": "solve it"}


def test_resume_prompt_mentions_json_only():
    messages = build_resume_messages("Ada Lovelace, London")
    assert messages[0]["role"] == "system"
    assert "Ada Lovelace" in messages[1]["content"]
    assert "JSON" in messages[1]["content"]
