"""Client context formatting and settings behaviour (no Qt imports)."""

from __future__ import annotations

from opengirgit.config import DEFAULT_HOTKEYS, AppSettings
from opengirgit.prompts import format_interview_context, format_resume_data

RESUME = {
    "name": "Ada Lovelace",
    "email": "ada@example.com",
    "summary": "First programmer.",
    "experience": [
        {
            "title": "Analyst",
            "company": "Difference Engine Co",
            "duration": "1842-1843",
            "description": "Wrote the first algorithm.",
        }
    ],
    "education": [{"degree": "Mathematics", "institution": "Home", "year": "1840"}],
    "skills": ["mathematics", "analytical engine"],
    "projects": [
        {
            "name": "Bernoulli numbers",
            "description": "Note G",
            "technologies": ["Analytical Engine"],
        }
    ],
    "languages": ["English"],
}


def test_resume_formatting_contains_sections():
    text = format_resume_data(RESUME)
    for fragment in (
        "Ada Lovelace",
        "--- Experience ---",
        "Analyst at Difference Engine Co (1842-1843)",
        "--- Education ---",
        "mathematics, analytical engine",
        "Bernoulli numbers",
        "--- Languages ---",
    ):
        assert fragment in text


def test_resume_formatting_handles_missing_data():
    assert "no resume provided" in format_resume_data(None)


def test_interview_context_includes_job_details():
    text = format_interview_context(RESUME, "Acme", "Build things", "Ask about scale")
    assert "Company: Acme" in text
    assert "Job Description:\nBuild things" in text
    assert "Additional Information:\nAsk about scale" in text


def test_interview_context_defaults():
    text = format_interview_context(None, "", "", "")
    assert "Company: Not specified" in text
    assert "Job Description: Not provided" in text


def test_settings_round_trip_and_clamping():
    settings = AppSettings.from_dict({"opacity": 5.0, "stt_engine": "banana", "unknown": 1})
    assert settings.opacity == 1.0
    assert settings.stt_engine == "local"
    assert not hasattr(settings, "unknown")


def test_old_default_opacity_is_migrated_once():
    migrated = AppSettings.from_dict({"opacity": 0.96})
    assert migrated.opacity == 0.95

    explicit = AppSettings.from_dict({"opacity": 0.96, "config_version": 2})
    assert explicit.opacity == 0.96


def test_silence_seconds_default_and_clamping():
    assert AppSettings().silence_seconds == 0.9
    assert AppSettings.from_dict({"silence_seconds": 0.01}).silence_seconds == 0.2
    assert AppSettings.from_dict({"silence_seconds": 99}).silence_seconds == 3.0


def test_partials_default_and_env_override(monkeypatch):
    assert AppSettings().partials is True
    monkeypatch.setenv("OPENGIRGIT_PARTIALS", "0")
    assert AppSettings().apply_env().partials is False
    monkeypatch.setenv("OPENGIRGIT_PARTIALS", "yes")
    assert AppSettings().apply_env().partials is True


def test_settings_hotkeys_merge_defaults():
    settings = AppSettings.from_dict({"hotkeys": {"ask": "Ctrl+Shift+Q"}})
    assert settings.hotkeys["ask"] == "Ctrl+Shift+Q"
    assert set(DEFAULT_HOTKEYS) <= set(settings.hotkeys)


def test_new_settings_defaults_and_clamping():
    settings = AppSettings.from_dict({})
    assert settings.chat_transport == "auto"
    assert settings.ui_scale == 0

    broken = AppSettings.from_dict({"chat_transport": "carrier-pigeon", "ui_scale": 7})
    assert broken.chat_transport == "auto"
    assert broken.ui_scale == 0

    explicit = AppSettings.from_dict({"chat_transport": "websocket", "ui_scale": "125"})
    assert explicit.chat_transport == "websocket"
    assert explicit.ui_scale == 125


def test_new_settings_env_overrides(monkeypatch):
    monkeypatch.setenv("OPENGIRGIT_CHAT_TRANSPORT", "sse")
    monkeypatch.setenv("OPENGIRGIT_UI_SCALE", "150")
    settings = AppSettings.from_dict({}).apply_env()
    assert settings.chat_transport == "sse"
    assert settings.ui_scale == 150


def test_english_only_settings_have_no_language_knobs(monkeypatch):
    monkeypatch.setenv("OPENGIRGIT_LANGUAGE", "de")
    monkeypatch.setenv("OPENGIRGIT_UI_LANGUAGE", "de")
    settings = AppSettings.from_dict({"language": "de", "ui_language": "de"}).apply_env()
    assert not hasattr(settings, "language")
    assert not hasattr(settings, "ui_language")
