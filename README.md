# OpenGirGit

<p align="center">
  <img src="docs/media/opengirgit-hero.png" alt="OpenGirGit — stay in the room, not in the share" width="100%">
</p>

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

## Table of contents

- [Install](#install)
- [Features](#features)
- [What is *not* in this repo](#what-is-not-in-this-repo)
- [Platform support](#platform-support)
- [Global hotkeys](#global-hotkeys)
- [Privacy and stealth notes](#privacy-and-stealth-notes)
- [License](#license)

---

## Install

OpenGirGit runs on **Windows 11 (64-bit)**. You do not need Python, Git, or a
paid account to use the installer; setup takes about 15 minutes, mostly
downloads.

### 1. Download and install

1. Open the [latest release](https://github.com/rajdeep-3305/opengirgit/releases/latest).
2. Download `OpenGirGit-windows-x64-setup.exe`. If you cannot run installers,
   download the portable `.zip` and unpack it instead.
3. Run the file. If Windows shows **“Windows protected your PC”**, click
   **More info → Run anyway** — the app is unsigned, so this warning is expected.
4. Click **Next → Install**. It installs for your user only, so no admin
   password is needed.
5. Start **OpenGirGit** from the Start menu. Keep both windows open: the floating
   bar and the black engine window. Closing the black window quits the app.

### 2. Sign in

Use any email-shaped name (for example `me@example.com`) as your local username —
it is not checked and nothing is sent to it. Click **Send code**. The local
server generates the code and, because no email provider is configured, shows it
in the app and the engine window; it fills in automatically. Then click
**Sign in**.

### 3. Give it an AI model

The app needs a model to answer with. The free, private option runs on your PC
with [Ollama](https://ollama.com/download).

**a) Install Ollama.** Download and run it from <https://ollama.com/download>.
It stays quietly in the background.

**b) Download a model.** Open **PowerShell** (Start → type “PowerShell” → Enter)
and run:

```powershell
ollama pull llama3.1:8b
```

*On a lighter laptop, use `ollama pull llama3.2:3b` and put that name in the file
below instead.*

**c) Point OpenGirGit at it.** Copy this whole block into PowerShell and press
Enter:

```powershell
@"
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_API_KEY=ollama
LLM_CHAT_MODEL=llama3.1:8b
LLM_VISION_MODEL=llava
"@ | Set-Content "$env:LOCALAPPDATA\Programs\OpenGirGit\.env"
```

If you used the portable zip or installed somewhere else, save the same content
as `.env` next to `OpenGirGit.exe`.

**d) Screenshot answers (optional).** Download the vision model once:

```powershell
ollama pull llava
```

**e) Restart OpenGirGit.**

Prefer a cloud model? Put your provider's URL, API key and model name in the
same `.env` file — see [configuration](docs/CONFIGURATION.md#server-environment).
The app is free; the provider bills you directly.

### 4. Set up for the interview

1. Open **Settings → Speech**, choose **System audio (interviewer)** under
   **Audio device to listen to**, and play a video to check the transcript. The
   first time, a small speech model (~150 MB) downloads.
2. Open **Settings → Server → Test connection**. It should say
   `Server is ok. LLM configured: yes.`
3. When the interview-info dialog opens, fill in the company, job description
   and resume. They are sent with every question for that session.
4. Join the call and keep the floating bar open. On Windows 11 the overlay is
   excluded from screen shares.
5. Use the panel or the hotkeys: `Shift+Alt+A` ask, `Shift+Alt+S` screenshot,
   `Shift+Alt+H` collapse, `Shift+Alt+C` click-through.

Full walkthrough and fixes: [setup guide](docs/SETUP.md). Building from source,
self-hosting, or checking verification? See [`CONTRIBUTING.md`](CONTRIBUTING.md),
[`docs/CONFIGURATION.md`](docs/CONFIGURATION.md), and
[`docs/VERIFICATION.md`](docs/VERIFICATION.md).

## Features

| Feature | What it does |
|---|---|
| **Speech input** | Captures system audio (WASAPI loopback) or a microphone. |
| **Transcription** | Local faster-whisper with live partials, or optional Deepgram streaming. |
| **Answers** | Streams Markdown, code, tables, LaTeX math and mermaid from any OpenAI-compatible model. |
| **Vision** | Attaches up to five screen regions to a question. |
| **Context** | Adds company, job description, resume and notes to every request. |
| **History** | Keeps sessions locally, with hotkey navigation and Markdown export. |
| **Overlay** | Always-on-top panel with click-through, opacity, resizing and UI scaling. |
| **Hotkeys** | 15 global actions, remappable in Settings. |
| **Stealth** | Capture exclusion, taskbar/Alt-Tab hiding and a decoy cursor. |
| **Auth** | Local email-OTP accounts on your own server. |
| **Packaging** | One-command launcher, Windows bundle and per-user installer. |
| **Zero billing** | No payments, minute accounting or phone-home. |

## What is *not* in this repo

* **No vendor binaries, strings, assets or decompiled code.** Everything here was
  written from scratch from the original's *observable behaviour*.
* **No subscription, billing or payment logic.** There is no payment code, no
  minute accounting and no phone-home anywhere in this repository; your server
  bills nothing.
* **No telemetry, no auto-update, no remote kill-switch.**

## Platform support

OpenGirGit targets **Windows 11 (64-bit)** only. Stealth is the point of the
product, and Win32 capture exclusion is the only supported way to get it.
Windows 10, Linux and macOS are out of scope: there are no builds, no install
guides, and no support claims for them. The interface, transcription and
built-in answer prompt are English-only.

| Capability | Windows 11 |
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
  `WS_EX_TOOLWINDOW` so it stays out of the taskbar and Alt-Tab. Supported on
  Windows 11 (64-bit) only; do not rely on stealth on any other platform.
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
vendored KaTeX/mermaid under MIT, highlight.js under BSD-3-Clause, Material
Symbols under Apache-2.0, …) — each under its own license, listed in
[`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md).
