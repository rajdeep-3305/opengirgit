"""Screen-region selection and JPEG encoding for vision requests."""

from __future__ import annotations

import base64

from PySide6.QtCore import QBuffer, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from . import decoy as decoy_mod
from . import stealth

MIN_SELECTION = 8  # px; smaller drags are treated as accidental clicks
GLIDE_STEPS = 10
GLIDE_INTERVAL_MS = 12


class RegionSelector(QWidget):
    """Full-screen crosshair overlay; emits the selected global QRect.

    With ``decoy=True`` (default) the real cursor is blanked while selecting
    and a stand-in copy stays parked at the anchor point, so screen-share
    viewers see a normal, motionless cursor; afterwards the real cursor is
    glided back to the anchor.
    """

    region_selected = Signal(QRect)
    selection_cancelled = Signal()

    def __init__(self, parent: QWidget | None = None, *, decoy: bool = True) -> None:
        flags = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        super().__init__(parent, flags)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._decoy_enabled = decoy
        self.setCursor(Qt.BlankCursor if decoy else Qt.CrossCursor)
        self.setMouseTracking(True)

        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        self._screen = screen
        if screen is not None:
            self.setGeometry(screen.geometry())

        self._origin = None
        self._current = None
        self._finished = False
        self._cursor_pos: QPoint | None = None
        self._anchor = QPoint(0, 0)
        self._dummy: decoy_mod.DummyCursor | None = None
        self._glide_timer: QTimer | None = None
        self._glide_step = 0

    # -- window hooks ------------------------------------------------------ #

    def showEvent(self, event) -> None:  # noqa: D102
        super().showEvent(event)
        stealth.apply_stealth(self)
        if self._decoy_enabled:
            self._anchor = QCursor.pos()
            self._cursor_pos = self.mapFromGlobal(self._anchor)
            if self._dummy is None:
                self._dummy = decoy_mod.DummyCursor()
            self._dummy.show_at(self._anchor)

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

        if self._decoy_enabled:
            self._draw_cursor_marker(painter)
        painter.end()

    def _draw_cursor_marker(self, painter: QPainter) -> None:
        """Crosshair drawn by hand: the real cursor is blanked in decoy mode."""
        center = self._cursor_pos
        if center is None:
            return
        arm, gap = 11, 4
        for color, width in ((QColor(0, 0, 0, 170), 3), (QColor(255, 255, 255), 1)):
            painter.setPen(QPen(color, width))
            painter.drawLine(center.x() - gap - arm, center.y(), center.x() - gap, center.y())
            painter.drawLine(center.x() + gap, center.y(), center.x() + gap + arm, center.y())
            painter.drawLine(center.x(), center.y() - gap - arm, center.x(), center.y() - gap)
            painter.drawLine(center.x(), center.y() + gap, center.x(), center.y() + gap + arm)
        painter.setPen(QPen(QColor(0, 120, 255), 2))
        painter.drawPoint(center)

    # -- mouse ------------------------------------------------------------- #

    def mousePressEvent(self, event) -> None:  # noqa: D102
        if event.button() == Qt.LeftButton:
            self._origin = event.position().toPoint()
            self._current = self._origin
            self._cursor_pos = self._origin
            self.update()
        elif event.button() == Qt.RightButton:
            self._finished = True
            self.selection_cancelled.emit()
            self.close()

    def mouseMoveEvent(self, event) -> None:  # noqa: D102
        self._cursor_pos = event.position().toPoint()
        if self._origin is not None:
            self._current = self._cursor_pos
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
        self._restore_cursor()
        super().closeEvent(event)

    # -- helpers ----------------------------------------------------------- #

    def _restore_cursor(self) -> None:
        """Hide the stand-in and glide the real cursor back to the anchor."""
        if self._dummy is not None:
            self._dummy.hide()
        if not self._decoy_enabled:
            return
        start = QCursor.pos()
        target = self._anchor
        if start == target:
            return
        timer = QTimer(self)
        timer.setInterval(GLIDE_INTERVAL_MS)
        self._glide_timer = timer
        self._glide_step = 0

        def tick() -> None:
            self._glide_step += 1
            ratio = min(1.0, self._glide_step / GLIDE_STEPS)
            pos = QPoint(
                round(start.x() + (target.x() - start.x()) * ratio),
                round(start.y() + (target.y() - start.y()) * ratio),
            )
            try:
                QCursor.setPos(pos)
            except Exception:  # noqa: BLE001 - not all platforms allow this
                timer.stop()
                return
            if self._glide_step >= GLIDE_STEPS:
                timer.stop()

        timer.timeout.connect(tick)
        timer.start()

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


def pixmap_from_b64(encoded: str) -> QPixmap:
    """Decode a base64 image (JPEG/PNG/…) into a QPixmap; null when invalid."""
    if not encoded:
        return QPixmap()
    try:
        raw = base64.b64decode(encoded)
    except ValueError:  # includes binascii.Error
        return QPixmap()
    pixmap = QPixmap()
    if not raw or not pixmap.loadFromData(raw):
        return QPixmap()
    return pixmap
