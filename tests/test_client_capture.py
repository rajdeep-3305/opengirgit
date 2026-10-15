"""Capture backends and the frozen region selector (skipped without PySide6)."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opengirgit import capture  # noqa: E402
from PySide6.QtCore import QPoint, QPointF, QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def _background(width: int, height: int, color: QColor | None = None) -> QPixmap:
    pixmap = QPixmap(width, height)
    pixmap.fill(color if color is not None else QColor(40, 40, 40))
    return pixmap


# -- frozen selector -------------------------------------------------------- #


def test_constructor_derives_background_scale(qt_app):
    probe = capture.RegionSelector(decoy=False)
    screen = probe.geometry()
    probe.close()

    pixmap = _background(screen.width() * 2, screen.height() * 2)
    selector = capture.RegionSelector(decoy=False, background=pixmap)
    assert selector._background_scale_x == pytest.approx(2.0)  # noqa: SLF001
    assert selector._background_scale_y == pytest.approx(2.0)  # noqa: SLF001
    selector.close()


def test_null_background_is_treated_as_absent(qt_app):
    selector = capture.RegionSelector(decoy=False, background=QPixmap())
    assert selector._background is None  # noqa: SLF001
    selector.close()


def test_background_source_maps_widget_coords_to_pixels(qt_app):
    selector = capture.RegionSelector(decoy=False, background=_background(400, 320))
    selector._background_origin = QPoint(0, 0)  # noqa: SLF001
    selector._background_scale_x = 2.0  # noqa: SLF001
    selector._background_scale_y = 2.0  # noqa: SLF001
    selector.setGeometry(QRect(10, 20, 200, 160))
    selector._origin = QPoint(5, 5)  # noqa: SLF001
    selector._current = QPoint(25, 25)  # noqa: SLF001

    selection = selector._selection_rect()  # noqa: SLF001
    assert selection == QRect(5, 5, 21, 21)
    # widget (10,20) + (5,5) = logical (15,25) -> pixel (30,50); 21px * 2 = 42
    assert selector._background_source(selection) == QRect(30, 50, 42, 42)  # noqa: SLF001
    selector.close()


def test_capture_selection_crops_the_background(qt_app):
    color = QColor(10, 200, 30)
    selector = capture.RegionSelector(decoy=False, background=_background(1600, 1600, color))
    selector._background_origin = QPoint(0, 0)  # noqa: SLF001
    selector._background_scale_x = 2.0  # noqa: SLF001
    selector._background_scale_y = 2.0  # noqa: SLF001
    selector._origin = QPoint(50, 40)  # noqa: SLF001
    selector._current = QPoint(150, 140)  # noqa: SLF001

    pixmap = selector.capture_selection()
    assert pixmap is not None
    assert (pixmap.width(), pixmap.height()) == (202, 202)
    assert pixmap.toImage().pixelColor(100, 100) == color
    selector.close()


def test_capture_selection_without_background_grabs_the_screen(qt_app):
    selector = capture.RegionSelector(decoy=False)
    selector._origin = QPoint(5, 5)  # noqa: SLF001
    selector._current = QPoint(45, 35)  # noqa: SLF001
    pixmap = selector.capture_selection()
    assert pixmap is not None
    assert (pixmap.width(), pixmap.height()) == (41, 31)
    selector.close()


def test_capture_selection_is_none_before_any_drag(qt_app):
    selector = capture.RegionSelector(decoy=False, background=_background(40, 30))
    assert selector.capture_selection() is None
    selector.close()


class _MouseEvent:
    """Minimal stand-in for a QMouseEvent on the selector."""

    def __init__(self, x: int, y: int) -> None:
        self._point = QPointF(x, y)

    def position(self) -> QPointF:
        return self._point

    def button(self) -> Qt.MouseButton:
        return Qt.LeftButton


def test_emitted_rectangle_captures_after_the_drag_state_is_cleared(qt_app):
    """The selector clears its drag before emitting; the rect must still work."""
    color = QColor(1, 2, 3)
    selector = capture.RegionSelector(decoy=False, background=_background(1600, 1600, color))
    selector._background_origin = QPoint(0, 0)  # noqa: SLF001
    selector._background_scale_x = 2.0  # noqa: SLF001
    selector._background_scale_y = 2.0  # noqa: SLF001

    received: list[QRect] = []
    selector.region_selected.connect(received.append)

    selector.mousePressEvent(_MouseEvent(50, 40))
    selector.mouseMoveEvent(_MouseEvent(150, 140))
    selector.mouseReleaseEvent(_MouseEvent(150, 140))

    assert received == [QRect(50, 40, 101, 101)]
    assert selector.capture_selection() is None  # drag state is cleared
    pixmap = selector.capture_selection(received[0])
    assert pixmap is not None
    assert (pixmap.width(), pixmap.height()) == (202, 202)
    assert pixmap.toImage().pixelColor(100, 100) == color


# -- pre-capture backends --------------------------------------------------- #


def test_portal_capture_needed_follows_the_session_type(qt_app, monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    assert capture.portal_capture_needed() is True
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    assert capture.portal_capture_needed() is False  # offscreen platform plugin


def test_desktop_pixmap_prefers_the_portal_on_wayland(qt_app, monkeypatch):
    sentinel = _background(20, 10)
    monkeypatch.setattr(capture, "portal_capture_needed", lambda: True)
    monkeypatch.setattr(capture, "portal_screenshot", lambda: sentinel)
    assert capture.desktop_pixmap() is sentinel
    assert capture.last_capture_error() == ""


def test_desktop_pixmap_falls_back_to_a_native_grab(qt_app, monkeypatch):
    monkeypatch.setattr(capture, "portal_capture_needed", lambda: True)
    monkeypatch.setattr(capture, "portal_screenshot", lambda: None)
    monkeypatch.setattr(capture, "grab_screen_region", lambda rect, screen=None: QPixmap(8, 6))
    pixmap = capture.desktop_pixmap()
    assert pixmap is not None and not pixmap.isNull()
    assert capture.last_capture_error() == ""


def test_native_fallback_grabs_the_virtual_desktop(qt_app, monkeypatch):
    """The native fallback must match the portal's frame of reference."""
    from PySide6.QtGui import QGuiApplication

    screen = QGuiApplication.primaryScreen()
    assert screen is not None
    rects: list[QRect] = []

    def fake_grab(rect, target=None):
        rects.append(QRect(rect))
        return QPixmap(8, 6)

    monkeypatch.setattr(capture, "portal_capture_needed", lambda: True)
    monkeypatch.setattr(capture, "portal_screenshot", lambda: None)
    monkeypatch.setattr(capture, "grab_screen_region", fake_grab)
    capture.desktop_pixmap()
    assert rects == [screen.virtualGeometry()]


def test_desktop_pixmap_reports_when_both_backends_fail(qt_app, monkeypatch):
    monkeypatch.setattr(capture, "portal_capture_needed", lambda: True)
    monkeypatch.setattr(capture, "portal_screenshot", lambda: None)
    monkeypatch.setattr(capture, "grab_screen_region", lambda rect, screen=None: QPixmap())
    assert capture.desktop_pixmap() is None
    assert capture.last_capture_error()


def test_portal_screenshot_reports_portal_errors(qt_app, monkeypatch):
    from opengirgit import portal

    class Broken:
        def screenshot(self, timeout_ms=15000, keep_file=False):
            raise portal.PortalError("the Screenshot portal is not available")

    monkeypatch.setattr(portal, "PortalClient", Broken)
    assert capture.portal_screenshot() is None
    assert "not available" in capture.last_capture_error()
