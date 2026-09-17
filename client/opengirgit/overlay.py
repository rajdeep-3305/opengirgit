"""The overlay: frameless, always-on-top control bar + streaming answer panel."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
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

from . import stealth
from .api import ApiClient, ApiError
from .audio import list_devices
from .config import AppSettings
from .stores import ConversationStore
from .workers import StreamWorker

STREAM_FLUSH_MS = 120
MOVE_STEP = 24
SCROLL_STEP = 80
OPACITY_STEP = 0.05

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
               border-radius: 10px; }
QFrame#bar { background: transparent; }
QLabel { color: #e8e8e8; }
QLabel#status { color: #9ad0ff; font-size: 11px; }
QLabel#status[error="true"] { color: #ff7b7b; }
QLabel#answer_title { color: #cfcfcf; font-size: 12px; font-weight: 600; }
QLineEdit { background: #111111; color: #ffffff; border: 1px solid #4a4a4a; border-radius: 5px;
            padding: 5px 7px; }
QLineEdit:focus { border: 1px solid #7ab7ff; }
QPushButton { background: #2f2f2f; color: #f0f0f0; border: 1px solid #4a4a4a; border-radius: 5px;
              padding: 5px 9px; }
QPushButton:hover { background: #3c3c3c; }
QPushButton:pressed { background: #262626; }
QPushButton:checked { background: #1f5f3f; border-color: #46c07e; }
QPushButton:disabled { color: #808080; }
QComboBox { background: #111111; color: #f0f0f0; border: 1px solid #4a4a4a; border-radius: 5px;
            padding: 4px 6px; }
QTextBrowser { background: rgba(26, 26, 26, 235); color: #f2f2f2; border: 1px solid #3a3a3a;
               border-radius: 6px; padding: 8px; }
QScrollBar:vertical { background: #1a1a1a; width: 10px; border-radius: 5px; }
QScrollBar::handle:vertical { background: #555555; border-radius: 5px; min-height: 24px; }
"""


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
        self._items: list[dict[str, str]] = []
        self._index = -1
        self._last_auto_question = ""
        self._last_auto_time = 0.0
        self._drag_offset: QPoint | None = None

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
        self._mic_button.setCheckable(True)
        self._mic_button.setToolTip("Listen to system audio / microphone")
        self._mic_button.toggled.connect(self._on_mic_toggled)
        row1.addWidget(self._mic_button)

        self._device_combo = QComboBox()
        self._device_combo.setToolTip("Audio device to listen to")
        self._device_combo.setMinimumWidth(180)
        self._device_combo.currentIndexChanged.connect(self._on_device_changed)
        row1.addWidget(self._device_combo)

        self._status = QLabel("idle")
        self._status.setObjectName("status")
        row1.addWidget(self._status, 1)

        for text, tip, signal in (
            ("🗂", "Interview details (resume, JD, company)", self.info_requested),
            ("🕘", "History", self.history_requested),
            ("⚙", "Settings", self.settings_requested),
            ("▾", "Collapse / expand answers", None),
            ("✕", "Quit", None),
        ):
            button = QPushButton(text)
            button.setToolTip(tip)
            button.setFixedWidth(30)
            if signal is not None:
                button.clicked.connect(signal.emit)
            elif text == "▾":
                self._collapse_button = button
                button.clicked.connect(self.toggle_collapse)
            else:
                button.clicked.connect(self.close)
            row1.addWidget(button)

        bar_layout.addLayout(row1)

        # -- row 2: transcript / manual question / actions ------------------ #
        row2 = QHBoxLayout()
        row2.setSpacing(6)

        self._stt_input = QLineEdit()
        self._stt_input.setPlaceholderText("interviewer's words appear here…")
        self._stt_input.returnPressed.connect(self._submit_stt_box)
        row2.addWidget(self._stt_input, 3)

        ask_button = QPushButton("Ask")
        ask_button.setToolTip(
            f"Ask with the manual box ({self._settings.hotkeys.get('ask', 'Shift+Alt+A')})"
        )
        ask_button.clicked.connect(self.submit_manual)
        row2.addWidget(ask_button)

        self._manual_input = QLineEdit()
        self._manual_input.setPlaceholderText("type your own question…")
        self._manual_input.returnPressed.connect(self.submit_manual)
        row2.addWidget(self._manual_input, 3)

        for text, tip, slot in (
            ("📷", "Screenshot region → analyse", self.screenshot_requested.emit),
            ("⌫", "Erase inputs and answer", self.erase),
            ("−", "Opacity down", lambda: self.nudge_opacity(-OPACITY_STEP)),
            ("+", "Opacity up", lambda: self.nudge_opacity(OPACITY_STEP)),
        ):
            button = QPushButton(text)
            button.setToolTip(tip)
            button.setFixedWidth(34)
            button.clicked.connect(slot)
            row2.addWidget(button)

        bar_layout.addLayout(row2)
        root.addWidget(self._bar)

        # -- answer panel --------------------------------------------------- #
        self._answer_panel = QFrame(self)
        answer_layout = QVBoxLayout(self._answer_panel)
        answer_layout.setContentsMargins(8, 2, 8, 8)
        answer_layout.setSpacing(4)

        header = QHBoxLayout()
        title = QLabel("Answer")
        title.setObjectName("answer_title")
        header.addWidget(title)
        header.addStretch(1)

        header.addWidget(QLabel("code:"))
        self._language_combo = QComboBox()
        self._language_combo.addItems(CODE_LANGUAGES)
        self._language_combo.setToolTip("Ask for code in a specific language")
        header.addWidget(self._language_combo)

        copy_button = QPushButton("copy")
        copy_button.setToolTip("Copy the answer")
        copy_button.clicked.connect(self._copy_answer)
        header.addWidget(copy_button)

        self._position_label = QLabel("")
        self._position_label.setObjectName("status")
        header.addWidget(self._position_label)
        answer_layout.addLayout(header)

        self._answer_view = QTextBrowser()
        self._answer_view.setOpenExternalLinks(True)
        self._answer_view.setMinimumHeight(150)
        answer_layout.addWidget(self._answer_view, 1)

        grip_row = QHBoxLayout()
        grip_row.addStretch(1)
        grip_row.addWidget(QSizeGrip(self._answer_panel))
        answer_layout.addLayout(grip_row)

        root.addWidget(self._answer_panel, 1)

    # ------------------------------------------------------------ lifecycle #

    def showEvent(self, event) -> None:  # noqa: D102
        super().showEvent(event)
        stealth.apply_stealth(self)

    def closeEvent(self, event) -> None:  # noqa: D102
        self.cancel_stream()
        self.closed.emit()
        super().closeEvent(event)

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
        devices = list_devices()
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
            for device in devices:
                if device.kind == source and device.is_default:
                    self._settings.audio_device = device.id
                    break
            else:
                self._settings.audio_device = devices[0].id
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
        self._status.setText(text)
        self._status.setProperty("error", "true" if error else "false")
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)

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
        if not question:
            return
        self._stt_input.clear()
        self.submit_question(question, kind="chat")

    def submit_manual(self) -> None:
        question = self._manual_input.text().strip()
        if not question:
            return
        self.submit_question(question, kind="chat")

    def erase(self) -> None:
        self._stt_input.clear()
        self._manual_input.clear()
        self._answer_buffer = ""
        self._answer_view.clear()
        self.set_status("erased")

    def _copy_answer(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None and self._answer_buffer:
            clipboard.setText(self._answer_buffer)
            self.set_status("answer copied")

    # ------------------------------------------------------------ submission #

    def submit_question(self, question: str, *, kind: str = "chat") -> None:
        question = question.strip()
        if not question:
            return

        language = self._language_combo.currentText()
        if language != "auto" and kind == "chat":
            question = (
                f"{question}\n\n(If the answer contains code, write it in {language}.)"
            )

        history = self._conversation_payload()
        self.cancel_stream()
        self._pending = {"question": question, "kind": "chat"}
        self._answer_buffer = ""
        self._answer_view.clear()
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
        history = self._conversation_payload()
        self.cancel_stream()
        self._pending = {"question": f"[screenshot] {prompt}", "kind": "vision"}
        self._answer_buffer = ""
        self._answer_view.clear()
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

    def _conversation_payload(self) -> list[dict[str, str]]:
        payload: list[dict[str, str]] = []
        for item in self._items:
            payload.append({"role": "user", "content": item["question"]})
            payload.append({"role": "assistant", "content": item["answer"]})
        return payload

    # -------------------------------------------------------------- streaming #

    def _on_chunk(self, text: str) -> None:
        if self.sender() is not self._worker:
            return  # stale chunk from a cancelled/replaced stream
        self._answer_buffer += text
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def _flush_answer(self, *, force: bool = False) -> None:
        scrollbar = self._answer_view.verticalScrollBar()
        at_bottom = scrollbar is not None and scrollbar.value() >= scrollbar.maximum() - 4
        self._answer_view.setMarkdown(self._answer_buffer)
        if at_bottom and scrollbar is not None:
            scrollbar.setValue(scrollbar.maximum())
        if force:
            self._flush_timer.stop()

    def _on_stream_succeeded(self, answer: str) -> None:
        if self.sender() is not self._worker:
            return
        pending = self._pending or {"question": "", "kind": "chat"}
        self._on_answer_done(pending["question"], answer, kind=pending["kind"])

    def _on_stream_failed(self, message: str) -> None:
        if self.sender() is not self._worker:
            return
        pending = self._pending or {"question": "", "kind": "chat"}
        self._on_stream_error(pending["question"], message)

    def _on_stream_cancelled(self) -> None:
        if self.sender() is not self._worker:
            return
        self._streaming = False
        self._worker = None
        self.set_status("cancelled")

    def _on_answer_done(self, question: str, answer: str, *, kind: str) -> None:
        self._streaming = False
        self._worker = None
        self._answer_buffer = answer or self._answer_buffer
        self._flush_answer(force=True)
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

    def _on_stream_error(self, question: str, message: str) -> None:
        self._streaming = False
        self._worker = None
        self._flush_answer(force=True)
        self.set_status(f"error: {message}", error=True)
        if self._answer_buffer.strip():
            self._answer_view.setMarkdown(
                self._answer_buffer + f"\n\n---\n*stream interrupted: {message}*"
            )
            self._items.append(
                {"question": question, "answer": self._answer_buffer, "kind": "chat"}
            )
            self._index = len(self._items) - 1
            self._update_position_label()

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
        self._answer_buffer = item["answer"]
        self._answer_view.setMarkdown(self._answer_buffer)
        self._update_position_label()

    def load_items(self, items: list[dict[str, str]]) -> None:
        """Seed the in-memory history (used when opening the history dialog)."""
        self._items = list(items)
        self._index = len(self._items) - 1
        self._update_position_label()

    # ------------------------------------------------------------ misc verbs #

    def toggle_collapse(self) -> None:
        collapsed = self._answer_panel.isVisible()
        self._answer_panel.setVisible(not collapsed)
        self._collapse_button.setText("▸" if collapsed else "▾")
        self.adjustSize()
        if not collapsed:
            self.resize(self.width(), self.minimumSizeHint().height())

    def set_collapsed(self, collapsed: bool) -> None:
        if self._answer_panel.isVisible() == collapsed:
            self.toggle_collapse()

    def nudge_opacity(self, delta: float) -> None:
        value = min(max(self.windowOpacity() + delta, 0.3), 1.0)
        self.setWindowOpacity(value)
        self._settings.opacity = value
        self._settings.save()
        self.set_status(f"opacity {int(value * 100)}%")

    def nudge_move(self, dx: int, dy: int) -> None:
        self.move(self.x() + dx, self.y() + dy)

    def nudge_scroll(self, pixels: int) -> None:
        scrollbar = self._answer_view.verticalScrollBar()
        if scrollbar is not None:
            scrollbar.setValue(scrollbar.value() + pixels)

    def ask_hotkey(self) -> None:
        question = self._manual_input.text().strip() or self._stt_input.text().strip()
        if question:
            self._manual_input.clear()
            self.submit_question(question)

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
        self._refresh_devices()
