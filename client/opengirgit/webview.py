"""Optional QtWebEngine answer view: LaTeX math (KaTeX) and mermaid diagrams.

The primary answer panel is a ``QTextBrowser`` — fast and dependency-free.
This module adds a second renderer used only when an answer actually contains
math or a mermaid fence: a ``QWebEngineView`` that loads KaTeX and mermaid
from the JS assets vendored in ``opengirgit/assets`` (MIT; no network access,
no CDN).

Everything here is imported lazily by the overlay, because importing
QtWebEngine is expensive and the module may be missing entirely (a
``PySide6-Essentials``-only install); callers fall back to ``QTextBrowser``.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget

#: Page background, matching the overlay's answer panel.
PANEL_BACKGROUND = "#2a2a2a"

_TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>answer</title>
<link rel="stylesheet" href="katex/katex.min.css">
<script src="katex/katex.min.js"></script>
<script src="katex/auto-render.min.js"></script>
<script src="mermaid/mermaid.min.js"></script>
<style>
  ::-webkit-scrollbar { display: none; }
  * { cursor: default !important; }
  html { background-color: #2a2a2a; }
  body { background-color: #2a2a2a; color: #ececf1; margin: 0;
         font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, Helvetica, Arial, sans-serif;
         font-size: 15px; line-height: 1.65; padding: 10px;
         max-width: 100%; word-wrap: break-word; overflow-anchor: none;
         -webkit-font-smoothing: antialiased; }
  #content > *:first-child { margin-top: 0 !important; }
  h1, h2, h3, h4, h5, h6 { color: #ffffff; font-weight: 600;
                           line-height: 1.3; margin: 20px 0 12px; }
  h1 { font-size: 1.7em; border-bottom: 1px solid #30363d; padding-bottom: 0.3em; }
  h2 { font-size: 1.4em; border-bottom: 1px solid #2a2f37; padding-bottom: 0.25em; }
  h3 { font-size: 1.2em; }
  h4 { font-size: 1.05em; }
  h5, h6 { font-size: 1em; color: #c9d1d9; }
  p { margin: 0 0 14px; }
  strong, b { font-weight: 600; color: #ffffff; }
  a { color: #58a6ff; text-decoration: none; }
  a:hover { text-decoration: underline; }
  ul, ol { margin: 0 0 14px; padding-left: 26px; }
  li { margin: 5px 0; }
  li > p { margin: 0 0 6px; }
  code { font-family: "Cascadia Code", Consolas, "Courier New", monospace;
         font-size: 0.92em; background-color: rgba(110, 118, 129, 0.18);
         color: #e6edf3; padding: 0.15em 0.4em; border-radius: 5px; }
  pre { background-color: #0d1117; color: #e6edf3; padding: 14px 16px;
        border-radius: 8px; white-space: pre-wrap; word-wrap: break-word;
        overflow-x: auto; tab-size: 4; font-size: 0.9em; line-height: 1.55;
        border: 1px solid #30363d; margin: 0 0 16px;
        font-family: "Cascadia Code", Consolas, "Courier New", monospace; }
  pre code { background-color: transparent; padding: 0; border: none;
             color: inherit; font-size: inherit; font-family: inherit; }
  table { border-collapse: collapse; width: 100%; margin: 0 0 16px;
          font-size: 0.95em; display: block; overflow-x: auto; }
  th { font-weight: 600; background-color: #161b22; border: 1px solid #30363d;
       padding: 8px 12px; text-align: left; }
  td { border: 1px solid #30363d; padding: 8px 12px; }
  tr:nth-child(2n) { background-color: rgba(110, 118, 129, 0.06); }
  blockquote { padding: 0.4em 1em; color: #c9d1d9;
               border-left: 3px solid #3b82f6;
               background: rgba(56, 139, 253, 0.08);
               border-radius: 0 6px 6px 0; margin: 0 0 16px; }
  blockquote p:last-child { margin-bottom: 0; }
  hr { height: 1px; padding: 0; margin: 20px 0; background-color: #30363d;
       border: 0; }
  .mermaid { background: #0d1117; border: 1px solid #30363d; border-radius: 8px;
             padding: 14px; margin: 0 0 16px; text-align: center;
             overflow-x: auto; }
  .mermaid svg { max-width: 100%; height: auto; }
  .mermaid pre { text-align: left; }
  .arithmatex { max-width: 100%; overflow-x: auto; }
  .katex { color: #ffffff; font-size: 1.05em; }
  .katex-display { margin: 1em 0; text-align: center;
                   overflow-x: auto; overflow-y: hidden; }
</style>
</head><body><div id="content"></div>
<script>
(function () {
  if (window.mermaid) {
    try {
      mermaid.initialize({startOnLoad: false, theme: "dark", securityLevel: "strict"});
    } catch (e) {}
  }
  var counter = 0;
  var generation = 0;
  var mermaidChain = Promise.resolve();

  function decodeSource(base64) {
    var binary = atob(base64);
    try {
      return new TextDecoder("utf-8").decode(
        Uint8Array.from(binary, function (c) { return c.charCodeAt(0); }));
    } catch (e) {
      return binary;
    }
  }

  function renderMath(root) {
    if (!window.renderMathInElement) { return; }
    try {
      renderMathInElement(root, {
        delimiters: [
          {left: "\\\\[", right: "\\\\]", display: true},
          {left: "\\\\(", right: "\\\\)", display: false}
        ],
        ignoredClasses: ["no-math", "mermaid"],
        throwOnError: false
      });
    } catch (e) {}
  }

  function renderMermaid(root, gen) {
    if (!window.mermaid) { return Promise.resolve(); }
    var nodes = root.querySelectorAll(".mermaid[data-src]");
    var index = 0;
    function step() {
      while (index < nodes.length) {
        var node = nodes[index++];
        var source = decodeSource(node.getAttribute("data-src"));
        node.removeAttribute("data-src");
        var renderId = "mmd-" + (counter++);
        return mermaid.render(renderId, source).then(function (result) {
          if (gen === generation) { node.innerHTML = result.svg; }
          return step();
        }).catch(function () {
          return step();  // keep the <pre> source already inside the node
        });
      }
      return Promise.resolve();
    }
    return step();
  }

  window.ogSetContent = function (html, streaming) {
    generation += 1;
    var gen = generation;
    var el = document.getElementById("content");
    var atBottom = (window.innerHeight + window.scrollY) >=
                   (document.documentElement.scrollHeight - 12);
    el.innerHTML = html;
    renderMath(el);
    if (streaming || atBottom) {
      window.scrollTo(0, document.documentElement.scrollHeight);
    }
    mermaidChain = mermaidChain.then(function () {
      return renderMermaid(el, gen);
    }).then(function () {
      if (gen === generation && (streaming || atBottom)) {
        window.scrollTo(0, document.documentElement.scrollHeight);
      }
    }, function () {});
  };

  window.ogClear = function () {
    generation += 1;
    document.getElementById("content").innerHTML = "";
  };

  window.ogScrollTop = function () { window.scrollTo(0, 0); };
  window.ogScrollBy = function (pixels) { window.scrollBy(0, pixels); };
})();
</script></body></html>"""


