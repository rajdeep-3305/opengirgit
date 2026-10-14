# Linux verification checklist

Everything in `README.md` → *Verification status* that is still marked **⏳** on
Linux, plus the platform-specific paths that only exist here: Wayland portal
screenshots, `GlobalShortcuts` portal hotkeys, X11 `XGrabKey` hotkeys, the
`parec` loopback and the Linux bundle. This file is the script for that pass:
work top to bottom, tick what passes, and report what does not (see
*Reporting* at the end).

CI builds the Linux bundle on `ubuntu-22.04` and smoke-tests the bundled server;
this checklist is the manual, real-hardware counterpart. Nothing here needs a
new runtime dependency — the portal and X11 paths go through PySide6's QtDBus
and `libX11` via `ctypes`.

## 0. Setup

```bash
./run.sh --check                     # venv + deps + prerequisites
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
.venv/bin/ruff check server client tests packaging tools
```

* Model provider: copy `server/.env.example` to `server/.env` and point
  `LLM_BASE_URL` / `LLM_API_KEY` at Ollama or a cloud provider.
* Note your session type — most checks below depend on it:

```bash
echo "$XDG_SESSION_TYPE" "$XDG_CURRENT_DESKTOP" "$(loginctl show-session "$XDG_SESSION_ID" -p Type --value 2>/dev/null)"
```

- [ ] Test suite green (WebEngine tests may skip if Chromium cannot start).
- [ ] `ruff` clean.

## 1. Launcher (`run.sh`)

```bash
./run.sh
```

- [ ] Virtualenv check passes, server starts, health probe succeeds, overlay appears.
- [ ] Closing the overlay shuts the server down (no orphan `python` process).
- [ ] `--print-settings`, `--list-devices` and `--check-render` do **not** start
      the server; `--check-render` prints `render check: OK`.

## 2. Wayland screenshots (`org.freedesktop.portal.Screenshot`)

Session must be Wayland (`XDG_SESSION_TYPE=wayland`). Preconditions:

```bash
busctl --user list | grep -E 'xdg-desktop-portal(\.[A-Za-z]+)?\.service'
gdbus call --session --dest org.freedesktop.portal.Desktop \
  --object-path /org/freedesktop/portal/desktop \
  --method org.freedesktop.DBus.Properties.Get \
  org.freedesktop.portal.Screenshot version
```

- [ ] The portal services are listed and `Screenshot` reports a version.
- [ ] Press the screenshot hotkey: the overlay opens showing a **frozen** image
      of the desktop; dragging a region gives a thumbnail that matches what you
      selected (no dimming baked into it).
- [ ] The portal's temporary file (`~/Pictures/Screenshot*.png`, top level) is
      gone after each capture; your own shots in `~/Pictures/Screenshots/` are
      untouched.
- [ ] Two captures queue as two removable thumbnails (cap 5).
- [ ] The next question carries all attached images (the answer mentions both).
- [ ] Negative test: `mask` the portal in a scratch session (or run with a
      stopped `xdg-desktop-portal`) — the status bar shows
      *could not capture the screen* instead of a blank thumbnail.

> Multi-monitor: the selector opens on the screen under the pointer, and the
> frozen image is cut from the full-desktop capture using the pixmap's size vs.
> the virtual desktop. Mixed-DPR multi-monitor setups are the interesting case —
> check the crop with the pointer on each screen.

## 3. Wayland global hotkeys (`org.freedesktop.portal.GlobalShortcuts`)

The portal scopes bindings to an **app id**, which the desktop derives from the
systemd scope of a grid-launched app plus an installed `.desktop` file. Register
the launcher entry first:

```bash
# from a source checkout, launch via the entry too:
packaging/install-linux.sh "$PWD/run.sh"
# from the bundle:
./dist/OpenGirGit/install-linux.sh
```

Then log out/in (or just use the application grid) and start OpenGirGit **from
the application grid**.

- [ ] First launch: the desktop shows its shortcut confirmation dialog with the
      preferred triggers (`ALT+SHIFT+a`, …).
