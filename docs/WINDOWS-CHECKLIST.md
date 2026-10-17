# Windows verification checklist

Everything in `README.md` → *Verification status* that is still marked **⏳** is
either Windows-only (WASAPI loopback, `RegisterHotKey`, `WDA_EXCLUDEFROMCAPTURE`,
the GDI decoy cursor, `run.ps1`, the packaged exe) or needs a screen share to
judge. This file is the script for that pass: work top to bottom, tick what
passes, and report what does not (see *Reporting* at the end).

CI already covers part of it: the **windows-tests** job in
`.github/workflows/ci.yml` installs `client/requirements.txt` on
`windows-latest` (a real test of the Windows install path) and runs the core
suite as a hard gate; the Qt/WebEngine GUI tests run there informationally.
This checklist is the manual, real-hardware counterpart.

## 0. Setup

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -U pip
.venv\Scripts\pip install -r client\requirements.txt -r server\requirements.txt
.venv\Scripts\pip install pytest ruff
```

* Model provider: copy `server\.env.example` to `server\.env` and point
  `LLM_BASE_URL` / `LLM_API_KEY` at Ollama or a cloud provider
  (`.env.example` documents both).
* Quick sanity that needs no display:

```powershell
.venv\Scripts\python -m compileall -q client\opengirgit
$env:QT_QPA_PLATFORM="offscreen"
.venv\Scripts\python -m pytest -q
.venv\Scripts\ruff check server client tests packaging tools
```

- [ ] Test suite green (the WebEngine tests may skip if Chromium cannot start).
- [ ] `ruff` clean.

## 1. Launcher (`run.ps1`)

```powershell
powershell -ExecutionPolicy Bypass -File run.ps1
```

- [ ] Virtualenv check passes, server starts, health probe succeeds, overlay appears.
- [ ] Closing the overlay shuts the server down (no orphan `python.exe`).
- [ ] `--print-settings`, `--list-devices` and `--check-render` do **not** start the server.

## 2. WASAPI loopback capture

```powershell
.venv\Scripts\python tests\e2e\stt_smoke.py --list-devices
# play a speech video, then:
.venv\Scripts\python tests\e2e\stt_smoke.py --capture 8 --source system
```

- [ ] `--list-devices` shows `loopback:<n>` entries for the output devices.
- [ ] The captured transcript matches the audio you played.
- [ ] The same with `--source microphone` and an explicit `--device input:n`.

## 3. Stealth (screen-share exclusion)

Share the **whole screen** in Teams / Zoom / Meet (not a single window).

- [ ] The overlay is visible to you but absent from the shared view.
- [ ] Have someone check the preview — or record with Xbox Game Bar and inspect the
      recording (the overlay must not be in it).
- [ ] While the overlay updates, focus stays in the meeting app (typing there keeps working).
- [ ] The overlay has no taskbar button and does not appear in Alt+Tab.

> Window-share mode (sharing one app window) is a different capture path; note
> whether the overlay leaks there — that is expected to vary by app.

## 4. Global hotkeys under a meeting app

With the meeting app focused (or a game), press each action:
mic toggle, screenshot, ask, erase, click-through, history, settings, prev/next
answer, scroll up/down, move up/down/left/right, opacity up/down.

- [ ] All actions fire while another app has focus.
- [ ] In Settings → Hotkeys, change one binding, save, and the new binding works immediately.
- [ ] An already-taken combo reports "hotkeys unavailable (already in use): …".

## 5. Region capture + decoy cursor

During a share, press the screenshot hotkey.

- [ ] Viewers of the share see a *decoy* cursor arrow (glides to the region), not your real cursor.
- [ ] Two captures queue as two removable thumbnails (cap 5); removing one works.
- [ ] The next typed/spoken/Ask question carries **all** attached images (the answer mentions both).

## 6. Math / mermaid inside the overlay

Ask something like *"Show the integral of x² as a formula and a mermaid flowchart of the steps."*

- [ ] KaTeX math and the mermaid diagram render inside the overlay.
- [ ] While the embedded browser is visible, the overlay stays **excluded from the share**
      (QtWebEngine creates child windows — this is the item most worth checking).
- [ ] `.venv\Scripts\python -m opengirgit --check-render` prints `render check: OK`.

## 7. Settings, language, scale, export

- [ ] Settings opens as tabs (Server / Speech / Behaviour / Hotkeys) and every tab fits 100–150 % scaling.
- [ ] Interface language → Deutsch applies immediately (labels, tooltips, statuses).
- [ ] Interface scale → 125 %, restart: the whole UI scales; thumbnails stay sharp on a HiDPI display.
- [ ] Answer transport → `websocket`: answers still stream (the server log shows no extra requests);
      stop the server and confirm the error surfaces instead of silently falling back.
- [ ] History → *Export session…* / *Export all…* write readable Markdown; *Copy* puts it on the clipboard.
- [ ] Answer view supports the scrollbar, code highlighting and copy.

## 8. The packaged exe

Either build locally:

```powershell
pip install pyinstaller
pyinstaller packaging\opengirgit.spec --noconfirm
```

or download the CI artifact (Actions → **release** → *Run workflow*, or a `v*` tag).

- [ ] `dist\OpenGirGit\OpenGirGit.exe` starts; the bundled server becomes healthy
      (`curl http://127.0.0.1:8000/api/health`).
- [ ] Put a `.env` next to the exe pointing at your model, then run the full flow:
      mic on → speak → answer; screenshot; export.
- [ ] `OpenGirGit.exe --check-render` prints `render check: OK`.
- [ ] `OpenGirGit.exe --print-settings` / `--list-devices` work.
- [ ] Unpacked folder is self-contained (no Python installed on the machine used to test).

## 9. Click-through, preview popup, pre-warm

- [ ] Press `Shift+Alt+C` (or the 🖱 button): the status bar shows *click-through on*;
      clicks over the overlay now reach the app underneath (type in Notepad through it).
- [ ] `Shift+Alt+C` again returns control; the mode is session-only (a restart starts
      with clicks on).
- [ ] Clear the `click_through` hotkey in Settings → Hotkeys: the toggle then refuses to
      enable — there would be no way back.
- [ ] Collapse the panel, ask a question: a preview popup floats above the bar with the
      incoming answer and fades out ~1.5 s after the stream ends.
- [ ] In a screen share, the popup is excluded from capture like the overlay itself.
- [ ] Collapse/expand slides and the overlay fades in at startup.
- [ ] Pre-warm: the server console shows the `/api/health` probe right after startup,
      before your first question.

## Reporting

For each failing item collect:

* what you did (the exact command or click path),
* what you expected vs. what happened,
* the console output (`run.ps1` window, or the exe's console),
* `%LOCALAPPDATA%\OpenGirGit\*.log` if present, and a screenshot.

Known non-issues (no report needed): SmartScreen warning for the unsigned exe,
the one-time whisper model download on first mic use, and a missing Deepgram key
(the local engine is the default, the Deepgram row in the README needs a key).
