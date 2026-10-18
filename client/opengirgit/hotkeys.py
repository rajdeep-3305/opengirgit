"""Global hotkeys.

* **Windows**: ``RegisterHotKey`` + a Qt native event filter.
* Everywhere else (unsupported platforms, development): application-level
  ``QShortcut`` fallbacks with the same combinations, firing while the overlay
  has focus.

Hotkey strings look like ``"Shift+Alt+A"`` / ``"Shift+Alt+["`` and are fully
configurable in ``~/.opengirgit/config.json``.
"""

from __future__ import annotations

import ctypes
import sys
from typing import Any

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut

IS_WINDOWS = sys.platform == "win32"

WM_HOTKEY = 0x0312

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

_MODIFIER_NAMES = {
    "shift": MOD_SHIFT,
    "alt": MOD_ALT,
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "win": MOD_WIN,
    "meta": MOD_WIN,
    "super": MOD_WIN,
    "cmd": MOD_WIN,
}

_VK_NAMES: dict[str, int] = {
    "space": 0x20,
    "tab": 0x09,
    "enter": 0x0D,
    "return": 0x0D,
    "escape": 0x1B,
    "esc": 0x1B,
    "backspace": 0x08,
    "delete": 0x2E,
    "insert": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "[": 0xDB,
    "]": 0xDD,
    "-": 0xBD,
    "=": 0xBB,
    ",": 0xBC,
    ".": 0xBE,
    "/": 0xBF,
    ";": 0xBA,
    "'": 0xDE,
    "`": 0xC0,
    "\\": 0xDC,
}

NO_REPEAT_ACTIONS = {"ask", "erase", "collapse", "screenshot", "prev", "next", "click_through"}


class HotkeyError(Exception):
    pass


# --------------------------------------------------------------------------- #
# parsing / conversion (pure, unit tested)
# --------------------------------------------------------------------------- #


def split_spec(spec: str) -> tuple[list[str], str]:
    """``"Shift+Alt+A"`` -> ``(["shift", "alt"], "A")``.  Raises HotkeyError."""
    parts = [p.strip() for p in (spec or "").split("+") if p.strip()]
    if not parts:
        raise HotkeyError("empty hotkey")
    modifiers: list[str] = []
    key_part: str | None = None
    for part in parts:
        lower = part.lower()
        if lower in _MODIFIER_NAMES:
            if key_part is not None:
                raise HotkeyError(f"bad hotkey {spec!r}: modifier after key")
            modifiers.append(lower)
        elif key_part is None:
            key_part = part
        else:
            raise HotkeyError(f"bad hotkey {spec!r}: more than one key")
    if key_part is None:
        raise HotkeyError(f"bad hotkey {spec!r}: no key")
    if not modifiers:
        raise HotkeyError(f"bad hotkey {spec!r}: at least one modifier is required")
    return modifiers, key_part


def parse_hotkey(spec: str) -> tuple[int, int]:
    """``"Shift+Alt+A"`` -> ``(modifiers, virtual_key)``. Raises HotkeyError."""
    modifiers, key_part = split_spec(spec)
    mask = 0
    for modifier in modifiers:
        mask |= _MODIFIER_NAMES[modifier]

    lower = key_part.lower()
    if lower in _VK_NAMES:
        vk = _VK_NAMES[lower]
    elif len(key_part) == 1 and key_part.isalnum():
        vk = ord(key_part.upper())
    elif lower.startswith("f") and lower[1:].isdigit() and 1 <= int(lower[1:]) <= 24:
        vk = 0x70 + int(lower[1:]) - 1
    else:
        raise HotkeyError(f"bad hotkey {spec!r}: unsupported key {key_part!r}")
    return mask, vk


def validate_hotkeys(hotkeys: dict[str, str]) -> dict[str, str]:
    """Return ``{action: error}`` for specs that would not register.

    An empty spec is valid (the hotkey is disabled). Duplicate combinations are
    reported for the later action, since only the first one can be registered.
    """
    problems: dict[str, str] = {}
    seen: dict[tuple[int, int], str] = {}
    for action, spec in hotkeys.items():
        spec = (spec or "").strip()
        if not spec:
            continue
        try:
            combo = parse_hotkey(spec)
        except HotkeyError as exc:
            problems[action] = str(exc)
            continue
        if combo in seen:
            problems[action] = f"already used by '{seen[combo]}'"
        else:
            seen[combo] = action
    return problems


