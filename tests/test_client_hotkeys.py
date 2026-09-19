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
