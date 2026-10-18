"""Small vector icons drawn with Qt (no platform emoji fonts required).

The toolbar uses simple, neutral line icons so the same glyphs render on every
Windows 11 machine, including systems without a colour-emoji font.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
_BRAND_SVG = ASSETS_DIR / "brand.svg"

PainterFn = Callable[[QPainter], None]


def _device_ratio() -> float:
    app = QGuiApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    return max(1.0, float(screen.devicePixelRatio())) if screen is not None else 1.0


def _canvas(size: int, draw: PainterFn) -> QPixmap:
    ratio = _device_ratio()
    pixmap = QPixmap(int(round(size * ratio)), int(round(size * ratio)))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.scale(ratio, ratio)
    painter.scale(size / 24.0, size / 24.0)
    draw(painter)
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def _stroke(painter: QPainter, width: float = 1.7) -> None:
    pen = QPen(QColor("#ffffff"), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)


def _logo(painter: QPainter) -> None:
    renderer = QSvgRenderer(str(_BRAND_SVG))
    if renderer.isValid():
        renderer.render(painter, QRectF(0, 0, 24, 24))
        return
    # Fallback: the same simple ring + G shape used by the brand mark.
    _stroke(painter, 1.8)
    painter.drawEllipse(QRectF(3, 3, 18, 18))
    painter.drawArc(QRectF(7, 7, 10, 10), 40 * 16, 290 * 16)


def _system_mic(painter: QPainter) -> None:
    _stroke(painter, 1.5)
    painter.drawRoundedRect(QRectF(4, 3, 11, 18), 1.5, 1.5)
    painter.drawLine(QPointF(7, 8), QPointF(11, 8))
    painter.drawLine(QPointF(7, 12), QPointF(10, 12))
    # Microphone capsule and stand.
    painter.drawRoundedRect(QRectF(15.5, 6, 3.2, 7), 1.6, 1.6)
    painter.drawArc(QRectF(13.8, 9, 6.6, 6.2), 200 * 16, 140 * 16)
    painter.drawLine(QPointF(17.1, 15.1), QPointF(17.1, 18.5))
    painter.drawLine(QPointF(14.8, 18.5), QPointF(19.4, 18.5))


def _eye_off(painter: QPainter) -> None:
    _stroke(painter, 1.5)
    path = QPainterPath(QPointF(3, 12))
    path.quadTo(QPointF(7.5, 6.5), QPointF(12, 6.5))
    path.quadTo(QPointF(16.5, 6.5), QPointF(21, 12))
    path.quadTo(QPointF(16.5, 17.5), QPointF(12, 17.5))
    path.quadTo(QPointF(7.5, 17.5), QPointF(3, 12))
    painter.drawPath(path)
    painter.drawEllipse(QRectF(9, 9, 6, 6))
    painter.drawLine(QPointF(4.5, 4.5), QPointF(19.5, 19.5))


def _circle(painter: QPainter) -> None:
    _stroke(painter, 1.7)
    painter.drawEllipse(QRectF(6, 6, 12, 12))


def _circle_filled(painter: QPainter) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#ffffff"))
    painter.drawEllipse(QRectF(6, 6, 12, 12))


def _close(painter: QPainter) -> None:
    _stroke(painter, 2.0)
    painter.drawLine(QPointF(6, 6), QPointF(18, 18))
    painter.drawLine(QPointF(18, 6), QPointF(6, 18))


def _analyze(painter: QPainter) -> None:
    _stroke(painter, 1.6)
    painter.drawPolyline(
        [
            QPointF(4, 9),
            QPointF(4, 4),
            QPointF(9, 4),
        ]
    )
    painter.drawPolyline(
        [
            QPointF(15, 4),
            QPointF(20, 4),
            QPointF(20, 9),
        ]
    )
    painter.drawPolyline(
        [
            QPointF(4, 15),
            QPointF(4, 20),
            QPointF(9, 20),
        ]
    )
    painter.drawLine(QPointF(15, 15), QPointF(21, 15))
    painter.drawLine(QPointF(18, 12), QPointF(18, 18))


def _send(painter: QPainter) -> None:
    _stroke(painter, 1.6)
    path = QPainterPath(QPointF(4, 4))
    path.lineTo(QPointF(21, 12))
    path.lineTo(QPointF(4, 20))
    path.lineTo(QPointF(8, 12))
    path.closeSubpath()
    painter.drawPath(path)
    painter.drawLine(QPointF(8, 12), QPointF(15, 12))


def _pencil(painter: QPainter) -> None:
    _stroke(painter, 1.5)
    path = QPainterPath(QPointF(4, 20))
    path.lineTo(QPointF(5.5, 14.5))
    path.lineTo(QPointF(15.5, 4.5))
    path.lineTo(QPointF(19.5, 8.5))
    path.lineTo(QPointF(9.5, 18.5))
    path.closeSubpath()
    painter.drawPath(path)
    painter.drawLine(QPointF(5.5, 14.5), QPointF(9.5, 18.5))
    painter.drawLine(QPointF(13.5, 6.5), QPointF(17.5, 10.5))


def _arrow_left(painter: QPainter) -> None:
    _stroke(painter, 1.6)
    painter.drawLine(QPointF(20, 12), QPointF(4.5, 12))
    painter.drawPolyline(
        [
            QPointF(10, 6.5),
            QPointF(4.5, 12),
            QPointF(10, 17.5),
        ]
    )


def _arrow_right(painter: QPainter) -> None:
    _stroke(painter, 1.6)
    painter.drawLine(QPointF(4, 12), QPointF(19.5, 12))
    painter.drawPolyline(
        [
            QPointF(14, 6.5),
            QPointF(19.5, 12),
            QPointF(14, 17.5),
        ]
    )


def _timer(painter: QPainter) -> None:
    _stroke(painter, 1.5)
    painter.drawEllipse(QRectF(4.5, 4.5, 15, 15))
    painter.drawLine(QPointF(12, 8), QPointF(12, 12.5))
    painter.drawLine(QPointF(12, 12.5), QPointF(15.5, 14.5))
    painter.drawLine(QPointF(10, 2.5), QPointF(14, 2.5))


_DRAWERS: dict[str, PainterFn] = {
    "logo": _logo,
    "system_mic": _system_mic,
    "eye_off": _eye_off,
    "circle": _circle,
    "circle_filled": _circle_filled,
    "close": _close,
    "analyze_screen": _analyze,
    "send": _send,
    "pencil": _pencil,
    "arrow_left": _arrow_left,
    "arrow_right": _arrow_right,
    "timer": _timer,
}


def pixmap(name: str, size: int = 20) -> QPixmap:
    """Return a crisp, transparent icon pixmap at ``size`` logical pixels."""
    return _canvas(size, _DRAWERS.get(name, _logo))


def icon(name: str, size: int = 20) -> QIcon:
    """Return an icon suitable for a ``QPushButton``."""
    return QIcon(pixmap(name, size))
