"""Toolbar icons, rendered from the original Material Symbols SVGs.

The overlay uses the same open-source Material Symbols glyphs, sizes and
optical alignment as the original control bar.  Rendering through
``QSvgRenderer`` keeps them crisp on high-DPI Windows displays; the brand mark
is the only OpenGirGit-specific image.
"""

from __future__ import annotations

import base64
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
_ICONS_DIR = ASSETS_DIR / "icons"
_BRAND_SVG = ASSETS_DIR / "brand.svg"

#: Stable names used by the overlay, mapped to the SVG files in ``assets/icons``.
_ICONS: dict[str, str] = {
    "logo": "brand",
    "system_mic": "system_mic",
    "eye_off": "hide",
    "hide": "hide",
    "timer": "timer",
    "circle": "opacity_decrease",
    "circle_filled": "opacity_increase",
    "close": "exit",
    "analyze_screen": "analyze_screen",
    "send": "send",
    "pencil": "erase",
    "erase": "erase",
    "arrow_left": "prev",
    "arrow_right": "next",
    "play": "play",
    "move": "move",
}


def _device_ratio() -> float:
    app = QGuiApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    return max(1.0, float(screen.devicePixelRatio())) if screen is not None else 1.0


def _path(name: str) -> Path:
    stem = _ICONS.get(name, name)
    if stem == "brand":
        return _BRAND_SVG
    return _ICONS_DIR / f"{stem}.svg"


def _render(path: Path, size: int) -> QPixmap:
    ratio = _device_ratio()
    pixmap = QPixmap(int(round(size * ratio)), int(round(size * ratio)))
    pixmap.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(str(path))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    if renderer.isValid():
        renderer.render(painter, QRectF(0, 0, size * ratio, size * ratio))
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def pixmap(name: str, size: int = 20) -> QPixmap:
    """Return a crisp, transparent icon pixmap at ``size`` logical pixels."""
    path = _path(name)
    if not path.is_file():
        path = _BRAND_SVG
    return _render(path, size)


def icon(name: str, size: int = 20) -> QIcon:
    """Return an icon suitable for a ``QPushButton``."""
    return QIcon(pixmap(name, size))


def data_uri(name: str) -> str:
    """A ``data:image/svg+xml;base64,...`` URI for the welcome table."""
    path = _path(name)
    if not path.is_file():
        path = _BRAND_SVG
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"
