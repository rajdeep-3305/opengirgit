# OpenGirGit — simple install guide (Windows & Linux)

No coding knowledge needed: you install the app like any other program, then
point it at an AI model once. Total setup time: about 15 minutes, most of it
downloads.

**The whole thing in three steps:**

1. **Install OpenGirGit** (~5 min)
2. **Give it a model to think with** — the free, private way is [Ollama](https://ollama.com), which runs on your own computer (~10 min, mostly waiting)
3. Done — after that, starting the app is one click

---

## 1. Download the right file

Open the **[latest release page](https://github.com/rajdeep-3305/opengirgit/releases/latest)** and pick:

| Your computer | Download this | What it is |
|---|---|---|
| Windows 10/11 (64-bit) | `OpenGirGit-windows-x64-setup.exe` | installs like a normal program |
| Windows, if you can't run installers | `OpenGirGit-windows-x64.zip` | unpack anywhere, run `OpenGirGit.exe` inside |
| Linux, 64-bit (Ubuntu 22.04+, Fedora 36+, …) | `OpenGirGit-linux-x64.tar.gz` | unpack, then register the app icon (below) |

Almost every PC made after 2010 is 64-bit. (macOS isn't supported — Windows
and Linux only.)

## 2. Install

### Windows

1. Run the file you downloaded.
2. Windows will probably show a blue box: **“Windows protected your PC”**.
   That's normal for free, unsigned open-source apps. Click **More info**, then
   **Run anyway**. It asks only once.
3. **Next → Next → Install.** No administrator password needed — it installs
   per-user. Tick “Create a desktop icon” if you want one.
4. Start **OpenGirGit** from the Start menu. Two windows appear — keep both:
   * the **floating bar** (usually top-right): this is the app, it stays on top;
   * a **black text window**: the app's engine and log. Closing it quits the app.
5. **Sign in**: type any email address (it's just your local account name —
   no mail is sent), click **Send code** — the code fills in by itself — then
   **Sign in**.

### Linux

1. Unpack the downloaded `.tar.gz` into your home folder (right-click →
   *Extract Here*, or `tar -xzf OpenGirGit-linux-x64.tar.gz`). You get an
   `OpenGirGit` folder.
2. Open a terminal and run this once. It adds OpenGirGit to your application
   menu and lets the desktop grant it global shortcuts:

   ```sh
   ~/OpenGirGit/install-linux.sh
   ```

3. Open **OpenGirGit** from your application grid (press Super, type
   “OpenGirGit”).
4. Sign in exactly like on Windows: email → **Send code** → **Sign in**.

   *Want to watch the log while it runs?* Start it from a terminal instead:
   `~/OpenGirGit/OpenGirGit` (the bar behaves the same; global hotkeys need the
   application-menu launch).

## 3. Give it a model to think with

The app is the radio; the model is the station. Pick **one** option.

### Option A — free & private, runs on your own computer *(recommended)*

**a) Install Ollama**
* Windows: download and run `OllamaSetup.exe` from <https://ollama.com/download>.
  It stays quietly in the background.
* Linux: in a terminal run `curl -fsSL https://ollama.com/install.sh | sh`.

**b) Download the model** — this is the one big download (a few GB, once).
Open **PowerShell** (Windows: press Start, type “PowerShell”, Enter) or your
terminal and run:

```sh
ollama pull llama3.1:8b
```

*On a lighter laptop, `ollama pull llama3.2:3b` is a slimmer alternative — if
you use it, write that name instead of `llama3.1:8b` in the next step too.*

**c) Tell OpenGirGit to use it.** Copy the whole block for your system into the
same PowerShell/terminal window and press Enter:

Windows (PowerShell):

```powershell
@"
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_API_KEY=ollama
LLM_CHAT_MODEL=llama3.1:8b
LLM_VISION_MODEL=llava
"@ | Set-Content "$env:LOCALAPPDATA\Programs\OpenGirGit\.env"
```

*(If you installed to a different folder, save a file named `.env` — this exact
content — next to `OpenGirGit.exe` instead.)*

