# Verification

> **Archived 2026-10-19.** This verification record is retained as-is for
> historical reference. The project is no longer maintained and the remaining
> Windows 11 hands-on checks were not completed. See
> [ARCHIVE.md](../ARCHIVE.md).

This page keeps the detailed test map, on-machine checks, latency numbers and
the current verification status. Windows 11-specific hands-on checks are tracked
in [WINDOWS-CHECKLIST.md](WINDOWS-CHECKLIST.md).

## Development checks

```bash
pip install pytest ruff
pip install -r server/requirements.txt    # needed by the server tests
pip install numpy PySide6                 # optional: dsp + offscreen UI tests
pytest                                    # 158 offline tests, no network needed
ruff check server client tests packaging
```

## Test layout

| File | Covers |
|---|---|
| `tests/test_server_prompts.py` | system prompt, history filtering, vision payloads |
| `tests/test_server_security.py` | OTP hashing, JWT issue/verify/expiry/refresh leeway |
| `tests/test_server_resume.py` | JSON extraction + normalisation of parsed resumes |
| `tests/test_server_ws.py` | the `/api/llm/ws` WebSocket endpoint: auth, chat/vision frames, validation, error frames |
| `tests/test_client_dsp.py` | down-mix, resampling (single-pass == chunked), levels |
| `tests/test_client_config.py` | settings defaults, clamping, env overrides, context formatting |
| `tests/test_client_stores.py` | bounded history, atomic writes, credential fallback, Markdown export |
| `tests/test_client_audio.py` | device hints for missing loopback/microphone inputs |
| `tests/test_client_hotkeys.py` | hotkey parsing + editor validation (skipped without PySide6) |
| `tests/test_client_api.py` | SSE assembly, WebSocket transport (auto/forced, cancel, fallback), retry policy, URLs |
| `tests/test_client_render.py` | markdown→HTML shape (`language-*` code blocks), tables, math/mermaid source, fallback |
| `tests/test_client_webview.py` | KaTeX + mermaid + highlight.js rendering in the embedded QtWebEngine (offscreen; skipped without WebEngine) |
| `tests/test_client_ui.py` | headless (offscreen) construction, streaming, capture queue, web-view swap, thumbnails, decoy cursor, dialogs, export |
| `tests/e2e/run_e2e.py` | boots the real server + mock model and drives the client HTTP layer (SSE + WebSocket) |
| `tests/e2e/stt_smoke.py` | optional live STT check (file replay or live capture, needs faster-whisper) |

The UI tests run under `QT_QPA_PLATFORM=offscreen` and are automatically skipped
when PySide6 is not installed. On top of the unit tests there is an end-to-end
check that boots the mock OpenAI-compatible model plus the real server and drives
the real client HTTP layer (`python tests/e2e/run_e2e.py`) — CI runs it on every
push. Tests never touch the network, Qt or optional heavy dependencies except
where noted above; client DSP is exercised through `client/opengirgit/dsp.py`,
which is deliberately dependency-light (numpy only).

## Verifying speech-to-text on your machine

The unit tests never load a model. To exercise the real pipeline end-to-end
(down-mix → resample → voice-activity segmentation → faster-whisper):

```bash
pip install faster-whisper        # already in client/requirements.txt

# replay an audio file (16-bit PCM; any sample rate / channel count):
python tests/e2e/stt_smoke.py --wav speech.wav --model base.en --expect "hello"

# real-time replay + latency measurement with a specific silence gate:
python tests/e2e/stt_smoke.py --wav speech.wav --model tiny.en --realtime --silence 0.4

# live capture — system audio loopback (WASAPI):
python tests/e2e/stt_smoke.py --capture 8 --source system

# live capture from a microphone on an explicit device:
python tests/e2e/stt_smoke.py --capture 8 --source microphone --device input:3
```

On the default `system` source the script picks the default WASAPI loopback
device itself.

The first run downloads the model; the script exits 0 only when a transcript
(and the `--expect` substring, if given) came back.

## Verifying math/diagram rendering on your machine

```bash
# source tree
python -m opengirgit --check-render

# packaged build (no display needed; runs headless)
dist/OpenGirGit/OpenGirGit.exe --check-render
```

This starts the embedded browser headlessly, renders a sample answer with KaTeX
+ mermaid and prints `KaTeX nodes: 2  mermaid SVGs: 1`; exit code 0 means both
rendered. If it reports `assets are missing`, reinstall/rebuild the client — the
vendored JS lives in `client/opengirgit/assets/` (`web_render=false` disables
the web view entirely, which is also a valid way to run on weak machines).

## Latency notes

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
hotkey. With the default local engine the box also fills **while the speaker is
still talking** (re-transcription every ~1.2 s, automatically throttled on slow
machines; disable with `partials=false`). Deepgram remains the word-level
lowest-latency option.

## Verification status

Windows-specific paths are tracked in
**[`WINDOWS-CHECKLIST.md`](WINDOWS-CHECKLIST.md)** (launcher, WASAPI
loopback, stealth, decoy cursor, hotkeys under a meeting app, the packaged exe).
The CI **windows-tests** job installs the client requirements on
`windows-latest` and runs the core suite as a first line of defence.

