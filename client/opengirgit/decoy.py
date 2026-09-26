"""Decoy cursor for region selection (screen-share stealth).

While the operator drags a selection rectangle, the real system cursor is
blanked on the selection overlay and this module renders a stand-in cursor
*frozen at the anchor* (the button the user pressed). Screen-capture viewers
therefore see an ordinary, unmoving pointer instead of a crosshair hunting for
a region; when the selection ends the real cursor is glided back to the anchor.

On Windows the stand-in is an exact copy of the current system cursor (same
bitmap, size and hotspot) read via ``GetCursorInfo`` → ``GetIconInfo`` →
``GetDIBits``. Everywhere else — or if anything about that fails — a small
drawn arrow is used.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import (
    QColor,
    QCursor,
    QGuiApplication,
    QImage,
    QPainter,
    QPen,
    QPixmap,
    QPolygon,
)
from PySide6.QtWidgets import QWidget

CURSOR_SHOWING = 0x0001
FALLBACK_WIDTH = 12
FALLBACK_HEIGHT = 19


# --------------------------------------------------------------------------- #
# System cursor grab (Windows)
# --------------------------------------------------------------------------- #


class _CURSORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hCursor", wintypes.HANDLE),
        ("pt", wintypes.POINT),
    ]


class _ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL),
        ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD),
        ("hbmMask", wintypes.HBITMAP),
        ("hbmColor", wintypes.HBITMAP),
    ]


class _BITMAP(ctypes.Structure):
    _fields_ = [
        ("bmType", wintypes.LONG),
        ("bmWidth", wintypes.LONG),
        ("bmHeight", wintypes.LONG),
        ("bmWidthBytes", wintypes.LONG),
        ("bmPlanes", wintypes.WORD),
        ("bmBitsPixel", wintypes.WORD),
        ("bmBits", ctypes.c_void_p),
    ]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


def _grab_system_cursor_windows() -> tuple[QImage, int, int] | None:
    """Read the current cursor's 32-bit bitmap; None on any failure."""
    if sys.platform != "win32":  # pragma: no cover - windows only
        return None
    try:  # pragma: no cover - windows only
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        info = _CURSORINFO()
        info.cbSize = ctypes.sizeof(_CURSORINFO)
        if not user32.GetCursorInfo(ctypes.byref(info)):
            return None
        if not (info.flags & CURSOR_SHOWING) or not info.hCursor:
            return None

        icon = _ICONINFO()
        if not user32.GetIconInfo(info.hCursor, ctypes.byref(icon)):
            return None
        try:
            bitmap = icon.hbmColor or icon.hbmMask
            if not bitmap:
                return None
            header = _BITMAP()
            if not gdi32.GetObjectW(bitmap, ctypes.sizeof(_BITMAP), ctypes.byref(header)):
                return None
            width = int(header.bmWidth)
            height = abs(int(header.bmHeight))
            if width <= 0 or height <= 0 or width > 256 or height > 256:
                return None
            if not icon.hbmColor:
                return None  # legacy monochrome cursor: use the drawn arrow

            hdc = user32.GetDC(None)
            if not hdc:
                return None
            try:
                pixel_header = _BITMAPINFOHEADER()
                pixel_header.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
                pixel_header.biWidth = width
                pixel_header.biHeight = -height  # top-down rows
                pixel_header.biPlanes = 1
                pixel_header.biBitCount = 32
                pixel_header.biCompression = 0  # BI_RGB
                pixel_info = _BITMAPINFO()
                pixel_info.bmiHeader = pixel_header

                buffer = ctypes.create_string_buffer(width * height * 4)
                lines = gdi32.GetDIBits(
                    hdc, bitmap, 0, height, buffer, ctypes.byref(pixel_info), 0
                )
                if lines != height:
                    return None
                image = QImage(
                    bytes(buffer), width, height, width * 4, QImage.Format_ARGB32
                ).copy()  # copy: detach from the temporary buffer
                return image, int(icon.xHotspot), int(icon.yHotspot)
            finally:
                user32.ReleaseDC(None, hdc)
        finally:
            if icon.hbmColor:
                gdi32.DeleteObject(icon.hbmColor)
            if icon.hbmMask:
                gdi32.DeleteObject(icon.hbmMask)
    except Exception:  # noqa: BLE001 - any GDI surprise falls back to the arrow
        return None


def _fallback_cursor_pixmap() -> QPixmap:
    """A small classic arrow, used off-Windows or when the grab fails."""
    pixmap = QPixmap(FALLBACK_WIDTH, FALLBACK_HEIGHT)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor(20, 20, 20), 1))
    painter.setBrush(QColor(255, 255, 255))
    painter.drawPolygon(
        QPolygon(
            [
                QPoint(0, 0),
                QPoint(0, 14),
                QPoint(3, 11),
                QPoint(5, 16),
                QPoint(8, 14),
                QPoint(6, 9),
                QPoint(10, 9),
            ]
        )
    )
    painter.end()
    return pixmap


def cursor_pixmap() -> tuple[QPixmap, QPoint]:
    """Return ``(pixmap, hotspot)`` for the current system cursor.

    The Windows path returns the real bitmap (hotspot in its pixels); the
    fallback returns a drawn arrow with a (0, 0) hotspot.
    """
    grabbed = _grab_system_cursor_windows()
    if grabbed is not None:
        image, hotspot_x, hotspot_y = grabbed
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        ratio = screen.devicePixelRatio() if screen is not None else 1.0
        image.setDevicePixelRatio(ratio)
        return QPixmap.fromImage(image), QPoint(round(hotspot_x / ratio), round(hotspot_y / ratio))
    return _fallback_cursor_pixmap(), QPoint(0, 0)


# --------------------------------------------------------------------------- #
# The stand-in widget
# --------------------------------------------------------------------------- #


class DummyCursor(QWidget):
    """A click-through cursor stand-in that *is* visible to screen capture.

    Deliberately not stealth-excluded (unlike the selection overlay), so
    capture sees an ordinary cursor parked at the anchor while the real one is
    blanked.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        flags = (
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowTransparentForInput
        )
        super().__init__(parent, flags)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self._pixmap: QPixmap | None = None
        self._hotspot = QPoint(0, 0)
        self.setFixedSize(FALLBACK_WIDTH, FALLBACK_HEIGHT)

    def show_at(self, global_pos: QPoint) -> None:
        """Grab the real cursor's look and park its hotspot on ``global_pos``."""
        pixmap, hotspot = cursor_pixmap()
        self._pixmap = pixmap
        self._hotspot = hotspot
        ratio = pixmap.devicePixelRatio() or 1.0
        self.setFixedSize(round(pixmap.width() / ratio), round(pixmap.height() / ratio))
        self.move(global_pos - hotspot)
        self.show()
        self.raise_()

    def paintEvent(self, event) -> None:  # noqa: D102
        painter = QPainter(self)
        if self._pixmap is not None and not self._pixmap.isNull():
            painter.drawPixmap(0, 0, self._pixmap)
        painter.end()
