"""Embedded QtWebEngine rendering: KaTeX math and mermaid diagrams (offscreen).

The module skips itself when PySide6's WebEngine component or the vendored JS
assets are missing, and when Chromium cannot start in the test environment.
"""

from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from opengirgit import render  # noqa: E402
from PySide6.QtCore import QEvent, QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

webview = pytest.importorskip("opengirgit.webview")  # needs PySide6-WebEngine

MATH_AND_MERMAID = """\
Compute $a^2 + b^2$ first.

$$
\\int_0^1 x\\,dx = \\tfrac12
$$

```mermaid
graph TD
    A[Start] --> B[End]
```
"""


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def _probe(qt_app, widget, expression: str, *, timeout: float = 25.0):
    """Pump the event loop until a JS expression returns truthy, or give up."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        box: dict[str, object] = {}
        loop = QEventLoop()
        widget._view.page().runJavaScript(  # noqa: SLF001 - test drives the page directly
            expression,
            lambda value, box=box, loop=loop: (box.update(value=value), loop.quit()),
        )
        QTimer.singleShot(3000, loop.quit)
        loop.exec()
        if box.get("value"):
            return box["value"]
        qt_app.processEvents()
        time.sleep(0.2)
    return None


@pytest.fixture()
def web_widget(qt_app):
    if not webview.web_view_available():
        pytest.skip("vendored KaTeX/mermaid assets missing")
    widget = webview.RichAnswerWebView()
    widget.resize(640, 480)
    widget.show()
    ready = _probe(qt_app, widget, "!!(window.ogSetContent && window.mermaid)")
    if not ready:
        widget.close()
        widget.deleteLater()
        qt_app.sendPostedEvents(None, QEvent.DeferredDelete)
        qt_app.processEvents()
        pytest.skip("QtWebEngine did not start in this environment")
    yield widget
    widget.close()
    widget.deleteLater()
    qt_app.sendPostedEvents(None, QEvent.DeferredDelete)
    qt_app.processEvents()


def test_bundled_assets_present():
    assets = webview.assets_dir()
    assert (assets / "katex" / "katex.min.js").is_file()
    assert (assets / "katex" / "auto-render.min.js").is_file()
    assert (assets / "mermaid" / "mermaid.min.js").is_file()
    assert (assets / "highlight" / "highlight.min.js").is_file()
    assert webview.web_view_available()


def test_welcome_fragment_is_the_branded_feature_table():
    fragment = webview.welcome_fragment()
    assert "Welcome to OpenGirGit AI Assistant!" in fragment
    assert "<table" in fragment and "Features" in fragment
    assert "Shortcut" in fragment and "Shift+Alt+A" in fragment
    assert fragment.count("data:image/svg+xml;base64,") >= 9


def test_math_and_mermaid_render_offscreen(qt_app, web_widget):
    fragment = render.answer_to_web_fragment(MATH_AND_MERMAID)
    assert fragment is not None and "$a^2 + b^2$" in fragment

    web_widget.set_content(fragment, streaming=False)
    katex = _probe(
        qt_app,
        web_widget,
        "document.querySelectorAll('.katex').length >= 2 ?"
        " document.querySelectorAll('.katex').length : 0",
    )
    assert katex is not None and katex >= 2  # KaTeX replaced both formulas

    svg = _probe(
        qt_app,
        web_widget,
        "document.querySelectorAll('.mermaid-box svg').length || 0",
    )
    assert svg == 1  # mermaid drew the diagram


def test_set_and_clear_content(qt_app, web_widget):
    web_widget.set_content("<p>hello world</p>", streaming=False)
    assert _probe(qt_app, web_widget, "document.getElementById('content').textContent === 'hello world'")

    web_widget.clear_content()
    assert _probe(qt_app, web_widget, "document.getElementById('content').textContent === ''")


def test_check_render_reports_missing_assets(monkeypatch):
    monkeypatch.setattr(webview, "web_view_available", lambda: False)
    assert webview.check_render(timeout=1.0) == 2  # never starts the browser


def test_check_render_passes(qt_app):
    """The documented user command (``--check-render``) succeeds end to end."""
    assert webview.check_render(timeout=40.0) == 0
