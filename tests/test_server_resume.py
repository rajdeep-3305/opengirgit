"""Server resume JSON extraction (no network)."""

from __future__ import annotations

import pytest
from app import llm
from app.resume import _extract_json, _normalise


def test_extract_json_plain():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced():
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_with_prose_around_it():
    raw = 'Sure! Here is the JSON:\n{"name": "Ada"}\nHope that helps.'
    assert _extract_json(raw) == {"name": "Ada"}


def test_extract_json_rejects_non_json():
    with pytest.raises(llm.LLMError):
        _extract_json("no json here")


def test_normalise_fills_all_keys():
    parsed = _normalise(
        {
            "name": "Ada",
            "skills": ["python", "", " sql "],
            "experience": [{"title": "Dev"}, "junk"],
            "projects": "oops",
        }
    )
    assert parsed["name"] == "Ada"
    assert parsed["skills"] == ["python", "sql"]
    assert parsed["experience"] == [
        {"title": "Dev", "company": "", "duration": "", "description": ""}
    ]
    assert parsed["projects"] == []
    assert parsed["education"] == []
    for key in ("phone", "location", "summary", "certifications", "languages"):
        assert key in parsed
