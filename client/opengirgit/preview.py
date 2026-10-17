"""Streaming preview: a small popup that teases the answer while collapsed.

While the answer panel is collapsed and a completion is streaming, this
popup floats above (or below) the overlay bar and shows the tail of the
incoming text — the same affordance the original app has. It is a
``Qt.ToolTip``-style window: it never takes focus, never eats a click, is
excluded from screen capture on Windows like the rest of the overlay, and
fades/slides in and out.
"""

from __future__ import annotations

import re

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from . import stealth
from .i18n import tr

#: How much of the stream tail the popup keeps (bounds the popup height).
PREVIEW_CHARS = 360
FADE_MS = 160
SLIDE_PX = 8
LINGER_MS = 1400
_OPAQUE = 0.95

_STYLESHEET = """
QFrame#preview_root { background-color: rgba(18, 18, 18, 235);
                      border: 1px solid rgba(255,255,255,90); border-radius: 8px; }
QLabel#preview_title { color: #9ad0ff; font-size: 10px; letter-spacing: 0.6px; }
QLabel#preview_text { color: #f2f2f2; font-size: 12px; }
"""

_HEADING = re.compile(r"(?m)^#{1,6}\s*")
_FENCE = re.compile(r"(?m)^\s*```.*$")


def clean_preview_text(text: str) -> str:
    """Flatten markdown to a one-glance teaser (tail of the stream)."""
    text = _FENCE.sub("", text or "")
    text = _HEADING.sub("", text)
    text = text.replace("**", "").replace("`", "")
    lines = [line.strip() for line in text.splitlines()]
    text = "\n".join(line for line in lines if line)
    if len(text) > PREVIEW_CHARS:
        text = "…" + text[-PREVIEW_CHARS:].lstrip()
    return text


class StreamPreview(QWidget):
    """Frameless popup with the streaming answer tail; hidden by default."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.ToolTip
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setWindowFlag(Qt.WindowTransparentForInput, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setStyleSheet(_STYLESHEET)

        frame = QFrame(self)
        frame.setObjectName("preview_root")
        frame.setMaximumWidth(560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(frame)

        inner = QVBoxLayout(frame)
        inner.setContentsMargins(10, 7, 10, 8)
        inner.setSpacing(3)
        self._title = QLabel(tr("Answer"), frame)
        self._title.setObjectName("preview_title")
        self._text = QLabel("", frame)
        self._text.setObjectName("preview_text")
        self._text.setWordWrap(True)
        self._text.setMaximumWidth(520)
        inner.addWidget(self._title)
        inner.addWidget(self._text)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(lambda: self._fade(0.0, hide_after=True))

        self._fade_animation: QPropertyAnimation | None = None
        self._slide_animation: QPropertyAnimation | None = None
        self._target_opacity = 0.0

    # -- content ------------------------------------------------------------- #

    def text(self) -> str:
        """The teaser currently shown (cleaned, tail-truncated)."""
        return self._text.text()

    def update_text(self, payload: str) -> None:
        self._text.setText(clean_preview_text(payload))
        self.adjustSize()

    # -- lifecycle ----------------------------------------------------------- #

    def show_near(self, anchor: QWidget, payload: str) -> None:
        """Show or refresh the popup near ``anchor`` with the stream tail."""
        self.update_text(payload)
        self._reposition(anchor)
        if not self._text.text().strip():
            return
        self._hide_timer.stop()
        if self.isVisible():
            if self._target_opacity < _OPAQUE:  # an earlier fade-out was in flight
                self._fade(_OPAQUE)
            return
        target = self.pos()
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self.move(target.x(), target.y() + SLIDE_PX)
        self._animate_slide(target)
        self._fade(_OPAQUE)

    def hide_soon(self) -> None:
        """Linger briefly, then fade out (used when a stream ends)."""
        if self.isVisible():
            self._hide_timer.start(LINGER_MS)

    def hide_now(self, *, immediate: bool = False) -> None:
        self._hide_timer.stop()
        if not self.isVisible():
            return
        if immediate:
            self._stop_animations()
            self.hide()
        else:
            self._fade(0.0, hide_after=True)

    def reposition(self, anchor: QWidget) -> None:
        """Follow the bar while it is dragged (no content or fade changes)."""
        if self.isVisible():
            self._reposition(anchor)

    def showEvent(self, event) -> None:  # noqa: D102
        super().showEvent(event)
        stealth.apply_stealth(self)

    # -- internals ----------------------------------------------------------- #

    def _reposition(self, anchor: QWidget) -> None:
        geo = anchor.frameGeometry()
        self.adjustSize()
        width, height = self.width(), self.height()
        screen = QGuiApplication.screenAt(geo.center()) or QGuiApplication.primaryScreen()
        x = geo.center().x() - width // 2
        y = geo.top() - height - 8
        if screen is not None:
            area = screen.availableGeometry()
            if y < area.top() + 4:
                y = geo.bottom() + 8  # no room above: drop below the bar
            x = min(max(x, area.left() + 8), max(area.left() + 8, area.right() - width - 8))
            y = min(max(y, area.top() + 4), max(area.top() + 4, area.bottom() - height - 4))
        self.move(x, y)

    def _stop_animations(self) -> None:
        for animation in (self._fade_animation, self._slide_animation):
            if animation is not None:
                animation.stop()

    def _fade(self, target: float, *, hide_after: bool = False) -> None:
        self._target_opacity = target
        if self._fade_animation is not None:
            self._fade_animation.stop()
        animation = QPropertyAnimation(self, b"windowOpacity", self)
        animation.setDuration(FADE_MS)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        animation.setStartValue(self.windowOpacity())
        animation.setEndValue(target)
        if hide_after:
            animation.finished.connect(self._on_fade_finished)
        self._fade_animation = animation
        animation.start()

    def _on_fade_finished(self) -> None:
        # Guard: a fade-out that was stopped/replaced must not hide the popup.
        if self._target_opacity <= 0.01:
            self.hide()

    def _animate_slide(self, target: QPoint) -> None:
        if self._slide_animation is not None:
            self._slide_animation.stop()
        animation = QPropertyAnimation(self, b"pos", self)
        animation.setDuration(FADE_MS + 60)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        animation.setStartValue(self.pos())
        animation.setEndValue(target)
        self._slide_animation = animation
        animation.start()
