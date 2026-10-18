# Vendored assets

Bundled so the answer view can render answers **offline** — no CDN, no network
access. Each component's license text sits next to its files.

| Asset | Version | Files | License |
| --- | --- | --- | --- |
| [KaTeX](https://katex.org/) | 0.16.22 | `katex/katex.min.js`, `katex/katex.min.css`, `katex/auto-render.min.js`, `katex/fonts/*.woff2` | MIT |
| [mermaid](https://mermaid.js.org/) | 11.12.0 | `mermaid/mermaid.min.js` | MIT |
| [highlight.js](https://highlightjs.org/) | 11.9.0 | `highlight/highlight.min.js`, `highlight/github-dark.min.css` | BSD-3-Clause |
| [Google Material Symbols](https://fonts.google.com/icons) | current | `icons/*.svg` | Apache-2.0 |

Sources: the `katex`, `mermaid` and `highlight.js` npm packages, and Google
Material Symbols.

Notes:

- Only `woff2` fonts are vendored (Chromium uses those); the `woff`/`ttf`
  fallbacks referenced by `katex.min.css` are omitted to keep the bundle small.
- `client/opengirgit/render.py` leaves `$…$`, `$$…$$` and mermaid fences in the
  HTML; `client/opengirgit/webview.py` loads KaTeX, mermaid and highlight.js
  from this directory (or from `_MEIPASS` in the PyInstaller bundle).
