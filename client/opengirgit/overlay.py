"""The overlay: a compact control bar plus a separate streaming answer window.

The layout mirrors the familiar interview-copilot shape: a fixed control bar
with device / timer / opacity controls, and an independent answer window that
can be resized from its bottom-right corner.  Both are frameless top-level
tool windows so they stay above the interview call and stay out of the
taskbar/Alt-Tab list.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPen,
    QRegion,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from . import render, stealth, ui_icons
from .api import ApiClient, ApiError
from .audio import list_devices
from .capture import pixmap_from_b64
from .config import AppSettings
from .preview import StreamPreview
from .prompts import rewrite_answer_prompt
from .stores import ConversationStore
from .workers import StreamWorker

STREAM_FLUSH_MS = 120
MOVE_STEP = 24
SCROLL_STEP = 80
OPACITY_STEP = 0.05
THUMBNAIL_HEIGHT = 56
MAX_CAPTURES = 5  # the server accepts at most 5 images per vision request
WEB_FLUSH_INTERVAL = 0.35  # seconds; throttles web-view renders while streaming
FADE_IN_MS = 220  # startup fade duration
_WIDGET_SIZE_MAX = 16777215

# Original-shaped geometry.  The control bar is a fixed, compact strip; the
# answer window floats underneath it and can be resized independently.
BAR_WIDTH = 700
BAR_HEIGHT = 107
RESPONSE_WIDTH = 700
RESPONSE_HEIGHT = 500
RESPONSE_MIN_WIDTH = 250
RESPONSE_MIN_HEIGHT = 250
RESPONSE_GAP = 4
COLLAPSED_SIZE = 48
THUMB_ROW_HEIGHT = 72
BORDER_RADIUS = 8

CODE_LANGUAGES = [
    "auto",
    "Python",
    "JavaScript",
    "TypeScript",
    "Java",
    "C++",
    "C#",
    "Go",
    "Rust",
    "SQL",
]

_FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"


def _rounded_region(width: int, height: int, radius: float) -> QRegion:
    """A rounded-rectangle mask matching the painted frame."""
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, width, height), radius, radius)
    return QRegion(path.toFillPolygon().toPolygon())

_STYLE_SHEET = f"""
QWidget {{
    color: #ffffff;
    font-family: {_FONT};
}}
QLabel {{
    background: transparent;
}}
QLabel#logoBox {{
    background-color: #3a3a3a;
    border: none;
    border-radius: 4px;
    padding: 3px 6px;
}}
QPushButton#barButton {{
    background-color: #3a3a3a;
    color: #ffffff;
    border: 1px solid #7a7a7a;
    border-radius: 4px;
    padding: 0px;
}}
QPushButton#barButton:hover {{
    background-color: #4a4a4a;
    border-color: #5a5a5a;
}}
QPushButton#barButton:pressed {{
    background-color: #2a2a2a;
}}
QPushButton#micButton {{
    background-color: #3a3a3a;
    color: #ffffff;
    border: none;
    border-radius: 4px;
    padding: 0px;
}}
QPushButton#micButton[active="true"] {{
    background-color: #006400;
    border: 1px solid #44FF44;
}}
QPushButton#micButton[connecting="true"] {{
    background-color: #8B6914;
    border: 1px solid #FFB347;
}}
QPushButton#tinyButton {{
    background-color: transparent;
    color: #ffffff;
    border: none;
    font-size: 16px;
    font-weight: 700;
    padding: 0px;
}}
QPushButton#tinyButton:hover {{
    background-color: #4a4a4a;
    border-radius: 3px;
}}
QPushButton#tinyButton:pressed {{
    background-color: #2a2a2a;
}}
QPushButton#closeButton {{
    background-color: rgba(30, 30, 30, 0.8);
    color: #ffffff;
    border: 1px solid #444444;
    border-radius: 16px;
}}
QPushButton#closeButton:hover {{
    background-color: rgba(200, 50, 50, 0.85);
    border-color: #ff7777;
}}
QPushButton#closeButton:pressed {{
    background-color: rgba(180, 40, 40, 0.95);
}}
QComboBox#deviceCombo {{
    background-color: #3a3a3a;
    color: #ffffff;
    border: 1px solid #7a7a7a;
    border-radius: 4px;
    padding: 2px 18px 2px 8px;
    font-size: 11px;
}}
QComboBox#deviceCombo:hover {{
    background-color: #4a4a4a;
    border-color: #5a5a5a;
}}
QComboBox#deviceCombo::drop-down {{
    border: none;
    background-color: transparent;
    width: 0px;
}}
QComboBox#deviceCombo::down-arrow {{
    image: none;
    width: 0px;
    height: 0px;
    border: none;
}}
QComboBox#deviceCombo QAbstractItemView {{
    background-color: #1a1a1a;
    color: #ffffff;
    border: 1px solid #7a7a7a;
    selection-background-color: #4a4a4a;
    selection-color: #ffffff;
    padding: 4px;
}}
QLabel#comboArrow {{
    color: #ffffff;
    font-size: 9px;
    background: transparent;
    border: none;
}}
QLineEdit#sttInput, QLineEdit#manualInput {{
    background-color: #1a1a1a;
    color: #ffffff;
    border: 1px solid #5a5a5a;
    border-radius: 4px;
    font-family: {_FONT};
    font-weight: 500;
    selection-background-color: #2f5f8f;
}}
QLineEdit#sttInput {{
    padding: 2px 28px 2px 8px;
    font-size: 14px;
}}
QLineEdit#manualInput {{
    padding: 2px 6px;
    font-size: 12px;
}}
QLineEdit#sttInput:focus, QLineEdit#manualInput:focus {{
    border-color: #7a7a7a;
}}
QPushButton#dropdownButton {{
    background-color: transparent;
    color: #888888;
    border: none;
    font-size: 14px;
    font-weight: bold;
    padding: 0px;
}}
QPushButton#dropdownButton:hover {{
    color: #ffffff;
    background-color: rgba(255, 255, 255, 0.1);
    border-radius: 3px;
}}
QFrame#historyBox {{
    background-color: #3a3a3a;
    border-radius: 6px;
}}
QPushButton#historyButton {{
    background-color: transparent;
    color: #ffffff;
    border: none;
    border-radius: 4px;
    padding: 0px;
}}
QPushButton#historyButton:hover {{
    background-color: #4a4a4a;
}}
QPushButton#historyButton:pressed {{
    background-color: #2a2a2a;
}}
QPushButton#historyButton:disabled {{
    opacity: 0.3;
}}
QFrame#languageSelector {{
    background-color: #3a3a3a;
    border: none;
    border-radius: 6px;
}}
QPushButton#langButton {{
    background-color: transparent;
    color: #ffffff;
    border: 1px solid #7a7a7a;
    border-radius: 4px;
    padding: 0px 6px;
    font-size: 11px;
    font-weight: 600;
}}
QPushButton#langButton:hover {{
    background-color: #4a4a4a;
}}
QPushButton#langButton[active="true"] {{
    background-color: #4a4a4a;
    border: 1px solid #58a6ff;
    font-weight: 700;
}}
QLabel#historyLabel {{
    color: #ffffff;
    background-color: transparent;
    font-size: 14px;
    padding: 2px 4px;
}}
QWidget#timerBox {{
    background-color: transparent;
    border: 1px solid #7a7a7a;
    border-radius: 4px;
}}
QLabel#timerText {{
    color: #ffffff;
    background-color: rgba(0, 200, 0, 0.80);
    border: 1px solid #7a7a7a;
    border-radius: 4px;
    padding: 0px 8px;
    font-size: 13px;
    font-weight: 600;
}}
QWidget#opacityBox {{
    background-color: #3a3a3a;
    border: 1px solid #7a7a7a;
    border-radius: 4px;
}}
QTextBrowser#answerView {{
    background: transparent;
    border: none;
    color: #ececf1;
    font-family: {_FONT};
    font-size: 15px;
}}
QTextBrowser#answerView QScrollBar:vertical,
QTextBrowser#answerView QScrollBar:horizontal {{
    width: 0px;
    height: 0px;
    background: transparent;
}}
QWidget#thumbRow {{
    background: transparent;
}}
QLabel#thumb {{
    background: #242424;
    border: 1px solid #4a4a4a;
    border-radius: 6px;
    padding: 1px;
}}
QPushButton#thumbRemove {{
    background: rgba(24, 24, 24, 220);
    color: #ff9b9b;
    border: 1px solid #5a5a5a;
    border-radius: 8px;
    padding: 0px;
    font-size: 10px;
}}
QPushButton#thumbRemove:hover {{
    background: #7a2b2b;
    color: #ffffff;
}}
QMenu {{
    background-color: #202020;
    color: #f0f0f0;
    border: 1px solid #4a4a4a;
    padding: 4px;
}}
QMenu::item {{
    padding: 5px 22px 5px 10px;
    border-radius: 3px;
}}
QMenu::item:selected {{
    background-color: #3a3a3a;
}}
QMenu::item:disabled {{
    color: #777777;
}}
QToolTip {{
    background-color: #202020;
    color: #f0f0f0;
    border: 1px solid #4a4a4a;
    padding: 4px 6px;
}}
"""


def _scaled_thumb(pixmap, height: int = THUMBNAIL_HEIGHT):
    """Scale a screenshot for a label, crisp on high-DPI screens."""
    if pixmap.isNull():
        return pixmap
    ratio = 1.0
    app = QGuiApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    if screen is not None:
        ratio = max(1.0, float(screen.devicePixelRatio()))
    scaled = pixmap.scaledToHeight(int(height * ratio), Qt.SmoothTransformation)
    scaled.setDevicePixelRatio(ratio)
    return scaled


class _DeviceComboBox(QComboBox):
    """The original 130–160 px device selector.

    QComboBox's default size hint counts the popup view, which makes the
    control stretch to the maximum.  The original selector instead starts at
    130 px and only widens for a long current device name.
    """

    MIN_WIDTH = 130
    MAX_WIDTH = 160

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._desired_width = self.MIN_WIDTH
        self._arrow: QLabel | None = None

    def set_arrow(self, arrow: QLabel) -> None:
        self._arrow = arrow
        self._move_arrow()

    def _move_arrow(self) -> None:
        if self._arrow is not None:
            self._arrow.move(self.width() - 14, 0)
            self._arrow.raise_()

    def resizeEvent(self, event) -> None:  # noqa: D102
        super().resizeEvent(event)
        self._move_arrow()

    def set_desired_width(self, width: int) -> None:
        self._desired_width = max(self.MIN_WIDTH, min(self.MAX_WIDTH, int(width)))
        self.updateGeometry()

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(self._desired_width, 28)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(self.MIN_WIDTH, 28)


class _PendingThumb(QWidget):
    """One queued screenshot with a small remove button."""

    remove_requested = Signal(str)

    def __init__(self, encoded: str, index: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._encoded = encoded
        size = THUMBNAIL_HEIGHT + 8
        self.setFixedSize(size, size)
        label = QLabel(self)
        label.setObjectName("thumb")
        label.setPixmap(_scaled_thumb(pixmap_from_b64(encoded)))
        label.move(4, 4)
        label.setToolTip(f"screenshot {index + 1} — sent with your next question")
        remove = QPushButton("\u2715", self)
        remove.setObjectName("thumbRemove")
        remove.setFixedSize(16, 16)
        remove.move(size - 18, 2)
        remove.setToolTip("remove this screenshot")
        remove.clicked.connect(lambda: self.remove_requested.emit(self._encoded))


class ResizeGrip(QWidget):
    """Small floating handle at the answer window's bottom-right corner."""

    def __init__(self, response: ResponseWindow) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self._response = response
        self._drag_start: QPoint | None = None
        self._start_size: QSize | None = None
        self.setFixedSize(18, 18)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setToolTip("Drag to resize the answer window")

    def paintEvent(self, _event) -> None:  # noqa: D102
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(255, 255, 255, 160), 1.3)
        painter.setPen(pen)
        for offset in (5, 9, 13):
            painter.drawLine(offset, 17, 17, offset)
        painter.end()

    def showEvent(self, event) -> None:  # noqa: D102
        super().showEvent(event)
        stealth.apply_stealth(self)

    def mousePressEvent(self, event) -> None:  # noqa: D102
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.globalPosition().toPoint()
            self._start_size = self._response.size()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: D102
        if self._drag_start is not None and self._start_size is not None:
            delta = event.globalPosition().toPoint() - self._drag_start
            width = max(RESPONSE_MIN_WIDTH, self._start_size.width() + delta.x())
            height = max(RESPONSE_MIN_HEIGHT, self._start_size.height() + delta.y())
            self._response.resize(width, height)
            self._response.position_grip()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: D102
        self._drag_start = None
        self._start_size = None
        event.accept()


