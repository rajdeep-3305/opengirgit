# OpenGirGit

<p align="center">
  <img src="docs/media/opengirgit-hero.png" alt="OpenGirGit — stay in the room, not in the share" width="100%">
</p>

<p align="center"><sub>Interface mock-up: the overlay listening, with a streamed answer.</sub></p>

An open-source **interview-copilot overlay**: it listens to the interviewer through
your speakers, transcribes speech in real time, and streams AI answers into a
small always-on-top panel that you can keep out of screen shares.

OpenGirGit is a **clean-room, MIT-licensed re-implementation** of the architecture
used by the commercial Windows app *GirGit AI*, written from observed behaviour.
It contains **no vendor code, no vendor keys, and no billing** — you
run your own server, plug in your own model, and pay nobody.

```
┌──────────────── your machine ─────────────────┐        ┌─────── optional ───────┐
│  client/  (PySide6 overlay)                   │        │ OpenAI / OpenRouter    │
│   ├ WASAPI loopback / mic capture             │        │ Ollama / LM Studio     │
│   ├ local faster-whisper STT  ────────────────┼───┐    │ any OpenAI-compatible  │
│   └ SSE chat + vision stream ─────────────────┼─┐ │    └────────────────────────┘
└───────────────────────────────────────────────┘ │ │              ▲
                                                  │ │              │
┌──────────────── server/ (FastAPI) ──────────────┼─┴──────────────┘
│  OTP auth · profiles · chat/vision SSE proxy    │
│  resume parsing · optional Deepgram token mint  │   ── wss://api.deepgram.com (opt-in)
└─────────────────────────────────────────────────┘
```

---

## Install

