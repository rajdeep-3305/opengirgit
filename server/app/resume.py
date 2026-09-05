"""Resume text → structured JSON, using the configured LLM."""

from __future__ import annotations

import json
import re

from . import llm
from .prompts import build_resume_messages

_MAX_TEXT = 200_000

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _extract_json(raw: str) -> dict:
    """Best-effort JSON extraction: direct, fenced, then first {...} block."""
    candidates: list[str] = [raw.strip()]
    fenced = _FENCE_RE.search(raw)
    if fenced:
        candidates.append(fenced.group(1).strip())
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        candidates.append(raw[start : end + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise llm.LLMError("model did not return valid JSON")


def _normalise(data: dict) -> dict:
    """Guarantee the shape the client expects."""
    def _list_of_dicts(key: str, fields: tuple[str, ...]) -> list[dict]:
        out = []
        for item in data.get(key) or []:
            if not isinstance(item, dict):
                continue
            out.append({field: item.get(field) or "" for field in fields})
        return out

    def _str_list(key: str) -> list[str]:
        return [str(x).strip() for x in (data.get(key) or []) if str(x).strip()]

    return {
        "name": data.get("name") or None,
        "email": data.get("email") or None,
        "phone": data.get("phone") or None,
        "location": data.get("location") or None,
        "summary": data.get("summary") or None,
        "experience": _list_of_dicts("experience", ("title", "company", "duration", "description")),
        "education": _list_of_dicts("education", ("degree", "institution", "year")),
        "skills": _str_list("skills"),
        "certifications": _str_list("certifications"),
        "projects": _list_of_dicts("projects", ("name", "description")),
        "languages": _str_list("languages"),
    }


async def parse_resume(resume_text: str, *, model: str | None = None) -> dict:
    text = (resume_text or "").strip()
    if not text:
        raise llm.LLMError("resume text is empty", status_code=400)
    if len(text) > _MAX_TEXT:
        text = text[:_MAX_TEXT]

    messages = build_resume_messages(text)

    try:
        raw = await llm.complete(messages, model=model, temperature=0.0, json_mode=True)
    except llm.LLMError:
        # Some providers reject response_format; retry without it.
        raw = await llm.complete(messages, model=model, temperature=0.0)

    return _normalise(_extract_json(raw))
