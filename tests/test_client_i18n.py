"""Offline i18n layer: catalogs, resolution and fallbacks (no Qt needed)."""

from __future__ import annotations

import json

from opengirgit import i18n


def test_english_is_implicit_and_identity():
    assert i18n.set_language("en") == "en"
    assert i18n.tr("done") == "done"
    assert i18n.tr("a string nobody translated") == "a string nobody translated"


def test_german_catalog_loads_and_translates():
    assert i18n.set_language("de") == "de"
    assert i18n.tr("done") == "fertig"
    assert i18n.tr("Ask") == "Fragen"
    # unknown strings still pass through
    assert i18n.tr("not in the catalog") == "not in the catalog"
    i18n.set_language("en")  # do not leak into other tests


def test_resolve_language_accepts_regions_and_falls_back():
    assert i18n.resolve_language("") == "en"
    assert i18n.resolve_language("de_DE") == "de"
    assert i18n.resolve_language("de-AT") == "de"
    assert i18n.resolve_language("xx") == "en"
    assert i18n.resolve_language("en_US") in ("en",)


def test_shipped_catalogs_are_complete_and_consistent():
    """de.json ships value-for-value with en.json and keeps every placeholder."""
    import string

    directory = i18n.TRANSLATIONS_DIR
    english = json.loads((directory / "en.json").read_text(encoding="utf-8"))
    german = json.loads((directory / "de.json").read_text(encoding="utf-8"))
    assert set(english) == set(german), "de.json is out of sync with en.json"

    formatter = string.Formatter()
    for key, value in german.items():
        assert isinstance(value, str) and value.strip(), f"empty translation for {key!r}"
        expected = sorted(field for _, field, _, _ in formatter.parse(key) if field)
        produced = sorted(field for _, field, _, _ in formatter.parse(value) if field)
        assert produced == expected, f"placeholder mismatch for {key!r}: {value!r}"


def test_catalog_inventory_matches_the_source_strings():
    """``tools/collect_strings.py --check`` must pass (en.json is fresh)."""
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "tools" / "collect_strings.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_available_languages_lists_shipped_catalogs():
    languages = i18n.available_languages()
    assert languages["en"] == "English"
    assert languages["de"] == "Deutsch"


def test_missing_catalog_falls_back_to_english(tmp_path, monkeypatch):
    monkeypatch.setattr(i18n, "TRANSLATIONS_DIR", tmp_path)
    assert i18n.set_language("fr") == "en"
    assert i18n.tr("done") == "done"
    i18n.set_language("en")


def test_broken_catalog_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(i18n, "TRANSLATIONS_DIR", tmp_path)
    (tmp_path / "fr.json").write_text("{not json", encoding="utf-8")
    assert i18n.set_language("fr") == "fr"
    assert i18n.tr("done") == "done"  # empty catalog → identity
    i18n.set_language("en")
