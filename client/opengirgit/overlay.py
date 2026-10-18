"""The overlay: frameless, always-on-top control bar + streaming answer panel."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizeGrip,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from . import render, stealth
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
PANEL_ANIM_MS = 170  # collapse/expand slide duration
FADE_IN_MS = 220  # startup fade duration
_WIDGET_SIZE_MAX = 16777215

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

_STYLE_SHEET = """
QWidget#root { background-color: rgba(18, 18, 18, 240); border: 1px solid rgba(255,255,255,90);
               border-radius: 10px; font-size: 12px; }
QFrame#bar { background: transparent; }
QLabel { color: #e8e8e8; }
QLabel#status { color: #9ad0ff; font-size: 11px; }
QLabel#status[error="true"] { color: #ff7b7b; }
QLabel#answer_title { color: #cfcfcf; font-size: 12px; font-weight: 600; letter-spacing: 0.4px; }
QLabel#code_label { color: #9a9a9a; font-size: 11px; }
QLabel#thumb { background: #141414; border: 1px solid #4a4a4a; border-radius: 6px; padding: 1px; }
QLineEdit { background: #111111; color: #ffffff; border: 1px solid #4a4a4a; border-radius: 5px;
            padding: 5px 7px; selection-background-color: #2f5f8f; }
QLineEdit:hover { border-color: #5a5a5a; }
QLineEdit:focus { border: 1px solid #7ab7ff; }
QPushButton { background: #2f2f2f; color: #f0f0f0; border: 1px solid #4a4a4a; border-radius: 5px;
              padding: 5px 9px; }
QPushButton:hover { background: #3c3c3c; border-color: #5a5a5a; }
QPushButton:pressed { background: #262626; }
QPushButton:checked { background: #1f5f3f; border-color: #46c07e; color: #dcffe9; }
QPushButton:disabled { color: #808080; border-color: #3a3a3a; }
QPushButton#icon { font-size: 13px; padding: 4px 0px; }
QComboBox { background: #111111; color: #f0f0f0; border: 1px solid #4a4a4a; border-radius: 5px;
            padding: 4px 6px; }
QComboBox:hover { border-color: #5a5a5a; }
QComboBox QAbstractItemView { background: #1c1c1c; color: #f0f0f0; border: 1px solid #4a4a4a;
                              selection-background-color: #2f5f8f; }
QTextBrowser { background: rgba(26, 26, 26, 235); color: #f2f2f2; border: 1px solid #3a3a3a;
               border-radius: 6px; padding: 8px; selection-background-color: #2f5f8f; }
QScrollBar:vertical { background: #1a1a1a; width: 10px; border-radius: 5px; margin: 0px; }
QScrollBar::handle:vertical { background: #555555; border-radius: 5px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: #6a6a6a; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QScrollBar:horizontal { background: #1a1a1a; height: 10px; border-radius: 5px; margin: 0px; }
QScrollBar::handle:horizontal { background: #555555; border-radius: 5px; min-width: 24px; }
QScrollBar::handle:horizontal:hover { background: #6a6a6a; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; }
QPushButton#thumb_remove { background: rgba(24, 24, 24, 220); color: #ff9b9b; border: 1px solid #5a5a5a;
                           border-radius: 8px; padding: 0px; font-size: 10px; }
QPushButton#thumb_remove:hover { background: #7a2b2b; color: #ffffff; }
QToolTip { background-color: #202020; color: #f0f0f0; border: 1px solid #4a4a4a; padding: 4px 6px; }
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
        remove.setObjectName("thumb_remove")
        remove.setFixedSize(16, 16)
        remove.move(size - 18, 2)
        remove.setToolTip("remove this screenshot")
        remove.clicked.connect(lambda: self.remove_requested.emit(self._encoded))


class OverlayWindow(QWidget):
    """The whole UI lives here: control bar + answer panel in one window."""

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
        flags = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        super().__init__(parent, flags)
        self.setWindowTitle("OpenGirGit")
        self.setObjectName("root")
        self.setStyleSheet(_STYLE_SHEET)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMinimumWidth(560)
        self.setWindowOpacity(settings.opacity)

        self._api = api
        self._settings = settings
        self._conversations = conversations
        self._context_provider = context_provider

        self._worker: StreamWorker | None = None
        self._answer_buffer = ""
        self._streaming = False
        self._pending: dict[str, str] | None = None
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

        # Collapse/expand is animated; the end state is what callers observe.
        self._answers_visible = True
        self._panel_animation: QPropertyAnimation | None = None
        self._opacity_animation: QPropertyAnimation | None = None

        # Teaser popup for the streaming answer while the panel is collapsed.
        self._preview = StreamPreview(self)

        # Screenshots queue up and attach to the next question (like the original).
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

        self._build_ui()
        self._refresh_devices()

    # ------------------------------------------------------------------ UI #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(4)

        self._bar = QFrame(self)
        self._bar.setObjectName("bar")
        bar_layout = QVBoxLayout(self._bar)
        bar_layout.setContentsMargins(8, 6, 8, 4)
        bar_layout.setSpacing(5)

        # -- row 1: mic / device / status / navigation ---------------------- #
        row1 = QHBoxLayout()
        row1.setSpacing(6)

        self._mic_button = QPushButton("🎙")
        self._mic_button.setObjectName("icon")
        self._mic_button.setCheckable(True)
        self._mic_button.toggled.connect(self._on_mic_toggled)
        row1.addWidget(self._mic_button)

        self._device_combo = QComboBox()
        self._device_combo.setMinimumWidth(180)
        self._device_combo.currentIndexChanged.connect(self._on_device_changed)
        row1.addWidget(self._device_combo)

        self._status_text = "idle"
        self._status = QLabel(self._status_text)
        self._status.setObjectName("status")
        row1.addWidget(self._status, 1)

        def _nav_button(text: str, slot) -> QPushButton:
            button = QPushButton(text)
            button.setObjectName("icon")
            button.setFixedWidth(30)
            button.clicked.connect(slot)
            row1.addWidget(button)
            return button

        self._click_button = _nav_button("🖱", self.toggle_click_through)
        self._click_button.setCheckable(True)
        self._info_button = _nav_button("🗂", self.info_requested.emit)
        self._history_button = _nav_button("🕘", self.history_requested.emit)
        self._settings_button = _nav_button("⚙", self.settings_requested.emit)
        self._collapse_button = _nav_button("▾", self.toggle_collapse)
        self._quit_button = _nav_button("✕", self.close)

        bar_layout.addLayout(row1)

        # -- row 2: transcript / manual question / actions ------------------ #
        row2 = QHBoxLayout()
        row2.setSpacing(6)

        self._stt_input = QLineEdit()
        self._stt_input.returnPressed.connect(self._submit_stt_box)
        row2.addWidget(self._stt_input, 3)

        self._ask_button = QPushButton("Ask")
        self._ask_button.clicked.connect(self.submit_manual)
        row2.addWidget(self._ask_button)

        self._manual_input = QLineEdit()
        self._manual_input.returnPressed.connect(self.submit_manual)
        row2.addWidget(self._manual_input, 3)

        def _action_button(text: str, slot) -> QPushButton:
            button = QPushButton(text)
            button.setObjectName("icon")
            button.setFixedWidth(34)
            button.clicked.connect(slot)
            row2.addWidget(button)
            return button

        self._screenshot_button = _action_button("📷", self.screenshot_requested.emit)
        self._erase_button = _action_button("⌫", self.erase)
        self._opacity_down_button = _action_button("−", lambda: self.nudge_opacity(-OPACITY_STEP))
        self._opacity_up_button = _action_button("+", lambda: self.nudge_opacity(OPACITY_STEP))

        bar_layout.addLayout(row2)
        root.addWidget(self._bar)

        # -- answer panel --------------------------------------------------- #
        self._answer_panel = QFrame(self)
        answer_layout = QVBoxLayout(self._answer_panel)
        answer_layout.setContentsMargins(8, 2, 8, 8)
        answer_layout.setSpacing(4)

        header = QHBoxLayout()
        self._title_label = QLabel("Answer")
        self._title_label.setObjectName("answer_title")
        header.addWidget(self._title_label)
        header.addStretch(1)

        self._code_label = QLabel("code:")
        self._code_label.setObjectName("code_label")
        header.addWidget(self._code_label)
        self._language_combo = QComboBox()
        self._language_combo.addItems(CODE_LANGUAGES)
        self._language_combo.currentIndexChanged.connect(self._on_language_changed)
        header.addWidget(self._language_combo)

        self._copy_button = QPushButton("copy")
        self._copy_button.clicked.connect(self._copy_answer)
        header.addWidget(self._copy_button)

        self._position_label = QLabel("")
        self._position_label.setObjectName("status")
        header.addWidget(self._position_label)
        answer_layout.addLayout(header)

        separator = QFrame(self._answer_panel)
        separator.setFixedHeight(1)
        separator.setStyleSheet("background: #3a3a3a; border: none;")
        answer_layout.addWidget(separator)

        # -- screenshot thumbnails (queued captures / sent with an answer) -- #
        self._attachment_row = QHBoxLayout()
        self._attachment_row.setSpacing(6)
        self._attachment_row.addStretch(1)
        self._attachment_widgets: list[QWidget] = []
        answer_layout.addLayout(self._attachment_row)

        self._answer_view = QTextBrowser()
        self._answer_view.setOpenExternalLinks(True)
        self._answer_view.setMinimumHeight(150)
        answer_layout.addWidget(self._answer_view, 1)
        self._answer_layout = answer_layout
        self._answer_view_index = answer_layout.indexOf(self._answer_view)

        grip_row = QHBoxLayout()
        grip_row.addStretch(1)
        grip_row.addWidget(QSizeGrip(self._answer_panel))
        answer_layout.addLayout(grip_row)

        root.addWidget(self._answer_panel, 1)
        self.retranslate()

    def retranslate(self) -> None:
        """(Re)apply the active language to the static interface texts."""
        self._mic_button.setToolTip("Listen to system audio / microphone")
        self._device_combo.setToolTip("Audio device to listen to")
        self._click_button.setToolTip(
            "Click-through — clicks work through to the app underneath ({hotkey})".format(
                hotkey=self._settings.hotkeys.get("click_through", "")
            )
        )
        self._info_button.setToolTip("Interview details (resume, JD, company)")
        self._history_button.setToolTip("History")
        self._settings_button.setToolTip("Settings")
        self._collapse_button.setToolTip("Collapse / expand answers")
        self._quit_button.setToolTip("Quit")

        self._stt_input.setPlaceholderText("interviewer's words appear here…")
        self._ask_button.setText("Ask")
        self._ask_button.setToolTip(
            "Ask with the manual box ({hotkey})".format(
                hotkey=self._settings.hotkeys.get("ask", "Shift+Alt+A")
            )
        )
        self._manual_input.setPlaceholderText("type your own question…")
        self._screenshot_button.setToolTip("Screenshot a region (repeat to attach several)")
        self._erase_button.setToolTip("Erase inputs and answer")
        self._opacity_down_button.setToolTip("Opacity down")
        self._opacity_up_button.setToolTip("Opacity up")

        self._title_label.setText("Answer")
        self._code_label.setText("code:")
        self._language_combo.setToolTip(
            "Prefer this language for code, or rewrite the current answer in it"
        )
        self._copy_button.setText("copy")
        self._copy_button.setToolTip("Copy the answer")
        self._update_position_label()

    # ------------------------------------------------------------ lifecycle #

    def showEvent(self, event) -> None:  # noqa: D102
        super().showEvent(event)
        stealth.apply_stealth(self)

    def closeEvent(self, event) -> None:  # noqa: D102
        self.cancel_stream()
        for animation in (self._panel_animation, self._opacity_animation):
            if animation is not None:
                animation.stop()
        self._preview.hide_now(immediate=True)
        self.closed.emit()
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: D102
        super().resizeEvent(event)
        self._apply_status_text()
        self._preview.reposition(self)

    def moveEvent(self, event) -> None:  # noqa: D102
        super().moveEvent(event)
        self._preview.reposition(self)

    def keyPressEvent(self, event) -> None:  # noqa: D102
        if event.key() == Qt.Key_Escape:
            self.erase()
        else:
            super().keyPressEvent(event)

    # ------------------------------------------------------------- dragging #

    def mousePressEvent(self, event) -> None:  # noqa: D102
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: D102
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

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
            self._device_combo.addItem("(no audio devices found)", "")
        index = max(self._device_combo.findData(current), 0)
        self._device_combo.setCurrentIndex(index)
        self._device_combo.blockSignals(False)

        if not current and devices:
            chosen = next((d for d in devices if d.is_default), devices[0])
            self._settings.audio_device = chosen.id
            self._settings.save()

    def _on_device_changed(self, _index: int) -> None:
        device_id = self._device_combo.currentData() or ""
        if device_id and device_id != self._settings.audio_device:
            self._settings.audio_device = device_id
            self._settings.save()
            if self._mic_button.isChecked():
                self.set_status("device changed — restarting capture…")
                self._mic_button.setChecked(False)
                self._mic_button.setChecked(True)

    def _on_mic_toggled(self, checked: bool) -> None:
        self._mic_button.setText("⏹" if checked else "🎙")
        self.set_status("starting capture…" if checked else "idle")
        self.mic_toggled.emit(checked)

    def set_mic_active(self, active: bool) -> None:
        """Reflect an externally-forced mic state (e.g. capture error)."""
        self._mic_button.blockSignals(True)
        self._mic_button.setChecked(active)
        self._mic_button.setText("⏹" if active else "🎙")
        self._mic_button.blockSignals(False)

    # ------------------------------------------------------------- statuses #

    def set_status(self, text: str, *, error: bool = False) -> None:
        self._status_text = text
        self._status.setToolTip("")
        self._apply_status_text()
        self._status.setProperty("error", "true" if error else "false")
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)

    def _apply_status_text(self) -> None:
        """Show the status, eliding it when space runs out (full text as tooltip)."""
        text = getattr(self, "_status_text", "")
        if not text or not self.isVisible():
            self._status.setText(text)
            return
        available = max(80, self._status.width() - 6)
        elided = self._status.fontMetrics().elidedText(text, Qt.ElideRight, available)
        self._status.setText(elided)
        if elided != text:
            self._status.setToolTip(text)

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
            self._clear_attachments()  # a new question starts; drop the old previews
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
            text += " — " + "Ask/Enter sends, 📷 adds another"
        return text

    def _rebuild_pending_row(self) -> None:
        for widget in self._pending_widgets:
            widget.setParent(None)
            widget.deleteLater()
        self._pending_widgets.clear()
        for index, encoded in enumerate(self._pending_images):
            thumb = _PendingThumb(encoded, index, self._answer_panel)
            thumb.remove_requested.connect(self._remove_capture)
            self._attachment_row.insertWidget(self._attachment_row.count() - 1, thumb)
            self._pending_widgets.append(thumb)

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
        """Show small previews of the screenshots sent with a vision request."""
        self._clear_attachments()
        shown = 0
        for index, encoded in enumerate(images_b64[:MAX_CAPTURES]):
            pixmap = pixmap_from_b64(encoded)
            if pixmap.isNull():
                continue
            label = QLabel()
            label.setObjectName("thumb")
            label.setPixmap(_scaled_thumb(pixmap))
            label.setToolTip(f"screenshot {index + 1}")
            self._attachment_row.insertWidget(self._attachment_row.count() - 1, label)
            self._attachment_widgets.append(label)
            shown += 1
        hidden = len(images_b64) - shown
        if shown and hidden > 0:
            more = QLabel(f"+{hidden} more")
            more.setObjectName("status")
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
        """Tease the streaming answer in the popup while the panel is collapsed."""
        if self._streaming and not self._answers_visible:
            self._preview.show_near(self, self._answer_buffer)
        elif self._answers_visible:
            self._preview.hide_now()

    def _render_answer(self, text: str | None = None, *, force: bool = False) -> None:
        """Render the buffered answer; math/mermaid answers use the web view."""
        payload = self._answer_buffer if text is None else text
        if self._should_render_web(payload):
            view = self._ensure_web_view()
            if view is not None:
                if not view.is_ready():
                    # The embedded browser is still loading its bundled assets.
                    # Keep the plain renderer visible (it re-renders when the
                    # page reports ready) and hand the fragment over meanwhile.
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
        return render.needs_web_view(text)

    def _ensure_web_view(self):
        """Create the QtWebEngine view on first need; None disables rich rendering."""
        if self._web_view is not None or self._web_failed:
            return self._web_view
        try:
            from .webview import RichAnswerWebView, web_view_available

            if not web_view_available():
                raise RuntimeError("bundled KaTeX/mermaid assets are missing")
            view = RichAnswerWebView(self._answer_panel)
        except Exception as exc:  # noqa: BLE001 - fall back to the text view
            self._web_failed = True
            self.set_status(f"math/diagram rendering unavailable: {exc}")
            return None
        view.ready_changed.connect(self._on_web_ready)
        self._answer_layout.insertWidget(self._answer_view_index + 1, view, 1)
        view.hide()
        self._web_view = view
        return view

    def _on_web_ready(self, ready: bool) -> None:
        """Swap the answer into the web view once its assets have loaded."""
        if not ready:
            self._web_failed = True  # page never loaded: stay on the text view
        if self._should_render_web(self._answer_buffer):
            self._render_answer(force=True)

    def _reset_answer_panel(self) -> None:
        """Clear both renderers and show the text view again."""
        self._answer_buffer = ""
        self._answer_view.clear()
        if self._web_view is not None:
            self._web_view.clear_content()
        if self._web_visible:
            self._web_visible = False
            self._web_view.hide()
            self._answer_view.show()

    def _flush_answer(self, *, force: bool = False) -> None:
        scrollbar = self._answer_view.verticalScrollBar()
        at_bottom = scrollbar is not None and scrollbar.value() >= scrollbar.maximum() - 4
        self._render_answer(force=force)
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

        # A fresh answer starts on the original variant; a pick before asking
        # was an instruction for that question and has done its job.
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
            return  # no answer yet — the pick rides along with the next question
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

    def _show_variant(self, language: str, text: str, *, cached: bool = False) -> None:
        self._variant_language = language
        self._answer_buffer = text
        self._render_answer(force=True)
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
        """Collapse or expand the answer panel with a short slide animation."""
        if visible == self._answers_visible:
            return
        self._answers_visible = visible
        panel = self._answer_panel

        if visible:
            panel.setVisible(True)
            start, end = 0, max(panel.sizeHint().height(), panel.height())
        else:
            start, end = panel.height(), 0

        if self._panel_animation is not None:
            self._panel_animation.stop()
        animation = QPropertyAnimation(panel, b"maximumHeight", self)
        animation.setDuration(PANEL_ANIM_MS)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.valueChanged.connect(self._grow_window_for_panel)
        animation.finished.connect(lambda: self._on_panel_animated(visible))
        self._panel_animation = animation
        animation.start()

        self._collapse_button.setText("▾" if visible else "▸")
        if visible:
            self._preview.hide_now()
        elif self._streaming:
            self._preview.show_near(self, self._answer_buffer)

    def _grow_window_for_panel(self, _value: float | None = None) -> None:
        """Let the top-level follow the expanding panel without ever shrinking."""
        needed = self.sizeHint().height()
        if needed > self.height():
            self.resize(self.width(), needed)

    def _on_panel_animated(self, visible: bool) -> None:
        panel = self._answer_panel
        panel.setMaximumHeight(_WIDGET_SIZE_MAX)
        if visible:
            self.adjustSize()
        else:
            panel.setVisible(False)
            self.adjustSize()
            self.resize(self.width(), self.minimumSizeHint().height())

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
        if not stealth.set_click_through(self, enabled):
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
        animation = QPropertyAnimation(self, b"windowOpacity", self)
        animation.setDuration(FADE_IN_MS)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        animation.setStartValue(0.0)
        animation.setEndValue(self._settings.opacity)
        self._opacity_animation = animation
        animation.start()

    def nudge_opacity(self, delta: float) -> None:
        if self._opacity_animation is not None:
            self._opacity_animation.stop()  # a user nudge beats the startup fade
        value = min(max(self.windowOpacity() + delta, 0.3), 1.0)
        self.setWindowOpacity(value)
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

    # ------------------------------------------------------------------ info #

    def set_api(self, api: ApiClient) -> None:
        self._api = api

    def apply_settings(self, settings: AppSettings) -> None:
        """Pick up settings changed in the dialog."""
        self._settings = settings
        self.setWindowOpacity(settings.opacity)
        self.retranslate()
        self._refresh_devices()
