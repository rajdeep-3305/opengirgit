"""Global hotkeys.

Three system-wide backends, picked automatically:

* **Windows**: ``RegisterHotKey`` + a Qt native event filter (unchanged).
* **X11** (Linux/BSD): ``XGrabKey`` through ``libX11`` (ctypes), with the
  NumLock/CapsLock modifier variants grabbed too and key auto-repeat
  suppressed through XKB.
* **Wayland**: the ``org.freedesktop.portal.GlobalShortcuts`` portal, because
  the compositor owns the keyboard (see :mod:`opengirgit.portal`).  Desktops
  show their own confirmation dialog and may let the user re-assign the keys;
  the combinations below are sent as *preferred* triggers.  This needs the
  app to have an app id, which desktops derive from launching
  ``<id>.desktop`` through their application grid -- a plain shell launch has
  none and falls back to focus-only shortcuts (``portal_hotkey_app_id``).

Everywhere else, application-level ``QShortcut`` fallbacks with the same
combinations are kept registered (they fire while the overlay has focus).

Hotkey strings look like ``"Shift+Alt+A"`` / ``"Shift+Alt+["`` and are fully
configurable in ``~/.opengirgit/config.json``.
"""

from __future__ import annotations

import ctypes
import os
import sys
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")

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

# Settings spelling -> X11/XKB keysym name (shared by the X11 and portal paths).
_KEYSYM_NAMES: dict[str, str] = {
    "space": "space",
    "tab": "Tab",
    "enter": "Return",
    "return": "Return",
    "escape": "Escape",
    "esc": "Escape",
    "backspace": "BackSpace",
    "delete": "Delete",
    "insert": "Insert",
    "home": "Home",
    "end": "End",
    "pageup": "Prior",
    "pagedown": "Next",
    "left": "Left",
    "up": "Up",
    "right": "Right",
    "down": "Down",
    "[": "bracketleft",
    "]": "bracketright",
    "-": "minus",
    "=": "equal",
    ",": "comma",
    ".": "period",
    "/": "slash",
    ";": "semicolon",
    "'": "apostrophe",
    "`": "grave",
    "\\": "backslash",
}

# shortcuts XDG specification modifier names (used by the GlobalShortcuts portal).
_PORTAL_MODIFIERS = {
    "ctrl": "CTRL",
    "control": "CTRL",
    "alt": "ALT",
    "shift": "SHIFT",
    "win": "LOGO",
    "meta": "LOGO",
    "super": "LOGO",
    "cmd": "LOGO",
}
_PORTAL_MODIFIER_ORDER = ("CTRL", "ALT", "SHIFT", "LOGO")

# X11 modifier masks (X.h): Shift, Lock, Control, Mod1 (Alt), Mod2 (NumLock), Mod4 (Super).
_X11_MODIFIERS = {
    "ctrl": 1 << 2,
    "control": 1 << 2,
    "shift": 1 << 0,
    "alt": 1 << 3,
    "win": 1 << 6,
    "meta": 1 << 6,
    "super": 1 << 6,
    "cmd": 1 << 6,
}
_X11_LOCK_MASK = 1 << 1
_X11_NUMLOCK_MASK = 1 << 4

# Actions where the OS key-repeat is undesirable (they submit/erase/toggle).
NO_REPEAT_ACTIONS = {"ask", "erase", "collapse", "screenshot", "prev", "next"}


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


def keysym_name(key: str) -> str | None:
    """Settings key spelling -> X11/XKB keysym name, or ``None`` if unknown."""
    lower = key.lower()
    if lower in _KEYSYM_NAMES:
        return _KEYSYM_NAMES[lower]
    if len(key) == 1 and key.isalnum():
        return key.lower()
    if lower.startswith("f") and lower[1:].isdigit() and 1 <= int(lower[1:]) <= 24:
        return f"F{int(lower[1:])}"
    return None


def portal_trigger(spec: str) -> str | None:
    """``"Shift+Alt+A"`` -> ``"ALT+SHIFT+a"`` (shortcuts XDG spec format)."""
    try:
        modifiers, key = split_spec(spec)
    except HotkeyError:
        return None
    name = keysym_name(key)
    if name is None:
        return None
    tokens = [token for token in _PORTAL_MODIFIER_ORDER if token in
              {_PORTAL_MODIFIERS[m] for m in modifiers}]
    tokens.append(name)
    return "+".join(tokens)


def x11_modifier_mask(modifiers: list[str]) -> int:
    mask = 0
    for modifier in modifiers:
        mask |= _X11_MODIFIERS.get(modifier, 0)
    return mask


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
# X11 backend (ctypes, no extra dependency)
# --------------------------------------------------------------------------- #

_X11_KEY_PRESS = 2
_X11_GRAB_MODE_ASYNC = 1


class _XKeyEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("window", ctypes.c_ulong),
        ("root", ctypes.c_ulong),
        ("subwindow", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("x_root", ctypes.c_int),
        ("y_root", ctypes.c_int),
        ("state", ctypes.c_uint),
        ("keycode", ctypes.c_uint),
        ("same_screen", ctypes.c_int),
    ]


