"""Application bootstrap: login, dialogs, overlay, audio/STT and hotkey wiring."""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication, QDialog

from . import stealth
from .api import ApiClient, ApiError
from .audio import AudioCapture, AudioError, default_device_id, list_devices, missing_device_hint
from .capture import RegionSelector, grab_screen_region, pixmap_to_jpeg_b64
from .config import AppSettings, load_dotenv_if_present
from .dialogs import HistoryDialog, InfoDialog, LoginDialog, SettingsDialog
from .hotkeys import GlobalHotkeyManager
from .i18n import set_language, tr
from .overlay import MOVE_STEP, OPACITY_STEP, SCROLL_STEP, OverlayWindow
from .prompts import format_interview_context
from .stores import ContextStore, ConversationStore, CredentialsStore, ResumeCache
from .stt import describe_engine, make_engine
from .version import APP_VERSION


class Listener(QObject):
    """Owns the audio capture thread and the STT engine for one mic session."""

    def __init__(self, overlay: OverlayWindow, settings: AppSettings, api: ApiClient) -> None:
        super().__init__(overlay)
        self._overlay = overlay
        self._settings = settings
        self._api = api
        self._capture: AudioCapture | None = None
        self._engine = None

    def start(self) -> None:
        settings = self._settings
        source_kind = "loopback" if settings.audio_source == "system" else "input"
        device_id = settings.audio_device or default_device_id(source_kind)
        if not device_id:
            self._overlay.set_status(missing_device_hint(settings.audio_source), error=True)
            self._overlay.set_mic_active(False)
            return

        try:
            capture = AudioCapture(device_id)
        except AudioError as exc:
            self._overlay.set_status(str(exc), error=True)
            self._overlay.set_mic_active(False)
            return

        engine = make_engine(settings, self._api)
        capture.frame.connect(engine.feed)
        capture.error.connect(self._on_error)
        capture.started_ok.connect(self._on_started)
        engine.partial.connect(self._on_partial)
        engine.final.connect(self._on_final)
        engine.error.connect(self._on_error)
        engine.status.connect(self._on_status)

        self._capture = capture
        self._engine = engine
        capture.start()
        engine.start()
        self._overlay.set_status(
            tr("listening — {engine}").format(engine=describe_engine(settings))
        )

    def stop(self) -> None:
        if self._capture is not None:
            self._capture.stop_capture()
            self._capture.wait(2000)
            self._capture.deleteLater()
            self._capture = None
        if self._engine is not None:
            self._engine.stop_engine()
            self._engine.wait(4000)
            self._engine.deleteLater()
            self._engine = None
        self._overlay.set_status(tr("idle"))

    def restart(self) -> None:
        self.stop()
        self.start()

    # -- slots (always on the UI thread) ------------------------------------ #

    def _on_started(self, rate: int) -> None:
        self._overlay.set_status(tr("capturing @ {rate} Hz").format(rate=rate))

    def _on_partial(self, text: str) -> None:
        self._overlay.set_partial(text)

    def _on_final(self, text: str) -> None:
        self._overlay.set_final(text)

    def _on_status(self, text: str) -> None:
        self._overlay.set_status(tr("stt: {status}").format(status=text))

    def _on_error(self, message: str) -> None:
        self._overlay.set_status(message, error=True)
        self._overlay.set_mic_active(False)
        self.stop()


