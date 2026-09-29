# Vendored rendering assets

Bundled so the overlay's optional web view can render answers **offline** — no
CDN, no network access. Both projects are MIT-licensed; their license texts sit
next to the files.

| Asset | Version | Files | License |
| --- | --- | --- | --- |
| [KaTeX](https://katex.org/) | 0.16.22 | `katex/katex.min.js`, `katex/katex.min.css`, `katex/auto-render.min.js`, `katex/fonts/*.woff2` | MIT |
| [mermaid](https://mermaid.js.org/) | 11.12.0 | `mermaid/mermaid.min.js` | MIT |

Source: the `katex` and `mermaid` npm packages (`dist/` folders).

Notes:

- Only `woff2` fonts are vendored (Chromium uses those); the `woff`/`ttf`
  fallbacks referenced by `katex.min.css` are omitted to keep the bundle small.
- `client/opengirgit/render.py` rewrites math into KaTeX delimiters and mermaid
  fences into `div.mermaid` nodes; `client/opengirgit/webview.py` loads these
  files from this directory (or from `_MEIPASS` in the PyInstaller bundle).