class _XEvent(ctypes.Union):
    _fields_ = [("type", ctypes.c_int), ("xkey", _XKeyEvent), ("pad", ctypes.c_char * 192)]


class X11Grabber:
    """System-wide hotkeys through ``XGrabKey``.

    Works on native X11 sessions (and XWayland clients on X11, which is the
    only place grabs are honoured).  Fails cleanly when ``libX11`` or the
    display is missing.
    """

    def __init__(self, on_trigger: Callable[[str], None]) -> None:
        self._on_trigger = on_trigger
        self._display: Any = None
        self._lib: Any = None
        self._root = 0
        self._bindings: dict[tuple[int, int], str] = {}
        self._grabbed: list[tuple[int, int]] = []
        self._error_code = 0
        self._error_handler: Any = None
        self._previous_handler = 0
        self._handler_type: Any = None
        self._timer: QTimer | None = None
        self._open()

    # -- setup ------------------------------------------------------------- #

    def _open(self) -> None:
        try:
            self._lib = ctypes.CDLL("libX11.so.6")
        except OSError:
            self._lib = None
            return
        lib = self._lib
        lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        lib.XOpenDisplay.restype = ctypes.c_void_p
        lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        lib.XDefaultRootWindow.restype = ctypes.c_ulong
        lib.XStringToKeysym.argtypes = [ctypes.c_char_p]
        lib.XStringToKeysym.restype = ctypes.c_ulong
        lib.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        lib.XKeysymToKeycode.restype = ctypes.c_ubyte
        lib.XGrabKey.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_ulong,
            ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ]
        lib.XGrabKey.restype = ctypes.c_int
        lib.XUngrabKey.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_ulong]
        lib.XPending.argtypes = [ctypes.c_void_p]
        lib.XPending.restype = ctypes.c_int
        lib.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.POINTER(_XEvent)]
        lib.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
        lib.XSetErrorHandler.argtypes = [ctypes.c_void_p]

        self._display = lib.XOpenDisplay(None)
        if not self._display:
            self._lib = None
            return
        self._root = lib.XDefaultRootWindow(self._display)

        # Suppress auto-repeat at the server: one KeyPress per physical press.
        try:
            lib.XkbSetDetectableAutoRepeat.argtypes = [
                ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int),
            ]
            supported = ctypes.c_int(0)
            lib.XkbSetDetectableAutoRepeat(self._display, 1, ctypes.byref(supported))
        except (AttributeError, OSError):
            pass

        # Record X errors (BadAccess = the combination is taken) instead of
        # letting the default handler print them.  Restored again in close().
        self._handler_type = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)

        def handler(display: Any, event: Any) -> int:
            try:
                self._error_code = ctypes.cast(event, ctypes.POINTER(ctypes.c_int))[0]
            except Exception:  # noqa: BLE001
                self._error_code = -1
            return 0

        self._error_handler = self._handler_type(handler)  # keep a reference alive
        lib.XSetErrorHandler.argtypes = [self._handler_type]
        lib.XSetErrorHandler.restype = ctypes.c_void_p
        self._previous_handler = lib.XSetErrorHandler(self._error_handler)

    @property
    def available(self) -> bool:
        return bool(self._display)

    # -- grabbing ---------------------------------------------------------- #

    def grab(self, action: str, spec: str) -> bool:
        if not self.available:
            return False
        try:
            modifiers, key = split_spec(spec)
        except HotkeyError:
            return False
        name = keysym_name(key)
        if name is None:
            return False
        keysym = self._lib.XStringToKeysym(name.encode("ascii"))
        if not keysym:
            return False
        keycode = int(self._lib.XKeysymToKeycode(self._display, keysym))
        if not keycode:
            return False
        mask = x11_modifier_mask(modifiers)
        lock = _X11_LOCK_MASK
        numlock = _X11_NUMLOCK_MASK
        self._error_code = 0
        attempted = [(keycode, mask | extra) for extra in (0, lock, numlock, lock | numlock)]
        for key_code, combo in attempted:
            self._lib.XGrabKey(
                self._display, key_code, combo, self._root, False,
                _X11_GRAB_MODE_ASYNC, _X11_GRAB_MODE_ASYNC,
            )
        self._lib.XSync(self._display, False)
        if self._error_code:
            # Someone else owns this combination (BadAccess == 10); undo the
            # variants so the key keeps reaching whoever owns it.
            for key_code, combo in attempted:
                try:
                    self._lib.XUngrabKey(self._display, key_code, combo, self._root)
                except Exception:  # noqa: BLE001
                    pass
            self._lib.XSync(self._display, False)
            self._bindings.pop((keycode, mask), None)
            return False
        self._grabbed.extend(attempted)
        self._bindings[(keycode, mask)] = action
        self._ensure_timer()
        return True

    def _ensure_timer(self) -> None:
        if self._timer is not None:
            return
        self._timer = QTimer()
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._pump)
        self._timer.start()

    def _pump(self) -> None:
        if not self.available:
            return
        while self._lib.XPending(self._display):
            event = _XEvent()
            self._lib.XNextEvent(self._display, ctypes.byref(event))
            if event.type != _X11_KEY_PRESS:
                continue
            key = event.xkey
            state = int(key.state) & ~(_X11_LOCK_MASK | _X11_NUMLOCK_MASK)
            action = self._bindings.get((int(key.keycode), state))
            if action:
                self._on_trigger(action)

    def ungrab_all(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        if self.available:
            for keycode, mask in self._grabbed:
                try:
                    self._lib.XUngrabKey(self._display, keycode, mask, self._root)
                except Exception:  # noqa: BLE001
                    pass
            self._lib.XSync(self._display, False)
        self._grabbed.clear()
        self._bindings.clear()

    def close(self) -> None:
        self.ungrab_all()
        if self.available:
            if self._previous_handler:
                try:
                    self._lib.XSetErrorHandler(
                        ctypes.cast(self._previous_handler, self._handler_type)
                    )
                except Exception:  # noqa: BLE001
                    pass
            try:
                self._lib.XCloseDisplay(self._display)
            except Exception:  # noqa: BLE001
                pass
        self._display = None
        self._lib = None


# --------------------------------------------------------------------------- #
# manager
# --------------------------------------------------------------------------- #


class GlobalHotkeyManager(QObject, QAbstractNativeEventFilter):
    """Registers system-wide hotkeys; emits ``triggered(action)``.

    ``backend_state()`` tells the UI which mechanism is active:
    ``"windows"``, ``"x11"``, ``"portal"`` (waiting for the desktop to
    confirm), ``"portal-ready"``, or ``"focus"`` (window-local fallback).
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
        self._x11: X11Grabber | None = None
        self._portal: Any = None
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

        # Every non-Windows platform keeps focus-local shortcuts as a safety
        # net; on Linux a system-wide backend is layered on top when possible.
        failures = []
        for action, spec in hotkeys.items():
            if not spec:
                continue
            if not self._register_shortcut(action, spec):
                failures.append(action)
        if IS_LINUX:
            self._register_linux_backend(hotkeys)
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

    # -- Linux backends ---------------------------------------------------- #

    def _register_linux_backend(self, hotkeys: dict[str, str]) -> None:
        if self._is_wayland():
            self._register_portal_backend(hotkeys)
        else:
            self._register_x11_backend(hotkeys)

    @staticmethod
    def _is_wayland() -> bool:
        if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
            return True
        try:
            return QGuiApplication.platformName().startswith("wayland")
        except Exception:  # noqa: BLE001 - no GUI application yet
            return False

    def _register_x11_backend(self, hotkeys: dict[str, str]) -> None:
        grabber = self._x11
        if grabber is None:
            grabber = X11Grabber(self.triggered.emit)
            self._x11 = grabber
        if not grabber.available:
            self._backend = "focus"
            self._backend_detail = "X11 display unavailable"
            return
        grabbed = 0
        for action, spec in hotkeys.items():
            if spec and grabber.grab(action, spec):
                grabbed += 1
        self._backend = "x11" if grabbed else "focus"
        self._backend_detail = "" if grabbed else "no combination could be grabbed"
        self.backend_changed.emit(self._backend)

    def _register_portal_backend(self, hotkeys: dict[str, str]) -> None:
        from . import portal

        specs = []
        for action, spec in sorted(hotkeys.items()):
            trigger = portal_trigger(spec) if spec else None
            if trigger:
                specs.append((action, action.replace("_", " "), trigger))
        if not specs:
            self._backend = "focus"
            return
        if self._portal is None:
            self._portal = portal.PortalClient(self)
            self._portal.shortcut_activated.connect(self.triggered.emit)
            self._portal.shortcuts_bound.connect(self._on_shortcuts_bound)
        try:
            self._portal.bind_shortcuts(specs)
        except portal.PortalError as exc:
            self._backend = "focus"
            app_id = portal.portal_hotkey_app_id()
            if app_id is None and "app id" in str(exc).lower():
                self._backend_detail = (
                    "the desktop only grants global shortcuts to apps launched "
                    "from its application menu (desktop file), not from a terminal"
                )
            else:
                self._backend_detail = str(exc)
            self.backend_changed.emit(self._backend)
            return
        self._backend = "portal"
        self._backend_detail = ""
        self.backend_changed.emit(self._backend)

    def _on_shortcuts_bound(self, ok: bool, message: str) -> None:
        if ok:
            self._backend = "portal-ready"
        else:
            self._backend = "focus"
            self._backend_detail = message
        self.backend_changed.emit(self._backend)

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
        if self._x11 is not None:
            self._x11.close()
            self._x11 = None
        if self._portal is not None:
            try:
                self._portal.close()
            except Exception:  # noqa: BLE001
                pass
            self._portal = None

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
