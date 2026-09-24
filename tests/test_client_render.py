"""Answer rendering: markdown → HTML with syntax-highlighted code (offline)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from opengirgit import render  # noqa: E402

pytestmark = pytest.mark.skipif(
    not render.rich_available(), reason="markdown/pygments not installed"
)

SAMPLE = """\
Here is a solution.

```python
def add(a, b):
    return a + b
```

Inline `code` too.
"""


def test_code_blocks_are_highlighted():
    html = render.answer_to_html(SAMPLE)
    assert html is not None
    assert "codehilite" in html
    assert 'style="color:' in html  # pygments inline styles


def test_tables_and_lists_render():
    html = render.answer_to_html("| a | b |\n|---|---|\n| 1 | 2 |\n\n- item\n")
    assert html is not None
    assert "<table>" in html
    assert "<li>item</li>" in html


def test_streaming_partial_fence_does_not_raise():
    partial = "working…\n\n```python\ndef add(a, b):\n    ret"
    assert render.answer_to_html(partial) is not None  # unclosed fence is fine


def test_fallback_when_libraries_missing(monkeypatch):
    monkeypatch.setattr(render, "_HAVE_PYGMENTS", False)
    assert render.answer_to_html(SAMPLE) is None
    monkeypatch.setattr(render, "_HAVE_MARKDOWN", False)
    assert render.answer_to_html(SAMPLE) is None


class _ViewStub:
    """Records which rendering path a QTextBrowser-like view took."""

    def __init__(self) -> None:
        self.html: str | None = None
        self.markdown: str | None = None
        self.stylesheet: str | None = None

    def document(self):
        return self

    def setDefaultStyleSheet(self, css: str) -> None:
        self.stylesheet = css

    def setHtml(self, html: str) -> None:
        self.html = html

    def setMarkdown(self, markdown: str) -> None:
        self.markdown = markdown


def test_render_into_prefers_html():
    view = _ViewStub()
    assert render.render_into(view, SAMPLE) is True
    assert view.html is not None and "codehilite" in view.html
    assert view.markdown is None
    assert view.stylesheet is not None


def test_render_into_falls_back(monkeypatch):
    monkeypatch.setattr(render, "_HAVE_MARKDOWN", False)
    view = _ViewStub()
    assert render.render_into(view, SAMPLE) is False
    assert view.markdown == SAMPLE
    assert view.html is None