- [ ] Accept it; with a browser focused, every action fires (mic, screenshot,
      ask, erase, history, settings, prev/next, scroll, move, opacity).
- [ ] Settings → Hotkeys reports *system-wide (desktop portal)*.
- [ ] Re-assign a binding in the desktop's own keyboard settings; the app still
      reacts to the desktop's binding (the app's preferred trigger is a hint).
- [ ] Launch from a terminal instead: no dialog, Settings → Hotkeys reports
      *only while this window has focus*, and shortcuts work while the overlay
      has focus. The console prints one line naming the reason.
- [ ] Cancel the desktop dialog once (negative test): Settings shows the
      desktop's refusal message and shortcuts stay window-local.

## 4. X11 session (`XGrabKey` via `libX11`)

Log into an Xorg/X11 session (or `QT_QPA_PLATFORM=xcb` inside a Wayland session
for a partial check, where grabs only see XWayland clients).

- [ ] Screenshots work natively (no portal involved); the frozen image has no
      dimming baked in.
- [ ] Settings → Hotkeys reports *system-wide (X11)*.
- [ ] Hotkeys fire while another app has focus; Caps Lock and Num Lock active
      while pressing still trigger them (the lock-modifier variants).
- [ ] Hold-to-repeat actions (opacity) repeat smoothly — XKB auto-repeat is on.
- [ ] Take a combo first in your WM/desktop (e.g. bind `Shift+Alt+A` in GNOME
      Settings → Keyboard), then start the app: the status bar lists the action
      as *hotkeys unavailable (already in use)* and the **other** hotkeys still
      work.
- [ ] Change a binding in Settings → Hotkeys: it takes effect immediately.

## 5. System audio (`parec` monitor source)

```bash
.venv/bin/python tests/e2e/stt_smoke.py --list-devices
# play a speech video, then:
.venv/bin/python tests/e2e/stt_smoke.py --capture 8 --source system
.venv/bin/python tests/e2e/stt_smoke.py --capture 5 --source microphone
```

- [ ] `--list-devices` lists `monitor` sources for the speakers.
- [ ] The system transcript matches the audio you played.
- [ ] Microphone capture works with an explicit `--device input:n`.

## 6. The Linux bundle

Either build locally:

```bash
pip install pyinstaller
pyinstaller packaging/opengirgit.spec --noconfirm --distpath dist --workpath build
```

or download the CI artifact (Actions → **release** → *Run workflow*, or a `v*` tag).

- [ ] `dist/OpenGirGit/OpenGirGit` starts; the bundled server becomes healthy
      (`curl http://127.0.0.1:8000/api/health`).
- [ ] `install-linux.sh` (inside the folder) registers the entry; launching from
      the grid still shows the desktop's shortcut dialog.
- [ ] Screenshots from the packaged app go through the portal and the frozen
      selector shows the right pixels.
- [ ] `--check-render` prints `render check: OK`; `--print-settings` and
      `--list-devices` work.
- [ ] The folder is self-contained (no Python installed on the machine used to
      test — a VM or a second user account works).
- [ ] `install-linux.sh --uninstall` removes the entry and icon again.

## Reporting

For each failing item collect:

* what you did (the exact command or click path),
* what you expected vs. what happened,
* the terminal output (the app prints portal/hotkey backend lines at startup),
* a screenshot, and `$XDG_SESSION_TYPE`, `XDG_CURRENT_DESKTOP` and the desktop
  version (`gnome-shell --version`, `plasmashell --version`, …).

Known non-issues (no report needed):

* The overlay **is** visible in screen shares on Linux — capture exclusion has
  no Linux API; only the decoy cursor applies (documented in the README).
* Global hotkeys stay window-local in terminal launches on Wayland; that is the
  portal's app-id rule, not a bug.
* The first transcription downloads the whisper model from Hugging Face.
* The desktop may show the shortcut dialog again after the app's triggers
  change (new defaults in an update).
