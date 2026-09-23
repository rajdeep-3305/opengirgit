# OpenGirGit

An open-source **interview-copilot overlay**: it listens to the interviewer through
your speakers, transcribes speech in real time, and streams AI answers into a
small always-on-top panel that you can keep out of screen shares.

OpenGirGit is a **clean-room, MIT-licensed re-implementation** of the architecture
used by the commercial Windows app *GirGit AI* (reverse-engineering report:
[`REPORT.md`](REPORT.md)). It contains **no vendor code, no vendor keys, and no
billing** — you run your own server, plug in your own model, and pay nobody.

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

- [Features](#features)
- [What is *not* in this repo](#what-is-not-in-this-repo)
- [Repository layout](#repository-layout)
- [Quick start](#quick-start)
  - [1. Server](#1-server)
  - [2. Client](#2-client)
- [Configuration](#configuration)
  - [Server environment](#server-environment)
  - [Client settings](#client-settings)
- [Global hotkeys](#global-hotkeys)
- [Privacy and stealth notes](#privacy-and-stealth-notes)
- [Relationship to the original app](#relationship-to-the-original-app)
- [Development](#development)
- [Roadmap](#roadmap)
- [License](#license)

---

## Features

| Area | What OpenGirGit does |
|---|---|
| **Speech input** | Captures **system audio loopback** (the interviewer's voice in Zoom/Meet/Teams — Windows/WASAPI) or a regular microphone (any OS), resamples to 16 kHz mono. |
| **Transcription** | **Local** [faster-whisper](https://github.com/SYSTRAN/faster-whisper) by default (nothing leaves your machine), or **Deepgram** streaming over a direct WebSocket using a short-lived token minted by *your* server. |
| **Answers** | SSE streaming chat from any **OpenAI-compatible** endpoint (OpenAI, OpenRouter, Groq, Ollama, LM Studio, vLLM…). Answers render as streaming Markdown. |
| **Vision** | Hotkey → select a screen region → the screenshot is sent to a vision-capable model (e.g. "solve the coding problem on screen"). |
| **Context** | Resume (PDF/DOCX/TXT), company, job description and free-form notes are formatted into a context block that is attached to every request. |
| **History** | Conversation history is stored **locally** in `~/.opengirgit/`, browsable in a dialog, navigable with hotkeys. |
| **Overlay UX** | Frameless, always-on-top, translucent, draggable bar; collapsible answer panel; opacity and move hotkeys; resize grip. |
| **Stealth** | On Windows the windows are excluded from capture (`SetWindowDisplayAffinity`, `WDA_EXCLUDEFROMCAPTURE`) and hidden from the taskbar/Alt-Tab — the same documented Win32 calls the original uses. |
| **Auth** | Local email-OTP accounts issued by your own server (SMTP optional — dev mode prints the code). |
| **Zero billing** | There is no payment code, no minute accounting and no phone-home anywhere in this repository. |

## What is *not* in this repo

* **No vendor binaries, strings, assets or decompiled code.** Everything here was
  written from scratch; `REPORT.md` only *describes* the original's behaviour.
* **No subscription/billing/payment logic.** The original debits ₹5 ≈ 1 minute of
  usage per 60-second heartbeat and sells prepaid minute packs through Razorpay;
  none of that exists here, and no code from it was reused. See
  [`REPORT.md` §7](REPORT.md#7-billing--payment--full-evidence-trail-subscription-every-5-minutes)
  for the full evidence trail of that mechanic.
* **No telemetry, no auto-update, no remote kill-switch.**

## Repository layout

```
opengirgit/
├── README.md                  ← you are here
├── REPORT.md                  ← reverse-engineering report of the original app
├── LICENSE                    ← MIT
├── docs/
│   └── API.md                 ← HTTP/SSE API reference implemented by server/
├── server/                    ← FastAPI backend (auth, LLM proxy, STT tokens)
│   ├── app/
│   │   ├── main.py            ← routes
│   │   ├── config.py          ← pydantic-settings (env + .env)
│   │   ├── security.py        ← OTP hashing, JWT
│   │   ├── db.py              ← SQLite (users, OTPs, feedback)
│   │   ├── llm.py             ← OpenAI-compatible client (stream + complete)
│   │   ├── prompts.py         ← system prompt + context assembly
│   │   ├── resume.py          ← resume → structured JSON
│   │   └── stt.py             ← optional Deepgram temp-token minting
│   ├── run.py
│   ├── requirements.txt
│   └── .env.example
├── client/                    ← PySide6 desktop overlay
│   ├── opengirgit/
│   │   ├── app.py             ← bootstrap & wiring
│   │   ├── overlay.py         ← the overlay window
│   │   ├── dialogs.py         ← login / interview info / settings / history
│   │   ├── api.py             ← HTTP client (auth, SSE chat/vision, STT token)
│   │   ├── workers.py         ← QThread helpers
│   │   ├── audio.py           ← WASAPI loopback / mic capture
│   │   ├── dsp.py             ← downmix + linear resampler (pure numpy)
│   │   ├── stt.py             ← local faster-whisper & Deepgram engines
│   │   ├── capture.py         ← screen region selection
│   │   ├── stealth.py         ← WDA_EXCLUDEFROMCAPTURE / tool-window
│   │   ├── hotkeys.py         ← global hotkeys (Win32 RegisterHotKey)
│   │   ├── prompts.py         ← context formatting
│   │   ├── resume.py          ← PDF/DOCX/TXT text extraction
│   │   ├── stores.py          ← ~/.opengirgit JSON stores
│   │   └── config.py          ← settings dataclass
│   ├── main.py
│   ├── requirements.txt
│   └── .env.example
├── tests/                     ← offline unit tests (server units + client units)
│   └── e2e/                   ← mock OpenAI-compatible model + end-to-end script
└── .github/workflows/ci.yml   ← lint + tests + e2e
```

## Quick start

Requirements: Python **3.10+** (3.11–3.13 recommended). Windows is required for
*system-audio* capture and the stealth APIs; on Linux/macOS the app still runs
with microphone input (and without capture exclusion).

### 1. Server

```bash
cd server
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then edit .env
python run.py                      # http://127.0.0.1:8000
```

Minimum `.env` for a cloud model:

```ini
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-...
LLM_CHAT_MODEL=gpt-4o-mini
LLM_VISION_MODEL=gpt-4o-mini
```

or, fully local, with [Ollama](https://ollama.com):

```ini
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_API_KEY=ollama
LLM_CHAT_MODEL=llama3.1:8b
LLM_VISION_MODEL=llava:latest
```

Health check: `curl http://127.0.0.1:8000/api/health`

> **OTP dev mode.** Without SMTP configured the server returns the login code in
> the API response and prints it in the console (the client fills it in
> automatically). Set `SMTP_HOST` … to send real email, or set
> `ALLOW_DEV_OTP_ECHO=false` to disable the echo.

### 2. Client

```bash
cd client
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # optional; defaults work for a local server
python main.py
```

First launch: the login dialog asks for your **server URL**, **email** and the
**one-time code** (auto-filled in dev mode). After that the interview-info dialog
opens once per session to collect company/JD/resume.

**Windows system audio.** Play something, then click the 🎙 button and pick the
`… (loopback)` entry for your output device — that is the interviewer's voice.
Pick a plain input device to use your microphone instead.

**Local STT models.** The first transcription downloads the faster-whisper model
(`WHISPER_MODEL`, default `base.en`) from Hugging Face and caches it. `tiny.en`
is fastest, `small.en`/`medium.en` are more accurate.

## Configuration

### Server environment

All server settings are environment variables (or `server/.env`); see
`server/.env.example` for the annotated list.

| Variable | Default | Meaning |
|---|---|---|
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Bind address. Use `0.0.0.0` to serve other machines. |
| `DATA_DIR` | `data` | SQLite location. |
| `JWT_SECRET` | `dev-secret-change-me-use-32-bytes-minimum` | **Change this.** HMAC key for access tokens (≥32 chars). |
| `JWT_EXPIRE_MINUTES` | `10080` | Token lifetime (7 days). |
| `OTP_TTL_SECONDS` / `OTP_MAX_ATTEMPTS` / `OTP_RATE_LIMIT_SECONDS` | `300` / `5` / `30` | OTP policy. |
| `ALLOW_DEV_OTP_ECHO` | `true` | Return the OTP in the response **when no SMTP is configured**. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_STARTTLS` | – | Real email delivery. |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | Any OpenAI-compatible base URL. |
| `LLM_API_KEY` | – | Bearer key for the LLM endpoint. |
| `LLM_CHAT_MODEL` | `gpt-4o-mini` | Default chat model (the client may override). |
| `LLM_VISION_MODEL` | `gpt-4o-mini` | Default model for screenshots. |
| `LLM_TEMPERATURE` / `LLM_MAX_TOKENS` | `0.3` / `1024` | Generation defaults. |
| `LLM_TIMEOUT_SECONDS` | `120` | Read timeout for streaming requests. |
| `SYSTEM_PROMPT` | built-in | Override the persona/system prompt. |
| `DEEPGRAM_API_KEY` | – | If set, `/api/stt/token` mints short-lived Deepgram tokens. |
| `DEEPGRAM_MODEL` / `DEEPGRAM_LANGUAGE` | `nova-2` / `en` | Deepgram stream parameters. |
| `DEEPGRAM_TOKEN_TTL_SECONDS` | `600` | Minted token lifetime. |
| `APP_VERSION` | `0.1.0` | Reported by `/api/version`. |

### Client settings

Client settings live in `client/.env` (first run) and are then persisted to
`~/.opengirgit/config.json`, editable from the **⚙ settings** dialog:

| Key | Default | Meaning |
|---|---|---|
| `server_url` | `http://127.0.0.1:8000` | Your OpenGirGit server. |
| `stt_engine` | `local` | `local` (faster-whisper) or `deepgram`. |
| `whisper_model` | `base.en` | faster-whisper model name. |
| `whisper_compute_type` | `int8` | `int8`, `int8_float16`, `float16`, `float32`. |
| `language` | `en` | Transcription/speech language hint. |
| `silence_seconds` | `0.9` | Silence that ends an utterance (0.2–3.0). Lower = transcript appears sooner but questions may split. |
| `audio_source` | `system` | `system` (loopback) or `microphone`. |
| `audio_device` | *(auto)* | Device id from the dropdown; empty selects the default. |
| `auto_ask` | `true` | Submit a question automatically when a final transcript arrives. |
| `opacity` | `0.96` | Overlay opacity. |
| `screenshot_prompt` | built-in | Prompt used for screenshot analysis. |
| `hotkeys` | see below | Hotkey combos as `"Shift+Alt+K"` strings; shown read-only in the settings dialog — edit `~/.opengirgit/config.json` to change them. |

Files written by the client: `~/.opengirgit/{config,credentials,context,conversations,resume_cache}.json`.
`credentials.json` is plaintext and contains a bearer token — keep it out of
version control (the repository `.gitignore` already ignores it).

## Global hotkeys

Defaults (all remappable in `config.json` / the settings dialog; on Windows they
are true system-wide hotkeys registered with `RegisterHotKey`, elsewhere they are
application shortcuts):

| Action | Default | Notes |
|---|---|---|
| Collapse / expand answers | `Shift+Alt+H` | |
| Ask AI (submits the manual box) | `Shift+Alt+A` | OS key-repeat suppressed |
| Erase inputs | `Shift+Alt+D` | OS key-repeat suppressed |
| Screenshot region → analyse | `Shift+Alt+S` | opens a selection overlay |
| Previous / next answer | `Shift+Alt+[` / `Shift+Alt+]` | |
| Scroll answer up / down | `Shift+Alt+W` / `Shift+Alt+X` | hold to repeat |
| Move overlay up/down/left/right | `Shift+Alt+I` / `K` / `J` / `L` | hold to repeat |
| Opacity down / up | `Shift+Alt+-` / `Shift+Alt+=` | hold to repeat |

## Privacy and stealth notes

* **Where your data goes.** Audio → only to the STT engine you chose (local
  faster-whisper by default; Deepgram if enabled). Questions/screenshots →
  only to the LLM endpoint your server is configured with. No third party
  receives anything else.
* **Screen-share invisibility (Windows).** Every OpenGirGit window calls
  `SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)`, which excludes it
  from `BitBlt`-style capture used by Zoom/Teams/Meet, and sets
  `WS_EX_TOOLWINDOW` so it stays out of the taskbar and Alt-Tab. On Windows
  builds older than 19041 the flag degrades and the window appears as a black
  rectangle in shares — the same caveat the original has.
* **Ethics.** You are responsible for complying with the rules of whatever
  interview, exam or call you use this in. Many employers and testing platforms
  forbid assistive tooling; nothing in this repository is designed to defeat
  human-perceptible detection (the stealth flag is a documented OS window
  attribute, not a hook or a cheat), and no warranty of any kind is provided.

## Relationship to the original app

`REPORT.md` documents the reverse engineering of *GirGit AI* 1.2.45 (PyInstaller +
PySide6, Windows) from its shipped artifacts and public endpoints. Key findings
reproduced here as architecture (not as code): system-audio loopback → direct
Deepgram WS with server-minted tokens; SSE/WS LLM chat with server-side system
prompt; client-side context blob; capture-excluding overlay windows.

**Billing, per the report:** the only purchase mechanism in the original is
prepaid usage at **₹5 per minute** (`rate_per_minute_paise=500`), sold in minute
packs (min 15, max 1000) through Razorpay, with a **60-second heartbeat that
debits 1 minute** per beat and a 10-minute server-side free trial. There is no
recurring subscription and no 5-minute billing unit anywhere in the binaries —
"5 minutes" only ever matches the "₹5/min" rate. OpenGirGit removes this layer
entirely: your server bills nothing.

## Development

```bash
pip install pytest ruff
pip install -r server/requirements.txt    # needed by the server tests
pip install numpy PySide6                 # optional: dsp + offscreen UI tests
pytest                                    # 50 offline tests, no network needed
ruff check server client tests
```

Test layout:

| File | Covers |
|---|---|
| `tests/test_server_prompts.py` | system prompt, history filtering, vision payloads |
| `tests/test_server_security.py` | OTP hashing, JWT issue/verify/expiry/refresh leeway |
| `tests/test_server_resume.py` | JSON extraction + normalisation of parsed resumes |
| `tests/test_client_dsp.py` | down-mix, resampling (single-pass == chunked), levels |
| `tests/test_client_config.py` | settings defaults, clamping, context formatting |
| `tests/test_client_stores.py` | bounded history, atomic writes, credential fallback |
| `tests/test_client_hotkeys.py` | hotkey string parsing (skipped without PySide6) |
| `tests/test_client_api.py` | SSE assembly, error events, cancellation, URL handling |
| `tests/test_client_ui.py` | headless (offscreen) construction + stream + wiring + teardown |
| `tests/e2e/run_e2e.py` | boots the real server + mock model and drives the client HTTP layer |
| `tests/e2e/stt_smoke.py` | optional live STT check (file replay or live capture, needs faster-whisper) |

The UI tests run under `QT_QPA_PLATFORM=offscreen` and are automatically skipped
when PySide6 is not installed. On top of the unit tests there is an end-to-end
check that boots the mock OpenAI-compatible model plus the real server and drives
the real client HTTP layer (`python tests/e2e/run_e2e.py`) — CI runs it on every
push. Tests never touch the network, Qt or optional heavy dependencies except
where noted above; client DSP is exercised through `client/opengirgit/dsp.py`,
which is deliberately dependency-light (numpy only).

### Verifying speech-to-text on your machine

The unit tests never load a model. To exercise the real pipeline end-to-end
(down-mix → resample → voice-activity segmentation → faster-whisper):

```bash
pip install faster-whisper        # already in client/requirements.txt

# replay an audio file (16-bit PCM; any sample rate / channel count):
python tests/e2e/stt_smoke.py --wav speech.wav --model base.en --expect "hello"

# real-time replay + latency measurement with a specific silence gate:
python tests/e2e/stt_smoke.py --wav speech.wav --model tiny.en --realtime --silence 0.4

# live capture — on Windows this records speaker output via WASAPI loopback:
python tests/e2e/stt_smoke.py --capture 8 --source system

# live capture from a microphone on an explicit device:
python tests/e2e/stt_smoke.py --capture 8 --source microphone --device input:3
```

The first run downloads the model; the script exits 0 only when a transcript
(and the `--expect` substring, if given) came back.

### Latency notes

Measured on an ordinary CPU (no GPU), 16 kHz input replayed in real time, an
11-second utterance — the window from the speaker stopping to the transcript
landing in the box:

| Model | `silence_seconds=0.9` (default) | `silence_seconds=0.4` |
|---|---|---|
| `tiny.en` | ~1.25 s | ~0.8 s |
| `base.en` | ~1.55 s | ~1.1 s |

That window is the silence gate plus transcription (greedy decode, no VAD
lookahead). Beyond it, the app itself adds ~20 ms between submit and the first
streamed answer token — everything else is your LLM's own speed. With
`auto_ask=true` (default) the question is sent the moment the transcript
arrives; with `auto_ask=false` it waits in the box for Enter or the `ask`
hotkey. If you want words to appear *while* the speaker is still talking (what
the original did with Deepgram), set `stt_engine=deepgram` — that path streams
live partials (`set_partial`) and finalises almost instantly.

### Verification status

| Area | Verification |
|---|---|
| Server (auth, profiles, SSE chat/vision, resume, limits) | ✅ unit tests + live HTTP smoke + `run_e2e.py` |
| Client HTTP (auth, chat, vision, resume, error paths) | ✅ live against the real server and the mock model |
| DSP chain (down-mix → resample → PCM16) | ✅ unit tests + real audio replay |
| Local STT (faster-whisper) | ✅ real speech clip transcribed word-perfect via `stt_smoke.py`, both 16 kHz mono and 48 kHz stereo through the capture chain |
| GUI flows (offscreen Qt) | ✅ construction, streaming, hotkey wiring, teardown |
| WASAPI loopback capture (pyaudiowpatch, Windows-only) | ⏳ run `stt_smoke.py --capture 8 --source system` |
| Native hotkeys (`RegisterHotKey`, Windows-only) | ✅ all 14 defaults parse and register as Qt fallbacks on Linux; native path needs Windows |
| Stealth (`WDA_EXCLUDEFROMCAPTURE`, Windows-only) | ⏳ verify with a screen-share |
| Deepgram engine | ⏳ needs an API key (`stt_engine=deepgram`) |
| Real model provider | ✅ any OpenAI-compatible endpoint (mock used in CI; point `.env` at your provider) |
| Visual polish (fonts, sizes, DPI) | ⏳ designed for Windows at 100–150 % scaling; not pixel-verified |

## Roadmap

- [ ] macOS audio capture (`ScreenCaptureKit`/BlackHole docs) and Linux PipeWire loopback helper.
- [ ] Streaming partial transcripts from local whisper (chunked re-transcription).
- [ ] Optional WebSocket chat transport (the server already speaks SSE; WS is a drop-in).
- [ ] Session recording/export to Markdown.
- [ ] Translations (the strings are all in `client/opengirgit/`, no i18n layer yet).

## License

MIT — see [`LICENSE`](LICENSE). No vendor code, strings, assets or binaries from
the original application are included or redistributed. "GirGit AI" is only
referenced descriptively for interoperability research; this project is not
affiliated with or endorsed by its authors.
