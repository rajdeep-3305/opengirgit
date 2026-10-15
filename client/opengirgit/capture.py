"""Screen-region selection and JPEG encoding for vision requests.

Two capture flows:

* **Live** (Windows): the selector overlay is transparent and the region is
  grabbed from the screen after the drag.  Windows excludes the overlay from
  captures (``stealth``), so the grab is clean.
* **Frozen** (Linux, macOS): the screen is captured *before* the selector
  opens and the selection simply crops that image.  This is required on
  Wayland (``QScreen.grabWindow`` returns a null pixmap there, capture goes
  through the portal) and avoids grabbing the dimming overlay on X11.
"""

from __future__ import annotations

import base64
import os

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

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        decoy: bool = True,
        background: QPixmap | None = None,
    ) -> None:
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

        # Frozen mode: ``background`` is a pre-capture of the screen (portal
        # capture on Wayland, an early grab elsewhere) that the selection is
        # cut out of.  ``background_origin``/``background_scale`` map widget
        # (logical) coordinates onto its pixels.
        self._background = background if background is not None and not background.isNull() else None
        self._background_origin = QPoint(0, 0)
        self._background_scale_x = 1.0
        self._background_scale_y = 1.0
        if self._background is not None:
            virtual = screen.virtualGeometry() if screen is not None else QRect()
            if virtual.width() > 0 and virtual.height() > 0:
                self._background_origin = virtual.topLeft()
                self._background_scale_x = self._background.width() / virtual.width()
                self._background_scale_y = self._background.height() / virtual.height()

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
            if self._background is not None:
                # Frozen mode: reveal the pre-captured screen under the
                # selection instead of clearing the translucent overlay.
                painter.drawPixmap(selection, self._background, self._background_source(selection))
            else:
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

    def _background_source(self, selection: QRect) -> QRect:
        """Map a widget-space selection onto *background* pixels."""
        origin = self.geometry().topLeft()
        logical_x = selection.x() + origin.x() - self._background_origin.x()
        logical_y = selection.y() + origin.y() - self._background_origin.y()
        scale_x = self._background_scale_x
        scale_y = self._background_scale_y
        left = round(logical_x * scale_x)
        top = round(logical_y * scale_y)
        right = round((logical_x + selection.width()) * scale_x)
        bottom = round((logical_y + selection.height()) * scale_y)
        return QRect(left, top, max(1, right - left), max(1, bottom - top))

    def capture_selection(self, selection: QRect | None = None) -> QPixmap | None:
        """The pixmap for *selection* (default: the current drag).

        Frozen mode crops the pre-captured background; live mode grabs the
        screen.  ``region_selected`` carries the rectangle because the selector
        clears its drag state before the signal is delivered.  Call before the
        selector is destroyed.
        """
        if selection is None:
            selection = self._selection_rect()
        if selection is None or selection.isNull() or self._screen is None:
            return None
        if self._background is not None:
            pixmap = self._background.copy(self._background_source(selection))
            return pixmap if not pixmap.isNull() else None
        pixmap = grab_screen_region(selection, self._screen)
        return pixmap if not pixmap.isNull() else None

    def selected_pixmap(self) -> QPixmap | None:
        """Grab the current selection from the screen (used by tests/headless)."""
        return self.capture_selection()


def grab_screen_region(rect: QRect, screen=None) -> QPixmap:
    """Grab a global-coordinate rectangle from its screen."""
    screen = screen or QGuiApplication.primaryScreen()
    if screen is None:
        return QPixmap()
    origin = screen.geometry().topLeft()
    local = rect.translated(-origin.x(), -origin.y())
    return screen.grabWindow(0, local.x(), local.y(), local.width(), local.height())


#: Reason the last :func:`desktop_pixmap` call failed, for status messages.
_last_capture_error = ""


def last_capture_error() -> str:
    """Why the last :func:`desktop_pixmap` returned ``None`` ("" when it worked)."""
    return _last_capture_error


def portal_capture_needed() -> bool:
    """True when the native screen grab is not usable (Wayland sessions)."""
    if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
        return True
    try:
        return QGuiApplication.platformName().startswith("wayland")
    except Exception:  # noqa: BLE001 - no GUI application
        return False


def portal_screenshot() -> QPixmap | None:
    """Whole-desktop grab through the xdg-desktop-portal ("" on failure)."""
    global _last_capture_error
    from . import portal

    try:
        pixmap = portal.PortalClient().screenshot()
    except portal.PortalError as exc:
        _last_capture_error = str(exc)
        return None
    except Exception as exc:  # noqa: BLE001 - D-Bus surprises are not fatal
        _last_capture_error = str(exc)
        return None
    if pixmap is None or pixmap.isNull():
        _last_capture_error = "the portal returned no image"
        return None
    return pixmap


def desktop_pixmap() -> QPixmap | None:
    """Pre-capture the whole screen for the frozen selector flow.

    Prefers the portal on Wayland (the only thing that works there) and falls
    back to a native grab, e.g. on X11 without a portal.
    """
    global _last_capture_error
    _last_capture_error = ""
    screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
    if screen is None:
        _last_capture_error = "no screen found"
        return None
    if portal_capture_needed():
        pixmap = portal_screenshot()
        if pixmap is not None:
            return pixmap
    # Native fallback: grab the whole virtual desktop, matching the portal's
    # frame of reference (the selector maps this against virtualGeometry()).
    virtual = screen.virtualGeometry()
    if virtual.width() > 0 and virtual.height() > 0:
        pixmap = grab_screen_region(virtual, screen)
    else:
        pixmap = grab_screen_region(screen.geometry(), screen)
    if pixmap.isNull():
        if not _last_capture_error:
            _last_capture_error = "screen capture is not supported by this display server"
        return None
    _last_capture_error = ""
    return pixmap


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
