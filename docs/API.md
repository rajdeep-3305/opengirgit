# OpenGirGit server API

Base URL: `http://127.0.0.1:8000` (configurable). All request/response bodies are
JSON unless stated otherwise. Authenticated endpoints expect
`Authorization: Bearer <access_token>`.

The API shape intentionally mirrors the endpoints the original client consumed
(observed during a reverse-engineering study of the shipped app; notes kept
locally), minus everything billing/payment related.

---

## Health & version

### `GET /`

```json
{"message": "OpenGirGit API", "version": "0.1.0", "status": "running"}
```

### `GET /api/health`

```json
{"status": "ok", "llm_configured": true, "stt_provider": "local"}
```

### `GET /api/version`

No auth. Consumed by the client to display server version information.

```json
{
  "version": "0.1.0",
  "download_url": "",
  "release_notes": "",
  "mandatory": false,
  "windows": "",
  "mac": ""
}
```

---

## Authentication

Email + one-time-code. Without SMTP configured the server runs in **dev mode**:
the OTP is returned as `otp_code` (and printed to the console) so the client can
fill it in automatically. Set `ALLOW_DEV_OTP_ECHO=false` to disable.

### `POST /api/auth/otp/send`

```json
{"email": "you@example.com"}
```

Response `200`:

```json
{"success": true, "message": "OTP sent", "expires_in": 300, "otp_code": "123456"}
```

`otp_code` is present only in dev mode. Rate limited per email
(`OTP_RATE_LIMIT_SECONDS`, via `429` if exceeded).

### `POST /api/auth/otp/verify`

```json
{"email": "you@example.com", "otp": "123456"}
```

Response `200`:

```json
{"success": true, "access_token": "eyJ…", "token_type": "bearer", "email": "you@example.com"}
```

Errors: `400` malformed, `401` wrong/expired code, `429` too many attempts
(OTP is invalidated after `OTP_MAX_ATTEMPTS` failures).

### `POST /api/auth/refresh`

Auth: bearer token (even a recently expired one is accepted for refresh within a
grace period). Returns a new token.

```json
{"success": true, "access_token": "eyJ…"}
```

### `GET /api/auth/me`

Auth required. Returns the stored profile.

```json
{"success": true, "email": "you@example.com", "profile": {"name": "Ada", "phone": "+91…"}}
```

### `GET /api/auth/user-exists/{email}`

```json
{"exists": true}
```

### `GET /api/auth/profile/{email}`

Auth required; only your own email is readable.

```json
{"success": true, "profile": {...}, "updated_at": "2026-10-17T09:00:00Z"}
```

### `POST /api/auth/profile`

Auth required. Stores an arbitrary profile object (name, phone, …).

```json
{"profile": {"name": "Ada", "phone": "+91…"}}
```

Response: `{"success": true, "profile": {...}}`

---

## LLM proxy

### `POST /api/llm/chat/stream` — Server-Sent Events

Auth required.

```json
{
  "message": "Explain the difference between a process and a thread",
  "conversation_history": [
    {"role": "user", "content": "hi"},
    {"role": "assistant", "content": "Hello!"}
  ],
  "context": "=== CANDIDATE RESUME ===\n…",
  "model": "gpt-4o-mini"
}
```

`context` is injected into the system prompt (see `server/app/prompts.py`);
`model` optionally overrides the configured default. Response is
`text/event-stream`:

```
data: {"chunk": "A process"}
data: {"chunk": " has its own"}
data: {"chunk": " memory space…"}
data: {"done": true}
```

On failure mid-stream:

```
data: {"error": "upstream 429: rate limited"}
```

### `POST /api/llm/vision/stream` — Server-Sent Events

Auth required. Same streaming envelope as chat.

```json
{
  "prompt": "Solve the coding problem in this screenshot.",
  "images": ["<base64 JPEG, no data: prefix>"],
  "conversation_history": [],
  "context": "",
  "model": "gpt-4o-mini"
}
```

