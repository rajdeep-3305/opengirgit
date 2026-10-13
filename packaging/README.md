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

## Linux bundle

The same spec builds on Linux (`dist/OpenGirGit/OpenGirGit`, one folder; CI
attaches it as `OpenGirGit-linux-x64.tar.gz` on release tags). Unpack and run

```sh
./OpenGirGit/install-linux.sh          # registers the launcher entry + icon
```

The install script is what makes **global hotkeys work on Wayland**: the
GlobalShortcuts portal scopes bindings to an app id, which the desktop derives
from the systemd scope of a grid-launched app plus the installed `.desktop`
file. Launch OpenGirGit from the application grid afterwards; terminal launches
keep window-local shortcuts (the settings dialog shows which backend is
active). For a source checkout the same trick works when systemd is present:

```sh
systemd-run --user --scope -u app-org.opengirgit.OpenGirGit-$$ ./run.sh
```

## Notes and caveats

* **Size.** The folder is large (PySide6 + QtWebEngine + faster-whisper/ctranslate2
  + numpy): a few hundred MB on Windows, ~1.1 GB in our Linux verification build
  (`libQt6WebEngineCore.so` alone is ~190 MB). This is the price of offline STT
  and the offline math/diagram renderer. KaTeX + mermaid add only ~3 MB, the
  translation catalogs a few KB; the spec drops Chromium's locale paks except
  `en-US.pak` (~40 MB saved). Set `OPENGIRGIT_WEB_RENDER=false` to skip creating
  the embedded browser at run time (the files stay in the bundle either way).
* **Self-test.** `OpenGirGit.exe --check-render` (or
  `python -m opengirgit --check-render`) starts the bundled browser headlessly,
  renders a sample with KaTeX + mermaid and prints the result — the quickest
  way to confirm the math/diagram path works on a machine. Exit code 0 = OK.
  `--print-settings`, `--list-devices` and `--help` are forwarded to the client
  without starting the bundled server.
* **Language files.** `opengirgit/translations/*.json` ship in the bundle; add a
  catalog next to the executable if you prefer (the app reads its own package
  directory, so a rebuild is the supported route).
* **Console window.** The launcher is built with `console=True` so server logs
  and dev-mode OTP codes stay visible; set `SMTP_*` for real email and you can
  rebuild with `console=False` if you prefer a silent app.
* **First transcription** still downloads the whisper model from Hugging Face
  (cached in your user profile). Ship a pre-downloaded model or switch to
  Deepgram if the target machine is offline.
* **Windows semantics** (WASAPI loopback, `RegisterHotKey`, capture exclusion)
  can only be exercised on Windows; build and test the exe there. CI does this
  on every release tag (see `.github/workflows/release.yml`, which also has a
  manual *Run workflow* trigger), and the hands-on pass is scripted in
  [`docs/WINDOWS-CHECKLIST.md`](../docs/WINDOWS-CHECKLIST.md).
* **Linux bundle.** Built and smoke-tested on this machine (Ubuntu 24.04,
  Wayland): server healthy from the executable, `--check-render` OK, portal
  capture and X11 grabs work from the frozen build. CI builds it on
  ubuntu-22.04 for an older glibc baseline; the release workflow runs the same
  health smoke test. Hands-on pass:
  [`docs/LINUX-CHECKLIST.md`](../docs/LINUX-CHECKLIST.md).
