"""Hotkey string parsing (skipped when PySide6 is unavailable)."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opengirgit.hotkeys import (  # noqa: E402
    MOD_ALT,
    MOD_CONTROL,
    MOD_SHIFT,
    HotkeyError,
    parse_hotkey,
    validate_hotkeys,
)


def test_letter_hotkey():
    modifiers, vk = parse_hotkey("Shift+Alt+A")
    assert modifiers == MOD_SHIFT | MOD_ALT
    assert vk == ord("A")


def test_symbol_and_alias_keys():
    assert parse_hotkey("Shift+Alt+[")[1] == 0xDB
    assert parse_hotkey("Shift+Alt+-")[1] == 0xBD
    assert parse_hotkey("Ctrl+Shift+Space")[1] == 0x20
    assert parse_hotkey("Ctrl+Alt+F5")[1] == 0x74
    assert parse_hotkey("Control+Shift+X")[0] == MOD_CONTROL | MOD_SHIFT


def test_invalid_hotkeys_raise():
    for bad in ("", "A", "Shift+", "Shift+Alt+A+B", "Shift+Alt+£", "Shift+Alt"):
        with pytest.raises(HotkeyError):
            parse_hotkey(bad)


def test_validate_hotkeys_accepts_valid_and_disabled():
    assert validate_hotkeys({"ask": "Shift+Alt+A", "erase": ""}) == {}


def test_validate_hotkeys_reports_bad_specs():
    problems = validate_hotkeys({"ask": "Q"})
    assert "ask" in problems and "modifier" in problems["ask"]


def test_validate_hotkeys_reports_duplicates_for_later_action():
    problems = validate_hotkeys({"ask": "Shift+Alt+A", "erase": "Shift+Alt+A"})
    assert list(problems) == ["erase"]
    assert "ask" in problems["erase"]


def test_validate_hotkeys_duplicate_ignores_case_and_spacing():
    # Both parse to the same modifiers+virtual key.
    problems = validate_hotkeys({"ask": "shift+alt+a", "erase": " Shift+Alt+A "})
    assert "erase" in problems