class AppController(QObject):
    def __init__(self, app: QApplication, settings: AppSettings, email: str, api: ApiClient) -> None:
        super().__init__()
        self._app = app
        self._settings = settings
        self._email = email
        self._api = api

        self._context_store = ContextStore()
        self._context = self._context_store.load()
        self._conversations = ConversationStore()
        self._resume_cache = ResumeCache()

        self._overlay = OverlayWindow(
            self._api,
            self._settings,
            self._conversations,
            self.context_string,
        )
        self._overlay.setWindowTitle(f"OpenGirGit — {email}")
        self._overlay.mic_toggled.connect(self._on_mic_toggled)
        self._overlay.screenshot_requested.connect(self.take_screenshot)
        self._overlay.settings_requested.connect(self.open_settings)
        self._overlay.history_requested.connect(self.open_history)
        self._overlay.info_requested.connect(self.open_info)
        self._overlay.closed.connect(self._shutdown)

        self._listener = Listener(self._overlay, self._settings, self._api)
        self._selector: RegionSelector | None = None

        self._hotkeys = GlobalHotkeyManager(self, fallback_window=self._overlay)
        self._hotkeys.triggered.connect(self._on_hotkey)
        self._register_hotkeys()

        self._seed_history()
        self._overlay.show()

    # ------------------------------------------------------------- context #

    def context_string(self) -> str:
        return format_interview_context(
            self._context.get("resume"),
            str(self._context.get("company") or ""),
            str(self._context.get("job_description") or ""),
            str(self._context.get("anything_else") or ""),
        )

    def _seed_history(self) -> None:
        sessions = self._conversations.sessions()
        if not sessions:
            return
        items = sessions[0].get("items") or []
        if items:
            self._overlay.load_items(
                [
                    {"question": i.get("question", ""), "answer": i.get("answer", ""), "kind": i.get("kind", "chat")}
                    for i in items
                ]
            )

    # ------------------------------------------------------------- listeners #

    def _on_mic_toggled(self, checked: bool) -> None:
        if checked:
            self._listener.start()
        else:
            self._listener.stop()

    # ------------------------------------------------------------ screenshot #

    def take_screenshot(self) -> None:
        if self._selector is not None:
            self._overlay.set_status(tr("region selection already open"))
            return
        self._selector = RegionSelector(decoy=self._settings.decoy_cursor)
        self._selector.region_selected.connect(self._on_region_selected)
        self._selector.selection_cancelled.connect(self._on_selection_cancelled)
        self._selector.showFullScreen()
        self._selector.raise_()
        self._selector.activateWindow()

    def _on_selection_cancelled(self) -> None:
        self._selector = None

    def _on_region_selected(self, rect) -> None:
        self._selector = None
        pixmap = grab_screen_region(rect)
        if pixmap.isNull():
            self._overlay.set_status(tr("could not capture that region"), error=True)
            return
        encoded = pixmap_to_jpeg_b64(pixmap)
        if not encoded:
            self._overlay.set_status(tr("could not encode the screenshot"), error=True)
            return
        # Queued: the next question (typed, spoken or Ask) carries it along.
        self._overlay.add_capture(encoded)

    # ---------------------------------------------------------------- hotkeys #

    def _register_hotkeys(self) -> None:
        failures = self._hotkeys.register_all(self._settings.hotkeys)
        if failures:
            self._overlay.set_status(
                tr("hotkeys unavailable (already in use): {actions}").format(
                    actions=", ".join(sorted(failures))
                ),
                error=True,
            )

    def _on_hotkey(self, action: str) -> None:
        dispatch = {
            "collapse": self._overlay.toggle_collapse,
            "ask": self._overlay.ask_hotkey,
            "erase": self._overlay.erase,
            "screenshot": self.take_screenshot,
            "prev": self._overlay.show_previous,
            "next": self._overlay.show_next,
            "scroll_up": lambda: self._overlay.nudge_scroll(-SCROLL_STEP),
            "scroll_down": lambda: self._overlay.nudge_scroll(SCROLL_STEP),
            "move_up": lambda: self._overlay.nudge_move(0, -MOVE_STEP),
            "move_down": lambda: self._overlay.nudge_move(0, MOVE_STEP),
            "move_left": lambda: self._overlay.nudge_move(-MOVE_STEP, 0),
            "move_right": lambda: self._overlay.nudge_move(MOVE_STEP, 0),
            "opacity_down": lambda: self._overlay.nudge_opacity(-OPACITY_STEP),
            "opacity_up": lambda: self._overlay.nudge_opacity(OPACITY_STEP),
        }
        handler = dispatch.get(action)
        if handler is not None:
            handler()

    # -------------------------------------------------------------- dialogs #

    def open_settings(self) -> None:
        previous_scale = self._settings.ui_scale
        dialog = SettingsDialog(self._settings, api=self._api, email=self._email)
        if dialog.exec() == QDialog.Accepted:
            self._listener.stop()
            self._listener.deleteLater()
            set_language(self._settings.ui_language)
            self._overlay.apply_settings(self._settings)
            self._hotkeys.unregister_all()
            self._register_hotkeys()
            self._api = ApiClient(
                self._settings.server_url,
                token=self._api.token,
                transport=self._settings.chat_transport,
            )
            self._overlay.set_api(self._api)
            self._listener = Listener(self._overlay, self._settings, self._api)
            if self._settings.ui_scale != previous_scale:
                self._overlay.set_status(tr("UI scale applies after a restart"))

    def open_history(self) -> None:
        HistoryDialog(self._conversations).exec()
        self._seed_history()

    def open_info(self) -> None:
        dialog = InfoDialog(self._api, self._context, self._resume_cache)
        if dialog.exec() == QDialog.Accepted and dialog.result is not None:
            self._context = dialog.result
            self._context_store.save(self._context)
            self._overlay.set_status(tr("interview details saved"))

    def prompt_info_once(self) -> None:
        if not self._context.get("company") and not self._context.get("resume"):
            self.open_info()

    # --------------------------------------------------------------- shutdown #

    def _shutdown(self) -> None:
        self._listener.stop()
        self._hotkeys.unregister_all()
        self._app.quit()


