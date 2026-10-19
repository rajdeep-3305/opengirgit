# Archive notice

OpenGirGit was archived on **2026-10-19**. The repository is read-only and the
project is no longer maintained. There will be no new releases, features,
dependency updates, support, or security fixes.

**v0.2.3 is the final release.**

## Why the project stopped

OpenGirGit set out to be a clean-room, MIT-licensed interview-copilot overlay for
Windows 11. The engineering was viable, but the product was not good enough for
the job it was built to do:

- **Latency.** On ordinary hardware, the local pipeline (Whisper speech-to-text
  plus a local 8B model) took too long end-to-end for a live interview. A fast
  cloud model shortens the answer latency, but adds an API key, a per-use bill,
  and setup friction for every user.
- **Answer quality.** General-purpose model prompts produced generic answers.
  We did not build an interview-specific answer pipeline comparable to the
  commercial products in this space.
- **Distribution.** Competing with a polished, established paid product through
  Windows-only stealth features was not a credible wedge for this project.
- **Unfinished hardware verification.** Automated tests and Windows CI passed,
  but the full real-hardware pass was never completed. The open items included
  WASAPI loopback, native hotkeys under a real meeting app, capture exclusion,
  the decoy cursor, the packaged UI, and install/upgrade/uninstall.

Stopping was more honest than continuing to ship something we could not recommend
for its intended use.

## What was built

The repository contains a working reference implementation:

- PySide6 overlay with a control bar, streaming answer panel, history,
  click-through mode, opacity controls, and global hotkeys.
- Local faster-whisper transcription with live partials, plus optional Deepgram
  streaming.
- A FastAPI backend for local accounts, profiles, resume parsing, and SSE or
  WebSocket chat/vision streaming to any OpenAI-compatible model.
- Offline Markdown, syntax highlighting, KaTeX math, and mermaid rendering.
- A Windows 11 x64 PyInstaller bundle and per-user Inno Setup installer.
- No billing, payments, telemetry, auto-update, or remote kill-switch.

The latest source and the `v0.2.3` Windows setup/ZIP assets remain available in
the repository and its releases. Release artifacts are unsigned and are provided
as-is.

## Verification

The following passed before release:

- 158 offline tests and `ruff check server client tests packaging`.
- The end-to-end server/client check (`tests/e2e/run_e2e.py`).
- Offline WebEngine rendering: `--check-render` reported
  `KaTeX nodes: 2  mermaid SVGs: 1` and `render check: OK`.
- Windows CI: core suite, Qt/WebEngine tests, bundle smoke test, packaged
  `--check-render`, and the Inno Setup build.

The real Windows 11 hands-on checklist in
[`docs/WINDOWS-CHECKLIST.md`](docs/WINDOWS-CHECKLIST.md) was not completed. Do
not treat CI as a substitute for those checks. The detailed record is in
[`docs/VERIFICATION.md`](docs/VERIFICATION.md).

## Clean-room status and license

OpenGirGit was written from observed behaviour. It contains no vendor code,
decompiled code, proprietary strings, assets, or binaries. The original
branding, local authentication, settings, history, and backend are
OpenGirGit-specific; the overlay is a close visual rebuild, not a certified
pixel-perfect copy.

The original code is released under the [MIT license](LICENSE). Third-party
components remain under their own licenses and are listed in
[`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md). OpenGirGit is not affiliated
with or endorsed by GirGit AI or its authors.

## If you use an old build

- Treat it as unmaintained software. There are no security patches.
- Rotate any provider API key that was configured in a development or release
  build. The project never shipped a key, but `.env` files and local settings
  are controlled by whoever installed the app.
- Review the ethics and rules of any interview, exam, or call before using any
  assistive tool. Many employers and testing platforms prohibit this class of
  software; the project provides no warranty and does not help evade
  human-perceptible detection.

## Thanks

Thanks to the maintainers of Qt/PySide6, faster-whisper, FastAPI, KaTeX,
mermaid, highlight.js, and the other open-source components that made the
reference implementation possible.
