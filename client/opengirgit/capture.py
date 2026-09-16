"""Screen-region selection and JPEG encoding for vision requests."""

from __future__ import annotations

import base64

from PySide6.QtCore import QBuffer, QRect, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from . import stealth

MIN_SELECTION = 8  # px; smaller drags are treated as accidental clicks


class RegionSelector(QWidget):
    """Full-screen crosshair overlay; emits the selected global QRect."""

    region_selected = Signal(QRect)
    selection_cancelled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        flags = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        super().__init__(parent, flags)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)

        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        self._screen = screen
        if screen is not None:
            self.setGeometry(screen.geometry())

        self._origin = None
        self._current = None
        self._finished = False

    # -- window hooks ------------------------------------------------------ #

    def showEvent(self, event) -> None:  # noqa: D102
        super().showEvent(event)
        stealth.apply_stealth(self)

    def keyPressEvent(self, event) -> None:  # noqa: D102
        if event.key() == Qt.Key_Escape:
            self._finished = True
            self.selection_cancelled.emit()
            self.close()
        else:
            super().keyPressEvent(event)

    # -- painting ---------------------------------------------------------- #

    def paintEvent(self, event) -> None:  # noqa: D102
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 130))

        selection = self._selection_rect()
        if selection is not None and not selection.isNull():
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
            painter.fillRect(selection, Qt.transparent)
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            painter.setPen(QPen(QColor(0, 200, 255), 2))
            painter.drawRect(selection.adjusted(1, 1, -1, -1))

            painter.setPen(QColor(255, 255, 255))
            label = f"{selection.width()} x {selection.height()}"
            anchor = selection.topLeft()
            painter.drawText(anchor.x(), max(anchor.y() - 6, 12), label)

    # -- mouse ------------------------------------------------------------- #

    def mousePressEvent(self, event) -> None:  # noqa: D102
        if event.button() == Qt.LeftButton:
            self._origin = event.position().toPoint()
            self._current = self._origin
            self.update()
        elif event.button() == Qt.RightButton:
            self._finished = True
            self.selection_cancelled.emit()
            self.close()

    def mouseMoveEvent(self, event) -> None:  # noqa: D102
        if self._origin is not None:
            self._current = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: D102
        if event.button() != Qt.LeftButton or self._origin is None:
            return
        selection = self._selection_rect()
        self._origin = None
        self._current = None
        if selection is None or selection.width() < MIN_SELECTION or selection.height() < MIN_SELECTION:
            self._finished = True
            self.selection_cancelled.emit()
            self.close()
            return
        self._finished = True
        self.region_selected.emit(selection)
        self.close()

    def closeEvent(self, event) -> None:  # noqa: D102
        if not self._finished:
            self.selection_cancelled.emit()
        super().closeEvent(event)

    # -- helpers ----------------------------------------------------------- #

    def _selection_rect(self) -> QRect | None:
        if self._origin is None or self._current is None:
            return None
        return QRect(self._origin, self._current).normalized()

    def selected_pixmap(self) -> QPixmap | None:
        """Grab the current selection from the screen (used by tests/headless)."""
        selection = self._selection_rect()
        if selection is None or self._screen is None:
            return None
        return grab_screen_region(selection, self._screen)


def grab_screen_region(rect: QRect, screen=None) -> QPixmap:
    """Grab a global-coordinate rectangle from its screen."""
    screen = screen or QGuiApplication.primaryScreen()
    if screen is None:
        return QPixmap()
    origin = screen.geometry().topLeft()
    local = rect.translated(-origin.x(), -origin.y())
    return screen.grabWindow(0, local.x(), local.y(), local.width(), local.height())


def pixmap_to_jpeg_b64(pixmap: QPixmap, quality: int = 85) -> str:
    """Encode a pixmap as base64 JPEG (no ``data:`` prefix)."""
    if pixmap.isNull():
        return ""
    buffer = QBuffer()  # uses its own internal QByteArray
    buffer.open(QBuffer.WriteOnly)
    try:
        if not pixmap.save(buffer, "JPEG", quality):
            return ""
        data = bytes(buffer.data())
    finally:
        buffer.close()
    return base64.b64encode(data).decode("ascii")
