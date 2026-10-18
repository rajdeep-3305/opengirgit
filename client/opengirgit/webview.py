"""The original Chromium answer view: Markdown, code, LaTeX and mermaid.

The overlay shows answers in a ``QWebEngineView`` that loads KaTeX,
mermaid and highlight.js from assets vendored in ``opengirgit/assets`` (no
network access, no CDN).  A hidden ``QTextBrowser`` remains as a fallback for
installations without QtWebEngine.

Everything here is imported lazily by the overlay, because importing
QtWebEngine is expensive and the module may be missing entirely (a
``PySide6-Essentials``-only install); callers fall back to ``QTextBrowser``.
"""

from __future__ import annotations

import html as _html
import json
import sys
import time
from collections.abc import Mapping
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget

from . import ui_icons
from .config import DEFAULT_HOTKEYS

#: Page background, matching the overlay's answer panel.
PANEL_BACKGROUND = "#2a2a2a"

_TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>answer</title>
<link rel="stylesheet" href="highlight/github-dark.min.css">
<link rel="stylesheet" href="katex/katex.min.css">
<script src="highlight/highlight.min.js"></script>
<script src="katex/katex.min.js"></script>
<script src="katex/auto-render.min.js"></script>
<script src="mermaid/mermaid.min.js"></script>
<style>
  ::-webkit-scrollbar { display: none; }
  * { cursor: default !important; }
  body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
      font-size: 15px;
      line-height: 1.65;
      color: #ececf1;
      background-color: #2a2a2a;
      padding: 10px;
      max-width: 100%;
      word-wrap: break-word;
      overflow-y: auto;
      -ms-overflow-style: none;
      scrollbar-width: none;
      overflow-anchor: none;
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
  }
  #content { overflow-anchor: none; }
  #content > *:first-child { margin-top: 0 !important; }

  h1, h2, h3, h4, h5, h6 {
      font-weight: 600;
      line-height: 1.3;
      color: #ffffff;
      margin: 20px 0 12px;
  }
  h1 { font-size: 1.7em; padding-bottom: 0.3em; border-bottom: 1px solid #30363d; }
  h2 { font-size: 1.4em; padding-bottom: 0.25em; border-bottom: 1px solid #2a2f37; }
  h3 { font-size: 1.2em; }
  h4 { font-size: 1.05em; }
  h5, h6 { font-size: 1em; color: #c9d1d9; }

  p { margin: 0 0 14px; }
  strong, b { font-weight: 600; color: #ffffff; }
  em, i { font-style: italic; }
  a { color: #58a6ff; text-decoration: none; }
  a:hover { text-decoration: underline; }

  ul, ol { margin: 0 0 14px; padding-left: 26px; }
  li { margin: 5px 0; }
  li > p { margin: 0 0 6px; }
  ul ul, ul ol, ol ul, ol ol { margin: 6px 0; }
  li::marker { color: #8b949e; }
  ul.task-list { list-style: none; padding-left: 6px; }
  .task-list-item { list-style: none; }
  .task-list-item input { margin-right: 8px; }

  code {
      font-family: 'Cascadia Code', 'Consolas', 'Courier New', monospace;
      font-size: 0.92em;
      background-color: rgba(110, 118, 129, 0.18);
      color: #e6edf3;
      padding: 0.15em 0.4em;
      border-radius: 5px;
  }
  pre {
      background-color: #0d1117;
      color: #e6edf3;
      padding: 14px 16px;
      border-radius: 8px;
      white-space: pre-wrap;
      word-wrap: break-word;
      overflow-x: auto;
      tab-size: 4;
      font-size: 0.9em;
      font-family: 'Cascadia Code', 'Consolas', 'Courier New', monospace;
      line-height: 1.55;
      border: 1px solid #30363d;
      margin: 0 0 16px;
  }
  pre code {
      background-color: transparent;
      padding: 0;
      border: none;
      color: inherit;
      font-size: inherit;
      font-family: inherit;
  }

  table {
      border-collapse: collapse;
      width: 100%;
      margin: 0 0 16px;
      font-size: 0.95em;
      display: block;
      overflow-x: auto;
  }
  th {
      font-weight: 600;
      background-color: #161b22;
      border: 1px solid #30363d;
      padding: 8px 12px;
      text-align: left;
  }
  td { border: 1px solid #30363d; padding: 8px 12px; }
  tr:nth-child(2n) { background-color: rgba(110, 118, 129, 0.06); }

  blockquote {
      padding: 0.4em 1em;
      color: #c9d1d9;
      border-left: 3px solid #3b82f6;
      background: rgba(56, 139, 253, 0.08);
      border-radius: 0 6px 6px 0;
      margin: 0 0 16px;
  }
  blockquote p:last-child { margin-bottom: 0; }

  hr { height: 1px; padding: 0; margin: 20px 0; background-color: #30363d; border: 0; }

  .mermaid-box {
      background: #0d1117;
      border: 1px solid #30363d;
      border-radius: 8px;
      padding: 14px;
      margin: 0 0 16px;
      text-align: center;
      overflow-x: auto;
  }
  .mermaid-box svg { max-width: 100%; height: auto; }
  .mermaid-src { background: transparent; border: none; text-align: left; color: #8b949e; margin: 0; }
  .katex { color: #ffffff; font-size: 1.05em; }
  .katex-display { margin: 1em 0; text-align: center; overflow-x: auto; overflow-y: hidden; }
</style>
<script>
(function () {
  var counter = 0;
  var generation = 0;
  var mmCache = {};
  var mmPending = {};
  var mmFailed = {};
  var mmReady = false;

  function mmHash(s) {
    var h = 0;
    for (var i = 0; i < s.length; i++) {
      h = ((h << 5) - h) + s.charCodeAt(i);
      h |= 0;
    }
    return 'mm' + (h >>> 0);
  }

  function forceVertical(src) {
    try {
      src = src.replace(/^(\\s*)(flowchart|graph)[ \\t]+(LR|RL|BT)\\b/im, '$1$2 TD');
      src = src.replace(/\\bdirection[ \\t]+(LR|RL|BT)\\b/gi, 'direction TB');
    } catch (e) {}
    return src;
  }

  function ensureMermaid() {
    if (typeof mermaid === 'undefined') { return false; }
    if (!mmReady) {
      try {
        mermaid.initialize({
          startOnLoad: false,
          theme: 'dark',
          securityLevel: 'loose',
          suppressErrorRendering: true,
          flowchart: { useMaxWidth: true }
        });
        mmReady = true;
      } catch (e) { return false; }
    }
    return true;
  }

  function cleanupMermaidArtifacts() {
    try {
      document.querySelectorAll('body > [id^="__mm_"], body > [id^="d__mm_"], body > .mermaid-error').forEach(function (n) {
        if (!n.closest || !n.closest('#content')) {
          if (n.parentNode) { n.parentNode.removeChild(n); }
        }
      });
    } catch (e) {}
  }

  function processMermaid(root) {
    if (!ensureMermaid()) { return; }
    cleanupMermaidArtifacts();
    root.querySelectorAll('code.language-mermaid').forEach(function (code) {
      var pre = code.closest('pre') || code;
      var src = forceVertical(code.textContent || '');
      var key = mmHash(src);
      var box = document.createElement('div');
      box.setAttribute('data-mmkey', key);
      if (mmCache[key]) {
        box.className = 'mermaid-box';
        box.innerHTML = mmCache[key];
      } else {
        box.className = mmFailed[key] ? '' : 'mermaid-box';
        box.innerHTML = '<pre><code class="language-text">' + code.innerHTML + '</code></pre>';
        if (!mmFailed[key] && !mmPending[key]) {
          mmPending[key] = true;
          try {
            Promise.resolve(mermaid.parse(src, { suppressErrors: true })).then(function (valid) {
              if (!valid) { mmFailed[key] = true; mmPending[key] = false; return; }
              return mermaid.render('__mm_' + (counter++), src).then(function (res) {
                if (res && res.svg) {
                  mmCache[key] = res.svg;
                  document.querySelectorAll('[data-mmkey="' + key + '"]').forEach(function (h) {
                    h.className = 'mermaid-box';
                    h.innerHTML = res.svg;
                  });
                }
                mmPending[key] = false;
              });
            }).catch(function () { mmFailed[key] = true; mmPending[key] = false; });
          } catch (e) {
            mmFailed[key] = true;
            mmPending[key] = false;
          }
        }
      }
      pre.parentNode.replaceChild(box, pre);
    });
  }

  function renderMath(root) {
    if (typeof renderMathInElement !== 'undefined') {
      try {
        renderMathInElement(root, {
          delimiters: [
            { left: '$$', right: '$$', display: true },
            { left: '$', right: '$', display: false }
          ],
          throwOnError: false
        });
      } catch (e) {}
    }
    processMermaid(root);
    if (typeof hljs !== 'undefined') {
      root.querySelectorAll('pre code:not([data-highlighted])').forEach(function (block) {
        try { hljs.highlightElement(block); } catch (e) {}
      });
    }
  }

  window.ogSetContent = function (html, streaming) {
    generation += 1;
    var el = document.getElementById('content');
    var wasEmpty = el.innerHTML.trim() === '';
    var atBottom = (window.innerHeight + window.scrollY) >=
                   (document.documentElement.scrollHeight - 12);
    el.innerHTML = html;
    renderMath(el);
    if (wasEmpty) {
      window.scrollTo(0, 0);
    } else if (atBottom) {
      window.scrollTo(0, document.documentElement.scrollHeight);
    }
  };

  window.ogClear = function () {
    generation += 1;
    document.getElementById('content').innerHTML = '';
  };

  window.ogScrollTop = function () { window.scrollTo(0, 0); };
  window.ogScrollBy = function (pixels) { window.scrollBy(0, pixels); };
})();
</script>
</head>
<body><div id="content"></div></body></html>"""


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
            "highlight/highlight.min.js",
            "highlight/github-dark.min.css",
        )
    )


def welcome_fragment(hotkeys: Mapping[str, str] | None = None) -> str:
    """The startup help panel, in the original three-column table layout.

    Every row, icon size, shortcut cell and the 92% / -10 px wrapper match the
    original viewer; only the product name differs.
    """
    bindings = hotkeys or DEFAULT_HOTKEYS

    def img(name: str, size: int = 20) -> str:
        return f'<img src="{ui_icons.data_uri(name)}" width="{size}" height="{size}">'

    def key_cell(*actions: str) -> str:
        keys = [str(bindings.get(action, "")).strip() for action in actions]
        codes = [
            f'<code style="font-size: 11px; color: #ffffff;">{_html.escape(key)}</code>'
            for key in keys
            if key
        ]
        if not codes:
            return '<td style="padding: 6px;"></td>'
        return (
            '<td style="padding: 6px; text-align: right; white-space: nowrap; '
            'line-height: 1.9;">' + "<br>".join(codes) + "</td>"
        )

    th = (
        'style="padding: 6px; font-size: 11px; text-transform: uppercase; '
        'letter-spacing: 0.04em; color: #ffffff; font-weight: 700; '
        'background: transparent; border: none; border-bottom: 1px solid #30363d; '
    )
    title = "Welcome to OpenGirGit AI Assistant!"
    rows = [
        (img("send"), "Ask AI a Question", ("ask",), "padding: 6px;"),
        (img("erase"), "Clear Input Box", ("erase",), "padding: 6px;"),
        (
            '<span style="font-size:15px; font-weight:700;">▲ ▼</span>',
            "Scroll the Answer Up / Down",
            ("scroll_up", "scroll_down"),
            "padding: 6px;",
        ),
        (
            img("analyze_screen"),
            "Capture &amp; Analyze Screenshot with AI",
            ("screenshot",),
            "padding: 6px;",
        ),
        (
            img("hide"),
            "Collapse Window to Circle (click circle to expand back)",
            ("collapse",),
            "padding: 6px;",
        ),
        (
            img("prev") + " " + img("next"),
            "Navigate Chat History",
            ("prev", "next"),
            "padding: 6px;",
        ),
        (
            img("circle", 18) + " " + img("circle_filled", 18),
            "Adjust Window Transparency (hollow = more transparent, solid = more opaque)",
            ("opacity_down", "opacity_up"),
            "padding: 6px;",
        ),
        (
            img("move"),
            "Move the Window Up<br>Move the Window Left<br>"
            "Move the Window Down<br>Move the Window Right",
            ("move_up", "move_left", "move_down", "move_right"),
            "padding: 6px; line-height: 1.9;",
        ),
        (
            '<span style="font-size:18px; font-weight:700;">◢</span>',
            "Drag the handle at the bottom-right corner of the answer window to resize it",
            (),
            "padding: 6px;",
        ),
        (
            img("system_mic"),
            "Listening to System Audio (Interviewer's Voice) - starts automatically",
            (),
            "padding: 6px;",
        ),
    ]
    body = "".join(
        f'<tr><td style="padding: 6px; text-align: center;">{icon}</td>'
        f'<td style="{text_style}">{text}</td>'
        f"{key_cell(*actions)}</tr>"
        for icon, text, actions, text_style in rows
    )
    return (
        '<div style="font-size: 92%; transform: translateY(-10px);">'
        f"<h1>{title}</h1>"
        "<p>Ask me anything and I'll respond using AI.</p>"
        "<hr>"
        "<h2>Features</h2>"
        '<table style="border-collapse: collapse; width: 100%;"><tbody>'
        f'<tr><th {th}text-align: center; width: 64px;">Button</th>'
        f'<th {th}text-align: left;">Purpose</th>'
        f'<th {th}text-align: right;">Shortcut</th></tr>'
        f"{body}</tbody></table></div>"
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
        print("markdown is unavailable; cannot build a sample answer")
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
        svg = _wait_for_js(
            view, "document.querySelectorAll('.mermaid-box svg').length || 0", timeout
        )
        print(f"KaTeX nodes: {katex:g}  mermaid SVGs: {svg:g}")
        ok = isinstance(katex, (int, float)) and katex >= 2 and svg == 1
        print("render check:", "OK" if ok else "FAILED")
        return 0 if ok else 4
    finally:
        view.close()
        view.deleteLater()
        app.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()
