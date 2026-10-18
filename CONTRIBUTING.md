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

You do not need a paid API key for development: run a local model behind an
OpenAI-compatible API (for example Ollama) and point the bundled server at it.
The "Quick start" section of the README walks through the zero-key setup.

## Before you open a pull request

```bash
pytest                                      # offline test suite, no network needed
ruff check server client tests packaging tools
python tools/collect_strings.py --check     # translation catalog is in sync
python tests/e2e/run_e2e.py                 # real server + mock LLM over SSE and WebSocket
```

CI runs the unit suite on Linux (Python 3.10 and 3.13) for the portable
modules, and on Windows (3.12) where the shipped client runs.
`tests/test_client_ui.py`, `tests/test_client_webview.py` and
`tests/test_client_hotkeys.py` need a full Qt/WebEngine stack and stay
informational on CI until they have been exercised on real hardware — see
[`docs/WINDOWS-CHECKLIST.md`](docs/WINDOWS-CHECKLIST.md).

## Translations

UI strings are English source strings; catalog files live in
`client/opengirgit/translations/`. When you add or change a user-visible
string, run:

```bash
python tools/collect_strings.py            # regenerates en.json
python tools/collect_strings.py --check    # what CI enforces
```

…and update `de.json` if you can. Details in
[`client/opengirgit/translations/README.md`](client/opengirgit/translations/README.md).

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