class ResponseWindow(QWidget):
    """The answer surface: an independent, resizable, always-on-top window."""

    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setObjectName("responseWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setWindowOpacity(settings.opacity)
        self.setMinimumSize(RESPONSE_MIN_WIDTH, RESPONSE_MIN_HEIGHT)
        self.resize(RESPONSE_WIDTH, RESPONSE_HEIGHT)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(4, 5, 4, 5)
        self._layout.setSpacing(0)

        self._content = QWidget(self)
        self._content.setObjectName("responseContent")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(0)
        self._layout.addWidget(self._content)

        self._grip = ResizeGrip(self)

    def paintEvent(self, _event) -> None:  # noqa: D102
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.setBrush(QColor("#2a2a2a"))
        painter.setPen(QPen(QColor(255, 255, 255, 102), 1))
        painter.drawRoundedRect(rect, BORDER_RADIUS, BORDER_RADIUS)
        painter.end()

    def _apply_mask(self) -> None:
        self.setMask(_rounded_region(self.width(), self.height(), BORDER_RADIUS))

    def showEvent(self, event) -> None:  # noqa: D102
        super().showEvent(event)
        self._apply_mask()
        stealth.apply_stealth(self)
        self.position_grip()
        self._grip.show()
        self._grip.raise_()

    def hideEvent(self, event) -> None:  # noqa: D102
        self._grip.hide()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:  # noqa: D102
        self._grip.close()
        super().closeEvent(event)

    def moveEvent(self, event) -> None:  # noqa: D102
        super().moveEvent(event)
        self.position_grip()

    def resizeEvent(self, event) -> None:  # noqa: D102
        super().resizeEvent(event)
        self._apply_mask()
        self.position_grip()

    def position_grip(self) -> None:
        """Put the resize handle just outside the bottom-right corner."""
        grip = getattr(self, "_grip", None)
        if grip is None:
            return
        grip.move(self.x() + self.width() - 8, self.y() + self.height() - 8)
        grip.setWindowOpacity(self.windowOpacity())

    def set_content_opacity(self, value: float) -> None:
        self.setWindowOpacity(value)
        self._grip.setWindowOpacity(value)


class HistoryLineEdit(QLineEdit):
    """Line edit with the small trailing dropdown used by the speech row."""

    dropdown_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._arrow = QPushButton("\u25bc", self)
        self._arrow.setObjectName("dropdownButton")
        self._arrow.setFixedSize(20, 20)
        self._arrow.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._arrow.setCursor(Qt.CursorShape.PointingHandCursor)
        self._arrow.clicked.connect(self.dropdown_clicked.emit)
        self._arrow.setToolTip("Recent questions and history")
        self.setTextMargins(0, 0, 26, 0)

    def resizeEvent(self, event) -> None:  # noqa: D102
        super().resizeEvent(event)
        self._arrow.move(max(0, self.width() - 24), 3)


class OverlayWindow(QWidget):
    """Control bar plus the separate answer window."""

    # Signals consumed by app.py (which owns capture/audio/stt wiring).
    mic_toggled = Signal(bool)
    screenshot_requested = Signal()
    settings_requested = Signal()
    history_requested = Signal()
    info_requested = Signal()
    logout_requested = Signal()
    closed = Signal()

    def __init__(
        self,
        api: ApiClient,
        settings: AppSettings,
        conversations: ConversationStore,
        context_provider: Callable[[], str],
        parent: QWidget | None = None,
    ) -> None:
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
        super().__init__(parent, flags)
        self.setObjectName("barRoot")
        self.setStyleSheet(_STYLE_SHEET)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowOpacity(settings.opacity)
        self.setFixedSize(BAR_WIDTH, BAR_HEIGHT)

        self._api = api
        self._settings = settings
        self._conversations = conversations
        self._context_provider = context_provider

        self._worker: StreamWorker | None = None
        self._answer_buffer = ""
        self._streaming = False
        self._pending: dict[str, Any] | None = None
        self._items: list[dict[str, Any]] = []
        self._index = -1
        self._last_auto_question = ""
        self._last_auto_time = 0.0
        self._drag_offset: QPoint | None = None

        # The code-language combo: which rewrite of the shown answer is visible.
        self._variant_language = "auto"
        self._rewrite_item: dict[str, Any] | None = None

        # Session-only click-through mode (mouse events reach the app below).
        self._click_through = False

        # Collapse/expand state.
        self._answers_visible = True
        self._collapsed = False
        self._expanded_height = BAR_HEIGHT
        self._opacity_animation: QPropertyAnimation | None = None

        # Recording clock shown in the green pill.
        self._recording_started = 0.0
        self._clock = QTimer(self)
        self._clock.setInterval(500)
        self._clock.timeout.connect(self._tick_clock)

        # Teaser popup for the streaming answer while the answers are hidden.
        self._preview = StreamPreview(self)

        # Screenshots queue up and attach to the next question.
        self._pending_images: list[str] = []
        self._pending_widgets: list[_PendingThumb] = []

        # Math/mermaid rendering uses a lazily-created QtWebEngine view.
        self._web_view = None
        self._web_failed = False
        self._web_visible = False
        self._last_web_render = 0.0

        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(STREAM_FLUSH_MS)
        self._flush_timer.timeout.connect(self._flush_answer)

        # The independent answer window lives for as long as the bar does.
        self._response = ResponseWindow(settings, self)
        self._answer_panel = self._response
        self._answer_layout = self._response._content_layout

        self._status_text = "idle"
        self._build_ui()
        self._refresh_devices()
        self._center_on_screen()
        self._apply_bar_mask()

    # ------------------------------------------------------------------ UI #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._content = QWidget(self)
        self._content.setObjectName("barContent")
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(4, 5, 4, 5)
        content_layout.setSpacing(0)
        root.addWidget(self._content)

        # -- row 1: logo / mic / device / hide / timer / opacity / close ---- #
        self._top_row = QFrame(self._content)
        self._top_row.setFixedHeight(34)
        top = QHBoxLayout(self._top_row)
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(0)

        self._logo = QLabel(self._top_row)
        self._logo.setObjectName("logoBox")
        self._logo.setFixedSize(40, 34)
        self._logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._logo.setPixmap(ui_icons.pixmap("logo", 28))
        top.addWidget(self._logo)
        top.addSpacing(14)

        self._mic_button = QPushButton(self._top_row)
        self._mic_button.setObjectName("micButton")
        self._mic_button.setFixedSize(36, 30)
        self._mic_button.setIcon(ui_icons.icon("system_mic", 20))
        self._mic_button.setIconSize(QSize(20, 20))
        self._mic_button.setCheckable(True)
        self._mic_button.toggled.connect(self._on_mic_toggled)
        top.addWidget(self._mic_button)
        top.addSpacing(4)

        self._device_combo = _DeviceComboBox(self._top_row)
        self._device_combo.setObjectName("deviceCombo")
        self._device_combo.setMinimumWidth(130)
        self._device_combo.setMaximumWidth(160)
        self._device_combo.setFixedHeight(28)
        self._device_combo.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self._device_combo.currentIndexChanged.connect(self._on_device_changed)
        self._device_arrow = QLabel("\u25bc", self._device_combo)
        self._device_arrow.setObjectName("comboArrow")
        self._device_arrow.setGeometry(116, 0, 12, 28)
        self._device_arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._device_arrow.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._device_combo.set_arrow(self._device_arrow)
        top.addWidget(self._device_combo)

        top.addStretch(1)

        self._hide_button = QPushButton(self._top_row)
        self._hide_button.setObjectName("barButton")
        self._hide_button.setFixedSize(28, 28)
        self._hide_button.setIcon(ui_icons.icon("eye_off", 18))
        self._hide_button.setIconSize(QSize(18, 18))
        self._hide_button.clicked.connect(self.toggle_collapse)
        top.addWidget(self._hide_button)

        top.addStretch(1)

        self._timer_box = QWidget(self._top_row)
        self._timer_box.setObjectName("timerBox")
        self._timer_box.setFixedSize(88, 28)
        self._timer_icon = QLabel(self._timer_box)
        self._timer_icon.setPixmap(ui_icons.pixmap("timer", 16))
        self._timer_icon.setGeometry(8, 6, 16, 16)
        self._timer_label = QLabel("00:00", self._timer_box)
        self._timer_label.setObjectName("timerText")
        self._timer_label.setGeometry(28, 0, 52, 28)
        self._timer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addWidget(self._timer_box)
        top.addSpacing(4)

        self._opacity_box = QWidget(self._top_row)
        self._opacity_box.setObjectName("opacityBox")
        self._opacity_box.setFixedSize(47, 28)
        self._opacity_down = QPushButton(self._opacity_box)
        self._opacity_down.setObjectName("tinyButton")
        self._opacity_down.setGeometry(3, 1, 18, 26)
        self._opacity_down.setIcon(ui_icons.icon("circle", 13))
        self._opacity_down.setIconSize(QSize(13, 13))
        self._opacity_down.clicked.connect(lambda: self.nudge_opacity(-OPACITY_STEP))
        self._opacity_separator = QFrame(self._opacity_box)
        self._opacity_separator.setGeometry(23, 6, 1, 16)
        self._opacity_separator.setStyleSheet("background-color: #7a7a7a; border: none;")
        self._opacity_up = QPushButton(self._opacity_box)
        self._opacity_up.setObjectName("tinyButton")
        self._opacity_up.setGeometry(26, 1, 18, 26)
        self._opacity_up.setIcon(ui_icons.icon("circle_filled", 13))
        self._opacity_up.setIconSize(QSize(13, 13))
        self._opacity_up.clicked.connect(lambda: self.nudge_opacity(OPACITY_STEP))
        top.addWidget(self._opacity_box)
        top.addSpacing(12)

        self._close_button = QPushButton(self._top_row)
        self._close_button.setObjectName("closeButton")
        self._close_button.setFixedSize(32, 32)
        self._close_button.setIcon(ui_icons.icon("close", 20))
        self._close_button.setIconSize(QSize(20, 20))
        self._close_button.clicked.connect(self.close)
        top.addWidget(self._close_button)

        content_layout.addWidget(self._top_row)

        # -- separator ------------------------------------------------------ #
        self._separator = QFrame(self._content)
        self._separator.setFixedHeight(1)
        self._separator.setStyleSheet("background-color: rgba(255, 255, 255, 0.40); border: none;")
        content_layout.addWidget(self._separator)

        # -- queued screenshot strip (hidden until an image is attached) ----- #
        self._thumb_row = QWidget(self._content)
        self._thumb_row.setObjectName("thumbRow")
        self._thumb_row.setFixedHeight(THUMB_ROW_HEIGHT)
        self._thumb_row.setVisible(False)
        self._thumb_layout = QHBoxLayout(self._thumb_row)
        self._thumb_layout.setContentsMargins(4, 0, 4, 0)
        self._thumb_layout.setSpacing(6)
        self._thumb_layout.addStretch(1)
        content_layout.addWidget(self._thumb_row)

        content_layout.addSpacing(5)

        # -- row 2: analyze / speech input / send / resume ------------------ #
        self._speech_row = QFrame(self._content)
        self._speech_row.setFixedHeight(28)
        speech = QHBoxLayout(self._speech_row)
        speech.setContentsMargins(0, 0, 0, 0)
        speech.setSpacing(5)

        self._screenshot_button = QPushButton(self._speech_row)
        self._screenshot_button.setObjectName("barButton")
        self._screenshot_button.setFixedSize(36, 28)
        self._screenshot_button.setIcon(ui_icons.icon("analyze_screen", 18))
        self._screenshot_button.setIconSize(QSize(18, 18))
        self._screenshot_button.clicked.connect(self.screenshot_requested.emit)
        speech.addWidget(self._screenshot_button)

        self._stt_input = HistoryLineEdit(self._speech_row)
        self._stt_input.setObjectName("sttInput")
        self._stt_input.setFixedHeight(26)
        self._stt_input.returnPressed.connect(self._submit_stt_box)
        self._stt_input.dropdown_clicked.connect(self._show_stt_menu)
        speech.addWidget(self._stt_input, 1)

        self._ask_button = QPushButton(self._speech_row)
        self._ask_button.setObjectName("barButton")
        self._ask_button.setFixedSize(34, 26)
        self._ask_button.setIcon(ui_icons.icon("send", 20))
        self._ask_button.setIconSize(QSize(20, 20))
        self._ask_button.clicked.connect(self._submit_stt_box)
        speech.addWidget(self._ask_button)

        self._resume_button = QPushButton(self._speech_row)
        self._resume_button.setObjectName("barButton")
        self._resume_button.setFixedSize(34, 26)
        self._resume_button.setIcon(ui_icons.icon("pencil", 20))
        self._resume_button.setIconSize(QSize(20, 20))
        self._resume_button.clicked.connect(self._stt_input.clear)
        speech.addWidget(self._resume_button)

        content_layout.addWidget(self._speech_row)
        content_layout.addSpacing(5)

        # -- row 3: history / manual input / send / resume ------------------ #
        self._manual_row = QFrame(self._content)
        self._manual_row.setFixedHeight(24)
        manual = QHBoxLayout(self._manual_row)
        manual.setContentsMargins(0, 0, 0, 0)
        manual.setSpacing(5)

        self._history_box = QFrame(self._manual_row)
        self._history_box.setObjectName("historyBox")
        self._history_box.setFixedSize(164, 24)
        history = QHBoxLayout(self._history_box)
        history.setContentsMargins(6, 1, 6, 1)
        history.setSpacing(4)

        self._prev_button = QPushButton(self._history_box)
        self._prev_button.setObjectName("historyButton")
        self._prev_button.setFixedSize(32, 20)
        self._prev_button.setIcon(ui_icons.icon("arrow_left", 20))
        self._prev_button.setIconSize(QSize(20, 20))
        self._prev_button.clicked.connect(self.show_previous)
        history.addWidget(self._prev_button, 0, Qt.AlignmentFlag.AlignTop)

        self._position_label = QLabel("", self._history_box)
        self._position_label.setObjectName("historyLabel")
        self._position_label.setFixedSize(80, 20)
        self._position_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        history.addWidget(self._position_label, 0, Qt.AlignmentFlag.AlignTop)

        self._next_button = QPushButton(self._history_box)
        self._next_button.setObjectName("historyButton")
        self._next_button.setFixedSize(32, 20)
        self._next_button.setIcon(ui_icons.icon("arrow_right", 20))
        self._next_button.setIconSize(QSize(20, 20))
        self._next_button.clicked.connect(self.show_next)
        history.addWidget(self._next_button, 0, Qt.AlignmentFlag.AlignTop)

        manual.addWidget(self._history_box)

        # Appears only when the visible answer contains a code block; it takes
        # the same 144 px slot as in the original row and shortens the input.
        self._language_selector = QFrame(self._manual_row)
        self._language_selector.setObjectName("languageSelector")
        self._language_selector.setFixedSize(144, 24)
        language_layout = QHBoxLayout(self._language_selector)
        language_layout.setContentsMargins(6, 1, 6, 1)
        language_layout.setSpacing(3)
        self._language_buttons: dict[str, QPushButton] = {}
        for label, language in (
            ("Py", "Python"),
            ("C++", "C++"),
            ("Java", "Java"),
            ("JS", "JavaScript"),
        ):
            button = QPushButton(label, self._language_selector)
            button.setObjectName("langButton")
            button.setFixedHeight(22)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda _checked=False, name=language: self._set_language(name)
            )
            language_layout.addWidget(button)
            self._language_buttons[language] = button
        self._language_selector.hide()
        manual.addWidget(self._language_selector)

        self._manual_input = QLineEdit(self._manual_row)
        self._manual_input.setObjectName("manualInput")
        self._manual_input.setFixedHeight(24)
        self._manual_input.returnPressed.connect(self.submit_manual)
        manual.addWidget(self._manual_input, 1)

        self._manual_ask_button = QPushButton(self._manual_row)
        self._manual_ask_button.setObjectName("barButton")
        self._manual_ask_button.setFixedSize(34, 24)
        self._manual_ask_button.setIcon(ui_icons.icon("send", 20))
        self._manual_ask_button.setIconSize(QSize(20, 20))
        self._manual_ask_button.clicked.connect(self.submit_manual)
        manual.addWidget(self._manual_ask_button)

        self._manual_resume_button = QPushButton(self._manual_row)
        self._manual_resume_button.setObjectName("barButton")
        self._manual_resume_button.setFixedSize(34, 24)
        self._manual_resume_button.setIcon(ui_icons.icon("pencil", 20))
        self._manual_resume_button.setIconSize(QSize(20, 20))
        self._manual_resume_button.clicked.connect(self._manual_input.clear)
        manual.addWidget(self._manual_resume_button)

        content_layout.addWidget(self._manual_row)

        # -- hidden compatibility widgets (used by settings/tests) ---------- #
        self._status = QLabel("", self)
        self._status.hide()

        self._language_combo = QComboBox(self)
        self._language_combo.addItems(CODE_LANGUAGES)
        self._language_combo.currentIndexChanged.connect(self._on_language_changed)
        self._language_combo.hide()

        self._copy_button = QPushButton("copy", self)
        self._copy_button.clicked.connect(self._copy_answer)
        self._copy_button.hide()

        self._collapse_button = QPushButton("\u25be", self)
        self._collapse_button.hide()

        self._click_button = QPushButton(self)
        self._click_button.setCheckable(True)
        self._click_button.hide()

        # Right-click affordances keep Settings/History/Interview details
        # reachable without adding chrome that the original layout does not have.
        self._logo.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._logo.customContextMenuRequested.connect(self._show_logo_menu)
        self._stt_input.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._stt_input.customContextMenuRequested.connect(self._show_stt_context_menu)
        self._manual_input.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._manual_input.customContextMenuRequested.connect(self._show_manual_context_menu)

        # -- collapsed-state logo ------------------------------------------- #
        self._collapsed_logo = QLabel(self)
        self._collapsed_logo.setPixmap(ui_icons.pixmap("logo", 32))
        self._collapsed_logo.setGeometry(8, 8, 32, 32)
        self._collapsed_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._collapsed_logo.setToolTip("Double-click to show the answers")
        self._collapsed_logo.hide()
        self._collapsed_logo.installEventFilter(self)

        # -- answer view ---------------------------------------------------- #
        self._answer_view = QTextBrowser(self._response._content)
        self._answer_view.setObjectName("answerView")
        self._answer_view.setOpenExternalLinks(True)
        self._answer_view.setFrameShape(QFrame.Shape.NoFrame)
        self._answer_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._answer_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._answer_view.document().setDocumentMargin(10)
        self._answer_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._answer_view.customContextMenuRequested.connect(self._answer_context_menu)
        self._response._content_layout.addWidget(self._answer_view, 1)
        self._answer_view_index = self._response._content_layout.indexOf(self._answer_view)

        # The original answer panel is always the Chromium view.  The text
        # browser stays as an invisible fallback for a machine without
        # QtWebEngine; on a normal Windows install it is never shown.
        self._answer_view.hide()
        if self._settings.web_render and self._ensure_web_view() is not None:
            self._web_view.show()
            self._web_visible = True
        else:
            self._answer_view.show()

        # Sent screenshots are retained for the history/test surface but are
        # intentionally not drawn as extra chrome in the answer window.
        self._sent_attachment_host = QWidget(self._response._content)
        self._sent_attachment_host.hide()
        self._attachment_row = QHBoxLayout(self._sent_attachment_host)
        self._attachment_row.setContentsMargins(0, 0, 0, 0)
        self._attachment_row.setSpacing(6)
        self._attachment_row.addStretch(1)
        self._attachment_widgets: list[QWidget] = []

        for widget in (
            self._content,
            self._top_row,
            self._separator,
            self._speech_row,
            self._manual_row,
            self._logo,
        ):
            widget.installEventFilter(self)

        self.retranslate()
        self._show_welcome_message()

    def retranslate(self) -> None:
        """Apply the current English interface strings."""
        self._mic_button.setToolTip("Start / stop listening")
        self._device_combo.setToolTip("Audio device to listen to")
        self._device_arrow.setToolTip("Audio device")
        self._hide_button.setToolTip(
            "Hide the answer window ({hotkey})".format(
                hotkey=self._settings.hotkeys.get("collapse", "")
            )
        )
        self._timer_box.setToolTip("Recording time")
        self._opacity_down.setToolTip("Opacity down")
        self._opacity_up.setToolTip("Opacity up")
        self._close_button.setToolTip("Quit")
        self._screenshot_button.setToolTip(
            "Capture a screen region ({hotkey})".format(
                hotkey=self._settings.hotkeys.get("screenshot", "")
            )
        )
        self._stt_input.setPlaceholderText("Speech to Text of System Audio...")
        self._ask_button.setToolTip(
            "Ask with the speech box ({hotkey})".format(
                hotkey=self._settings.hotkeys.get("ask", "")
            )
        )
        self._resume_button.setToolTip("Clear the input field")
        self._manual_input.setPlaceholderText("Ask any question manually ...")
        self._manual_ask_button.setToolTip("Ask the question")
        self._manual_resume_button.setToolTip("Clear the manual input field")
        self._prev_button.setToolTip("Previous answer")
        self._next_button.setToolTip("Next answer")
        self._position_label.setToolTip("Answer history")
        self._language_combo.setToolTip("Prefer a language for code answers")
        self._copy_button.setToolTip("Copy the answer")
        self._update_position_label()

    # ------------------------------------------------------------ lifecycle #

    def _apply_bar_mask(self) -> None:
        if self._collapsed:
            self.setMask(
                QRegion(0, 0, COLLAPSED_SIZE, COLLAPSED_SIZE, QRegion.RegionType.Ellipse)
            )
        else:
            self.setMask(_rounded_region(self.width(), self.height(), BORDER_RADIUS))

    def showEvent(self, event) -> None:  # noqa: D102
        super().showEvent(event)
        self._apply_bar_mask()
        stealth.apply_stealth(self)
        if self._answers_visible:
            self._position_response()
            self._response.setWindowOpacity(self.windowOpacity())
            self._response.show()
            self._response.raise_()
            self.raise_()

    def closeEvent(self, event) -> None:  # noqa: D102
        self.cancel_stream()
        if self._opacity_animation is not None:
            self._opacity_animation.stop()
        self._preview.hide_now(immediate=True)
        self._response.close()
        self.closed.emit()
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: D102
        super().resizeEvent(event)
        self._apply_bar_mask()
        self._position_response()
        self._preview.reposition(self)

    def moveEvent(self, event) -> None:  # noqa: D102
        super().moveEvent(event)
        self._position_response()
        self._preview.reposition(self)

    def eventFilter(self, watched: QWidget, event: QEvent) -> bool:  # noqa: D102
        if event.type() == QEvent.Type.MouseButtonDblClick and watched in (
            self._logo,
            self._collapsed_logo,
        ):
            self.toggle_collapse()
            return True
        if event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                self._drag_offset = (
                    event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                )
                return True
        elif event.type() == QEvent.Type.MouseMove:
            if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
                self.move(event.globalPosition().toPoint() - self._drag_offset)
                return True
        elif event.type() == QEvent.Type.MouseButtonRelease:
            self._drag_offset = None
            return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event) -> None:  # noqa: D102
        if event.key() == Qt.Key.Key_Escape:
            self.erase()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: D102
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(0, 0, -1, -1)
        radius = COLLAPSED_SIZE // 2 if self._collapsed else BORDER_RADIUS
        painter.setBrush(QColor("#000000"))
        painter.setPen(QPen(QColor(255, 255, 255, 102), 1))
        painter.drawRoundedRect(rect, radius, radius)
        painter.end()

    def _center_on_screen(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.geometry()
        # Match the original's "centre a 700×700 window, then shrink to the
        # control strip" placement.
        x = area.left() + (area.width() - BAR_WIDTH) // 2
        y = area.top() + (area.height() - 700) // 2
        x = max(area.left() + 8, x)
        y = max(area.top() + 8, y)
        self.move(x, y)

    def _position_response(self) -> None:
        if not hasattr(self, "_response"):
            return
        x = self.x()
        y = self.y() + self.height() + RESPONSE_GAP
        self._response.move(x, y)
        self._response.position_grip()

    # ------------------------------------------------------------- dragging #

    def mousePressEvent(self, event) -> None:  # noqa: D102
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: D102
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: D102
        self._drag_offset = None
        event.accept()

    # -------------------------------------------------------------- devices #

    def _refresh_devices(self) -> None:
        source = "loopback" if self._settings.audio_source == "system" else "input"
        all_devices = list_devices()
        devices = [device for device in all_devices if device.kind == source] or all_devices
        current = self._settings.audio_device

        self._device_combo.blockSignals(True)
        self._device_combo.clear()
        for device in devices:
            self._device_combo.addItem(device.label(), device.id)
        if not devices:
            self._device_combo.addItem("No devices found", "")
        index = max(self._device_combo.findData(current), 0)
        self._device_combo.setCurrentIndex(index)
        self._device_combo.blockSignals(False)
        self._resize_device_combo()
        self._device_arrow.raise_()

        if not current and devices:
            chosen = next((d for d in devices if d.is_default), devices[0])
            self._settings.audio_device = chosen.id
            self._settings.save()

    def _resize_device_combo(self) -> None:
        """Keep the selector at 130 px, widening only for a long device name."""
        text = self._device_combo.currentText()
        if not self._device_combo.currentData():
            width = _DeviceComboBox.MIN_WIDTH
        else:
            width = QFontMetrics(self._device_combo.font()).horizontalAdvance(text) + 46
        self._device_combo.set_desired_width(width)
        self._device_arrow.move(self._device_combo.width() - 14, 0)

    def _on_device_changed(self, _index: int) -> None:
        self._resize_device_combo()
        device_id = self._device_combo.currentData() or ""
        if device_id and device_id != self._settings.audio_device:
            self._settings.audio_device = device_id
            self._settings.save()
            if self._mic_button.isChecked():
                self.set_status("device changed — restarting capture…")
                self._mic_button.setChecked(False)
                self._mic_button.setChecked(True)

    def _set_mic_visual(self, active: bool) -> None:
        self._mic_button.blockSignals(True)
        self._mic_button.setChecked(active)
        self._mic_button.blockSignals(False)
        self._mic_button.setProperty("active", "true" if active else "false")
        self._mic_button.style().unpolish(self._mic_button)
        self._mic_button.style().polish(self._mic_button)
        if active:
            if not self._clock.isActive():
                self._recording_started = time.monotonic()
                self._clock.start()
        else:
            self._clock.stop()
            self._recording_started = 0.0
            self._timer_label.setText("00:00")

    def _on_mic_toggled(self, checked: bool) -> None:
        self._set_mic_visual(checked)
        self.set_status("starting capture…" if checked else "idle")
        self.mic_toggled.emit(checked)

    def set_mic_active(self, active: bool) -> None:
        """Reflect an externally-forced mic state (e.g. capture error)."""
        self._set_mic_visual(active)

    def _tick_clock(self) -> None:
        elapsed = max(0, int(time.monotonic() - self._recording_started))
        minutes, seconds = divmod(elapsed, 60)
        self._timer_label.setText(f"{minutes:02d}:{seconds:02d}")

    # ------------------------------------------------------------- statuses #

    def set_status(self, text: str, *, error: bool = False) -> None:
        self._status_text = text
        self._status.setText(text)
        self._status.setToolTip(text)
        self._status.setProperty("error", "true" if error else "false")
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)
        # The bar deliberately has no permanent status label; keep the
        # transient message available on the recording timer and inputs.
        self._timer_label.setToolTip(text)
        self._stt_input.setToolTip(text)
        self._manual_input.setToolTip(text)

    def _apply_status_text(self) -> None:
        self._status.setText(getattr(self, "_status_text", ""))

    def set_partial(self, text: str) -> None:
        self._stt_input.setText(text)
        if text:
            self._stt_input.setCursorPosition(len(text))

    def set_final(self, text: str) -> None:
        self._stt_input.setText(text.strip())
        if self._settings.auto_ask and text.strip():
            self._submit_stt_box()

    # ---------------------------------------------------------------- input #

    def _submit_stt_box(self) -> None:
        question = self._stt_input.text().strip()
        if not question and not self._pending_images:
            return
        self._stt_input.clear()
        self.submit_question(question, kind="chat")

    def submit_manual(self) -> None:
        self.submit_question(self._manual_input.text(), kind="chat")

    def erase(self) -> None:
        self._stt_input.clear()
        self._manual_input.clear()
        self._clear_attachments()
        self._clear_pending()
        self._reset_answer_panel()
        self.set_status("erased")

    def _copy_answer(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None and self._answer_buffer:
            clipboard.setText(self._answer_buffer)
            self.set_status("answer copied")

    # ------------------------------------------------------------- captures #

    def add_capture(self, encoded: str) -> bool:
        """Queue a screenshot; it is attached to the next question asked."""
        if len(self._pending_images) >= MAX_CAPTURES:
            self.set_status(
                f"maximum {MAX_CAPTURES} screenshots per question",
                error=True,
            )
            return False
        if not self._pending_images:
            self._clear_attachments()
        self._pending_images.append(encoded)
        self._rebuild_pending_row()
        self.set_status(self._capture_status(len(self._pending_images), hint=True))
        return True

    def _capture_status(self, count: int, *, hint: bool = False) -> str:
        if count == 1:
            text = "1 screenshot ready"
        else:
            text = f"{count} screenshots ready"
        if hint:
            text += " — Enter sends, the capture button adds another"
        return text

    def _rebuild_pending_row(self) -> None:
        for widget in self._pending_widgets:
            widget.setParent(None)
            widget.deleteLater()
        self._pending_widgets.clear()
        for index, encoded in enumerate(self._pending_images):
            thumb = _PendingThumb(encoded, index, self._thumb_row)
            thumb.remove_requested.connect(self._remove_capture)
            self._thumb_layout.insertWidget(self._thumb_layout.count() - 1, thumb)
            self._pending_widgets.append(thumb)
        self._thumb_row.setVisible(bool(self._pending_images))
        self._set_expanded_height(
            BAR_HEIGHT + (THUMB_ROW_HEIGHT if self._pending_images else 0)
        )

    def _set_expanded_height(self, height: int) -> None:
        self._expanded_height = height
        if not self._collapsed:
            self.setFixedSize(BAR_WIDTH, height)
            self._position_response()

    def _remove_capture(self, encoded: str) -> None:
        if encoded in self._pending_images:
            self._pending_images.remove(encoded)
        self._rebuild_pending_row()
        count = len(self._pending_images)
        if count:
            self.set_status(self._capture_status(count))
        else:
            self.set_status("screenshots cleared")

    def _clear_pending(self) -> None:
        self._pending_images = []
        self._rebuild_pending_row()

    def _take_pending_images(self) -> list[str]:
        images = list(self._pending_images)
        self._clear_pending()
        return images

    # ------------------------------------------------------------ submission #

    def _clear_attachments(self) -> None:
        for widget in self._attachment_widgets:
            widget.setParent(None)
            widget.deleteLater()
        self._attachment_widgets.clear()

    def _set_attachments(self, images_b64: list[str]) -> None:
        """Retain small previews of the screenshots sent with a vision request."""
        self._clear_attachments()
        shown = 0
        for index, encoded in enumerate(images_b64[:MAX_CAPTURES]):
            pixmap = pixmap_from_b64(encoded)
            if pixmap.isNull():
                continue
            label = QLabel(self._sent_attachment_host)
            label.setObjectName("thumb")
            label.setPixmap(_scaled_thumb(pixmap))
            label.setToolTip(f"screenshot {index + 1}")
            self._attachment_row.insertWidget(self._attachment_row.count() - 1, label)
            self._attachment_widgets.append(label)
            shown += 1
        hidden = len(images_b64) - shown
        if shown and hidden > 0:
            more = QLabel(f"+{hidden} more", self._sent_attachment_host)
            more.setObjectName("historyLabel")
            self._attachment_row.insertWidget(self._attachment_row.count() - 1, more)
            self._attachment_widgets.append(more)

    def submit_question(self, question: str, *, kind: str = "chat") -> None:
        """Ask a question; queued screenshots ride along as a vision request."""
        question = question.strip()
        images = self._take_pending_images()
        if not question and not images:
            return
        if images:
            self.submit_vision(question or self._settings.screenshot_prompt, images)
            return
        self._clear_attachments()

        language = self._language_combo.currentText()
        if language != "auto" and kind == "chat":
            question = f"{question}\n\n(If the answer contains code, write it in {language}.)"

        history = self._conversation_payload()
        self.cancel_stream()
        self._pending = {"question": question, "kind": "chat"}
        self._reset_answer_panel()
        self._streaming = True
        self.set_status("asking…")

        def stream(cancel, on_chunk):
            return self._api.chat_stream(
                question,
                conversation_history=history,
                context=self._context_provider(),
                on_chunk=on_chunk,
                cancel=cancel,
            )

        self._start_worker(stream)

    def submit_vision(self, prompt: str, images_b64: list[str]) -> None:
        if not images_b64:
            self.set_status("no image captured", error=True)
            return
        prompt = prompt.strip() or self._settings.screenshot_prompt
        self._set_attachments(images_b64)
        history = self._conversation_payload()
        self.cancel_stream()
        self._pending = {
            "question": f"[{len(images_b64)} screenshot(s)] {prompt}",
            "kind": "vision",
        }
        self._reset_answer_panel()
        self._streaming = True
        self.set_status("analysing screenshot…")

        def stream(cancel, on_chunk):
            return self._api.vision_stream(
                prompt,
                images_b64,
                conversation_history=history,
                context=self._context_provider(),
                on_chunk=on_chunk,
                cancel=cancel,
            )

        self._start_worker(stream)

    def _start_worker(self, stream) -> None:
        worker = StreamWorker(stream, self)
        worker.chunk.connect(self._on_chunk)
        worker.succeeded.connect(self._on_stream_succeeded)
        worker.failed.connect(self._on_stream_failed)
        worker.cancelled.connect(self._on_stream_cancelled)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()

    def cancel_stream(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(1500)
        self._worker = None
        self._streaming = False
        self._flush_timer.stop()
        self._preview.hide_now()

    def _conversation_payload(self) -> list[dict[str, str]]:
        payload: list[dict[str, str]] = []
        for index, item in enumerate(self._items):
            answer = item["answer"]
            if index == self._index and self._variant_language != "auto":
                answer = (item.get("variants") or {}).get(self._variant_language, answer)
            payload.append({"role": "user", "content": item["question"]})
            payload.append({"role": "assistant", "content": answer})
        return payload

    # -------------------------------------------------------------- streaming #

    def _on_chunk(self, text: str) -> None:
        if self.sender() is not self._worker:
            return  # stale chunk from a cancelled/replaced stream
        self._answer_buffer += text
        self._update_stream_preview()
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def _update_stream_preview(self) -> None:
        """Tease the streaming answer in the popup while answers are hidden."""
        if self._streaming and not self._answers_visible:
            self._preview.show_near(self, self._answer_buffer)
        elif self._answers_visible:
            self._preview.hide_now()

    def _render_answer(self, text: str | None = None, *, force: bool = False) -> None:
        """Render the buffered answer in the original Chromium answer view."""
        payload = self._answer_buffer if text is None else text
        self._update_language_selector(render.has_switchable_code(payload))
        if self._should_render_web(payload):
            view = self._ensure_web_view()
            if view is not None:
                if not view.is_ready():
                    render.render_into_web(view, payload, streaming=True)
                    self._show_text_answer(payload)
                    return
                now = time.monotonic()
                if (
                    not force
                    and self._web_visible
                    and now - self._last_web_render < WEB_FLUSH_INTERVAL
                ):
                    return  # a later flush (or the final one) picks up the newest text
                self._last_web_render = now
                if not self._web_visible:
                    self._answer_view.hide()
                    view.show()
                    self._web_visible = True
                if render.render_into_web(view, payload, streaming=not force and self._streaming):
                    return
        self._show_text_answer(payload)

    def _show_text_answer(self, payload: str) -> None:
        if self._web_visible and self._web_view is not None:
            self._web_view.hide()
            self._answer_view.show()
            self._web_visible = False
        render.render_into(self._answer_view, payload)

    def _should_render_web(self, text: str) -> bool:
        if not self._settings.web_render or not text or self._web_failed:
            return False
        return self._web_view is not None

    def _ensure_web_view(self):
        """Create the QtWebEngine view on first need; None disables rich rendering."""
        if self._web_view is not None or self._web_failed:
            return self._web_view
        try:
            from .webview import RichAnswerWebView, web_view_available

            if not web_view_available():
                raise RuntimeError("bundled KaTeX/mermaid assets are missing")
            view = RichAnswerWebView(self._response._content)
        except Exception as exc:  # noqa: BLE001 - fall back to the text view
            self._web_failed = True
            self.set_status(f"answer rendering unavailable: {exc}")
            return None
        view.ready_changed.connect(self._on_web_ready)
        self._response._content_layout.insertWidget(self._answer_view_index + 1, view, 1)
        view.hide()
        self._web_view = view
        return view

    def _on_web_ready(self, ready: bool) -> None:
        """Swap the answer into the web view once its assets have loaded."""
        if not ready:
            self._web_failed = True
            self._show_text_answer(self._answer_buffer)
            if not self._answer_buffer:
                self._show_welcome_message()
            return
        if self._should_render_web(self._answer_buffer):
            self._render_answer(force=True)

    def _show_welcome_message(self) -> None:
        """Show the original help table on a fresh answer window."""
        try:
            from .webview import welcome_fragment

            fragment = welcome_fragment(self._settings.hotkeys)
        except Exception:  # noqa: BLE001 - welcome is optional
            return
        if self._web_view is not None and self._web_visible:
            self._web_view.set_content(fragment)
        else:
            self._answer_view.setHtml(fragment)

    def _reset_answer_panel(self) -> None:
        """Clear the answer surface, keeping the original web renderer active."""
        self._answer_buffer = ""
        self._answer_view.clear()
        if self._web_view is not None:
            self._web_view.clear_content()
            if not self._web_visible:
                self._answer_view.hide()
                self._web_view.show()
                self._web_visible = True
        else:
            self._answer_view.show()
        self._update_language_selector(False)
        if self._answers_visible and self.isVisible():
            self._position_response()
            self._response.show()
            self._response.raise_()
            self.raise_()

    def _flush_answer(self, *, force: bool = False) -> None:
        scrollbar = self._answer_view.verticalScrollBar()
        at_bottom = scrollbar is not None and scrollbar.value() >= scrollbar.maximum() - 4
        self._render_answer(force=force)
        self._update_language_selector()
        if at_bottom and scrollbar is not None and not self._web_visible:
            scrollbar.setValue(scrollbar.maximum())
        if force:
            self._flush_timer.stop()

    def _on_stream_succeeded(self, answer: str) -> None:
        if self.sender() is not self._worker:
            return
        pending = self._pending or {"question": "", "kind": "chat"}
        if pending.get("rewrite"):
            self._on_rewrite_done(answer)
            return
        self._on_answer_done(pending["question"], answer, kind=pending["kind"])

    def _on_stream_failed(self, message: str) -> None:
        if self.sender() is not self._worker:
            return
        pending = self._pending or {"question": "", "kind": "chat"}
        if pending.get("rewrite"):
            self._on_rewrite_error(message)
            return
        self._on_stream_error(pending["question"], message)

    def _on_stream_cancelled(self) -> None:
        if self.sender() is not self._worker:
            return
        self._streaming = False
        self._worker = None
        self._preview.hide_soon()
        self.set_status("cancelled")

    def _on_answer_done(self, question: str, answer: str, *, kind: str) -> None:
        self._streaming = False
        self._worker = None
        self._answer_buffer = answer or self._answer_buffer
        self._flush_answer(force=True)
        self._preview.hide_soon()
        self.set_status("done")

        if self._answer_buffer.strip():
            item = {
                "question": question,
                "answer": self._answer_buffer,
                "kind": kind,
            }
            self._items.append(item)
            self._index = len(self._items) - 1
            self._update_position_label()
            self._conversations.add_item(question, self._answer_buffer, kind)

        self._variant_language = "auto"
        self._rewrite_item = None
        self._select_language("auto")

    def _on_stream_error(self, question: str, message: str) -> None:
        self._streaming = False
        self._worker = None
        self._flush_answer(force=True)
        self._preview.hide_soon()
        self.set_status(f"error: {message}", error=True)
        if self._answer_buffer.strip():
            self._render_answer(
                self._answer_buffer + "\n\n---\n" + f"*stream interrupted: {message}*",
                force=True,
            )
            self._items.append(
                {"question": question, "answer": self._answer_buffer, "kind": "chat"}
            )
            self._index = len(self._items) - 1
            self._update_position_label()

    # ------------------------------------------------------ language variants #

    def _on_language_changed(self, _index: int = 0) -> None:
        """The code-language combo: rewrite the shown answer, or aim the next one."""
        if self._language_combo.signalsBlocked():
            return
        target = self._language_combo.currentText()
        if target == self._variant_language:
            return
        if self._streaming:
            self.set_status("answer still streaming")
            self._select_language(self._variant_language)
            return
        if not self._items or self._index < 0:
            return
        item = self._items[self._index]
        if target == "auto":
            self._show_variant("auto", item["answer"])
            return
        variants = item.get("variants") or {}
        if target in variants:
            self._show_variant(target, variants[target], cached=True)
            return
        self._start_rewrite(item, target)

    def _select_language(self, language: str) -> None:
        """Set the combo without invoking the switcher."""
        self._language_combo.blockSignals(True)
        self._language_combo.setCurrentText(language)
        self._language_combo.blockSignals(False)
        self._update_language_selector()

    def _set_language(self, language: str) -> None:
        """Choose a code language from the bar buttons or the context menu."""
        self._language_combo.setCurrentText(language)

    def _update_language_selector(self, visible: bool | None = None) -> None:
        """Show the original four-button selector for answers containing code."""
        if not hasattr(self, "_language_selector"):
            return
        if visible is None:
            visible = render.has_switchable_code(self._answer_buffer)
        self._language_selector.setVisible(bool(visible))
        for language, button in self._language_buttons.items():
            active = language == self._variant_language
            if button.property("active") == active:
                continue
            button.setProperty("active", active)
            button.style().unpolish(button)
            button.style().polish(button)

    def _show_variant(self, language: str, text: str, *, cached: bool = False) -> None:
        self._variant_language = language
        self._answer_buffer = text
        self._render_answer(force=True)
        self._update_language_selector()
        if language == "auto":
            self.set_status("showing the original answer")
        elif cached:
            self.set_status(f"{language} variant (cached)")
        else:
            self.set_status(f"{language} variant ready")

    def _start_rewrite(self, item: dict[str, Any], language: str) -> None:
        """Re-ask the model to write one existing answer's code in ``language``."""
        question = item["question"]
        self.cancel_stream()
        self._pending = {"question": question, "kind": "chat", "rewrite": language}
        self._rewrite_item = item
        self._reset_answer_panel()
        self._streaming = True
        self.set_status(f"rewriting in {language}…")

        def stream(cancel, on_chunk):
            return self._api.chat_stream(
                rewrite_answer_prompt(question, item["answer"], language),
                conversation_history=[],
                context="",
                on_chunk=on_chunk,
                cancel=cancel,
            )

        self._start_worker(stream)

    def _on_rewrite_done(self, answer: str) -> None:
        self._streaming = False
        self._worker = None
        self._preview.hide_soon()
        item = self._rewrite_item
        self._rewrite_item = None
        language = (self._pending or {}).get("rewrite") or ""
        text = answer or self._answer_buffer
        if item is None or item not in self._items or not language or not text.strip():
            if item is not None:
                self._restore_base_answer(item)
            self.set_status("rewrite failed", error=True)
            return
        item.setdefault("variants", {})[language] = text
        self._conversations.set_variant(item["question"], item["answer"], language, text)
        if 0 <= self._index < len(self._items) and self._items[self._index] is item:
            self._variant_language = language
            self._select_language(language)
            self._answer_buffer = text
            self._flush_answer(force=True)
        self.set_status(f"{language} variant ready")

    def _on_rewrite_error(self, message: str) -> None:
        self._streaming = False
        self._worker = None
        self._flush_answer(force=True)
        self._preview.hide_soon()
        item = self._rewrite_item
        self._rewrite_item = None
        if item is not None:
            self._restore_base_answer(item)
        self.set_status(f"error: {message}", error=True)

    def _restore_base_answer(self, item: dict[str, Any]) -> None:
        """Put the untouched answer back after a failed rewrite."""
        if not (0 <= self._index < len(self._items)) or self._items[self._index] is not item:
            return
        self._variant_language = "auto"
        self._select_language("auto")
        self._answer_buffer = item["answer"]
        self._render_answer(force=True)
        self._update_language_selector()

    # --------------------------------------------------------------- history #

    def _update_position_label(self) -> None:
        if not self._items or self._index < 0:
            self._position_label.setText("")
        else:
            self._position_label.setText(f"{self._index + 1}/{len(self._items)}")

    def show_previous(self) -> None:
        if not self._items:
            return
        self._index = max(0, self._index - 1)
        self._show_index()

    def show_next(self) -> None:
        if not self._items:
            return
        self._index = min(len(self._items) - 1, self._index + 1)
        self._show_index()

    def _show_index(self) -> None:
        item = self._items[self._index]
        self._variant_language = "auto"
        self._select_language("auto")
        self._answer_buffer = item["answer"]
        self._render_answer(force=True)
        self._update_position_label()

    def load_items(self, items: list[dict[str, Any]]) -> None:
        """Seed the in-memory history (used when opening the history dialog)."""
        self._items = list(items)
        self._index = len(self._items) - 1
        self._variant_language = "auto"
        self._select_language("auto")
        self._update_position_label()

    # ------------------------------------------------------------ misc verbs #

    def toggle_collapse(self) -> None:
        self.set_answers_visible(not self._answers_visible)

    def set_collapsed(self, collapsed: bool) -> None:
        self.set_answers_visible(not collapsed)

    def set_answers_visible(self, visible: bool) -> None:
        """Show or hide the answer window, collapsing the bar to a logo disc."""
        if visible == self._answers_visible:
            return
        self._answers_visible = visible
        self._response.setMaximumHeight(_WIDGET_SIZE_MAX)

        if visible:
            self._expand_bar()
            if self.isVisible():
                self._position_response()
                self._response.setWindowOpacity(self.windowOpacity())
                self._response.show()
                self._response.raise_()
                self.raise_()
            self._preview.hide_now()
        else:
            self._response.hide()
            self._preview.hide_now()
            self._collapse_bar()
            if self._streaming:
                self._preview.show_near(self, self._answer_buffer)

        self._collapse_button.setText("\u25be" if visible else "\u25b8")

    def _collapse_bar(self) -> None:
        if not self._collapsed:
            self._expanded_height = max(self.height(), BAR_HEIGHT)
        self._collapsed = True
        self._content.hide()
        self._collapsed_logo.show()
        self.setFixedSize(COLLAPSED_SIZE, COLLAPSED_SIZE)
        self._apply_bar_mask()
        self.update()

    def _expand_bar(self) -> None:
        self._collapsed = False
        self._content.show()
        self._collapsed_logo.hide()
        self.setFixedSize(BAR_WIDTH, self._expanded_height)
        self._apply_bar_mask()
        self.update()

    # ------------------------------------------------------------ click-through #

    def toggle_click_through(self) -> None:
        """Pass the mouse through to the app underneath (hotkey switches back)."""
        self.set_click_through_enabled(not self._click_through)

    def set_click_through_enabled(self, enabled: bool) -> None:
        if enabled == self._click_through:
            return
        hotkey = self._settings.hotkeys.get("click_through", "")
        if enabled and not hotkey:
            self.set_status(
                "click-through needs a hotkey to switch back — set one in Settings",
                error=True,
            )
            return
        windows = [self, self._response]
        results = [stealth.set_click_through(window, enabled) for window in windows]
        if not all(results):
            for window in windows:
                stealth.set_click_through(window, False)
            self._click_button.setChecked(False)
            self.set_status("click-through is unavailable on this system", error=True)
            return
        self._click_through = enabled
        self._click_button.setChecked(enabled)
        if enabled:
            self.set_status(f"click-through on — {hotkey} returns control")
        else:
            self.set_status("click-through off")

    def fade_in(self) -> None:
        """Fade the overlay in at startup (harmlessly ignored where unsupported)."""
        if self._opacity_animation is not None:
            self._opacity_animation.stop()
        self.setWindowOpacity(0.0)
        self._response.set_content_opacity(0.0)
        animation = QPropertyAnimation(self, b"windowOpacity", self)
        animation.setDuration(FADE_IN_MS)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        animation.setStartValue(0.0)
        animation.setEndValue(self._settings.opacity)
        animation.valueChanged.connect(
            lambda value: self._response.set_content_opacity(float(value))
        )
        self._opacity_animation = animation
        animation.start()

    def nudge_opacity(self, delta: float) -> None:
        if self._opacity_animation is not None:
            self._opacity_animation.stop()
        value = min(max(self.windowOpacity() + delta, 0.3), 1.0)
        self.setWindowOpacity(value)
        self._response.set_content_opacity(value)
        self._settings.opacity = value
        self._settings.save()
        self.set_status(f"opacity {int(value * 100)}%")

    def nudge_move(self, dx: int, dy: int) -> None:
        self.move(self.x() + dx, self.y() + dy)

    def nudge_scroll(self, pixels: int) -> None:
        if self._web_visible and self._web_view is not None:
            self._web_view.scroll_by(pixels)
            return
        scrollbar = self._answer_view.verticalScrollBar()
        if scrollbar is not None:
            scrollbar.setValue(scrollbar.value() + pixels)

    def ask_hotkey(self) -> None:
        """Submit the manual box, else the transcript box, else queued screenshots."""
        question = self._manual_input.text().strip() or self._stt_input.text().strip()
        if question:
            self._manual_input.clear()
            self.submit_question(question)
            return
        if self._pending_images:
            self.submit_vision(self._settings.screenshot_prompt, self._take_pending_images())

    def report_api_error(self, error: Exception) -> None:
        message = str(error) if isinstance(error, ApiError) else f"unexpected error: {error}"
        self.set_status(message, error=True)

    # --------------------------------------------------------------- menus #

    def _show_stt_menu(self) -> None:
        menu = QMenu(self)
        recent = [item.get("question", "") for item in self._items[-8:]]
        if recent:
            for question in reversed(recent):
                label = question.replace("\n", " ")[:70]
                action = menu.addAction(label)
                action.triggered.connect(
                    lambda _checked=False, text=question: self._stt_input.setText(text)
                )
            menu.addSeparator()
        else:
            empty = menu.addAction("No recent questions")
            empty.setEnabled(False)
            menu.addSeparator()
        menu.addAction("Open history…", self.history_requested.emit)
        menu.addAction("Clear", self.erase)
        menu.exec(self._stt_input.mapToGlobal(QPoint(0, self._stt_input.height() + 2)))

    def _show_stt_context_menu(self, pos: QPoint) -> None:
        menu = self._stt_input.createStandardContextMenu()
        menu.addSeparator()
        menu.addAction("Open history…", self.history_requested.emit)
        menu.exec(self._stt_input.mapToGlobal(pos))

    def _show_manual_context_menu(self, pos: QPoint) -> None:
        menu = self._manual_input.createStandardContextMenu()
        menu.addSeparator()
        menu.addAction("Open history…", self.history_requested.emit)
        menu.exec(self._manual_input.mapToGlobal(pos))

    def _show_logo_menu(self, pos: QPoint) -> None:
        menu = QMenu(self)
        menu.addAction("Interview details…", self.info_requested.emit)
        menu.addAction("History…", self.history_requested.emit)
        menu.addAction("Settings…", self.settings_requested.emit)
        menu.addSeparator()
        menu.addAction("Hide answers", self.toggle_collapse)
        menu.addAction("Quit", self.close)
        menu.exec(self._logo.mapToGlobal(pos))

    def _answer_context_menu(self, pos: QPoint) -> None:
        menu = self._answer_view.createStandardContextMenu()
        menu.addSeparator()
        menu.addAction("Copy full answer", self._copy_answer)
        rewrite = menu.addMenu("Rewrite code in")
        for language in CODE_LANGUAGES[1:]:
            action = rewrite.addAction(language)
            action.triggered.connect(
                lambda _checked=False, name=language: self._set_language(name)
            )
        menu.addSeparator()
        menu.addAction("Interview details…", self.info_requested.emit)
        menu.addAction("History…", self.history_requested.emit)
        menu.addAction("Settings…", self.settings_requested.emit)
        menu.exec(self._answer_view.mapToGlobal(pos))

    # ------------------------------------------------------------------ info #

    def set_api(self, api: ApiClient) -> None:
        self._api = api

    def apply_settings(self, settings: AppSettings) -> None:
        """Pick up settings changed in the dialog."""
        self._settings = settings
        self.setWindowOpacity(settings.opacity)
        self._response.set_content_opacity(settings.opacity)
        self.retranslate()
        self._refresh_devices()
