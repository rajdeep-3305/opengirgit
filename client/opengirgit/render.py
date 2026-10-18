"""Markdown → the answer HTML shared by the original web answer view.

The visible answer panel uses QtWebEngine.  This module converts the model's
Markdown to the same HTML shape the original viewer produced: fenced code
blocks keep their ``language-*`` class for highlight.js, tables stay tables,
and math/mermaid source is left for the bundled KaTeX/mermaid scripts to
render.  No network access is used.

The ``QTextBrowser`` path remains only as a fallback for installations without
QtWebEngine; it still gets a dark stylesheet and HTML, but cannot run scripts.
"""

from __future__ import annotations

import re
from typing import Any

try:  # pragma: no cover - trivial import guard
    import markdown as _markdown

    _HAVE_MARKDOWN = True
except Exception:  # noqa: BLE001 - any import failure means no rich rendering
    _markdown = None  # type: ignore[assignment]
    _HAVE_MARKDOWN = False


#: Extra CSS applied to the fallback answer document (dark theme).
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

_EXTENSIONS = ["fenced_code", "tables", "sane_lists"]
_RICH_EXTENSIONS = [
    *_EXTENSIONS,
    "attr_list",
    "pymdownx.betterem",
    "pymdownx.tasklist",
]
_EXTENSION_CONFIGS = {"pymdownx.tasklist": {"custom_checkbox": True}}
_MD_EXTENSIONS: list[str] | None = None
_MD_EXTENSION_CONFIGS: dict[str, dict[str, Any]] | None = None


def _resolve_md_extensions() -> tuple[list[str], dict[str, dict[str, Any]]]:
    """Use the same rich Markdown set as the original, with a basic fallback."""
    global _MD_EXTENSIONS, _MD_EXTENSION_CONFIGS
    if _MD_EXTENSIONS is not None:
        return _MD_EXTENSIONS, _MD_EXTENSION_CONFIGS or {}
    if _markdown is not None:
        try:
            _markdown.markdown(
                "probe",
                extensions=_RICH_EXTENSIONS,
                extension_configs=_EXTENSION_CONFIGS,
            )
        except Exception:  # noqa: BLE001 - pymdownx is optional
            _MD_EXTENSIONS = list(_EXTENSIONS)
            _MD_EXTENSION_CONFIGS = {}
        else:
            _MD_EXTENSIONS = list(_RICH_EXTENSIONS)
            _MD_EXTENSION_CONFIGS = _EXTENSION_CONFIGS
    else:
        _MD_EXTENSIONS = list(_EXTENSIONS)
        _MD_EXTENSION_CONFIGS = {}
    return _MD_EXTENSIONS, _MD_EXTENSION_CONFIGS


def rich_available() -> bool:
    """True when Markdown is importable."""
    return _HAVE_MARKDOWN


def _preprocess_latex(text: str) -> str:
    """Turn the LaTeX delimiters models commonly use into KaTeX delimiters."""
    text = re.sub(r"\\\[\s*(.*?)\s*\\\]", r"$$\1$$", text, flags=re.DOTALL)
    text = re.sub(
        r"^\[\s*\n(.*?)\n\s*\]$",
        r"$$\1$$",
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    text = re.sub(
        r"^\[\s*([^\[\]]*\\[a-zA-Z]+[^\[\]]*)\s*\]$",
        r"$$\1$$",
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    text = re.sub(r"\\\(\s*(.*?)\s*\\\)", r"$\1$", text, flags=re.DOTALL)
    return text


_LIST_INDENT_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])(\s+)(.*)$")
_FENCE_RE = re.compile(r"^(```|~~~)")


def _normalize_list_indentation(text: str) -> str:
    """Snap nested list indentation to the four-space steps Markdown expects."""
    lines = text.split("\n")
    out: list[str] = []
    in_fence = False
    for line in lines:
        stripped = line.lstrip()
        if _FENCE_RE.match(stripped):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        match = _LIST_INDENT_RE.match(line)
        if match:
            spaces = len(match.group(1))
            if spaces:
                spaces = max(4, ((spaces + 3) // 4) * 4)
            out.append(" " * spaces + line[len(match.group(1)) :])
        else:
            out.append(line)
    return "\n".join(out)


def answer_css(variant: str = "dark") -> str:
    """Stylesheet set on a document before importing HTML.

    ``variant`` is ``"dark"`` for the translucent overlay answer panel (default)
    or ``"light"`` for views on the standard light palette.
    """
    return _LIGHT_CSS if variant == "light" else _DARK_CSS


def answer_to_html(text: str) -> str | None:
    """Convert markdown to HTML (code carries ``language-*`` classes)."""
    if not text or not rich_available():
        return None
    try:
        extensions, configs = _resolve_md_extensions()
        prepared = _normalize_list_indentation(_preprocess_latex(text))
        return _markdown.markdown(
            prepared,
            extensions=extensions,
            extension_configs=configs,
        )
    except Exception:  # noqa: BLE001 - never let rendering break streaming
        return None


def render_into(view: Any, markdown_text: str, *, variant: str = "dark") -> bool:
    """Render ``markdown_text`` into a ``QTextBrowser``-like ``view``.

    ``variant`` selects the colour scheme (see :func:`answer_css`). Returns True
    when the HTML path was used, False when the plain ``setMarkdown`` fallback
    was taken.
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
    r"^(?P<indent>[ \t]*)(?P<fence>`{3,}|~{3,})[ \t]*(?P<info>[^\n`]*?)[ \t]*\r?\n"
    r"(?P<body>.*?)"
    r"^(?P=indent)(?P=fence)[ \t]*$",
    re.M | re.S,
)
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


def answer_to_web_fragment(text: str) -> str | None:
    """Markdown → the same HTML fragment the original web view receives.

    Math (``$…$``/``$$…$$``) and mermaid fences are intentionally left in the
    HTML: the bundled KaTeX and mermaid scripts recognize the same syntax after
    the fragment is inserted, exactly as the original viewer did.  Code blocks
    keep their ``language-*`` class so highlight.js can colour them.
    """
    return answer_to_html(text)


def has_switchable_code(text: str) -> bool:
    """True when an answer has a fenced code block other than mermaid."""
    if not text:
        return False
    for match in _CODE_FENCE_RE.finditer(text):
        info = (match.group("info") or "").strip().lower()
        if info.split(" ", 1)[0] != "mermaid":
            return True
    return False


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
