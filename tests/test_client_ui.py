"""Headless construction/wiring tests for the Qt UI (skipped without PySide6).

Runs under the ``offscreen`` Qt platform plugin, so it works on CI without a
display server.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from opengirgit.api import ApiClient  # noqa: E402
from opengirgit.capture import RegionSelector, pixmap_to_jpeg_b64  # noqa: E402
from opengirgit.config import AppSettings  # noqa: E402
from opengirgit.dialogs import HistoryDialog, InfoDialog, LoginDialog, SettingsDialog  # noqa: E402
from opengirgit.overlay import OverlayWindow  # noqa: E402
from opengirgit.stores import ConversationStore  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _qt_cleanup(qt_app):
    """Delete top-level widgets deterministically, in *Qt's* order.

    Letting Python garbage-collect parent/child widgets in arbitrary order at
    interpreter exit makes shiboken crash, so widgets are closed here while a
    live QApplication still owns them.
    """
    yield
    for widget in list(qt_app.topLevelWidgets()):
        widget.close()
        widget.deleteLater()
    qt_app.processEvents()
    qt_app.sendPostedEvents()
    qt_app.processEvents()


class _StubApi(ApiClient):
    """Streams a canned answer without touching the network."""

    def __init__(self) -> None:
        super().__init__("http://127.0.0.1:1")
        self.calls: list[str] = []

    def chat_stream(self, message, **kwargs):  # type: ignore[override]
        self.calls.append(message)
        on_chunk = kwargs.get("on_chunk")
        parts = ["Answer to: ", message]
        for part in parts:
            if on_chunk:
                on_chunk(part)
        return "".join(parts)

    def vision_stream(self, prompt, images_b64, **kwargs):  # type: ignore[override]
        self.calls.append(f"vision:{prompt}")
        on_chunk = kwargs.get("on_chunk")
        answer = "Screenshot answer"
        if on_chunk:
            on_chunk(answer)
        return answer


def _settings(tmp_path) -> AppSettings:
    return AppSettings.from_dict({"audio_source": "microphone"})


def test_overlay_constructs_and_streams_answer(qt_app, tmp_path, monkeypatch):
    stub = _StubApi()
    conversations = ConversationStore()
    monkeypatch.setattr(conversations, "_flush", lambda: None)

    overlay = OverlayWindow(stub, _settings(tmp_path), conversations, lambda: "ctx")
    assert overlay.windowTitle().startswith("OpenGirGit")

    overlay.submit_question("Explain goroutines")
    worker = overlay._worker  # noqa: SLF001 - test needs to await the thread
    assert worker is not None
    worker.wait(5000)
    qt_app.processEvents()

    assert stub.calls == ["Explain goroutines"]
    assert overlay._answer_buffer == "Answer to: Explain goroutines"  # noqa: SLF001
    assert overlay._items[0]["question"] == "Explain goroutines"  # noqa: SLF001

    # history navigation and misc verbs must not raise
    overlay.show_previous()
    overlay.show_next()
    overlay.nudge_opacity(0.01)
    overlay.nudge_move(5, 5)
    overlay.nudge_scroll(10)
    overlay.toggle_collapse()
    overlay.toggle_collapse()
    overlay.erase()
    assert overlay._answer_buffer == ""  # noqa: SLF001

    # vision path
    overlay.submit_vision("solve it", ["aGVsbG8="])
    worker = overlay._worker  # noqa: SLF001
    assert worker is not None
    worker.wait(5000)
    qt_app.processEvents()
    assert overlay._answer_buffer == "Screenshot answer"  # noqa: SLF001
    overlay.close()


def test_overlay_reports_errors(qt_app, tmp_path):
    class _Failing(ApiClient):
        def chat_stream(self, *args, **kwargs):
            raise RuntimeError("boom")

    overlay = OverlayWindow(_Failing("http://127.0.0.1:1"), _settings(tmp_path),
                            ConversationStore(), lambda: "")
    overlay.submit_question("hi")
    worker = overlay._worker  # noqa: SLF001
    assert worker is not None
    worker.wait(5000)
    qt_app.processEvents()
    assert "boom" in overlay._status.text()  # noqa: SLF001
    overlay.close()


def test_dialogs_construct(qt_app, tmp_path):
    settings = _settings(tmp_path)
    login = LoginDialog(settings)
    assert login.credentials is None

    settings_dialog = SettingsDialog(settings)
    assert settings_dialog._engine.count() == 2  # noqa: SLF001
    settings_dialog._test_server()  # noqa: SLF001 - must not raise without a server
    settings_dialog.close()

    info = InfoDialog(ApiClient("http://127.0.0.1:1"), {"company": "Acme"}, _ResumeCache(tmp_path))
    info._save()  # noqa: SLF001
    assert info.result is not None and info.result["company"] == "Acme"

    history = HistoryDialog(ConversationStore())
    assert history._sessions.count() >= 0  # noqa: SLF001

    for dialog in (login, settings_dialog, info, history):
        dialog.close()
        dialog.deleteLater()
    qt_app.processEvents()


class _ResumeCache:
    def __init__(self, tmp_path) -> None:
        self._path = tmp_path

    def load(self) -> dict:
        return {}

    def save(self, *args, **kwargs) -> None:
        return None


def test_region_selector_constructs_and_encodes(qt_app):
    selector = RegionSelector()
    selector.show()
    qt_app.processEvents()
    selector.close()

    screen = QGuiApplication.primaryScreen()
    assert screen is not None
    pixmap = screen.grabWindow(0, 0, 0, 40, 30)
    encoded = pixmap_to_jpeg_b64(pixmap)
    assert encoded == "" or isinstance(encoded, str)


def test_app_controller_wiring(qt_app, tmp_path, monkeypatch):
    from opengirgit import app as app_module

    # Keep the controller out of the real ~/.opengirgit stores.
    monkeypatch.setattr(app_module, "ContextStore", lambda: _StubContextStore())
    monkeypatch.setattr(app_module, "ConversationStore", ConversationStore)
    monkeypatch.setattr(app_module, "CredentialsStore", lambda: _StubCredentials())

    settings = AppSettings.from_dict(
        {
            "audio_source": "microphone",
            "hotkeys": {"ask": "Shift+Alt+A", "erase": "Shift+Alt+D"},
        }
    )
    controller = app_module.AppController(qt_app, settings, "test@example.com", _StubApi())

    assert controller._overlay.isVisible()  # noqa: SLF001
    assert controller.context_string().startswith("=== CANDIDATE RESUME ===")
    # Hotkey dispatch must not raise for every action.
    for action in (
        "ask",
        "erase",
        "prev",
        "next",
        "scroll_up",
        "scroll_down",
        "move_up",
        "move_down",
        "move_left",
        "move_right",
        "opacity_down",
        "opacity_up",
        "collapse",
    ):
        controller._on_hotkey(action)  # noqa: SLF001

    controller._listener.stop()  # noqa: SLF001
    controller._hotkeys.unregister_all()  # noqa: SLF001
    overlay = controller._overlay  # noqa: SLF001
    overlay.close()
    overlay.deleteLater()
    del controller
    qt_app.processEvents()


class _StubContextStore:
    def load(self) -> dict:
        return {"resume": {"name": "Ada"}, "company": "Acme"}

    def save(self, data) -> None:
        return None


class _StubCredentials:
    def load(self) -> dict:
        return {}

    def save(self, *args, **kwargs) -> None:
        return None

    def clear(self) -> None:
        return None
