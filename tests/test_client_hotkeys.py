"""Hotkey string parsing (skipped when PySide6 is unavailable)."""

from __future__ import annotations

import sys

import pytest

pytest.importorskip("PySide6")

from opengirgit.hotkeys import (  # noqa: E402
    MOD_ALT,
    MOD_CONTROL,
    MOD_SHIFT,
    GlobalHotkeyManager,
    HotkeyError,
    keysym_name,
    parse_hotkey,
    portal_trigger,
    validate_hotkeys,
    x11_modifier_mask,
)
from PySide6.QtCore import QObject, Signal  # noqa: E402


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


# -- Linux conversions ------------------------------------------------------ #


def test_keysym_names_cover_the_settings_spellings():
    assert keysym_name("A") == "a"
    assert keysym_name("7") == "7"
    assert keysym_name("[") == "bracketleft"
    assert keysym_name("\\") == "backslash"
    assert keysym_name("Space") == "space"
    assert keysym_name("PageUp") == "Prior"
    assert keysym_name("PageDown") == "Next"
    assert keysym_name("Return") == "Return"
    assert keysym_name("F5") == "F5"
    assert keysym_name("f24") == "F24"
    assert keysym_name("f25") is None
    assert keysym_name("Nope") is None


def test_portal_triggers_follow_the_shortcuts_spec():
    assert portal_trigger("Shift+Alt+A") == "ALT+SHIFT+a"
    assert portal_trigger("Ctrl+Shift+[") == "CTRL+SHIFT+bracketleft"
    assert portal_trigger("Ctrl+Alt+F5") == "CTRL+ALT+F5"
    assert portal_trigger("Alt+PageUp") == "ALT+Prior"
    assert portal_trigger("Win+Space") == "LOGO+space"
    assert portal_trigger("Shift+Alt+Nope") is None
    assert portal_trigger("A") is None
    assert portal_trigger("") is None


def test_x11_modifier_masks():
    assert x11_modifier_mask(["shift"]) == 1
    assert x11_modifier_mask(["ctrl"]) == 4
    assert x11_modifier_mask(["alt"]) == 8
    assert x11_modifier_mask(["win"]) == 64
    assert x11_modifier_mask(["shift", "alt", "ctrl"]) == 1 | 8 | 4


# -- backend selection (Linux) ---------------------------------------------- #


class _FakePortalClient(QObject):
    shortcuts_bound = Signal(bool, str)
    shortcut_activated = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bound: list[list[tuple[str, str, str]]] = []
        self.closed = False

    def bind_shortcuts(self, shortcuts, timeout_ms=120000):
        self.bound.append(shortcuts)

    def close(self):
        self.closed = True


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux only")
def test_wayland_backend_binds_through_the_portal(monkeypatch):
    from opengirgit import hotkeys, portal

    monkeypatch.setattr(
        hotkeys.GlobalHotkeyManager, "_is_wayland", staticmethod(lambda: True)
    )
    monkeypatch.setattr(portal, "PortalClient", _FakePortalClient)

    manager = GlobalHotkeyManager()
    failures = manager.register_all({"ask": "Shift+Alt+A", "erase": "Ctrl+Shift+["})
    assert failures == ["ask", "erase"]  # no fallback window in this test
    assert manager.backend_state() == "portal"
    assert manager._portal.bound == [  # noqa: SLF001
        [("ask", "ask", "ALT+SHIFT+a"), ("erase", "erase", "CTRL+SHIFT+bracketleft")]
    ]

    manager._portal.shortcuts_bound.emit(True, "")  # noqa: SLF001
    assert manager.backend_state() == "portal-ready"

    manager.unregister_all()
    assert manager._portal is None  # noqa: SLF001


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux only")
def test_portal_refusal_falls_back_to_focus_with_a_hint(monkeypatch):
    from opengirgit import hotkeys, portal

    class Refusing(_FakePortalClient):
        def bind_shortcuts(self, shortcuts, timeout_ms=120000):
            raise portal.PortalError("An app id is required")

    monkeypatch.setattr(
        hotkeys.GlobalHotkeyManager, "_is_wayland", staticmethod(lambda: True)
    )
    monkeypatch.setattr(portal, "PortalClient", Refusing)
    monkeypatch.setattr(portal, "portal_hotkey_app_id", lambda: None)

    manager = GlobalHotkeyManager()
    manager.register_all({"ask": "Shift+Alt+A"})
    assert manager.backend_state() == "focus"
    assert "application menu" in manager.backend_detail()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux only")
def test_portal_failure_after_binding_reports_the_desktop_message(monkeypatch):
    from opengirgit import hotkeys, portal

    monkeypatch.setattr(
        hotkeys.GlobalHotkeyManager, "_is_wayland", staticmethod(lambda: True)
    )
    monkeypatch.setattr(portal, "PortalClient", _FakePortalClient)

    manager = GlobalHotkeyManager()
    manager.register_all({"ask": "Shift+Alt+A"})
    manager._portal.shortcuts_bound.emit(False, "the shortcuts were cancelled")  # noqa: SLF001
    assert manager.backend_state() == "focus"
    assert manager.backend_detail() == "the shortcuts were cancelled"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux only")
def test_x11_backend_grabs_the_combinations(monkeypatch):
    from opengirgit import hotkeys

    grabbed: list[str] = []

    class FakeGrabber:
        available = True

        def __init__(self, on_trigger):
            self.on_trigger = on_trigger

        def grab(self, action, spec):
            grabbed.append(action)
            return True

        def ungrab_all(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(hotkeys, "X11Grabber", FakeGrabber)
    monkeypatch.setattr(
        hotkeys.GlobalHotkeyManager, "_is_wayland", staticmethod(lambda: False)
    )

    manager = GlobalHotkeyManager()
    manager.register_all({"ask": "Shift+Alt+A", "erase": ""})
    assert manager.backend_state() == "x11"
    assert grabbed == ["ask"]
    manager.unregister_all()
    assert manager._x11 is None  # noqa: SLF001


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux only")
def test_x11_conflicts_fall_back_to_focus(monkeypatch):
    from opengirgit import hotkeys

    class BusyGrabber:
        available = True

        def __init__(self, on_trigger):
            pass

        def grab(self, action, spec):
            return False

        def ungrab_all(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(hotkeys, "X11Grabber", BusyGrabber)
    monkeypatch.setattr(
        hotkeys.GlobalHotkeyManager, "_is_wayland", staticmethod(lambda: False)
    )

    manager = GlobalHotkeyManager()
    manager.register_all({"ask": "Shift+Alt+A"})
    assert manager.backend_state() == "focus"
    assert "no combination" in manager.backend_detail()
