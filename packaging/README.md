# Packaging (single-folder desktop build)

`opengirgit.spec` bundles the **client overlay and the API server into one
folder** (`OpenGirGit/`, launched via `OpenGirGit.exe`).

```bash
pip install -r client/requirements.txt -r server/requirements.txt pyinstaller
pyinstaller packaging/opengirgit.spec --noconfirm --distpath dist --workpath build
```

The launcher (`launcher.py`) starts the bundled FastAPI server in a background
thread (skipped if something already answers `/api/health`) and then runs the
normal client bootstrap.

## Runtime configuration

Everything is configured the way the source distribution is: environment
variables or a **`.env` file next to the executable** —

```ini
# packed build: point the server at your model
LLM_BASE_URL=http://127.0.0.1:11434/v1     # Ollama example
LLM_API_KEY=ollama
LLM_CHAT_MODEL=llama3.1:8b
LLM_VISION_MODEL=llava:latest
```

Useful defaults set by the launcher:

| Variable | Default when unset |
|---|---|
| `DATA_DIR` | `%LOCALAPPDATA%\OpenGirGit\data` (Windows), `~/.local/share/opengirgit/data` elsewhere |
| `HOST` / `PORT` | `127.0.0.1` / `8000` |
| `OPENGIRGIT_SERVER_URL` | `http://HOST:PORT` |

## Notes and caveats

* **Size.** The folder is large (PySide6 + faster-whisper/ctranslate2 + numpy);
  expect several hundred MB. This is the price of offline STT in one bundle.
* **Console window.** The launcher is built with `console=True` so server logs
  and dev-mode OTP codes stay visible; set `SMTP_*` for real email and you can
  rebuild with `console=False` if you prefer a silent app.
* **First transcription** still downloads the whisper model from Hugging Face
  (cached in your user profile). Ship a pre-downloaded model or switch to
  Deepgram if the target machine is offline.
* **Windows semantics** (WASAPI loopback, `RegisterHotKey`, capture exclusion)
  can only be exercised on Windows; build and test the exe there. CI does this
  on every release tag (see `.github/workflows/release.yml`).
