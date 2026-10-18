"""Windows "stealth" helpers: keep overlay windows out of screen shares.

Uses only documented Win32 calls:

* ``SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)`` — the window is
  omitted from ``BitBlt``-style capture used by Zoom/Meet/Teams/OBS. On Windows
  builds older than 19041 the flag degrades to ``WDA_MONITOR`` (a black box).
* ``WS_EX_TOOLWINDOW`` (and clearing ``WS_EX_APPWINDOW``) — removes the window
  from the taskbar and Alt-Tab.
* optionally ``WS_EX_TRANSPARENT | WS_EX_LAYERED`` — click-through; off
  Windows the same toggle falls back to Qt's ``WindowTransparentForInput``
  flag (development only).

The capture/taskbar helpers are no-ops on non-Windows platforms; the
click-through toggle has the portable fallback above.
"""

from __future__ import annotations

import ctypes
import sys
from typing import Any

IS_WINDOWS = sys.platform == "win32"

WDA_NONE = 0x00000000
WDA_MONITOR = 0x00000001
WDA_EXCLUDEFROMCAPTURE = 0x00000011

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000

_cached_build: int | None = None


def _user32() -> Any:  # pragma: no cover - windows only
    return ctypes.windll.user32


def get_windows_build() -> int:
    """Return the Windows build number (0 on non-Windows/failure)."""
    global _cached_build
    if _cached_build is not None:
        return _cached_build
    if not IS_WINDOWS:
        _cached_build = 0
        return 0
    try:  # pragma: no cover - windows only
        ntdll = ctypes.windll.ntdll
        version = ctypes.create_string_buffer(272)
        ntdll.RtlGetVersion(ctypes.byref(version))  # type: ignore[attr-defined]
        # RTL_OSVERSIONINFOEXW: dwMajorVersion(4) dwMinorVersion(4) dwBuildNumber(4)…
        build = int.from_bytes(version.raw[12:16], "little")
        _cached_build = build
    except Exception:
        _cached_build = 0
    return _cached_build


def exclude_from_capture(widget: Any) -> bool:
    """Hide a shown window from screen capture. Returns True on success."""
    if not IS_WINDOWS:
        return False
    try:  # pragma: no cover - windows only
        hwnd = int(widget.winId())
        ok = bool(_user32().SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE))
        if not ok:
            ok = bool(_user32().SetWindowDisplayAffinity(hwnd, WDA_MONITOR))
        return ok
    except Exception:
        return False


def apply_tool_window(widget: Any) -> None:
    """Hide from taskbar / Alt-Tab (``WS_EX_TOOLWINDOW``)."""
    if not IS_WINDOWS:
        return
    try:  # pragma: no cover - windows only
        user32 = _user32()
        hwnd = int(widget.winId())
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style = (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
    except Exception:
        pass


def set_click_through(widget: Any, enabled: bool) -> bool:
    """Let mouse events pass through the window when enabled.

    Windows flips ``WS_EX_TRANSPARENT | WS_EX_LAYERED`` on the native handle.
    Everywhere else (development on unsupported platforms) the portable
    ``Qt.WindowTransparentForInput`` flag is used; changing window flags hides
    the widget, so a visible window is re-shown right away.

    Returns ``True`` when the toggle was applied.
    """
    if IS_WINDOWS:
        try:  # pragma: no cover - windows only
            user32 = _user32()
            hwnd = int(widget.winId())
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if enabled:
                style |= WS_EX_TRANSPARENT | WS_EX_LAYERED
            else:
                style &= ~WS_EX_TRANSPARENT
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            return True
        except Exception:
            return False
    try:
        from PySide6.QtCore import Qt  # local import: keep this module Qt-free on Windows

        was_visible = bool(widget.isVisible())
        widget.setWindowFlag(Qt.WindowTransparentForInput, enabled)
        if was_visible:
            widget.show()  # flag changes hide the window; bring it straight back
        return True
    except Exception:
        return False


def apply_stealth(widget: Any) -> None:
    """Apply the full stealth treatment to a shown widget."""
    apply_tool_window(widget)
    exclude_from_capture(widget)


def capability_note() -> str:
    """Human-readable note about stealth support on this machine."""
    if not IS_WINDOWS:
        return "Capture exclusion is Windows-only; windows are visible in screen shares here."
    build = get_windows_build()
    if build and build < 19041:
        return (
            f"Windows build {build} < 19041: capture exclusion degrades to a black "
            "rectangle in screen shares."
        )
    return "Capture exclusion active (WDA_EXCLUDEFROMCAPTURE)."
