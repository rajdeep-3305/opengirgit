"""Markdown → rich HTML for the answer panel (syntax-highlighted code).

The answer panel is a ``QTextBrowser``, which understands a subset of HTML.
Plain ``setMarkdown`` renders code blocks as unstyled monospace text; this
module converts the answer to HTML first so fenced code blocks are
syntax-highlighted with Pygments (inline styles, so Qt needs no external CSS
for them) and tables render properly.

Math (``$…$``, ``$$…$$``, ``\\(…\\)``, ``\\[…\\]``) and mermaid fenced blocks
cannot be drawn by ``QTextBrowser``; ``answer_to_web_fragment`` produces the
same markdown as an HTML fragment for the optional QtWebEngine answer view
(:mod:`opengirgit.webview`), leaving KaTeX delimiters and
``div.mermaid`` nodes for the bundled JavaScript to render.

Both ``markdown`` and ``pygments`` are soft dependencies: if either is missing
the caller falls back to ``QTextBrowser.setMarkdown``.
"""

from __future__ import annotations

import base64
import html as _html
import itertools
import re
import uuid
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
_DARK_CSS = """
body { color: #ececf1; background-color: transparent; }
h1, h2, h3, h4 { color: #ffffff; }
a { color: #58a6ff; }
code { font-family: Consolas, "Courier New", monospace; background-color: #2c2c2c;
       color: #e6edf3; }
pre { font-family: Consolas, "Courier New", monospace; background-color: #0d1117;
      color: #e6edf3; }
blockquote { color: #c9d1d9; }
table { border-collapse: collapse; }
th, td { border: 1px solid #30363d; padding: 6px 9px; }
hr { color: #30363d; }
"""

#: CSS for documents shown on a standard light palette (e.g. the history dialog).
_LIGHT_CSS = """
body { color: #1f1f1f; background-color: transparent; }
h1, h2, h3, h4 { color: #111111; }
a { color: #0b5cad; }
code { font-family: Consolas, "Courier New", monospace; background-color: #ececec;
       color: #1f1f1f; }
pre { font-family: Consolas, "Courier New", monospace; background-color: #f4f4f4;
      color: #1f1f1f; }
blockquote { color: #555555; }
table { border-collapse: collapse; }
th, td { border: 1px solid #b8b8b8; padding: 3px 7px; }
hr { color: #bbbbbb; }
"""

_EXTENSIONS = ["fenced_code", "codehilite", "tables", "sane_lists"]


def rich_available() -> bool:
    """True when markdown+pygments are importable."""
    return _HAVE_MARKDOWN and _HAVE_PYGMENTS


def answer_css(variant: str = "dark") -> str:
    """Stylesheet set on a document before importing HTML.

    ``variant`` is ``"dark"`` for the translucent overlay answer panel (default)
    or ``"light"`` for views on the standard light palette.
    """
    return _LIGHT_CSS if variant == "light" else _DARK_CSS


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


def render_into(view: Any, markdown_text: str, *, variant: str = "dark") -> bool:
    """Render ``markdown_text`` into a ``QTextBrowser``-like ``view``.

    ``variant`` selects the colour scheme (see :func:`answer_css`). Returns True
    when the rich (highlighted) path was used, False when the plain
    ``setMarkdown`` fallback was taken.
    """
    try:
        view.document().setDefaultStyleSheet(answer_css(variant))
    except Exception:  # noqa: BLE001 - not a QTextDocument view; keep going
        pass
    html = answer_to_html(markdown_text)
    if html is None:
        view.setMarkdown(markdown_text)
        return False
    view.setHtml(html)
    return True


# --------------------------------------------------------------------------- #
# Math / mermaid → web-view fragment
# --------------------------------------------------------------------------- #

_CODE_FENCE_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<fence>`{3,})[ \t]*(?P<info>[^\n`]*?)[ \t]*\r?\n"
    r"(?P<body>.*?)"
    r"^(?P=indent)(?P=fence)[ \t]*$",
    re.M | re.S,
)
_INLINE_CODE_RE = re.compile(r"(?P<ticks>`+)(?P<body>[^\n]*?)(?P=ticks)")
_DISPLAY_MATH_RE = re.compile(r"\\\[(?P<paren>.+?)\\\]|\$\$(?P<dollar>.+?)\$\$", re.S)
_INLINE_MATH_RE = re.compile(
    r"\\\((?P<paren>.+?)\\\)"
    r"|(?<![\\$])\$(?![ \t$])(?P<dollar>(?:\\.|[^$\\\n])+?)(?<![\\ \t])\$(?!\d)"
)
_MERMAID_FENCE_RE = re.compile(r"^[ \t]*(?:`{3,}|~{3,})[ \t]*mermaid\b", re.M | re.I)


