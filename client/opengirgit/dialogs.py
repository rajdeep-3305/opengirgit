"""Dialogs: login, interview info, settings, history."""

from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from . import render as render_mod
from . import resume as resume_mod
from .api import ApiClient, ApiError
from .audio import list_devices
from .config import DEFAULT_HOTKEYS, AppSettings
from .resume import ResumeExtractionError
from .stores import ConversationStore, ResumeCache
from .workers import FunctionWorker

WHISPER_MODELS = ["tiny.en", "base.en", "small.en", "medium.en", "large-v3", "tiny", "base", "small"]
COMPUTE_TYPES = ["int8", "int8_float16", "float16", "float32"]


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
# Login (server URL + email OTP)
# --------------------------------------------------------------------------- #


class LoginDialog(QDialog, _WorkerOwner):
    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        QDialog.__init__(self, parent)
        _WorkerOwner.__init__(self)
        self.setWindowTitle("OpenGirGit — sign in")
        self.setMinimumWidth(430)
        self.settings = settings
        self.credentials: dict[str, str] | None = None

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._server = QLineEdit(settings.server_url)
        form.addRow("Server URL", self._server)

        self._email = QLineEdit()
        self._email.setPlaceholderText("you@example.com")
        form.addRow("Email", self._email)

        otp_row = QHBoxLayout()
        self._otp = QLineEdit()
        self._otp.setPlaceholderText("6-digit code")
        self._send_button = QPushButton("Send code")
        self._send_button.clicked.connect(self._send_code)
        otp_row.addWidget(self._otp, 1)
        otp_row.addWidget(self._send_button)
        otp_container = QWidget()
        otp_container.setLayout(otp_row)
        form.addRow("One-time code", otp_container)

        layout.addLayout(form)

        self._status = QLabel("Enter your email, then press “Send code”.")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Sign in")
        buttons.accepted.connect(self._verify)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._otp.returnPressed.connect(self._verify)

    def _client(self) -> ApiClient:
        return ApiClient(self._server.text().strip())

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

        self.run_async(work, ok, lambda message: self._status.setText(f"Error: {message}"))


# --------------------------------------------------------------------------- #
# Interview info (company / JD / resume / notes)
# --------------------------------------------------------------------------- #


class InfoDialog(QDialog, _WorkerOwner):
    def __init__(
        self,
        api: ApiClient,
        context: dict[str, Any],
        cache: ResumeCache,
        parent: QWidget | None = None,
    ) -> None:
        QDialog.__init__(self, parent)
        _WorkerOwner.__init__(self)
        self.setWindowTitle("Interview details")
        self.setMinimumSize(560, 620)
        self._api = api
        self._cache = cache
        self._parsed_resume: dict[str, Any] | None = context.get("resume")
        self._resume_path: str | None = cache.load().get("source_name") or None
        self.result: dict[str, Any] | None = None

        layout = QVBoxLayout(self)

        details = QGroupBox("Role")
        details_layout = QFormLayout(details)
        self._company = QLineEdit(str(context.get("company") or ""))
        self._company.setPlaceholderText("e.g. Acme Corp — Senior Backend Engineer")
        details_layout.addRow("Company / role", self._company)

        self._jd = QPlainTextEdit(str(context.get("job_description") or ""))
        self._jd.setPlaceholderText("Paste the job description…")
        details_layout.addRow("Job description", self._jd)
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
        layout.addWidget(extra_box, 1)

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

            self.run_async(parse, parsed, lambda message: self._resume_status.setText(f"Parse failed: {message}"))

        self.run_async(work, ok, lambda message: self._resume_status.setText(f"Error: {message}"))

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


