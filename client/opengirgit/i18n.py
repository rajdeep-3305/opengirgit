"""Tiny offline i18n layer: JSON catalogs in ``opengirgit/translations``.

Strings are keyed by their **English source text**, so a missing catalog —
or a missing entry in one — degrades to English with no lookup failures::

    from .i18n import tr

    self.set_status(tr("done"))
    self.set_status(tr("{count} screenshots ready").format(count=count))

Catalogs are plain JSON files (``translations/de.json``). Adding a language is
dropping in a file — the settings dialog lists whatever ships. Generate the
key inventory for a new language with ``tools/collect_strings.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

TRANSLATIONS_DIR = Path(__file__).resolve().parent / "translations"
DEFAULT_LANGUAGE = "en"

#: Friendly names for the language picker (unknown codes show the code itself).
LANGUAGE_NAMES = {
    "en": "English",
    "ar": "العربية",
    "de": "Deutsch",
    "es": "Español",
    "fr": "Français",
    "hi": "हिन्दी",
    "it": "Italiano",
    "ja": "日本語",
    "ko": "한국어",
    "nl": "Nederlands",
    "pl": "Polski",
    "pt": "Português",
    "ru": "Русский",
    "tr": "Türkçe",
    "uk": "Українська",
    "zh": "中文",
}

_current = DEFAULT_LANGUAGE
_catalog: dict[str, str] = {}


def _catalog_codes() -> set[str]:
    if not TRANSLATIONS_DIR.is_dir():
        return set()
    return {path.stem for path in TRANSLATIONS_DIR.glob("*.json")}


def available_languages() -> dict[str, str]:
    """Language code → display name for every shipped catalog (English first)."""
    languages = {DEFAULT_LANGUAGE: LANGUAGE_NAMES.get(DEFAULT_LANGUAGE, "English")}
    for code in sorted(_catalog_codes()):
        if code == DEFAULT_LANGUAGE:
            continue
        languages[code] = LANGUAGE_NAMES.get(code, code)
    return languages


def _load_catalog(language: str) -> dict[str, str]:
    path = TRANSLATIONS_DIR / f"{language}.json"
    if language == DEFAULT_LANGUAGE or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(key): str(value) for key, value in data.items() if isinstance(value, str)}


def _system_language() -> str:
    try:
        from PySide6.QtCore import QLocale

        return QLocale.system().name() or DEFAULT_LANGUAGE
    except Exception:  # pragma: no cover - Qt always present in the client
        return DEFAULT_LANGUAGE


def resolve_language(language: str) -> str:
    """Map a setting value (``auto``, ``de_DE``, …) to a shipped catalog code."""
    code = str(language or "").strip().lower()
    if code in ("", "auto"):
        code = _system_language().lower()
    if code in _catalog_codes() or code == DEFAULT_LANGUAGE:
        return code
    short = code.replace("-", "_").split("_")[0]
    if short in _catalog_codes() or short == DEFAULT_LANGUAGE:
        return short
    return DEFAULT_LANGUAGE


def set_language(language: str) -> str:
    """Activate a catalog (English when nothing matches); returns the code used."""
    global _current, _catalog
    _current = resolve_language(language)
    _catalog = _load_catalog(_current)
    return _current


def current_language() -> str:
    return _current


def tr(text: str) -> str:
    """Translate a source string; unknown strings pass through unchanged."""
    if not _catalog:
        return text
    return _catalog.get(text, text)


__all__ = [
    "DEFAULT_LANGUAGE",
    "TRANSLATIONS_DIR",
    "available_languages",
    "current_language",
    "resolve_language",
    "set_language",
    "tr",
]