Linux:

```sh
cat > ~/OpenGirGit/.env <<'EOF'
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_API_KEY=ollama
LLM_CHAT_MODEL=llama3.1:8b
LLM_VISION_MODEL=llava
EOF
```

*(If you unpacked the `OpenGirGit` folder somewhere else, create the `.env`
file inside that folder instead.)*

**d) Screenshot answers (optional).** Pictures go to a “vision” model — download
it once:

```sh
ollama pull llava
```

**e) Restart OpenGirGit** (close it and start it again).

### Option B — a cloud service instead *(needs an account, usually paid)*

If your computer is slow, use OpenAI, OpenRouter or any “OpenAI-compatible”
provider: create the same `.env` file with that provider's address, API key and
model name — see [Server environment](../README.md#server-environment) in the
main README. The app itself is always free; the provider bills you directly.

## 4. Quick tour (30 seconds)

* **Ask a written question**: type in the box, press Enter (or `Shift+Alt+A`).
* **Let it hear the interviewer**: gear icon → **Speech** → *Audio device to
  listen to* → **System audio (interviewer)** (Windows). On Linux, pick the
  **monitor** of your speakers. The first time, a small speech model (~150 MB)
  downloads once.
* **Screenshot a question on your screen**: press `Shift+Alt+S`, drag a box.
  (Needs the vision model from step 3d.)
* **Get it out of the way instantly**: `Shift+Alt+H` collapses the panel;
  `Shift+Alt+C` makes the bar click-through. Change any shortcut under
  Settings → **Hotkeys**.

**Did it work?** Settings → **Server** → **Test connection** should say
`Server is ok. LLM configured: yes.` — then asking a question should answer.

## 5. Good to know

* **Privacy.** Speech is transcribed **on your computer**, and conversations are
  stored **on your computer** (`%LOCALAPPDATA%\OpenGirGit` on Windows,
  `~/.local/share/opengirgit` + `~/.opengirgit` on Linux). With Ollama, nothing
  leaves your machine at all; with a cloud provider, only your questions (and
  any screenshot you attach) are sent to that provider.
* **The first answer is slow** (10–30 s): the model loads into memory. Later
  answers are fast.
* **Updating:** download the newer installer/bundle and run/overwrite it — your
  settings and history are kept.
* **Uninstalling:** Windows: *Settings → Apps → OpenGirGit → Uninstall*.
  Linux: `~/OpenGirGit/install-linux.sh --uninstall`, then delete the folder.

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| Blue “Windows protected your PC” box | **More info → Run anyway.** The app is open-source and unsigned, so Windows is extra cautious — it asks once. |
| The floating bar never appears | Look for an error message: on Windows in the **black window**, on Linux start OpenGirGit from a terminal (`~/OpenGirGit/OpenGirGit`). If it says the server “did not become healthy”, another copy may already be running — close everything and start once. |
| “cannot reach” / “connection refused” | The app's engine must be running: on Windows keep the black window open; on Linux don't kill the process — restart OpenGirGit. |
| Asking a question shows an error | Ollama isn't running, or step 3c didn't work. Check with `ollama list` — `llama3.1:8b` should be listed. Fix and restart OpenGirGit. |
| No words appear while someone talks | Settings → **Speech**: pick the right device. On Windows also check *Settings → Privacy → Microphone → Let desktop apps access your microphone*. |
| Linux: “no system-audio monitor found” | `sudo apt install pulseaudio-utils` (most newer systems already have a PipeWire equivalent). |
| Screenshot answers don't work | Run `ollama pull llava`, then restart OpenGirGit. |
| Something else | Open an issue: <https://github.com/rajdeep-3305/opengirgit/issues> — a screenshot of the error window (or a terminal log) helps a lot. |

---

*Technical reader? The [main README](../README.md) covers running from source,
advanced configuration and the full hotkey list. The
[Windows](WINDOWS-CHECKLIST.md) / [Linux](LINUX-CHECKLIST.md) checklists go
deeper.*