def assets_dir() -> Path:
    """Directory holding the vendored KaTeX/mermaid assets (source or frozen)."""
    base = Path(__file__).resolve().parent / "assets"
    if base.is_dir():
        return base
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = Path(meipass) / "opengirgit" / "assets"
        if candidate.is_dir():
            return candidate
    return base


def web_view_available() -> bool:
    """True when the JS/CSS assets needed by the template are on disk."""
    assets = assets_dir()
    return all(
        (assets / relative).is_file()
        for relative in (
            "katex/katex.min.js",
            "katex/katex.min.css",
            "katex/auto-render.min.js",
            "mermaid/mermaid.min.js",
        )
    )


class _AnswerPage(QWebEnginePage):
    """Keeps the embedded browser local and quiet."""

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):  # noqa: N802
        if url.scheme() in ("http", "https"):
            QDesktopServices.openUrl(url)
            return False
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)

    def javaScriptConsoleMessage(self, level, message, line, source):  # noqa: N802
        pass  # errors are visible in the page itself; keep the console quiet


class RichAnswerWebView(QWidget):
    """Web view that renders math/mermaid HTML fragments produced by render.py.

    The template page is loaded once; ``set_content`` then swaps the fragment
    through ``window.ogSetContent`` so the bundled JS is not reloaded for
    every streaming flush.
    """

    ready_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(150)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._view = QWebEngineView(self)
        self._view.setContextMenuPolicy(Qt.NoContextMenu)
        self._view.setFocusPolicy(Qt.NoFocus)  # typing stays in the overlay's inputs
        page = _AnswerPage(self._view)
        page.setBackgroundColor(QColor(PANEL_BACKGROUND))
        self._view.setPage(page)
        settings = self._view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.ShowScrollBars, True)
        layout.addWidget(self._view)

        self._ready = False
        self._pending_script: str | None = None
        self._view.loadFinished.connect(self._on_load_finished)
        self._view.setHtml(_TEMPLATE, QUrl.fromLocalFile(str(assets_dir()) + "/"))

    # ------------------------------------------------------------------ API #

    def is_ready(self) -> bool:
        """True once the template page (and its JS) finished loading."""
        return self._ready

    def set_content(self, fragment: str, *, streaming: bool = False) -> None:
        """Replace the rendered answer with ``fragment`` (already escaped HTML)."""
        script = f"window.ogSetContent({json.dumps(fragment)}, {str(bool(streaming)).lower()});"
        self._run(script)

    def clear_content(self) -> None:
        self._run("window.ogClear();")

    def scroll_to_top(self) -> None:
        self._run("window.ogScrollTop();")

    def scroll_by(self, pixels: int) -> None:
        self._run(f"window.ogScrollBy({int(pixels)});")

    # ------------------------------------------------------------ internals #

    def _on_load_finished(self, ok: bool) -> None:
        self._ready = bool(ok)
        if self._pending_script is not None:
            script, self._pending_script = self._pending_script, None
            self._run(script)
        self.ready_changed.emit(self._ready)

    def _run(self, script: str) -> None:
        if not self._ready:
            self._pending_script = script  # latest fragment wins once loaded
            return
        self._view.page().runJavaScript(script)


