"""Prompt assembly.

The client sends a plain ``context`` string (resume + job description); the
server owns the persona and the final system prompt, exactly like the original
architecture (the system message is built server-side).
"""

from __future__ import annotations

from typing import Any

from .config import DEFAULT_SYSTEM_PROMPT

_HISTORY_LIMIT = 24


def build_system_message(
    context: str | None,
    *,
    base_prompt: str | None = None,
    kind: str = "chat",
) -> str:
    """Compose the system message for one request."""
    parts: list[str] = [(base_prompt or DEFAULT_SYSTEM_PROMPT).strip()]

    context = (context or "").strip()
    if context:
        parts.append(
            "CONTEXT — the candidate's background, resume and the role they are "
            "interviewing for. Use it to ground every answer:\n"
            "<<<CONTEXT\n" + context + "\nCONTEXT>>>"
        )

    if kind == "vision":
        parts.append(
            "A screenshot from the candidate's screen accompanies the request. "
            "Read the visible problem/task text first, then answer it fully."
        )

    return "\n\n".join(parts)


def _normalise_history(history: Any) -> list[dict[str, str]]:
    """Accept [{'role': .., 'content': ..}] lists, drop anything malformed."""
    if not isinstance(history, list):
        return []
    out: list[dict[str, str]] = []
    for item in history[-_HISTORY_LIMIT:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            out.append({"role": role, "content": content})
    return out


def build_chat_messages(
    message: str,
    conversation_history: Any = None,
    context: str | None = None,
    *,
    base_prompt: str | None = None,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": build_system_message(context, base_prompt=base_prompt)}
    ]
    messages.extend(_normalise_history(conversation_history))
    messages.append({"role": "user", "content": message.strip()})
    return messages


def build_vision_messages(
    prompt: str,
    images_b64: list[str],
    conversation_history: Any = None,
    context: str | None = None,
    *,
    base_prompt: str | None = None,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": build_system_message(context, base_prompt=base_prompt, kind="vision"),
        }
    ]
    messages.extend(_normalise_history(conversation_history))

    content: list[dict[str, Any]] = [{"type": "text", "text": prompt.strip()}]
    for image in images_b64[:5]:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{image}", "detail": "high"},
            }
        )
    messages.append({"role": "user", "content": content})
    return messages


RESUME_PARSE_PROMPT = """\
Extract this resume into STRICT JSON with exactly these keys:

{
  "name": string|null,
  "email": string|null,
  "phone": string|null,
  "location": string|null,
  "summary": string|null,
  "experience": [{"title": string, "company": string, "duration": string, "description": string}],
  "education": [{"degree": string, "institution": string, "year": string}],
  "skills": [string],
  "certifications": [string],
  "projects": [{"name": string, "description": string, "technologies": [string]}],
  "languages": [string]
}

Rules: never invent facts; use null or empty arrays when the resume does not say.
Return only the JSON object, no markdown fences, no commentary.

RESUME TEXT:
"""


def build_resume_messages(resume_text: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": "You are a precise resume parser. Output JSON only.",
        },
        {"role": "user", "content": RESUME_PARSE_PROMPT + resume_text.strip()},
    ]
