# Configuration

These tables are the reference for self-hosters and anyone changing the
defaults; most client options are also editable in the app's settings dialog.
For the ordinary install path, start with [SETUP.md](SETUP.md).

## Server environment

All server settings are environment variables (or `server/.env`); see
`server/.env.example` for the annotated list.

| Variable | Default | Meaning |
|---|---|---|
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Bind address. Use `0.0.0.0` to serve other machines. |
| `DATA_DIR` | `data` | SQLite location. |
| `JWT_SECRET` | `dev-secret-change-me-use-32-bytes-minimum` | **Change this.** HMAC key for access tokens (≥32 chars); a non-loopback bind refuses to start with the default. |
| `JWT_EXPIRE_MINUTES` | `10080` | Token lifetime (7 days). |
| `OTP_TTL_SECONDS` / `OTP_MAX_ATTEMPTS` / `OTP_RATE_LIMIT_SECONDS` | `300` / `5` / `30` | OTP policy. |
| `ALLOW_DEV_OTP_ECHO` | `true` | Return the OTP in the response **when no SMTP is configured**; a non-loopback bind refuses to start with this on. |
| `CORS_ORIGINS` | empty | Comma-separated browser origins; empty = CORS **off** (the desktop client needs none). |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_STARTTLS` | – | Real email delivery. |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | Any OpenAI-compatible base URL. |
| `LLM_API_KEY` | – | Bearer key for the LLM endpoint. |
| `LLM_CHAT_MODEL` | `gpt-4o-mini` | Default chat model (the client may override). |
| `LLM_VISION_MODEL` | `gpt-4o-mini` | Default model for screenshots. |
| `LLM_TEMPERATURE` / `LLM_MAX_TOKENS` | `0.3` / `1024` | Generation defaults. |
| `LLM_TIMEOUT_SECONDS` | `120` | Read timeout for streaming requests. |
| `SYSTEM_PROMPT` | built-in | Override the persona/system prompt. |
| `DEEPGRAM_API_KEY` | – | If set, `/api/stt/token` mints short-lived Deepgram tokens. |
| `DEEPGRAM_MODEL` | `nova-2` | Deepgram model; transcription is fixed to English. |
| `DEEPGRAM_TOKEN_TTL_SECONDS` | `600` | Minted token lifetime. |
| `APP_VERSION` | `0.2.1` | Reported by `/api/version`. |

## Client settings

Client settings live in `client/.env` (first run) and are then persisted to
`~/.opengirgit/config.json`, editable from the **⚙ settings** dialog. The
interface and transcription are English-only; there is no language picker.

| Key | Default | Meaning |
|---|---|---|
| `server_url` | `http://127.0.0.1:8000` | Your OpenGirGit server. |
| `stt_engine` | `local` | `local` (faster-whisper) or `deepgram`. |
| `whisper_model` | `base.en` | faster-whisper model name. |
| `whisper_compute_type` | `int8` | `int8`, `int8_float16`, `float16`, `float32`. |
| `silence_seconds` | `0.9` | Silence that ends an utterance (0.2–3.0). Lower = transcript appears sooner but questions may split. |
| `audio_source` | `system` | `system` (loopback) or `microphone`. |
| `audio_device` | *(auto)* | Device id from the dropdown; empty selects the default. |
| `auto_ask` | `true` | Submit a question automatically when a final transcript arrives. |
| `partials` | `true` | Live partial transcripts while the local engine is transcribing. |
| `decoy_cursor` | `true` | Hide the real cursor during region selection (see stealth notes). |
| `web_render` | `true` | Render LaTeX math and mermaid diagrams in the embedded QtWebEngine view (falls back to plain text when unavailable; set `false` to save memory). |
| `opacity` | `0.96` | Overlay opacity. |
| `screenshot_prompt` | built-in | Prompt used when you attach screenshot(s) with no typed question. |
| `chat_transport` | `auto` | `auto` (WebSocket, falls back to SSE) · `sse` · `websocket`. |
| `ui_scale` | `0` | Interface scale in percent (`0` follows the system/session DPI; 100–200 preset). Applied at startup — takes effect after a restart. |
| `hotkeys` | see [the hotkey table](../README.md#global-hotkeys) | Hotkey combos as `"Shift+Alt+K"` strings; editable in the settings dialog (an empty value disables a hotkey). |

Files written by the client: `~/.opengirgit/{config,credentials,context,conversations,resume_cache}.json`.
`credentials.json` contains a bearer token: the client prefers the **OS keyring**
(Windows Credential Manager) and only falls back to the plaintext file, which is
written **owner-only** (`0600`) like the other store files. Keep it out of version control (the repository
`.gitignore` already ignores it).