**Windows 10 2004+ / Windows 11 (64-bit) only.** Download the latest
`OpenGirGit-windows-x64-setup.exe` (or the portable zip) from
[Releases](https://github.com/rajdeep-3305/opengirgit/releases/latest), then follow
the plain-language [setup guide](docs/SETUP.md) — install, point it at a free
local model, done.

Building from source, self-hosting, or checking verification? See
[`CONTRIBUTING.md`](CONTRIBUTING.md), [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md)
and [`docs/VERIFICATION.md`](docs/VERIFICATION.md).

## Table of contents

- [Features](#features)
- [What is *not* in this repo](#what-is-not-in-this-repo)
- [Platform support](#platform-support)
- [Global hotkeys](#global-hotkeys)
- [Privacy and stealth notes](#privacy-and-stealth-notes)
- [License](#license)

---

## Features

| Area | What OpenGirGit does |
|---|---|
| **Speech input** | Captures **system audio loopback** through WASAPI — or a regular microphone — and resamples everything to 16 kHz mono. |
| **Transcription** | **Local** [faster-whisper](https://github.com/SYSTRAN/faster-whisper) by default (nothing leaves your machine), or **Deepgram** streaming over a direct WebSocket using a short-lived token minted by *your* server. The local engine also fills the box **while the speaker is talking** (re-transcribes every ~1.2 s, with adaptive back-off on slow machines). |
| **Answers** | Streaming chat from any **OpenAI-compatible** endpoint (OpenAI, OpenRouter, Groq, Ollama, LM Studio, vLLM…), over **SSE** or the optional **WebSocket** transport (auto, with SSE fallback). Answers render as streaming Markdown with **syntax-highlighted code blocks**, tables, **LaTeX math** (KaTeX) and **mermaid diagrams** — rendered by a bundled, fully offline web view (no CDN). The `code:` combo rewrites the shown answer's code in the picked language and **caches each variant per answer**. |
| **Vision** | Hotkey → select a screen region. Each selection is **queued as a removable thumbnail**, so several regions (up to 5, e.g. a problem statement and its examples) can be attached to one question; the next question you type, speak or Ask carries them to a vision-capable model ("solve the coding problem on screen"). |
| **Context** | Resume (PDF/DOCX/TXT), company, job description and free-form notes are formatted into a context block that is attached to every request. The JD and notes boxes also accept **attached files**: documents are text-extracted locally (never uploaded), images are transcribed by the vision model and folded in. |
| **History** | Conversation history is stored **locally** in `~/.opengirgit/`, browsable in a dialog (sessions are named after their first question), navigable with hotkeys, and **exportable to Markdown** (one session or all of it, or straight to the clipboard). |
| **Overlay UX** | Frameless, always-on-top, translucent, draggable bar with a short slide animation for collapse/expand and a startup fade; **click-through mode** (the mouse works through the overlay to the app underneath — `Shift+Alt+C` returns control); a **streaming preview popup** teases the answer while the panel is collapsed; tabbed settings (Server / Speech / Behaviour / Hotkeys); opacity and move hotkeys; resize grip; hi-DPI-aware thumbnails and an optional **interface scale** for 100–200 % sessions. |
| **Hotkeys** | 15 global actions, editable **in the settings dialog** (empty value disables one) with validation. |
| **Languages** | The interface ships an offline translation layer (English + German today) with `auto` following the desktop locale; adding a language is dropping one JSON file in [`client/opengirgit/translations/`](client/opengirgit/translations/README.md) — no Qt/`.qm` toolchain needed. |
| **Stealth** | The windows are excluded from capture (`SetWindowDisplayAffinity`, `WDA_EXCLUDEFROMCAPTURE`) and hidden from the taskbar/Alt-Tab. During region selection the real cursor is blanked and a stand-in copy stays parked at the anchor, so a screen share sees an ordinary motionless cursor. |
| **Auth** | Local email-OTP accounts issued by your own server (SMTP optional — dev mode prints the code). |
| **Packaging** | `run.ps1` bootstraps everything with one command; CI builds a PyInstaller **one-folder Windows build** (client + server in one exe) and a **per-user installer** (Inno Setup, no admin prompt, German + English wizard) on release tags. |
| **Zero billing** | There is no payment code, no minute accounting and no phone-home anywhere in this repository. |

## What is *not* in this repo

* **No vendor binaries, strings, assets or decompiled code.** Everything here was
  written from scratch from the original's *observable behaviour*.
* **No subscription, billing or payment logic.** There is no payment code, no
  minute accounting and no phone-home anywhere in this repository; your server
  bills nothing.
* **No telemetry, no auto-update, no remote kill-switch.**

## Platform support

OpenGirGit targets **Windows 10 2004+ / Windows 11 (64-bit)** only. Stealth is
the point of the product, and Win32 capture exclusion is the only supported way
to get it. Linux and macOS are out of scope: there are no builds, no install
guides, and no support claims for them.

| Capability | Windows |
|---|---|
| Overlay, dialogs, streaming answers | ✅ |
| Region screenshots | ✅ native grab |
| System-wide hotkeys | ✅ `RegisterHotKey` |
| System-audio loopback | ✅ WASAPI |
| Capture exclusion (screen-share invisibility) | ✅ `WDA_EXCLUDEFROMCAPTURE` |
| Taskbar / Alt-Tab hiding | ✅ `WS_EX_TOOLWINDOW` |

The source is portable Python and still runs on Linux for development, but the
system-audio, global-hotkey and stealth backends exist only on Windows.

## Global hotkeys

Defaults (all remappable in the settings dialog or `config.json`). They are
**system-wide** on Windows through `RegisterHotKey`, with OS key-repeat
suppressed for the tap-style actions:

| Action | Default | Notes |
|---|---|---|
| Collapse / expand answers | `Shift+Alt+H` | |
| Ask AI (submits the manual box) | `Shift+Alt+A` | OS key-repeat suppressed |
| Erase inputs | `Shift+Alt+D` | OS key-repeat suppressed |
| Screenshot region (repeat to attach several) | `Shift+Alt+S` | opens a selection overlay; each region is queued as a thumbnail |
| Click-through (mouse works through the overlay) | `Shift+Alt+C` | session-only; the same hotkey brings clicks back |
| Previous / next answer | `Shift+Alt+[` / `Shift+Alt+]` | |
| Scroll answer up / down | `Shift+Alt+W` / `Shift+Alt+X` | hold to repeat |
| Move overlay up/down/left/right | `Shift+Alt+I` / `K` / `J` / `L` | hold to repeat |
| Opacity down / up | `Shift+Alt+-` / `Shift+Alt+=` | hold to repeat |

## Privacy and stealth notes

* **Where your data goes.** Audio → only to the STT engine you chose (local
  faster-whisper by default; Deepgram if enabled). Questions/screenshots →
  only to the LLM endpoint your server is configured with. No third party
  receives anything else.
* **Screen-share invisibility.** Every OpenGirGit window calls
  `SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)`, which excludes it
  from `BitBlt`-style capture used by Zoom/Teams/Meet, and sets
  `WS_EX_TOOLWINDOW` so it stays out of the taskbar and Alt-Tab. This needs
  Windows 10 version 2004 (build 19041) or newer; on older builds the flag
  degrades and the window appears as a black rectangle in shares. Unsupported
  platforms have no capture exclusion at all; do not rely on stealth there.
* **Decoy cursor (`decoy_cursor=true`).** While you drag the screenshot region,
  the real pointer is blanked on the selection overlay and a stand-in copy
  (the actual system cursor bitmap on Windows, read via GDI) stays parked at
  the button you pressed, so a screen share sees a normal, motionless cursor
  instead of a crosshair sweeping the screen; when you finish, the real cursor
  is glided back to the anchor.
* **Ethics.** You are responsible for complying with the rules of whatever
  interview, exam or call you use this in. Many employers and testing platforms
  forbid assistive tooling; nothing in this repository is designed to defeat
  human-perceptible detection (the stealth flag is a documented OS window
  attribute, not a hook or a cheat), and no warranty of any kind is provided.

## License

MIT — see [`LICENSE`](LICENSE). OpenGirGit is an independent project inspired by
the commercial Windows app *GirGit AI*; it contains no vendor code, strings,
assets or binaries from it and is not affiliated with or endorsed by its
authors.

Release bundles redistribute third-party components (Qt/PySide6 under LGPL-3.0,
vendored KaTeX/mermaid under MIT, …) — each under its own license, listed in
[`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md).
