"""Answer rendering: the same Markdown HTML shape as the original web view."""

from __future__ import annotations

import os
import re

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from opengirgit import render  # noqa: E402

pytestmark = pytest.mark.skipif(
    not render.rich_available(), reason="markdown not installed"
)

SAMPLE = """\
Here is a solution.

```python
def add(a, b):
    return a + b
```

Inline `code` too.
"""

MATH_ANSWER = """\
Energy is $E = mc^2$ at rest.

$$
\\int_0^1 x^2\\,dx = \\tfrac13
$$

```bash
echo "$HOME $(date)"
```

```mermaid
graph TD
    A[One] --> B[Two]
```
"""


def test_code_blocks_keep_the_original_language_class():
    html = render.answer_to_html(SAMPLE)
    assert html is not None
    assert '<pre><code class="language-python">' in html
    assert "codehilite" not in html
    assert "def add(a, b):" in html


def test_tables_and_lists_render():
    html = render.answer_to_html("| a | b |\n|---|---|\n| 1 | 2 |\n\n- item\n")
    assert html is not None
    assert "<table>" in html
    assert "<li>item</li>" in html


def test_streaming_partial_fence_does_not_raise():
    partial = "working…\n\n```python\ndef add(a, b):\n    ret"
    assert render.answer_to_html(partial) is not None  # unclosed fence is fine


def test_fallback_when_markdown_missing(monkeypatch):
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
    assert view.html is not None and 'class="language-python"' in view.html
    assert view.markdown is None
    assert view.stylesheet is not None


def test_render_into_falls_back(monkeypatch):
    monkeypatch.setattr(render, "_HAVE_MARKDOWN", False)
    view = _ViewStub()
    assert render.render_into(view, SAMPLE) is False
    assert view.markdown == SAMPLE
    assert view.html is None


# --------------------------------------------------------------- math/mermaid #


def test_latex_delimiters_are_normalized_for_katex():
    html = render.answer_to_html(r"Use \[x^2\] and \(a+b\).")
    assert html is not None
    assert "$$x^2$$" in html
    assert "$a+b$" in html


def test_nested_list_indentation_is_normalized():
    html = render.answer_to_html("- top\n  - nested\n")
    assert html is not None
    assert "nested" in html
    assert "<ul>" in html


def test_needs_web_view_detection():
    assert render.needs_web_view("solve $x^2$ for x")
    assert render.needs_web_view("$$\nx\n$$")
    assert render.needs_web_view(r"use \(a+b\) here")
    assert render.needs_web_view("\\[\nf(x)\n\\]")
    assert render.needs_web_view("```mermaid\ngraph TD\n```")
    assert not render.needs_web_view("plain answer")
    assert not render.needs_web_view("")
    # currency is not math (no web view needed for prose alone)
    assert not render.needs_web_view("It costs $5 and $10 in total.")


def test_web_fragment_leaves_math_and_mermaid_for_the_scripts():
    fragment = render.answer_to_web_fragment(MATH_ANSWER)
    assert fragment is not None
    assert "$E = mc^2$" in fragment
    assert "$$" in fragment
    assert '<code class="language-mermaid">' in fragment
    assert '<code class="language-bash">' in fragment
    assert "codehilite" not in fragment


def test_web_fragment_leaves_dollar_signs_in_code_alone():
    fragment = render.answer_to_web_fragment(MATH_ANSWER)
    assert fragment is not None
    text = re.sub(r"<[^>]+>", "", fragment)
    text = text.replace("&quot;", '"')
    assert 'echo "$HOME $(date)"' in text
    assert "$E = mc^2$" in fragment


def test_switchable_code_detection():
    assert render.has_switchable_code("```python\nprint(1)\n```")
    assert not render.has_switchable_code("```mermaid\ngraph TD\n```")
    assert not render.has_switchable_code("inline `code` only")
    assert not render.has_switchable_code("")


def test_web_fragment_none_without_libraries(monkeypatch):
    monkeypatch.setattr(render, "_HAVE_MARKDOWN", False)
    assert render.answer_to_web_fragment(MATH_ANSWER) is None


class _WebViewStub:
    """Records what render_into_web pushes into a web view."""

    def __init__(self) -> None:
        self.content: str | None = None
        self.streaming: bool | None = None

    def set_content(self, fragment: str, *, streaming: bool = False) -> None:
        self.content = fragment
        self.streaming = streaming


def test_render_into_web_records_content():
    view = _WebViewStub()
    assert render.render_into_web(view, MATH_ANSWER, streaming=True) is True
    assert view.content is not None and "$E = mc^2$" in view.content
    assert view.streaming is True


def test_render_into_web_falls_back(monkeypatch):
    monkeypatch.setattr(render, "_HAVE_MARKDOWN", False)
    view = _WebViewStub()
    assert render.render_into_web(view, MATH_ANSWER) is False
    assert view.content is None


def test_light_and_dark_stylesheets_differ():
    dark = render.answer_css()
    light = render.answer_css("light")
    assert "#ffffff" in dark and "#111111" in light
    assert dark != light
    assert render.answer_css("dark") == dark  # default variant unchanged


def test_render_into_selects_the_stylesheet_variant():
    class _Document:
        def __init__(self) -> None:
            self.sheet = ""
            self.html = ""

        def setDefaultStyleSheet(self, css: str) -> None:
            self.sheet = css

    class _View:
        def __init__(self) -> None:
            self._document = _Document()

        def document(self) -> _Document:
            return self._document

        def setHtml(self, html: str) -> None:
            self._document.html = html

        def setMarkdown(self, text: str) -> None:  # pragma: no cover - fallback only
            self._document.html = text

    dark_view = _View()
    assert render.render_into(dark_view, "# title\n\ntext") is True
    assert dark_view._document.sheet == render.answer_css()

    light_view = _View()
    render.render_into(light_view, "# title\n\ntext", variant="light")
    assert light_view._document.sheet == render.answer_css("light")