# --------------------------------------------------------------------------- #
# manager
# --------------------------------------------------------------------------- #


class GlobalHotkeyManager(QObject, QAbstractNativeEventFilter):
    """Registers system-wide hotkeys; emits ``triggered(action)``.

    ``backend_state()`` tells the UI which mechanism is active:
    ``"windows"`` or ``"focus"`` (window-local fallback).
    """

    triggered = Signal(str)
    backend_changed = Signal(str)

    def __init__(self, parent: QObject | None = None, fallback_window: Any = None) -> None:
        super().__init__(parent)
        self._fallback_window = fallback_window
        self._bindings: dict[int, str] = {}
        self._shortcuts: dict[str, QShortcut] = {}
        self._next_id = 0xB000
        self._registered: list[int] = []
        self._backend = "focus" if not IS_WINDOWS else "windows"
        self._backend_detail = ""
        if IS_WINDOWS:
            from PySide6.QtCore import QCoreApplication

            app = QCoreApplication.instance()
            if app is not None:
                app.installNativeEventFilter(self)

    # -- info -------------------------------------------------------------- #

    def backend_state(self) -> str:
        return self._backend

    def backend_detail(self) -> str:
        """Human-readable reason when the strongest backend is unavailable."""
        return self._backend_detail

    # -- registration ------------------------------------------------------ #

    def register_all(self, hotkeys: dict[str, str]) -> list[str]:
        """Register every mapping; returns the actions that failed."""
        if IS_WINDOWS:
            failures: list[str] = []
            for action, spec in hotkeys.items():
                if not spec:
                    continue
                if not self.register(action, spec):
                    failures.append(action)
            return failures

        # Non-Windows platforms keep focus-local shortcuts as a safety net.
        failures = []
        for action, spec in hotkeys.items():
            if not spec:
                continue
            if not self._register_shortcut(action, spec):
                failures.append(action)
        return failures

    def register(self, action: str, spec: str) -> bool:
        try:
            parse_hotkey(spec)
        except HotkeyError:
            return False

        if not IS_WINDOWS:
            return self._register_shortcut(action, spec)

        modifiers, vk = parse_hotkey(spec)
        if action in NO_REPEAT_ACTIONS:
            modifiers |= MOD_NOREPEAT

        hotkey_id = self._next_id
        self._next_id += 1
        try:  # pragma: no cover - windows only
            ok = bool(ctypes.windll.user32.RegisterHotKey(None, hotkey_id, modifiers, vk))
        except Exception:
            ok = False
        if not ok:
            return False
        self._bindings[hotkey_id] = action
        self._registered.append(hotkey_id)
        return True

    def _register_shortcut(self, action: str, spec: str) -> bool:
        if self._fallback_window is None:
            return False
        sequence = QKeySequence(spec)
        if sequence.isEmpty():
            return False
        shortcut = QShortcut(sequence, self._fallback_window)
        shortcut.setContext(Qt.ApplicationShortcut)
        shortcut.activated.connect(lambda name=action: self.triggered.emit(name))
        self._shortcuts[action] = shortcut
        return True

    # -- teardown ---------------------------------------------------------- #

    def unregister_all(self) -> None:
        if IS_WINDOWS:  # pragma: no cover - windows only
            for hotkey_id in self._registered:
                try:
                    ctypes.windll.user32.UnregisterHotKey(None, hotkey_id)
                except Exception:
                    pass
        self._registered.clear()
        self._bindings.clear()
        for shortcut in self._shortcuts.values():
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        self._shortcuts.clear()

    # -- native event filter ---------------------------------------------- #

    def nativeEventFilter(self, event_type: Any, message: Any) -> tuple[bool, int]:
        if not IS_WINDOWS:  # pragma: no cover - only installed on Windows
            return False, 0
        try:  # pragma: no cover - windows only
            if event_type in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
                msg = ctypes.cast(int(message), ctypes.POINTER(_MSG)).contents
                if msg.message == WM_HOTKEY:
                    action = self._bindings.get(int(msg.wParam))
                    if action:
                        self.triggered.emit(action)
                        return True, 0
        except Exception:
            pass
        return False, 0


class _MSG(ctypes.Structure):  # pragma: no cover - windows only
    _fields_ = [
        ("hWnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_ssize_t),
        ("time", ctypes.c_uint),
        ("pt_x", ctypes.c_long),
        ("pt_y", ctypes.c_long),
    ]