class SettingsDialog(QDialog, _WorkerOwner):
    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        QDialog.__init__(self, parent)
        _WorkerOwner.__init__(self)
        self.setWindowTitle("OpenGirGit settings")
        self.setMinimumWidth(520)
        self.settings = settings
        self._working = AppSettings.from_dict(settings.to_dict())

        layout = QVBoxLayout(self)

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
        layout.addWidget(server_box)

        speech_box = QGroupBox("Speech-to-text")
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

        self._language = QLineEdit(settings.language)
        self._language.setPlaceholderText("en")
        speech_layout.addRow("Language", self._language)
        layout.addWidget(speech_box)

        audio_box = QGroupBox("Audio")
        audio_layout = QFormLayout(audio_box)
        self._source = QComboBox()
        self._source.addItem("System audio (interviewer, Windows)", "system")
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
        layout.addWidget(audio_box)

        behaviour_box = QGroupBox("Behaviour")
        behaviour_layout = QFormLayout(behaviour_box)
        self._auto_ask = QCheckBox("Submit transcribed questions automatically")
        self._auto_ask.setChecked(settings.auto_ask)
        behaviour_layout.addRow(self._auto_ask)

        self._opacity = QSpinBox()
        self._opacity.setRange(30, 100)
        self._opacity.setSuffix(" %")
        self._opacity.setValue(int(settings.opacity * 100))
        behaviour_layout.addRow("Opacity", self._opacity)

        self._screenshot_prompt = QPlainTextEdit(settings.screenshot_prompt)
        self._screenshot_prompt.setMaximumHeight(70)
        behaviour_layout.addRow("Screenshot prompt", self._screenshot_prompt)
        layout.addWidget(behaviour_box)

        hotkeys_box = QGroupBox("Global hotkeys (edit ~/.opengirgit/config.json to change)")
        hotkey_layout = QFormLayout(hotkeys_box)
        for action, spec in sorted(settings.hotkeys.items()):
            value = QLineEdit(spec)
            value.setReadOnly(True)
            hotkey_layout.addRow(action.replace("_", " "), value)
        layout.addWidget(hotkeys_box)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Save")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._refresh_devices()

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
            state = "ok" if data.get("status") == "ok" else "unexpected"
            llm = "yes" if data.get("llm_configured") else "no"
            self._health.setText(
                f"Server {state}. LLM configured: {llm}. STT provider: {data.get('stt_provider')}."
            )

        self.run_async(lambda: ApiClient.health(url), ok, lambda m: self._health.setText(f"Error: {m}"))

    def _save(self) -> None:
        self._working.server_url = self._server.text().strip()
        self._working.stt_engine = self._engine.currentData() or "local"
        self._working.whisper_model = self._model.currentText().strip() or "base.en"
        self._working.whisper_compute_type = self._compute.currentText()
        self._working.language = self._language.text().strip() or "en"
        self._working.audio_source = self._source.currentData() or "system"
        self._working.audio_device = self._device.currentData() or ""
        self._working.auto_ask = self._auto_ask.isChecked()
        self._working.opacity = self._opacity.value() / 100.0
        self._working.screenshot_prompt = self._screenshot_prompt.toPlainText().strip()

        # Mutate the live settings object in place.
        for key, value in self._working.to_dict().items():
            if key != "hotkeys":
                setattr(self.settings, key, value)
        self.settings.save()
        self.accept()


# --------------------------------------------------------------------------- #
# History
# --------------------------------------------------------------------------- #


class HistoryDialog(QDialog):
    def __init__(self, conversations: ConversationStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Conversation history (local only)")
        self.setMinimumSize(680, 520)
        self._conversations = conversations

        layout = QVBoxLayout(self)
        row = QHBoxLayout()

        self._sessions = QListWidget()
        self._sessions.setMaximumWidth(220)
        self._sessions.currentItemChanged.connect(self._show_session)
        row.addWidget(self._sessions)

        self._viewer = QTextBrowser()
        row.addWidget(self._viewer, 1)
        layout.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._populate()

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

    def _show_session(self, current: QListWidgetItem | None, _previous=None) -> None:
        if current is None:
            self._viewer.clear()
            return
        session_id = current.data(Qt.UserRole)
        session = next(
            (s for s in self._conversations.sessions() if s.get("id") == session_id), None
        )
        if session is None:
            self._viewer.clear()
            return
        parts = [f"# {session.get('title', 'Session')}", f"*{session.get('started_at', '')}*", ""]
        for index, item in enumerate(session.get("items") or [], start=1):
            tag = " (screenshot)" if item.get("kind") == "vision" else ""
            parts.append(f"## Q{index}{tag}")
            parts.append(f"**Q:** {item.get('question', '')}")
            parts.append("")
            parts.append(item.get("answer", ""))
            parts.append("")
        render_mod.render_into(self._viewer, "\n".join(parts))


def render_hotkey_help(settings: AppSettings) -> str:
    lines = [f"`{action}` → `{spec}`" for action, spec in sorted(settings.hotkeys.items())]
    return "\n".join(lines)


def dump_settings(settings: AppSettings) -> str:
    """Debug helper used by the CLI entry point (``--print-settings``)."""
    return json.dumps(settings.to_dict(), indent=2)


__all__ = [
    "DEFAULT_HOTKEYS",
    "HistoryDialog",
    "InfoDialog",
    "LoginDialog",
    "SettingsDialog",
    "dump_settings",
    "render_hotkey_help",
]