| Area | Verification |
|---|---|
| Server (auth, profiles, SSE chat/vision, resume, limits) | ✅ unit tests + live HTTP smoke + `run_e2e.py` |
| Client HTTP (auth, chat, vision, resume, error paths, retries) | ✅ live against the real server and the mock model; retry semantics unit-tested |
| DSP chain (down-mix → resample → PCM16) | ✅ unit tests + real audio replay |
| Local STT (faster-whisper) | ✅ real speech clip transcribed word-perfect via `stt_smoke.py`, both 16 kHz mono and 48 kHz stereo through the capture chain |
| Live partials (local engine) | ✅ real speech clip, real-time replay: 9 partial updates during an 11 s utterance |
| Answer rendering (highlight.js code, tables, fallback) | ✅ unit tests + offscreen render |
| Math (KaTeX) + mermaid rendering | ✅ offscreen WebEngine test: formulas become KaTeX nodes, the diagram renders as an SVG, code blocks round-trip untouched; ⏳ appearance inside the capture-excluded overlay on Windows |
| Math/diagram self-test (`--check-render`) | ✅ from source and inside a PyInstaller one-folder build; the release workflow runs it on the Windows exe (non-fatal step) |
| Screenshot thumbnails | ✅ offscreen UI tests |
| Multi-region screenshots | ✅ queue/cap/remove/attach tests + `run_e2e.py` sends two images in one vision request; ⏳ Windows capture flow |
| Decoy cursor (region selection) | ✅ blank/dummy/glide logic + pixmap fallback offscreen; ⏳ GDI bitmap and share appearance on Windows |
| Hotkey editor | ✅ validation + save flow offscreen; registration path unchanged |
| Click-through toggle | ✅ state machine + portable `WindowTransparentForInput` fallback (offscreen), refusal without a hotkey; ⏳ real click pass-through on Windows |
| Streaming preview popup | ✅ show/update/linger/hide while collapsed, teaser cleaning (offscreen); ⏳ on-screen placement |
| Startup pre-warm | ✅ health probe + WebSocket handshake with stubbed transports, failures swallowed; ⏳ latency delta against a live provider |
| UI animations (collapse, preview, startup fade) | ✅ end-state tests offscreen; ⏳ visual smoothness on Windows |
| Feedback dialog | ✅ payload test + offscreen send flow |
| WebSocket transport | ✅ in-process server tests (auth, chat/vision frames, validation, error frames) + `run_e2e.py` streams chat/vision over WS and cancels mid-stream + verified against the **frozen bundle** (chat over ws/sse/auto, vision over ws, unauthenticated socket rejected); ⏳ reverse-proxied `wss://` deployments |
| Session export to Markdown | ✅ store + dialog tests (file written, clipboard, empty case); sessions are auto-named after their first question (truncation, empty and explicit-title cases tested) |
| Code-language rewrites (per-answer variants) | ✅ rewrite/cache/restore/instruction/failure paths offscreen + variant persistence in the store; ⏳ visual check against a live provider |
| Context file attachments | ✅ document extraction (no model call), image JPEG re-encode, stubbed vision transcription and save flow offscreen; ⏳ a real model transcribing a photographed page |
| Server security policy | ✅ HMAC-hashed OTPs (`compare_digest`), per-email send cooldown, attempt cap, JWT claim validation; non-loopback binds refuse to start with the default secret or the dev OTP echo; CORS off unless configured; client stores written owner-only; unit-tested |
| Interface scale / hi-DPI | ✅ setting plumb-through + DPR-aware thumbnails; ⏳ visual review at 125–200 % |
| Pixel polish (states, scrollbars, tabs) | ✅ hover/focus/checked styles, themed scrollbars and tooltips, tabbed settings — offscreen construction tests; ⏳ visual pass on Windows at 100–150 % |
| One-command launcher | ⏳ `run.ps1` on Windows: venv check, server start, health wait, clean shutdown |
| Packaged bundle (PyInstaller + CI) | ✅ the PyInstaller spec, vendored assets and the `--check-render` self-test were exercised in a one-folder build; the release workflow builds the Windows bundle and installer on release tags; ⏳ hands-on Windows pass with the CI-built zip |
| Windows installer (Inno Setup, per-user) | ✅ CI compiles and attaches `…-setup.exe` on release tags; per-user layout, shortcuts, uninstaller and license page are declarative; ⏳ install → launch → upgrade → uninstall on real Windows |
| TLS trust-store fallback + classified connection errors | ✅ unit tests: a certificate error is retried once against the OS-store ∪ certifi bundle on all three transports, then reported as a TLS diagnostic; DNS/refused/handshake failures get distinct messages; ⏳ a real corporate-proxy/antivirus environment |
| GUI flows (offscreen Qt) | ✅ construction, streaming, hotkey wiring, teardown |
| Dialog chrome | ✅ frameless dark cards, draggable headers, dark history rendering and capture-exclusion hooks are unit-tested offscreen; ⏳ appearance and screen-share exclusion on Windows |
| WASAPI loopback capture (pyaudiowpatch, Windows-only) | ⏳ run `stt_smoke.py --capture 8 --source system` |
| Native hotkeys (`RegisterHotKey`) | ✅ all 15 defaults parse and validate; ⏳ native registration on Windows |
| Stealth (`WDA_EXCLUDEFROMCAPTURE`, Windows-only) | ⏳ verify with a screen-share |
| Deepgram engine | ⏳ needs an API key (`stt_engine=deepgram`) |
| Real model provider | ✅ any OpenAI-compatible endpoint (mock used in CI; point `.env` at your provider) |