Up to 5 images per request (the `images` field, or `image` for a single image).

### `WS /api/llm/ws` — WebSocket transport (optional)

Same auth (`Authorization: Bearer …` on the handshake), same payloads and the
same event shapes as the SSE endpoints — the client picks it with
`chat_transport = "auto" | "websocket"` and falls back to SSE automatically when
the socket cannot be opened. One connection can carry any number of requests;
frames between the client and the server are JSON text messages.

Client → server (one per request):

```json
{"kind": "chat", "message": "…", "conversation_history": [], "context": "", "model": null}
{"kind": "vision", "prompt": "…", "images": ["<base64 JPEG>"], "conversation_history": [], "context": ""}
```

Server → client:

```json
{"chunk": "A process"}
{"chunk": " has its own"}
{"done": true}
{"error": "upstream 429: rate limited"}
{"error": "invalid request: Field required"}
```

* `kind` defaults to `chat`; `vision` validates against the vision schema
  (`images` ≤ 5) and answers `{"error": "no image supplied"}` without one.
* A missing/invalid token closes the socket with code **`4401`** (the WebSocket
  equivalent of HTTP 401).
* Closing the socket mid-stream cancels the upstream LLM request, exactly like
  dropping an SSE response.
* Requires a server started with WebSocket support — `uvicorn[standard]`
  (already in `server/requirements.txt`) provides it.

---

## Resume

### `POST /api/resume/parse`

Auth required. Sends extracted resume text to the configured LLM and returns
structured JSON:

```json
{
  "name": "Ada Lovelace",
  "email": "ada@example.com",
  "phone": "+44…",
  "location": "London",
  "summary": "…",
  "experience": [{"title": "…", "company": "…", "duration": "…", "description": "…"}],
  "education": [{"degree": "…", "institution": "…", "year": "…"}],
  "skills": ["python"],
  "certifications": [],
  "projects": [{"name": "…", "description": "…", "technologies": ["…"]}],
  "languages": ["English"]
}
```

Response: `{"success": true, "resume": {...}}`. The request body is
`{"resume_text": "…"}` (max ~200 000 characters).

---

## Speech-to-text token

### `POST /api/stt/token`

Auth required. Returns a short-lived Deepgram token plus a ready-to-use WebSocket
URL, so the client streams audio **directly to Deepgram** without the audio ever
transiting this server (same pattern as the original app).

```json
{
  "provider": "deepgram",
  "token": "…",
  "expires_in": 600,
  "deepgram_url": "wss://api.deepgram.com/v1/listen?model=nova-2&language=en&encoding=linear16&sample_rate=16000&channels=1&interim_results=true&smart_format=true"
}
```

If `DEEPGRAM_API_KEY` is not configured the endpoint returns `501` with:

```json
{"detail": "Deepgram is not configured on this server. Use the local (faster-whisper) STT engine."}
```

The client connects with `Authorization: Token <token>` and sends raw
`linear16` PCM (16 kHz, mono). During silence it sends
`{"type": "KeepAlive"}` every ~5 s.

---

## Feedback

### `POST /api/feedback/submit`

No auth.

```json
{"message": "great app", "email": "you@example.com", "app_version": "0.1.0"}
```

Response: `{"success": true}`. Stored in the `feedback` table.

---

## Errors

Uniform FastAPI error shape unless noted:

```json
{"detail": "human readable message"}
```

| Status | Meaning |
|---|---|
| `401` | Missing/expired/invalid bearer token, or bad OTP (auth family). |
| `403` | Authenticated but not allowed (e.g. reading someone else's profile). |
| `402` | Reserved — never returned by this server (the original used it for "insufficient minutes"). |
| `404` | Unknown route or resource. |
| `429` | Rate-limited (OTP send, OTP attempts). |
| `501` | Optional feature not configured (Deepgram). |
| `502` | Upstream LLM/Deepgram failure. |
