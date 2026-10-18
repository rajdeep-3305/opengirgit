# Contributing

Thanks for taking the time to contribute. A few ground rules first:

- OpenGirGit is a **clean-room** project. Do not contribute code, strings,
  assets or binaries that originate from the original closed-source
  application, from decompiled builds of it, or from any other project whose
  license is incompatible with MIT.
- By opening a pull request you agree that your contribution is released
  under the project's [MIT license](LICENSE).

## Development setup

Python 3.10 or newer is required.

```bash
git clone https://github.com/rajdeep-3305/opengirgit
cd opengirgit
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r server/requirements.txt -r client/requirements.txt
pip install pytest ruff
```

You do not need a paid API key for development. Run a local model behind an
OpenAI-compatible API (for example Ollama), copy `server/.env.example` to
`server/.env`, and set:

```ini
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_API_KEY=ollama
LLM_CHAT_MODEL=llama3.1:8b
LLM_VISION_MODEL=llava:latest
```

The [simple setup guide](docs/SETUP.md) walks through the same zero-key flow for
the installed app, and [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) lists
every server and client setting.

## Before you open a pull request

```bash
pytest                                      # offline test suite, no network needed
ruff check server client tests packaging
python tests/e2e/run_e2e.py                 # real server + mock LLM over SSE and WebSocket
```

The full test map, latency numbers and current verification status live in
[`docs/VERIFICATION.md`](docs/VERIFICATION.md).

CI runs the unit suite on Linux (Python 3.10 and 3.13) for the portable
modules, and on Windows (3.12) where the shipped client runs.
`tests/test_client_ui.py`, `tests/test_client_webview.py` and
`tests/test_client_hotkeys.py` need a full Qt/WebEngine stack and stay
informational on CI until they have been exercised on real hardware — see
[`docs/WINDOWS-CHECKLIST.md`](docs/WINDOWS-CHECKLIST.md).

## Bundling (optional)

The release workflow builds one-folder bundles with PyInstaller; you can
reproduce them locally:

```bash
pip install pyinstaller
pyinstaller packaging/opengirgit.spec --noconfirm --distpath dist --workpath build
```

## Style

- Conventional-commit subjects: `feat(scope): …`, `fix(scope): …`,
  `docs: …`, `test(scope): …`, `ci: …`.
- Keep pull requests focused, and update the docs and tests your change
  affects.
- Bug reports are most useful when they include the Windows version, the exact
  command used, and what happened instead of what you expected.