# --------------------------------------------------------------------------- #
# Headless self-test (``python -m opengirgit --check-render``)
# --------------------------------------------------------------------------- #

_CHECK_SAMPLE = """\
Energy is $E = mc^2$ at rest. A display block:

$$
\\int_0^1 x^2\\,dx = \\tfrac13
$$

```mermaid
graph TD
    A[Start] --> B[End]
```
"""


def _wait_for_js(view: RichAnswerWebView, expression: str, timeout: float) -> object:
    """Pump events until a JS expression returns truthy; returns its value or 0."""
    from PySide6.QtCore import QEventLoop, QTimer

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        box: dict[str, object] = {}
        loop = QEventLoop()
        view._view.page().runJavaScript(  # noqa: SLF001 - same-module helper
            expression,
            lambda value, box=box, loop=loop: (box.update(value=value), loop.quit()),
        )
        QTimer.singleShot(1000, loop.quit)
        loop.exec()
        if box.get("value"):
            return box["value"]
        time.sleep(0.1)
    return 0


def check_render(timeout: float = 40.0) -> int:
    """Render a sample answer headlessly and report what came back.

    Used by ``python -m opengirgit --check-render`` (and by the packaged
    ``OpenGirGit(.exe) --check-render``) so the math/diagram path can be
    verified on any machine, including the Windows build.

    Exit codes: 0 = math and diagram both rendered, 2 = assets or libraries
    missing, 3 = QtWebEngine did not start, 4 = rendering produced nothing.
    """
    if not web_view_available():
        print("math/diagram assets are missing from this installation")
        return 2

    from PySide6.QtCore import QCoreApplication, QEvent, Qt
    from PySide6.QtWidgets import QApplication

    if QApplication.instance() is None:
        QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
    app = QApplication.instance() or QApplication([])

    from . import render

    fragment = render.answer_to_web_fragment(_CHECK_SAMPLE)
    if fragment is None:
        print("markdown/pygments are unavailable; cannot build a sample answer")
        return 2

    view = RichAnswerWebView()
    view.resize(720, 480)
    view.show()
    try:
        if not _wait_for_js(view, "!!(window.ogSetContent && window.mermaid)", timeout):
            print("QtWebEngine did not start in this environment")
            return 3
        view.set_content(fragment, streaming=False)
        katex = _wait_for_js(view, "document.querySelectorAll('.katex').length || 0", timeout)
        svg = _wait_for_js(view, "document.querySelectorAll('.mermaid svg').length || 0", timeout)
        print(f"KaTeX nodes: {katex:g}  mermaid SVGs: {svg:g}")
        ok = isinstance(katex, (int, float)) and katex >= 2 and svg == 1
        print("render check:", "OK" if ok else "FAILED")
        return 0 if ok else 4
    finally:
        view.close()
        view.deleteLater()
        app.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()
