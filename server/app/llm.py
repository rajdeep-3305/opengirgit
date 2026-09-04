"""Minimal OpenAI-compatible LLM client (chat completions, streaming + JSON).

Works with OpenAI, OpenRouter, Groq, Together, Ollama, LM Studio, vLLM, …
— anything that exposes ``POST {base_url}/chat/completions``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .config import get_settings


class LLMError(Exception):
    """Upstream LLM failure, safe to surface to the client."""

    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


def _client(timeout: float | None = None) -> httpx.AsyncClient:
    settings = get_settings()
    return httpx.AsyncClient(
        base_url=settings.llm_base_url.rstrip("/"),
        headers={
            "Authorization": f"Bearer {settings.llm_api_key or 'not-needed'}",
            "Content-Type": "application/json",
        },
        timeout=httpx.Timeout(
            connect=10.0,
            read=timeout or settings.llm_timeout_seconds,
            write=30.0,
            pool=10.0,
        ),
    )


def _payload(
    messages: list[dict[str, Any]],
    *,
    model: str | None,
    temperature: float | None,
    max_tokens: int | None,
    stream: bool,
    response_format: dict | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    payload: dict[str, Any] = {
        "model": model or settings.llm_chat_model,
        "messages": messages,
        "temperature": settings.llm_temperature if temperature is None else temperature,
        "max_tokens": settings.llm_max_tokens if max_tokens is None else max_tokens,
        "stream": stream,
    }
    if response_format:
        payload["response_format"] = response_format
    return payload


async def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    try:
        body = (await response.aread()).decode("utf-8", "replace")
    except Exception:  # pragma: no cover - already consumed / network gone
        body = ""
    detail = body.strip()[:500] or response.reason_phrase
    raise LLMError(f"upstream {response.status_code}: {detail}")


def _delta_text(chunk: dict[str, Any]) -> str:
    """Extract text from a streaming chunk across provider dialects."""
    choices = chunk.get("choices") or []
    if not choices:
        return ""
    choice = choices[0] or {}
    delta = choice.get("delta") or {}
    for key in ("content", "text", "reasoning_content"):
        value = delta.get(key)
        if isinstance(value, str) and value:
            return value
    message = choice.get("message") or {}
    value = message.get("content")
    return value if isinstance(value, str) else ""


async def stream_chat(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> AsyncIterator[str]:
    """Yield text deltas from a streaming chat completion."""
    payload = _payload(
        messages, model=model, temperature=temperature, max_tokens=max_tokens, stream=True
    )
    try:
        async with _client() as client:
            async with client.stream("POST", "/chat/completions", json=payload) as response:
                await _raise_for_status(response)
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    text = _delta_text(chunk)
                    if text:
                        yield text
    except LLMError:
        raise
    except httpx.HTTPError as exc:
        raise LLMError(f"llm request failed: {exc}") from exc
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise LLMError(f"llm returned malformed data: {exc}") from exc


async def complete(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    json_mode: bool = False,
) -> str:
    """Non-streaming completion; returns the assistant message content."""
    payload = _payload(
        messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=False,
        response_format={"type": "json_object"} if json_mode else None,
    )
    try:
        async with _client() as client:
            response = await client.post("/chat/completions", json=payload)
            await _raise_for_status(response)
            data = response.json()
    except LLMError:
        raise
    except httpx.HTTPError as exc:
        raise LLMError(f"llm request failed: {exc}") from exc

    choices = data.get("choices") or []
    if not choices:
        raise LLMError("llm returned no choices")
    content = (choices[0].get("message") or {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise LLMError("llm returned an empty answer")
    return content


def vision_model_name(override: str | None = None) -> str:
    settings = get_settings()
    return override or settings.llm_vision_model or settings.llm_chat_model