def _authenticate(settings: AppSettings, credentials: CredentialsStore) -> tuple[str, ApiClient] | None:
    """Return (email, client) for an authenticated session, or None if cancelled."""
    stored = credentials.load()
    token = str(stored.get("access_token") or "")
    email = str(stored.get("email") or "")
    stored_server = str(stored.get("server_url") or "")

    if token and email and stored_server and stored_server != settings.server_url:
        token = ""  # token belongs to a different server

    if token:
        api = ApiClient(settings.server_url, token=token, transport=settings.chat_transport)
        try:
            account = api.me()
            return str(account.get("email") or email), api
        except ApiError:
            try:
                refreshed = api.refresh()
                token = str(refreshed.get("access_token") or "")
            except ApiError:
                token = ""
            if token:
                api = ApiClient(settings.server_url, token=token, transport=settings.chat_transport)
                credentials.save(email, token, settings.server_url)
                return email, api

    dialog = LoginDialog(settings)
    if dialog.exec() != QDialog.Accepted or not dialog.credentials:
        return None

    email = dialog.credentials["email"]
    token = dialog.credentials["access_token"]
    credentials.save(email, token, settings.server_url)
    return email, ApiClient(settings.server_url, token=token, transport=settings.chat_transport)


def main(argv: list[str] | None = None) -> int:
    load_dotenv_if_present()
    settings = AppSettings.load()
    set_language(settings.ui_language)

    # Optional interface scaling (0 = leave the system/session DPI alone).
    if settings.ui_scale:
        os.environ.setdefault("QT_SCALE_FACTOR", f"{settings.ui_scale / 100:.2f}")
        os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")

    try:
        from PySide6.QtCore import QCoreApplication, Qt

        # Needed before the QApplication exists for the lazily-created QtWebEngine
        # answer view that renders math and mermaid diagrams.
        QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
    except Exception:  # noqa: BLE001 - only a hint; never block startup over it
        pass

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("OpenGirGit")
    app.setApplicationVersion(APP_VERSION)
    app.setQuitOnLastWindowClosed(False)

    credentials = CredentialsStore()
    session = _authenticate(settings, credentials)
    if session is None:
        print("Sign-in cancelled.")
        return 1
    email, api = session

    controller = AppController(app, settings, email, api)
    controller.prompt_info_once()
    note = stealth.capability_note()
    if not note.startswith("Capture exclusion active"):
        controller._overlay.set_status(note)  # noqa: SLF001 - startup hint

    print(f"OpenGirGit {APP_VERSION} — signed in as {email} via {settings.server_url}")
    return app.exec()


def print_settings() -> int:
    """``python -m opengirgit --print-settings`` debug helper."""
    import json

    load_dotenv_if_present()
    print(json.dumps(AppSettings.load().to_dict(), indent=2))
    return 0


def list_audio_devices() -> int:
    """``python -m opengirgit --list-devices`` helper for device ids."""
    for device in list_devices():
        marker = " (default)" if device.is_default else ""
        print(f"{device.id}\t{device.kind}\t{device.name}{marker}")
    return 0
