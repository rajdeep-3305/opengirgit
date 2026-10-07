"""Headless construction/wiring tests for the Qt UI (skipped without PySide6).

Runs under the ``offscreen`` Qt platform plugin, so it works on CI without a
display server.
"""

from __future__ import annotations

import base64
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from opengirgit.api import ApiClient  # noqa: E402
from opengirgit.capture import RegionSelector, pixmap_from_b64, pixmap_to_jpeg_b64  # noqa: E402
from opengirgit.config import AppSettings  # noqa: E402
from opengirgit.dialogs import (  # noqa: E402
    FeedbackDialog,
    HistoryDialog,
    InfoDialog,
    LoginDialog,
    SettingsDialog,
)
from opengirgit.overlay import OverlayWindow  # noqa: E402
from opengirgit.stores import ConversationStore  # noqa: E402
from PySide6.QtCore import QBuffer, QEvent, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QPixmap  # noqa: E402
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
    live QApplication still owns them. Deferred deletions are delivered too:
    tests run outside an event loop, and a surviving QWebEnginePage crashes at
    exit when the WebEngine profile is released.
    """
    yield
    for widget in list(qt_app.topLevelWidgets()):
        widget.close()
        widget.deleteLater()
    qt_app.processEvents()
    qt_app.sendPostedEvents(None, QEvent.DeferredDelete)
    qt_app.sendPostedEvents()
    qt_app.processEvents()


class _StubApi(ApiClient):
    """Streams a canned answer without touching the network."""

    def __init__(self) -> None:
        super().__init__("http://127.0.0.1:1")
        self.calls: list[str] = []
        self.vision_images: list[list[str]] = []

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
        self.vision_images.append(list(images_b64))
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
    settings_dialog.wait_for_workers()  # the dialog must not outlive its worker thread
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


def test_settings_hotkey_editor(qt_app, tmp_path, monkeypatch):
    from opengirgit import dialogs as dialogs_module
    from opengirgit.config import DEFAULT_HOTKEYS

    monkeypatch.setattr(AppSettings, "save", lambda self: None)  # never touch ~/.opengirgit
    warnings: list[str] = []
    monkeypatch.setattr(
        dialogs_module.QMessageBox,
        "warning",
        lambda *args, **kwargs: warnings.append(str(args[-1])),
    )

    settings = _settings(tmp_path)
    dialog = SettingsDialog(settings)
    assert set(dialog._hotkey_edits) == set(DEFAULT_HOTKEYS)  # noqa: SLF001

    # invalid spec: warned, nothing saved
    dialog._hotkey_edits["ask"].setText("Q")  # noqa: SLF001
    dialog._save()  # noqa: SLF001
    assert warnings and "ask" in warnings[-1]
    assert settings.hotkeys["ask"] == DEFAULT_HOTKEYS["ask"]

    # duplicate: warned
    warnings.clear()
    dialog._hotkey_edits["ask"].setText(DEFAULT_HOTKEYS["erase"])  # noqa: SLF001
    dialog._save()  # noqa: SLF001
    assert warnings and "erase" in warnings[-1]

    # reset restores defaults
    dialog._reset_hotkeys()  # noqa: SLF001
    assert dialog._hotkey_edits["ask"].text() == DEFAULT_HOTKEYS["ask"]  # noqa: SLF001

    # valid change: saved in place and accepted
    dialog._hotkey_edits["ask"].setText("Ctrl+Shift+F9")  # noqa: SLF001
    dialog._hotkey_edits["erase"].setText("")  # noqa: SLF001 - disable is allowed
    dialog._save()  # noqa: SLF001
    assert settings.hotkeys["ask"] == "Ctrl+Shift+F9"
    assert settings.hotkeys["erase"] == ""
    assert dialog.result() == dialog.DialogCode.Accepted
    dialog.close()
    dialog.deleteLater()


class _ResumeCache:
    def __init__(self, tmp_path) -> None:
        self._path = tmp_path

    def load(self) -> dict:
        return {}

    def save(self, *args, **kwargs) -> None:
        return None


class _FeedbackApi(ApiClient):
    def __init__(self) -> None:
        super().__init__("http://127.0.0.1:1")
        self.sent: list[str] = []

    def submit_feedback(self, message, **kwargs):  # type: ignore[override]
        self.sent.append(message)
        return {"success": True}


def test_feedback_dialog_sends(qt_app):
    api = _FeedbackApi()
    dialog = FeedbackDialog(api, email="a@b.c")

    dialog._send()  # noqa: SLF001 - empty message must not send
    assert api.sent == []
    assert "Write something" in dialog._status.text()  # noqa: SLF001

    dialog._message.setPlainText("great tool")  # noqa: SLF001
    dialog._send()  # noqa: SLF001
    from PySide6.QtTest import QTest

    for _ in range(100):  # run the loop until the queued worker signal arrives
        qt_app.processEvents()
        if "Sent" in dialog._status.text():  # noqa: SLF001
            break
        QTest.qWait(20)
    assert api.sent == ["great tool"]
    assert "Sent" in dialog._status.text()  # noqa: SLF001
    dialog.close()
    dialog.deleteLater()


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


def test_region_selector_decoy_cursor(qt_app):
    from opengirgit import decoy as decoy_module

    selector = RegionSelector()  # decoy on by default
    selector.show()
    qt_app.processEvents()
    assert selector.cursor().shape() == Qt.BlankCursor
    assert selector._dummy is not None  # noqa: SLF001
    assert selector._dummy.isVisible()  # noqa: SLF001
    assert selector._dummy.windowFlags() & Qt.WindowTransparentForInput  # noqa: SLF001

    selector.close()
    qt_app.processEvents()
    assert not selector._dummy.isVisible()  # noqa: SLF001

    plain = RegionSelector(decoy=False)
    plain.show()
    qt_app.processEvents()
    assert plain.cursor().shape() == Qt.CrossCursor
    assert plain._dummy is None  # noqa: SLF001
    plain.close()

    pixmap, hotspot = decoy_module.cursor_pixmap()
    assert not pixmap.isNull()
    assert pixmap.width() > 0 and pixmap.height() > 0
    assert isinstance(hotspot.x(), int)


def _png_b64(width: int = 6, height: int = 4) -> str:
    source = QPixmap(width, height)
    source.fill(Qt.red)
    buffer = QBuffer()
    buffer.open(QBuffer.WriteOnly)
    assert source.save(buffer, "PNG")
    return base64.b64encode(bytes(buffer.data())).decode("ascii")


def test_pixmap_from_b64_roundtrip(qt_app):
    pixmap = pixmap_from_b64(_png_b64(5, 7))
    assert not pixmap.isNull()
    assert (pixmap.width(), pixmap.height()) == (5, 7)
    assert pixmap_from_b64("").isNull()
    assert pixmap_from_b64("!!!not-base64!!!").isNull()
    assert pixmap_from_b64("aGVsbG8=").isNull()  # valid base64, not an image


def test_overlay_shows_screenshot_thumbnails(qt_app, tmp_path):
    overlay = OverlayWindow(_StubApi(), _settings(tmp_path), ConversationStore(), lambda: "")
    encoded = _png_b64()

    overlay._set_attachments([encoded])  # noqa: SLF001
    assert len(overlay._attachment_widgets) == 1  # noqa: SLF001
    assert overlay._attachment_widgets[0].pixmap().height() == 56  # noqa: SLF001

    overlay._set_attachments([encoded] * 6)  # noqa: SLF001
    assert len(overlay._attachment_widgets) == 6  # 5 thumbs + "+1 more"  # noqa: SLF001
    assert "1 more" in overlay._attachment_widgets[-1].text()  # noqa: SLF001

    overlay.erase()
    assert overlay._attachment_widgets == []  # noqa: SLF001
    overlay.close()
    overlay.deleteLater()


def test_capture_queue_attaches_to_next_question(qt_app, tmp_path):
    stub = _StubApi()
    overlay = OverlayWindow(stub, _settings(tmp_path), ConversationStore(), lambda: "")

    assert overlay.add_capture(_png_b64(6, 4)) is True
    assert overlay.add_capture(_png_b64(5, 5)) is True
    assert len(overlay._pending_images) == 2  # noqa: SLF001
    assert len(overlay._pending_widgets) == 2  # noqa: SLF001
    assert "2 screenshots ready" in overlay._status.text()  # noqa: SLF001

    overlay.submit_question("read both regions")
    worker = overlay._worker  # noqa: SLF001
    assert worker is not None
    worker.wait(5000)
    qt_app.processEvents()

    assert stub.calls == ["vision:read both regions"]  # queued shots rode along
    assert len(stub.vision_images[0]) == 2
    assert overlay._pending_images == []  # noqa: SLF001
    assert overlay._pending_widgets == []  # noqa: SLF001
    overlay.close()


def test_capture_queue_caps_and_removes(qt_app, tmp_path):
    overlay = OverlayWindow(_StubApi(), _settings(tmp_path), ConversationStore(), lambda: "")
    shot = _png_b64()

    for _ in range(5):
        assert overlay.add_capture(shot) is True
    assert overlay.add_capture(shot) is False
    assert "maximum 5" in overlay._status.text()  # noqa: SLF001

    overlay._remove_capture(shot)  # noqa: SLF001
    assert len(overlay._pending_images) == 4  # noqa: SLF001

    overlay.erase()
    assert overlay._pending_images == []  # noqa: SLF001
    assert overlay._pending_widgets == []  # noqa: SLF001
    overlay.close()


def test_ask_hotkey_sends_only_screenshots(qt_app, tmp_path):
    stub = _StubApi()
    overlay = OverlayWindow(stub, _settings(tmp_path), ConversationStore(), lambda: "")

    assert overlay.add_capture(_png_b64()) is True
    overlay.ask_hotkey()
    worker = overlay._worker  # noqa: SLF001
    assert worker is not None
    worker.wait(5000)
    qt_app.processEvents()

    assert len(stub.calls) == 1 and stub.calls[0].startswith("vision:")
    assert stub.calls[0] != "vision:"  # the default screenshot prompt was used
    assert len(stub.vision_images[0]) == 1
    overlay.close()


def test_overlay_switches_to_web_view_for_math(qt_app, tmp_path):
    webview = pytest.importorskip("opengirgit.webview")
    if not webview.web_view_available():
        pytest.skip("vendored KaTeX/mermaid assets missing")

    class _MathApi(_StubApi):
        def chat_stream(self, message, **kwargs):  # type: ignore[override]
            self.calls.append(message)
            on_chunk = kwargs.get("on_chunk")
            parts = ["Euler: ", "$e^{i\\pi} + 1 = 0$ completes."]
            for part in parts:
                if on_chunk:
                    on_chunk(part)
            return "".join(parts)

    overlay = OverlayWindow(_MathApi(), _settings(tmp_path), ConversationStore(), lambda: "")
    overlay.submit_question("do the math")
    worker = overlay._worker  # noqa: SLF001
    assert worker is not None
    worker.wait(5000)
    qt_app.processEvents()

    # The embedded page loads asynchronously; the overlay swaps to it on ready.
    deadline = time.monotonic() + 30.0
    while not overlay._web_visible and time.monotonic() < deadline:  # noqa: SLF001
        qt_app.processEvents()
        time.sleep(0.1)
    overlay._flush_answer(force=True)  # noqa: SLF001

    assert overlay._web_visible is True  # noqa: SLF001
    assert overlay._web_view is not None  # noqa: SLF001

    overlay._render_answer("plain text answer", force=True)  # noqa: SLF001
    assert overlay._web_visible is False  # noqa: SLF001
    assert "plain text answer" in overlay._answer_view.toPlainText()  # noqa: SLF001
    overlay.close()


def test_overlay_web_render_disabled_and_failed_fallback(qt_app, tmp_path):
    settings = _settings(tmp_path)
    settings.web_render = False
    overlay = OverlayWindow(_StubApi(), settings, ConversationStore(), lambda: "")
    overlay._answer_buffer = "math $x^2$ here"  # noqa: SLF001
    overlay._render_answer(force=True)  # noqa: SLF001
    assert overlay._web_view is None  # never created  # noqa: SLF001
    assert overlay._web_visible is False  # noqa: SLF001
    assert "x^2" in overlay._answer_view.toPlainText()  # noqa: SLF001

    overlay._web_failed = True  # noqa: SLF001 - pretend the web engine broke
    overlay._render_answer(force=True)  # noqa: SLF001
    assert overlay._web_visible is False  # noqa: SLF001
    assert "x^2" in overlay._answer_view.toPlainText()  # noqa: SLF001
    overlay.close()


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


def test_settings_dialog_persists_the_new_options(qt_app, tmp_path, monkeypatch):
    from opengirgit.config import DEFAULT_HOTKEYS

    monkeypatch.setattr(AppSettings, "save", lambda self: None)
    settings = _settings(tmp_path)
    dialog = SettingsDialog(settings)

    # defaults are reflected in the widgets
    assert dialog._web_render.isChecked() is True  # noqa: SLF001
    assert dialog._partials.isChecked() is True  # noqa: SLF001
    assert dialog._decoy_cursor.isChecked() is True  # noqa: SLF001
    assert dialog._transport.currentData() == "auto"  # noqa: SLF001
    assert dialog._ui_language.currentData() == "en"  # noqa: SLF001
    assert dialog._ui_scale.currentData() == 0  # noqa: SLF001

    dialog._web_render.setChecked(False)  # noqa: SLF001
    dialog._partials.setChecked(False)  # noqa: SLF001
    dialog._decoy_cursor.setChecked(False)  # noqa: SLF001
    dialog._transport.setCurrentIndex(dialog._transport.findData("websocket"))  # noqa: SLF001
    dialog._ui_language.setCurrentIndex(dialog._ui_language.findData("de"))  # noqa: SLF001
    dialog._ui_scale.setCurrentIndex(dialog._ui_scale.findData(125))  # noqa: SLF001
    dialog._hotkey_edits[list(DEFAULT_HOTKEYS)[0]].setText(DEFAULT_HOTKEYS[list(DEFAULT_HOTKEYS)[0]])  # noqa: SLF001
    dialog._save()  # noqa: SLF001

    assert settings.web_render is False
    assert settings.partials is False
    assert settings.decoy_cursor is False
    assert settings.chat_transport == "websocket"
    assert settings.ui_language == "de"
    assert settings.ui_scale == 125
    dialog.close()
    dialog.deleteLater()


def test_history_dialog_exports_and_copies(qt_app, tmp_path, monkeypatch):
    from opengirgit import dialogs as dialogs_module
    from opengirgit import stores as stores_module

    monkeypatch.setattr(stores_module, "CONVERSATIONS_PATH", tmp_path / "conversations.json")
    conversations = stores_module.ConversationStore()
    conversations.start_session("mock interview")
    conversations.add_item("what is a closure?", "It captures its environment.")

    target = tmp_path / "export.md"
    monkeypatch.setattr(
        dialogs_module.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(target), "Markdown (*.md)")),
    )

    dialog = HistoryDialog(conversations)
    assert dialog._sessions.count() == 1  # noqa: SLF001
    # the light palette keeps headings visible (regression: white-on-white)
    assert "#111111" in dialog._viewer.document().defaultStyleSheet()  # noqa: SLF001

    dialog._export_selected()  # noqa: SLF001
    written = target.read_text(encoding="utf-8")
    assert "what is a closure?" in written
    assert "It captures its environment." in written
    assert "Exported" in dialog._status.text()  # noqa: SLF001

    dialog._export_all()  # noqa: SLF001
    assert "OpenGirGit conversation export" in target.read_text(encoding="utf-8")

    dialog._copy_selected()  # noqa: SLF001
    clipboard = QGuiApplication.clipboard()
    assert clipboard is not None and "what is a closure?" in clipboard.text()
    dialog.close()
    dialog.deleteLater()


def test_history_dialog_export_without_selection_warns(qt_app, tmp_path, monkeypatch):
    from opengirgit import stores as stores_module

    monkeypatch.setattr(stores_module, "CONVERSATIONS_PATH", tmp_path / "empty.json")
    conversations = stores_module.ConversationStore()
    dialog = HistoryDialog(conversations)
    dialog._export_selected()  # noqa: SLF001 - nothing selected
    assert "Select a session" in dialog._status.text()  # noqa: SLF001
    dialog.close()
    dialog.deleteLater()


def test_overlay_retranslates_when_the_language_changes(qt_app, tmp_path, monkeypatch):
    from opengirgit import i18n

    monkeypatch.setattr(i18n, "_current", "en")
    i18n.set_language("de")
    try:
        overlay = OverlayWindow(_StubApi(), _settings(tmp_path), ConversationStore(), lambda: "")
        assert overlay._ask_button.text() == "Fragen"  # noqa: SLF001
        assert overlay._title_label.text() == "Antwort"  # noqa: SLF001
        assert "Mikrofon" in overlay._mic_button.toolTip()  # noqa: SLF001
        # the overlay answer panel keeps the dark stylesheet
        overlay._show_text_answer("# Heading\n\n**bold** text")  # noqa: SLF001
        assert "#ffffff" in overlay._answer_view.document().defaultStyleSheet()  # noqa: SLF001

        assert overlay.add_capture(_png_b64()) is True
        status = overlay._status.text()  # noqa: SLF001
        assert "1 Screenshot bereit" in status
        assert overlay.add_capture(_png_b64()) is True
        assert "2 Screenshots bereit" in overlay._status.text()  # noqa: SLF001

        overlay.erase()
        assert overlay._status.text() == "geleert"  # noqa: SLF001
        overlay.close()
    finally:
        i18n.set_language("en")