def needs_web_view(text: str) -> bool:
    """True when the answer contains math or a mermaid block.

    Used by the overlay to pick the web view renderer; a few false positives
    (dollar signs in prose) only cost a slightly heavier renderer.
    """
    if not text:
        return False
    if _MERMAID_FENCE_RE.search(text):
        return True
    if "$$" in text or "\\(" in text or "\\[" in text:
        return True
    return _INLINE_MATH_RE.search(text) is not None


def _mermaid_div(source: str) -> str:
    """A mermaid node the web view turns into an SVG (source kept as fallback)."""
    source = source.strip("\n")
    encoded = base64.b64encode(source.encode("utf-8")).decode("ascii")
    return (
        f'<div class="mermaid" data-src="{encoded}">'
        f'<pre class="mermaid-source">{_html.escape(source)}</pre>'
        f"</div>"
    )


def answer_to_web_fragment(text: str) -> str | None:
    """Markdown → HTML fragment with KaTeX/mermaid nodes, or None if unavailable.

    Code (fenced blocks and inline spans) is protected first so ``$`` or
    backslash-parens inside code are never mistaken for math; the protected
    text is put back before markdown runs, so highlighting is unchanged.
    """
    if not text or not rich_available():
        return None

    nonce = uuid.uuid4().hex[:10]
    counter = itertools.count()
    blocks: dict[str, str] = {}  # token → block-level HTML (math display, mermaid)
    inlines: dict[str, str] = {}  # token → inline HTML (math)
    protected: dict[str, str] = {}  # token → original code text (restored pre-markdown)

    def token() -> str:
        return f"OG{nonce}T{next(counter)}X"

    def protect_fence(match: re.Match[str]) -> str:
        info = (match.group("info") or "").strip().lower()
        if info.split(" ", 1)[0] == "mermaid":
            tok = token()
            blocks[tok] = _mermaid_div(match.group("body"))
            return f"\n\n{tok}\n\n"
        tok = token()
        protected[tok] = match.group(0)
        return tok

    def protect_inline_code(match: re.Match[str]) -> str:
        tok = token()
        protected[tok] = match.group(0)
        return tok

    def display_math(match: re.Match[str]) -> str:
        latex = match.group("paren") or match.group("dollar") or ""
        tok = token()
        blocks[tok] = (
            f'<div class="arithmatex">\\[{_html.escape(latex.strip(), quote=False)}\\]</div>'
        )
        return f"\n\n{tok}\n\n"

    def inline_math(match: re.Match[str]) -> str:
        latex = match.group("paren") or match.group("dollar") or ""
        tok = token()
        inlines[tok] = (
            f'<span class="arithmatex">\\({_html.escape(latex.strip(), quote=False)}\\)</span>'
        )
        return tok

    stripped = _CODE_FENCE_RE.sub(protect_fence, text)
    stripped = _INLINE_CODE_RE.sub(protect_inline_code, stripped)
    stripped = _DISPLAY_MATH_RE.sub(display_math, stripped)
    stripped = _INLINE_MATH_RE.sub(inline_math, stripped)
    for tok, original in protected.items():
        stripped = stripped.replace(tok, original)

    fragment = answer_to_html(stripped)
    if fragment is None:
        return None
    for tok, replacement in blocks.items():
        fragment = re.sub(
            r"<p>\s*" + re.escape(tok) + r"\s*</p>",
            lambda _match, html=replacement: html,
            fragment,
        )
        fragment = fragment.replace(tok, replacement)
    for tok, replacement in inlines.items():
        fragment = fragment.replace(tok, replacement)
    return fragment


def render_into_web(view: Any, markdown_text: str, *, streaming: bool = False) -> bool:
    """Render math/mermaid markdown into a web view; False = use the text view."""
    fragment = answer_to_web_fragment(markdown_text)
    if fragment is None:
        return False
    try:
        view.set_content(fragment, streaming=streaming)
    except Exception:  # noqa: BLE001 - a broken web view must not break answers
        return False
    return True
