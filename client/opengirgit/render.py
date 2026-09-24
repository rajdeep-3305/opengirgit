"""Markdown → rich HTML for the answer panel (syntax-highlighted code).

The answer panel is a ``QTextBrowser``, which understands a subset of HTML.
Plain ``setMarkdown`` renders code blocks as unstyled monospace text; this
module converts the answer to HTML first so fenced code blocks are
syntax-highlighted with Pygments (inline styles, so Qt needs no external CSS
for them) and tables render properly.

Both ``markdown`` and ``pygments`` are soft dependencies: if either is missing
the caller falls back to ``QTextBrowser.setMarkdown``.
"""

from __future__ import annotations

from typing import Any

try:  # pragma: no cover - trivial import guard
    import markdown as _markdown

    _HAVE_MARKDOWN = True
except Exception:  # noqa: BLE001 - any import failure means no rich rendering
    _markdown = None  # type: ignore[assignment]
    _HAVE_MARKDOWN = False

try:  # pragma: no cover - trivial import guard
    from pygments.formatters import HtmlFormatter as _HtmlFormatter

    _HAVE_PYGMENTS = True
except Exception:  # noqa: BLE001
    _HtmlFormatter = None  # type: ignore[assignment]
    _HAVE_PYGMENTS = False

PYGMENTS_STYLE = "monokai"

#: Extra CSS applied to the answer document (dark theme, matches the overlay).
_BASE_CSS = """
body { color: #f2f2f2; background-color: transparent; }
h1, h2, h3, h4 { color: #ffffff; }
a { color: #7ab7ff; }
code { font-family: Consolas, "Courier New", monospace; background-color: #2c2c2c;
       color: #f8f8f2; }
pre { font-family: Consolas, "Courier New", monospace; background-color: #272822;
      color: #f8f8f2; }
blockquote { color: #c9c9c9; }
table { border-collapse: collapse; }
th, td { border: 1px solid #555555; padding: 3px 7px; }
hr { color: #555555; }
"""

_EXTENSIONS = ["fenced_code", "codehilite", "tables", "sane_lists"]


def rich_available() -> bool:
    """True when markdown+pygments are importable."""
    return _HAVE_MARKDOWN and _HAVE_PYGMENTS


def answer_css() -> str:
    """Stylesheet set on the answer document before importing HTML."""
    return _BASE_CSS


def answer_to_html(text: str) -> str | None:
    """Convert markdown to HTML with highlighted code, or None if unavailable."""
    if not text or not rich_available():
        return None
    try:
        return _markdown.markdown(
            text,
            extensions=_EXTENSIONS,
            extension_configs={
                "codehilite": {
                    "noclasses": True,  # inline styles: Qt does not load CSS classes
                    "guess_lang": True,
                    "pygments_style": PYGMENTS_STYLE,
                }
            },
        )
    except Exception:  # noqa: BLE001 - never let rendering break streaming
        return None


def render_into(view: Any, markdown_text: str) -> bool:
    """Render ``markdown_text`` into a ``QTextBrowser``-like ``view``.

    Returns True when the rich (highlighted) path was used, False when the
    plain ``setMarkdown`` fallback was taken.
    """
    try:
        view.document().setDefaultStyleSheet(answer_css())
    except Exception:  # noqa: BLE001 - not a QTextDocument view; keep going
        pass
    html = answer_to_html(markdown_text)
    if html is None:
        view.setMarkdown(markdown_text)
        return False
    view.setHtml(html)
    return True
