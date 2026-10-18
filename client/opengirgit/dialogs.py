"""Dialogs: login, interview info, settings, history."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPoint, QSize, Qt, QThread
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from . import render as render_mod
from . import resume as resume_mod
from . import stealth, ui_icons
from .api import ApiClient, ApiError
from .audio import list_devices
from .capture import pixmap_to_jpeg_b64
from .config import DEFAULT_HOTKEYS, UI_SCALES, AppSettings
from .hotkeys import validate_hotkeys
from .prompts import IMAGE_TRANSCRIPTION_PROMPT
from .resume import ResumeExtractionError
from .stores import ConversationStore, ResumeCache
from .version import APP_VERSION
from .workers import FunctionWorker

WHISPER_MODELS = [
    "tiny.en",
    "base.en",
    "small.en",
    "medium.en",
    "large-v3",
    "tiny",
    "base",
    "small",
]
COMPUTE_TYPES = ["int8", "int8_float16", "float16", "float32"]
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


class _WorkerOwner:
    """Mixin keeping QThread references alive and callbacks on the UI thread.

    Callbacks are stored per-worker and invoked from *bound-method* slots, so
    Qt delivers the signals through the owning (main) thread instead of running
    UI code inside the worker thread.
    """

    def __init__(self) -> None:
        self._workers: list[FunctionWorker] = []
        self._callbacks: dict[int, tuple[Any, Any]] = {}

    def run_async(self, fn, on_success, on_error) -> FunctionWorker:
        worker = FunctionWorker(fn, self)  # type: ignore[arg-type]
        self._callbacks[id(worker)] = (on_success, on_error)
        worker.succeeded.connect(self._on_worker_success)
        worker.failed.connect(self._on_worker_failure)
        worker.finished.connect(worker.deleteLater)
        self._workers.append(worker)
        worker.start()
        return worker

    def _on_worker_success(self, result: object) -> None:
        worker = self.sender()
        on_success, _ = self._finish_worker(worker)
        if on_success is not None:
            on_success(result)

    def _on_worker_failure(self, message: str) -> None:
        worker = self.sender()
        _, on_error = self._finish_worker(worker)
        if on_error is not None:
            on_error(message)

    def _finish_worker(self, worker: object) -> tuple[Any, Any]:
        if isinstance(worker, QThread) and worker.isRunning():
            worker.wait(2000)
        if worker in self._workers:
            self._workers.remove(worker)
        return self._callbacks.pop(id(worker), (None, None))

    def wait_for_workers(self, timeout_ms: int = 6000) -> None:
        """Let in-flight workers finish before the dialog is destroyed."""
        for worker in list(self._workers):
            if worker.isRunning():
                worker.wait(timeout_ms)
        self._workers.clear()
        self._callbacks.clear()


# --------------------------------------------------------------------------- #
# Shared dark dialog chrome
# --------------------------------------------------------------------------- #

DIALOG_STYLESHEET = """
QDialog {
    background: transparent;
    color: #f0f6fc;
    font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
}
QLabel { background: transparent; color: #c9d1d9; }
QLabel#dialogTitle { color: #f0f6fc; font-size: 17px; font-weight: 600; }
QLabel#dialogSubtitle { color: #8b949e; font-size: 12px; }
QLabel#dialogHint, QLabel#dialogStatus { color: #8b949e; font-size: 12px; }
QPushButton {
    background-color: #21262d;
    color: #c9d1d9;
    border: 1px solid #30363d;
    border-radius: 7px;
    padding: 6px 14px;
    min-height: 16px;
}
QPushButton:hover { background-color: #30363d; border-color: #8b949e; }
QPushButton:pressed { background-color: #161b22; }
QPushButton:default {
    background-color: #238636;
    border-color: #2ea043;
    color: #ffffff;
    font-weight: 600;
}
QPushButton:default:hover { background-color: #2ea043; }
QPushButton:disabled { color: #6e7681; border-color: #21262d; }
QPushButton#dialogClose { background: transparent; border: none; border-radius: 14px; padding: 0; }
QPushButton#dialogClose:hover { background-color: rgba(248, 81, 73, 0.85); }
QLineEdit, QPlainTextEdit, QTextBrowser, QListWidget, QComboBox, QSpinBox {
    background-color: #161b22;
    color: #f0f6fc;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 5px 7px;
    selection-background-color: #1f6feb;
    selection-color: #ffffff;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextBrowser:focus, QComboBox:focus, QSpinBox:focus {
    border-color: #58a6ff;
}
QLineEdit:disabled, QPlainTextEdit:disabled, QComboBox:disabled, QSpinBox:disabled {
    color: #6e7681;
}
QComboBox QAbstractItemView {
    background-color: #161b22;
    color: #f0f6fc;
    border: 1px solid #30363d;
    selection-background-color: #1f6feb;
    outline: 0;
}
QComboBox::drop-down { border: none; width: 22px; }
QSpinBox::up-button, QSpinBox::down-button { background-color: #21262d; border: none; width: 16px; }
QTabWidget::pane { border: 1px solid #30363d; border-radius: 8px; background-color: #0d1117; }
QTabBar::tab {
    background: transparent;
    color: #8b949e;
    padding: 7px 14px;
    border: 1px solid transparent;
    border-bottom: none;
}
QTabBar::tab:selected {
    color: #f0f6fc;
    background-color: #161b22;
    border-color: #30363d;
    border-top-left-radius: 7px;
    border-top-right-radius: 7px;
}
QTabBar::tab:hover { color: #c9d1d9; }
QGroupBox {
    border: 1px solid #30363d;
    border-radius: 8px;
    margin-top: 13px;
    padding: 14px 10px 10px 10px;
    color: #c9d1d9;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #8b949e; }
QCheckBox { color: #c9d1d9; spacing: 8px; }
QListWidget { outline: 0; padding: 4px; }
QListWidget::item { padding: 6px; border-radius: 6px; color: #c9d1d9; }
QListWidget::item:selected { background-color: rgba(31, 111, 235, 0.35); color: #ffffff; }
QListWidget::item:hover { background-color: rgba(255, 255, 255, 0.06); }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #30363d; border-radius: 5px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: #484f58; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: #30363d; border-radius: 5px; min-width: 24px; }
QScrollBar::handle:horizontal:hover { background: #484f58; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
QToolTip {
    background-color: #161b22;
    color: #f0f6fc;
    border: 1px solid #30363d;
    padding: 4px 6px;
}
"""


class _DialogBase(QDialog, _WorkerOwner):
    """Frameless dark card shared by every OpenGirGit dialog.

    The original app paints its dialogs as rounded cards instead of native
    title-bar windows.  Keeping the frame in one place also means every dialog
    gets the Windows capture-exclusion treatment on show.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        title: str,
        subtitle: str = "",
    ) -> None:
        QDialog.__init__(self, parent)
        _WorkerOwner.__init__(self)
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet(DIALOG_STYLESHEET)
        self._drag_offset: QPoint | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 14, 20, 18)
        root.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(8)
        brand = QLabel()
        brand.setFixedSize(24, 24)
        brand.setPixmap(ui_icons.pixmap("logo", 24))
        header.addWidget(brand)
        title_label = QLabel(title)
        title_label.setObjectName("dialogTitle")
        header.addWidget(title_label)
        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("dialogSubtitle")
            header.addWidget(subtitle_label)
        header.addStretch(1)

        close = QPushButton()
        close.setObjectName("dialogClose")
        close.setIcon(ui_icons.icon("close", 15))
        close.setIconSize(QSize(15, 15))
        close.setFixedSize(28, 28)
        close.setToolTip("Close")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.reject)
        header.addWidget(close)
        root.addLayout(header)

        self.content = QVBoxLayout()
        self.content.setSpacing(10)
        root.addLayout(self.content, 1)

    def paintEvent(self, _event) -> None:  # noqa: D102
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.setPen(QPen(QColor("#30363d"), 1))
        painter.setBrush(QColor("#0d1117"))
        painter.drawRoundedRect(rect, 14, 14)

    def showEvent(self, event) -> None:  # noqa: D102
        super().showEvent(event)
        stealth.apply_stealth(self)

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
        super().mouseReleaseEvent(event)

    def done(self, result: int) -> None:  # noqa: D102
        self.wait_for_workers()
        super().done(result)


# --------------------------------------------------------------------------- #
# Login (server URL + email OTP)
# --------------------------------------------------------------------------- #


class LoginDialog(_DialogBase):
    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent, title="Sign in", subtitle="local server")
        self.setMinimumWidth(520)
        self.settings = settings
        self.credentials: dict[str, str] | None = None

        layout = self.content
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._server = QLineEdit(settings.server_url)
        form.addRow("Server URL", self._server)
        server_hint = QLabel("The bundled server starts automatically on this computer.")
        server_hint.setObjectName("dialogHint")
        form.addRow("", server_hint)

        self._email = QLineEdit()
        self._email.setPlaceholderText("you@example.com")
        form.addRow("Email", self._email)
        email_hint = QLabel("Any email-shaped name works as a local username — no mail is sent.")
        email_hint.setObjectName("dialogHint")
        email_hint.setWordWrap(True)
        form.addRow("", email_hint)

        otp_row = QHBoxLayout()
        otp_row.setSpacing(8)
        self._otp = QLineEdit()
        self._otp.setPlaceholderText("6-digit code")
        self._send_button = QPushButton("Send code")
        self._send_button.clicked.connect(self._send_code)
        otp_row.addWidget(self._otp, 1)
        otp_row.addWidget(self._send_button)
        otp_container = QWidget()
        otp_container.setLayout(otp_row)
        form.addRow("One-time code", otp_container)
        otp_hint = QLabel(
            "The local server shows the code in the engine window and fills it in automatically."
        )
        otp_hint.setObjectName("dialogHint")
        otp_hint.setWordWrap(True)
        form.addRow("", otp_hint)

        layout.addLayout(form)

        self._status = QLabel("Enter your email, then press “Send code”.")
        self._status.setObjectName("dialogStatus")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Sign in")
        buttons.button(QDialogButtonBox.Ok).setDefault(True)
        buttons.accepted.connect(self._verify)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._otp.returnPressed.connect(self._verify)

    def _client(self) -> ApiClient:
        return ApiClient(self._server.text().strip(), transport=self.settings.chat_transport)

    def done(self, result: int) -> None:  # noqa: D102
        self.wait_for_workers()
        super().done(result)

    def _send_code(self) -> None:
        email = self._email.text().strip()
        if "@" not in email:
            self._status.setText("Enter a valid email address first.")
            return
        self._send_button.setEnabled(False)
        self._status.setText("Requesting a code…")

        def work() -> dict[str, Any]:
            return self._client().send_otp(email)

        def ok(data: dict[str, Any]) -> None:
            self._send_button.setEnabled(True)
            self._status.setText(str(data.get("message") or "Code sent."))
            if data.get("otp_code"):
                self._otp.setText(str(data["otp_code"]))
                self._status.setText("Dev mode: code filled in automatically.")

        def fail(message: str) -> None:
            self._send_button.setEnabled(True)
            self._status.setText(f"Error: {message}")

        self.run_async(work, ok, fail)

    def _verify(self) -> None:
        email = self._email.text().strip()
        code = self._otp.text().strip()
        if "@" not in email or not code:
            self._status.setText("Email and code are both required.")
            return
        self._status.setText("Verifying…")

        def work() -> dict[str, Any]:
            client = self._client()
            data = client.verify_otp(email, code)
            token = data.get("access_token")
            if not token:
                raise ApiError("server did not return a token")
            client.token = token
            try:
                client.save_profile({"email": email})
            except ApiError:
                pass  # profile is optional
            return data

        def ok(data: dict[str, Any]) -> None:
            self.settings.server_url = self._server.text().strip()
            self.settings.save()
            self.credentials = {"email": email, "access_token": str(data["access_token"])}
            self.accept()

        self.run_async(
            work,
            ok,
            lambda message: self._status.setText(f"Error: {message}"),
        )


# --------------------------------------------------------------------------- #
# Interview info (company / JD / resume / notes)
# --------------------------------------------------------------------------- #


class InfoDialog(_DialogBase):
    def __init__(
        self,
        api: ApiClient,
        context: dict[str, Any],
        cache: ResumeCache,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, title="Interview details", subtitle="local context")
        self.setMinimumSize(600, 700)
        self._api = api
        self._cache = cache
        self._parsed_resume: dict[str, Any] | None = context.get("resume")
        self._resume_path: str | None = cache.load().get("source_name") or None
        self.result: dict[str, Any] | None = None

        layout = self.content

        details = QGroupBox("Role")
        details_layout = QFormLayout(details)
        self._company = QLineEdit(str(context.get("company") or ""))
        self._company.setPlaceholderText("e.g. Acme Corp — Senior Backend Engineer")
        details_layout.addRow("Company / role", self._company)

        self._jd = QPlainTextEdit(str(context.get("job_description") or ""))
        self._jd.setPlaceholderText("Paste the job description…")
        details_layout.addRow("Job description", self._jd)
        attach_tip = "Add a file's text here — documents are read locally, images are transcribed"
        jd_attach = QPushButton("Attach a file…")
        jd_attach.setToolTip(attach_tip)
        jd_attach.clicked.connect(
            lambda: self._attach_into(self._jd, "Attach to the job description")
        )
        details_layout.addRow("", jd_attach)
        layout.addWidget(details, 2)

        resume_box = QGroupBox("Resume")
        resume_layout = QVBoxLayout(resume_box)
        row = QHBoxLayout()
        self._resume_label = QLabel(self._resume_description())
        self._resume_label.setWordWrap(True)
        row.addWidget(self._resume_label, 1)
        browse = QPushButton("Choose file…")
        browse.clicked.connect(self._choose_resume)
        row.addWidget(browse)
        resume_layout.addLayout(row)
        self._resume_status = QLabel("")
        self._resume_status.setWordWrap(True)
        resume_layout.addWidget(self._resume_status)
        layout.addWidget(resume_box)

        extra_box = QGroupBox("Anything else")
        extra_layout = QVBoxLayout(extra_box)
        self._extra = QPlainTextEdit(str(context.get("anything_else") or ""))
        self._extra.setPlaceholderText(
            "Notes the assistant should know: target level, salary expectations, topics to revise…"
        )
        extra_layout.addWidget(self._extra)
        extra_attach = QPushButton("Attach a file…")
        extra_attach.setToolTip(attach_tip)
        extra_attach.clicked.connect(
            lambda: self._attach_into(self._extra, "Attach to anything else")
        )
        extra_layout.addWidget(extra_attach, 0, Qt.AlignRight)
        layout.addWidget(extra_box, 1)

        self._attach_status = QLabel("")
        self._attach_status.setWordWrap(True)
        layout.addWidget(self._attach_status)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Save")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # -- resume handling ---------------------------------------------------- #

    def done(self, result: int) -> None:  # noqa: D102
        self.wait_for_workers()
        super().done(result)

    def _resume_description(self) -> str:
        if not self._parsed_resume:
            return "No resume parsed yet."
        name = self._parsed_resume.get("name") or "candidate"
        skills = len(self._parsed_resume.get("skills") or [])
        jobs = len(self._parsed_resume.get("experience") or [])
        return f"Parsed: {name} · {jobs} roles · {skills} skills"

    def _choose_resume(self) -> None:
        filters = "Resumes (*.pdf *.docx *.txt *.md *.rtf)"
        path, _ = QFileDialog.getOpenFileName(self, "Choose a resume", "", filters)
        if not path:
            return
        self._resume_path = path
        self._resume_label.setText(f"Selected: {path}")
        self._resume_status.setText("Extracting text…")

        def work() -> tuple[str, str]:
            text = resume_mod.extract_text(path)
            if not text.strip():
                raise ResumeExtractionError("the file contains no extractable text")
            return text, resume_mod.text_hash(text)

        def ok(payload: tuple[str, str]) -> None:
            text, digest = payload
            self._resume_status.setText("Parsing with the model…")

            def parse() -> dict[str, Any]:
                return self._api.parse_resume(text)

            def parsed(resume: dict[str, Any]) -> None:
                self._parsed_resume = resume
                self._resume_label.setText(self._resume_description())
                self._resume_status.setText("Resume parsed.")
                try:
                    self._cache.save(path, digest, resume)
                except Exception:
                    pass

            self.run_async(
                parse,
                parsed,
                lambda message: self._resume_status.setText(f"Parse failed: {message}"),
            )

        self.run_async(
            work,
            ok,
            lambda message: self._resume_status.setText(f"Error: {message}"),
        )

    # -- attachments -------------------------------------------------------- #

    def _attach_into(self, editor: QPlainTextEdit, title: str) -> None:
        """Pick a document or image and fold its text into ``editor``.

        Documents are extracted locally; images are sent to the vision model
        and their transcription is appended instead.
        """
        filters = (
            "Documents (*.pdf *.docx *.txt *.md *.rtf);;Images (*.png *.jpg *.jpeg *.webp *.bmp)"
        )
        path, _ = QFileDialog.getOpenFileName(self, title, "", filters)
        if not path:
            return
        name = Path(path).name
        if Path(path).suffix.lower() in IMAGE_SUFFIXES:
            self._attach_image(editor, path, name)
        else:
            self._attach_document(editor, path, name)

    def _append_text(self, editor: QPlainTextEdit, name: str, text: str) -> None:
        section = f"--- {name} ---\n{text.strip()}"
        current = editor.toPlainText().strip()
        editor.setPlainText(f"{current}\n\n{section}" if current else section)

    def _attach_document(self, editor: QPlainTextEdit, path: str, name: str) -> None:
        self._attach_status.setText(f"Reading {name}…")

        def work() -> str:
            return resume_mod.extract_text(path).strip()

        def ok(text: str) -> None:
            if not text:
                self._attach_status.setText(f"No text found in {name}")
                return
            self._append_text(editor, name, text)
            self._attach_status.setText(f"Attached {name}")

        self.run_async(
            work,
            ok,
            lambda message: self._attach_status.setText(f"Error: {message}"),
        )

    def _attach_image(self, editor: QPlainTextEdit, path: str, name: str) -> None:
        # The server tags every image as JPEG, so re-encode before sending.
        encoded = pixmap_to_jpeg_b64(QPixmap(path))
        if not encoded:
            self._attach_status.setText(f"Not an image: {name}")
            return
        self._attach_status.setText(f"Transcribing {name}…")

        def work() -> str:
            return self._api.vision_stream(IMAGE_TRANSCRIPTION_PROMPT, [encoded])

        def ok(text: str) -> None:
            if not text.strip():
                self._attach_status.setText(f"No text found in {name}")
                return
            self._append_text(editor, name, text)
            self._attach_status.setText(f"Attached {name}")

        self.run_async(
            work,
            ok,
            lambda message: self._attach_status.setText(f"Error: {message}"),
        )

    # -- result ------------------------------------------------------------- #

    def _save(self) -> None:
        self.result = {
            "resume": self._parsed_resume,
            "company": self._company.text().strip(),
            "job_description": self._jd.toPlainText().strip(),
            "anything_else": self._extra.toPlainText().strip(),
        }
        self.accept()


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #


class SettingsDialog(_DialogBase):
    def __init__(
        self,
        settings: AppSettings,
        parent: QWidget | None = None,
        *,
        api: ApiClient | None = None,
        email: str = "",
        hotkey_state: tuple[str, str] | None = None,
    ) -> None:
        super().__init__(parent, title="Settings", subtitle="OpenGirGit")
        self.setMinimumSize(620, 620)
        self.settings = settings
        self._api = api
        self._email = email
        self._hotkey_state = hotkey_state
        self._working = AppSettings.from_dict(settings.to_dict())

        layout = self.content
        tabs = QTabWidget(self)
        layout.addWidget(tabs, 1)

        # -- Server --------------------------------------------------------- #
        server_page = QWidget()
        server_page_layout = QVBoxLayout(server_page)
        server_box = QGroupBox("Server")
        server_layout = QVBoxLayout(server_box)
        row = QHBoxLayout()
        self._server = QLineEdit(settings.server_url)
        row.addWidget(self._server, 1)
        test = QPushButton("Test connection")
        test.clicked.connect(self._test_server)
        row.addWidget(test)
        server_layout.addLayout(row)
        self._health = QLabel("")
        self._health.setWordWrap(True)
        server_layout.addWidget(self._health)

        transport_form = QFormLayout()
        self._transport = QComboBox()
        self._transport.addItem("Auto (WebSocket, falls back to SSE)", "auto")
        self._transport.addItem("SSE (plain HTTP)", "sse")
        self._transport.addItem("WebSocket", "websocket")
        self._transport.setCurrentIndex(max(self._transport.findData(settings.chat_transport), 0))
        transport_form.addRow("Answer transport", self._transport)
        server_layout.addLayout(transport_form)
        server_page_layout.addWidget(server_box)
        server_page_layout.addStretch(1)
        tabs.addTab(server_page, "Server")

        # -- Speech --------------------------------------------------------- #
        speech_page = QWidget()
        speech_page_layout = QVBoxLayout(speech_page)
        speech_box = QGroupBox("Transcription")
        speech_layout = QFormLayout(speech_box)
        self._engine = QComboBox()
        self._engine.addItem("Local (faster-whisper, private)", "local")
        self._engine.addItem("Deepgram (cloud, direct WebSocket)", "deepgram")
        self._engine.setCurrentIndex(max(self._engine.findData(settings.stt_engine), 0))
        speech_layout.addRow("Engine", self._engine)

        self._model = QComboBox()
        self._model.setEditable(True)
        self._model.addItems(WHISPER_MODELS)
        self._model.setCurrentText(settings.whisper_model)
        speech_layout.addRow("Whisper model", self._model)

        self._compute = QComboBox()
        self._compute.addItems(COMPUTE_TYPES)
        self._compute.setCurrentText(settings.whisper_compute_type)
        speech_layout.addRow("Compute type", self._compute)

        speech_page_layout.addWidget(speech_box)

        audio_box = QGroupBox("Audio")
        audio_layout = QFormLayout(audio_box)
        self._source = QComboBox()
        self._source.addItem("System audio (interviewer)", "system")
        self._source.addItem("Microphone", "microphone")
        self._source.setCurrentIndex(max(self._source.findData(settings.audio_source), 0))
        audio_layout.addRow("Source", self._source)

        device_row = QHBoxLayout()
        self._device = QComboBox()
        device_row.addWidget(self._device, 1)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._refresh_devices)
        device_row.addWidget(refresh)
        device_container = QWidget()
        device_container.setLayout(device_row)
        audio_layout.addRow("Device", device_container)
        speech_page_layout.addWidget(audio_box)
        speech_page_layout.addStretch(1)
        tabs.addTab(speech_page, "Speech")

        # -- Behaviour ------------------------------------------------------ #
        behaviour_page = QWidget()
        behaviour_page_layout = QVBoxLayout(behaviour_page)
        behaviour_box = QGroupBox("Answers and input")
        behaviour_layout = QFormLayout(behaviour_box)
        self._auto_ask = QCheckBox("Submit transcribed questions automatically")
        self._auto_ask.setChecked(settings.auto_ask)
        behaviour_layout.addRow(self._auto_ask)

        self._partials = QCheckBox("Show live partial transcripts while speaking")
        self._partials.setChecked(settings.partials)
        behaviour_layout.addRow(self._partials)

        self._web_render = QCheckBox("Render math and diagrams in the embedded view")
        self._web_render.setChecked(settings.web_render)
        behaviour_layout.addRow(self._web_render)

        self._screenshot_prompt = QPlainTextEdit(settings.screenshot_prompt)
        self._screenshot_prompt.setMaximumHeight(70)
        behaviour_layout.addRow("Screenshot prompt", self._screenshot_prompt)
        behaviour_page_layout.addWidget(behaviour_box)

        appearance_box = QGroupBox("Appearance and privacy")
        appearance_layout = QFormLayout(appearance_box)
        self._opacity = QSpinBox()
        self._opacity.setRange(30, 100)
        self._opacity.setSuffix(" %")
        self._opacity.setValue(int(settings.opacity * 100))
        appearance_layout.addRow("Opacity", self._opacity)

        self._ui_scale = QComboBox()
        self._ui_scale.addItem("Follow the system", 0)
        for scale in UI_SCALES:
            if scale:
                self._ui_scale.addItem(f"{scale} %", scale)
        self._ui_scale.setCurrentIndex(max(self._ui_scale.findData(settings.ui_scale), 0))
        appearance_layout.addRow("Interface scale", self._ui_scale)

        self._decoy_cursor = QCheckBox("Decoy cursor during region selection")
        self._decoy_cursor.setChecked(settings.decoy_cursor)
        appearance_layout.addRow(self._decoy_cursor)
        behaviour_page_layout.addWidget(appearance_box)
        behaviour_page_layout.addStretch(1)
        tabs.addTab(behaviour_page, "Behaviour")

        # -- Hotkeys -------------------------------------------------------- #
        hotkeys_page = QWidget()
        hotkeys_page_layout = QVBoxLayout(hotkeys_page)
        if self._hotkey_state is not None:
            state, detail = self._hotkey_state
            status_text = {
                "windows": "global hotkeys: system-wide",
                "focus": "global hotkeys: only while this window has focus",
            }.get(state, "global hotkeys: only while this window has focus")
            if detail:
                status_text = f"{status_text} — {detail}"
            status = QLabel(status_text)
            status.setWordWrap(True)
            hotkeys_page_layout.addWidget(status)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        hotkey_container = QWidget()
        hotkey_layout = QFormLayout(hotkey_container)
        self._hotkey_edits: dict[str, QLineEdit] = {}
        for action, spec in sorted(settings.hotkeys.items()):
            value = QLineEdit(spec)
            value.setPlaceholderText("empty = disabled")
            hotkey_layout.addRow(action.replace("_", " "), value)
            self._hotkey_edits[action] = value
        hint = QLabel("Format: modifiers + key, e.g. Shift+Alt+A (at least one modifier).")
        hint.setWordWrap(True)
        hotkey_layout.addRow(hint)
        reset = QPushButton("Reset to defaults")
        reset.clicked.connect(self._reset_hotkeys)
        hotkey_layout.addRow(reset)
        scroll.setWidget(hotkey_container)
        hotkeys_page_layout.addWidget(scroll, 1)
        tabs.addTab(hotkeys_page, "Hotkeys")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Save")
        feedback_button = buttons.addButton("Send feedback…", QDialogButtonBox.ActionRole)
        feedback_button.clicked.connect(self._open_feedback)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._refresh_devices()

    # -- feedback ----------------------------------------------------------- #

    def _open_feedback(self) -> None:
        api = self._api or ApiClient(self._server.text().strip() or self.settings.server_url)
        FeedbackDialog(api, email=self._email, parent=self).exec()

    # -- helpers ------------------------------------------------------------ #

    def done(self, result: int) -> None:  # noqa: D102
        self.wait_for_workers()
        super().done(result)

    def _refresh_devices(self) -> None:
        self._device.clear()
        devices = list_devices()
        if not devices:
            self._device.addItem("(no audio devices found)", "")
            return
        for device in devices:
            self._device.addItem(device.label(), device.id)
        index = self._device.findData(self._working.audio_device)
        self._device.setCurrentIndex(max(index, 0))

    def _test_server(self) -> None:
        self._health.setText("Checking…")
        url = self._server.text().strip()

        def ok(data: dict[str, Any]) -> None:
            state = "Server {state}.".format(
                state="is ok" if data.get("status") == "ok" else "answered unusually"
            )
            llm = "yes" if data.get("llm_configured") else "no"
            self._health.setText(
                state
                + " "
                + f"LLM configured: {llm}."
                + " "
                + "STT provider: {value}.".format(value=data.get("stt_provider"))
            )

        self.run_async(
            lambda: ApiClient.health(url),
            ok,
            lambda message: self._health.setText(f"Error: {message}"),
        )

    def _reset_hotkeys(self) -> None:
        for action, edit in self._hotkey_edits.items():
            edit.setText(DEFAULT_HOTKEYS.get(action, ""))

    def _edited_hotkeys(self) -> dict[str, str]:
        return {action: edit.text().strip() for action, edit in self._hotkey_edits.items()}

    def _save(self) -> None:
        hotkeys = self._edited_hotkeys()
        problems = validate_hotkeys(hotkeys)
        if problems:
            summary = "\n".join(
                f"• {action}: {message}" for action, message in sorted(problems.items())
            )
            QMessageBox.warning(
                self,
                "Invalid hotkeys",
                f"Fix these before saving:\n\n{summary}",
            )
            return

        self._working.server_url = self._server.text().strip()
        self._working.stt_engine = self._engine.currentData() or "local"
        self._working.whisper_model = self._model.currentText().strip() or "base.en"
        self._working.whisper_compute_type = self._compute.currentText()
        self._working.audio_source = self._source.currentData() or "system"
        self._working.audio_device = self._device.currentData() or ""
        self._working.auto_ask = self._auto_ask.isChecked()
        self._working.partials = self._partials.isChecked()
        self._working.web_render = self._web_render.isChecked()
        self._working.decoy_cursor = self._decoy_cursor.isChecked()
        self._working.opacity = self._opacity.value() / 100.0
        self._working.screenshot_prompt = self._screenshot_prompt.toPlainText().strip()
        self._working.chat_transport = self._transport.currentData() or "auto"
        self._working.ui_scale = int(self._ui_scale.currentData() or 0)

        # Mutate the live settings object in place.
        for key, value in self._working.to_dict().items():
            if key != "hotkeys":
                setattr(self.settings, key, value)
        self.settings.hotkeys.clear()
        self.settings.hotkeys.update(hotkeys)
        self.settings.save()
        self.accept()


# --------------------------------------------------------------------------- #
# History
# --------------------------------------------------------------------------- #


class HistoryDialog(_DialogBase):
    def __init__(self, conversations: ConversationStore, parent: QWidget | None = None) -> None:
        super().__init__(parent, title="Conversation history", subtitle="local only")
        self.setMinimumSize(900, 600)
        self.resize(940, 640)
        self._conversations = conversations

        layout = self.content
        row = QHBoxLayout()
        row.setSpacing(12)

        sessions_column = QVBoxLayout()
        sessions_column.setSpacing(4)
        sessions_label = QLabel("Previous sessions")
        sessions_label.setObjectName("dialogHint")
        sessions_column.addWidget(sessions_label)

        self._sessions = QListWidget()
        self._sessions.setMaximumWidth(260)
        self._sessions.currentItemChanged.connect(self._show_session)
        sessions_column.addWidget(self._sessions, 1)
        row.addLayout(sessions_column)

        self._viewer = QTextBrowser()
        row.addWidget(self._viewer, 1)
        layout.addLayout(row)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)

        export_session = buttons.addButton("Export session…", QDialogButtonBox.ActionRole)
        export_session.setToolTip("Write the selected conversation to a Markdown file")
        export_session.clicked.connect(self._export_selected)

        export_all = buttons.addButton("Export all…", QDialogButtonBox.ActionRole)
        export_all.setToolTip("Write every stored session to one Markdown file")
        export_all.clicked.connect(self._export_all)

        copy_button = buttons.addButton("Copy", QDialogButtonBox.ActionRole)
        copy_button.setToolTip("Copy the selected conversation as Markdown")
        copy_button.clicked.connect(self._copy_selected)

        layout.addWidget(buttons)

        self._populate()

    # -- listing ------------------------------------------------------------ #

    def _populate(self) -> None:
        self._sessions.clear()
        for session in self._conversations.sessions():
            items = session.get("items") or []
            label = session.get("title") or "Session"
            entry = QListWidgetItem(
                f"{label}\n{str(session.get('started_at', ''))[:16]} · {len(items)} Q&A"
            )
            entry.setData(Qt.UserRole, session.get("id"))
            self._sessions.addItem(entry)
        if self._sessions.count():
            self._sessions.setCurrentRow(0)

    def _selected_session(self) -> dict[str, Any] | None:
        current = self._sessions.currentItem()
        if current is None:
            return None
        session_id = current.data(Qt.UserRole)
        return next((s for s in self._conversations.sessions() if s.get("id") == session_id), None)

    def _show_session(self, current: QListWidgetItem | None, _previous=None) -> None:
        session = self._selected_session() if current is not None else None
        if session is None:
            self._viewer.clear()
            return
        render_mod.render_into(
            self._viewer, self._conversations.session_markdown(session), variant="dark"
        )

    # -- export ------------------------------------------------------------- #

    def _write_file(self, default_name: str, content: str) -> None:
        path, _selected = QFileDialog.getSaveFileName(
            self,
            "Export conversation",
            default_name,
            "Markdown (*.md);;Text files (*.txt);;All files (*)",
        )
        if not path:
            return
        try:
            Path(path).write_text(content, encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
            return
        self._status.setText(f"Exported {len(content)} characters to {path}")

    def _export_selected(self) -> None:
        session = self._selected_session()
        if session is None:
            self._status.setText("Select a session first.")
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        self._write_file(
            f"opengirgit-session-{stamp}.md",
            self._conversations.export_markdown(str(session.get("id") or "")),
        )

    def _export_all(self) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        self._write_file(
            f"opengirgit-history-{stamp}.md", self._conversations.export_markdown(None)
        )

    def _copy_selected(self) -> None:
        session = self._selected_session()
        if session is None:
            self._status.setText("Select a session first.")
            return
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self._conversations.session_markdown(session))
            self._status.setText("Copied the selected session as Markdown.")


# --------------------------------------------------------------------------- #
# Feedback
# --------------------------------------------------------------------------- #


class FeedbackDialog(_DialogBase):
    """Send feedback to your own server (stored in its local database).

    Unlike the original app, nothing here phones home to a vendor: the message
    goes to whatever server URL is configured.
    """

    def __init__(self, api: ApiClient, email: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent, title="Send feedback", subtitle="local server")
        self.setMinimumWidth(520)
        self._api = api
        self._email = email

        layout = self.content

        caption = QLabel("Feedback is stored on your own server. Nothing goes anywhere else.")
        caption.setObjectName("dialogHint")
        caption.setWordWrap(True)
        layout.addWidget(caption)

        self._message = QPlainTextEdit()
        self._message.setPlaceholderText("What worked, what didn't, what you'd like to see…")
        self._message.setMinimumHeight(140)
        layout.addWidget(self._message, 1)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Close)
        self._buttons.button(QDialogButtonBox.Ok).setText("Send")
        self._buttons.accepted.connect(self._send)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

    def done(self, result: int) -> None:  # noqa: D102
        self.wait_for_workers()
        super().done(result)

    def _send(self) -> None:
        message = self._message.toPlainText().strip()
        if not message:
            self._status.setText("Write something first.")
            return
        self._status.setText("Sending…")
        send = self._buttons.button(QDialogButtonBox.Ok)
        send.setEnabled(False)

        def work() -> dict[str, Any]:
            return self._api.submit_feedback(
                message, email=self._email or None, app_version=APP_VERSION
            )

        def ok(_result: dict[str, Any]) -> None:
            self._status.setText("Sent — thank you!")
            self._message.clear()
            send.setEnabled(True)

        def failed(message_text: str) -> None:
            self._status.setText(f"Could not send: {message_text}")
            send.setEnabled(True)

        self.run_async(work, ok, failed)


def render_hotkey_help(settings: AppSettings) -> str:
    lines = [f"`{action}` → `{spec}`" for action, spec in sorted(settings.hotkeys.items())]
    return "\n".join(lines)


def dump_settings(settings: AppSettings) -> str:
    """Debug helper used by the CLI entry point (``--print-settings``)."""
    return json.dumps(settings.to_dict(), indent=2)


__all__ = [
    "DEFAULT_HOTKEYS",
    "FeedbackDialog",
    "HistoryDialog",
    "InfoDialog",
    "LoginDialog",
    "SettingsDialog",
    "dump_settings",
    "render_hotkey_help",
]
