# Third-party notices

OpenGirGit itself is licensed under the MIT License (see [`LICENSE`](LICENSE)).
The desktop bundles published in the GitHub releases **redistribute** the
components below, each under its own license. This file lists them with the
license identifiers and the place the component is used.

No code, strings, assets or binaries from the original closed-source "GirGit AI"
application are included anywhere in this repository or its release artifacts.

## Desktop application

| Component | License (SPDX) | Notes |
| --- | --- | --- |
| [PySide6 / Qt 6](https://www.qt.io/) (Core, Gui, Widgets, Network, WebEngine, DBus) | `LGPL-3.0-only` (or GPL/commercial) | Dynamically linked. The shared libraries ship as replaceable files under `_internal/`, so an LGPL relink against a compatible Qt build is possible; sources are published by the Qt project. |
| QtWebEngine (embedded Chromium) | `LGPL-3.0-only`, `BSD-3-Clause` and others | Used for the offline math/diagram answer view. Chromium component licenses ship with Qt. |
| [NumPy](https://numpy.org/) | `BSD-3-Clause` | Audio buffers and resampling. |
| [httpx](https://www.python-httpx.org/) | `BSD-3-Clause` | HTTP/SSE transport. |
| [python-dotenv](https://github.com/theskumar/python-dotenv) | `BSD-3-Clause` | Reads optional `.env` files. |
| [Markdown](https://python-markdown.github.io/) | `BSD-3-Clause` | Answer rendering. |
| [Pymdown Extensions](https://facelessuser.github.io/pymdown-extensions/) | `MIT` | Optional rich Markdown extensions (`betterem`, `tasklist`) used for the original answer styling. |
| [KaTeX](https://katex.org/) | `MIT` | Vendored offline under `client/opengirgit/assets/katex` (its `LICENSE` ships alongside). |
| [mermaid](https://mermaid.js.org/) | `MIT` | Vendored offline under `client/opengirgit/assets/mermaid` (its `LICENSE` ships alongside). |
| [highlight.js](https://highlightjs.org/) | `BSD-3-Clause` | Code-block highlighting; vendored under `client/opengirgit/assets/highlight` (its `LICENSE` ships alongside). |
| [Google Material Symbols](https://fonts.google.com/icons) | `Apache-2.0` | Toolbar SVGs under `client/opengirgit/assets/icons` (the Apache license ships alongside). |
| [sounddevice](https://python-sounddevice.readthedocs.io/) | `MIT` | Microphone capture; bundles PortAudio (`MIT`). |
| [PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch) | `MIT` | Windows system-audio (WASAPI loopback) capture; bundles PortAudio (`MIT`). Windows builds only. |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | `MIT` | Local speech-to-text engine. |
| [CTranslate2](https://github.com/OpenNMT/CTranslate2) | `MIT` | Whisper inference backend. |
| [onnxruntime](https://onnxruntime.ai/) | `MIT` | Voice-activity detection for faster-whisper. |
| [tokenizers](https://github.com/huggingface/tokenizers) | `Apache-2.0` | Whisper tokenizer. |
| [huggingface_hub](https://github.com/huggingface/huggingface_hub) | `Apache-2.0` | Downloads Whisper model weights on first use. |
| [tqdm](https://tqdm.github.io/) | `MIT` | Model download progress. |
| [PyAV](https://pyav.org/) | `BSD-3-Clause` | Audio decoding for local STT; binary wheels bundle FFmpeg libraries (`LGPL-2.1-or-later`). |
| [websockets](https://github.com/python-websockets/websockets) | `BSD-3-Clause` | Deepgram streaming client. |
| [pypdf](https://pypdf.readthedocs.io/) | `BSD-3-Clause` | Resume text extraction. |
| [python-docx](https://python-docx.readthedocs.io/) | `MIT` | Resume text extraction. |
| [PyInstaller](https://pyinstaller.org/) (bootloader) | `GPL-2.0-or-later` **with exception** | The bootloader's exception explicitly permits bundling and distributing applications under any license, including this one. |

**Model weights.** The Whisper speech models are **downloaded by the user** at
first transcription time (OpenAI Whisper weights, `MIT`) and are not part of the
repository or the release bundles.

## Backend (embedded in the desktop bundle; also installable from `server/requirements.txt`)

| Component | License (SPDX) | Notes |
| --- | --- | --- |
| [FastAPI](https://fastapi.tiangolo.com/) | `MIT` | HTTP/WebSocket API. |
| [Starlette](https://www.starlette.io/) | `BSD-3-Clause` | Transitive (FastAPI ASGI toolkit). |
| [Uvicorn](https://www.uvicorn.org/) | `BSD-3-Clause` | ASGI server. |
| [PyJWT](https://pyjwt.readthedocs.io/) | `MIT` | Access-token signing/validation. |
| [Pydantic](https://docs.pydantic.dev/) + `pydantic-settings`, `pydantic-core` | `MIT` | Configuration and request models. |
| [httpx](https://www.python-httpx.org/) | `BSD-3-Clause` | Outbound LLM/STT calls. |
| uvicorn `[standard]` extras: [uvloop](https://github.com/MagicStack/uvloop) (`MIT`), [httptools](https://github.com/MagicStack/httptools) (`MIT`), [watchfiles](https://github.com/samuelcolvin/watchfiles) (`MIT`), [PyYAML](https://pyyaml.org/) (`MIT`), [websockets](https://github.com/python-websockets/websockets) (`BSD-3-Clause`), [colorama](https://github.com/tartley/colorama) (`BSD-3-Clause`, Windows) | see left | Transitive server dependencies. |

## Services

Cloud engines (Deepgram, or any OpenAI-compatible LLM endpoint) are contacted
over the network with **the user's own credentials**; no vendor code is bundled
or redistributed. Ollama and other local models run on the user's machine and
are not part of this project.

---

If you redistribute OpenGirGit or build on it, keep this file (and the vendored
`LICENSE` files under `client/opengirgit/assets/`) with the artifacts.
