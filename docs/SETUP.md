# OpenGirGit — simple install guide (Windows 11)

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
| Windows 11 (64-bit) | `OpenGirGit-windows-x64-setup.exe` | installs like a normal program |
| Windows 11, if you can't run installers | `OpenGirGit-windows-x64.zip` | unpack anywhere, run `OpenGirGit.exe` inside |

OpenGirGit needs **Windows 11 (64-bit)**. Windows 10, Linux and macOS are not
supported — stealth is the point of the app, and the supported capture path is
Windows 11.

## 2. Install

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

## 3. Give it a model to think with

The app is the radio; the model is the station. Pick **one** option.

### Option A — free & private, runs on your own computer *(recommended)*

**a) Install Ollama**

Download and run `OllamaSetup.exe` from <https://ollama.com/download>.
It stays quietly in the background.

**b) Download the model** — this is the one big download (a few GB, once).
Open **PowerShell** (press Start, type “PowerShell”, Enter) and run:

```sh
ollama pull llama3.1:8b
```

*On a lighter laptop, `ollama pull llama3.2:3b` is a slimmer alternative — if
you use it, write that name instead of `llama3.1:8b` in the next step too.*

**c) Tell OpenGirGit to use it.** Copy this block into the same PowerShell
window and press Enter:

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

**d) Screenshot answers (optional).** Pictures go to a “vision” model — download
it once:

```sh
ollama pull llava
```

**e) Restart OpenGirGit** (close it and start it again).

### Option B — a cloud service instead *(needs an account, usually paid)*

If your computer is slow, use OpenAI, OpenRouter or any “OpenAI-compatible”
provider: create the same `.env` file with that provider's address, API key and
model name — see [Server environment](CONFIGURATION.md#server-environment). The
app itself is always free; the provider bills you directly.

## 4. Quick tour (30 seconds)

* **Ask a written question**: type in the box, press Enter (or `Shift+Alt+A`).
* **Let it hear the interviewer**: gear icon → **Speech** → *Audio device to
  listen to* → **System audio (interviewer)**. The first time, a small speech
  model (~150 MB) downloads once.
* **Screenshot a question on your screen**: press `Shift+Alt+S`, drag a box.
  (Needs the vision model from step 3d.)
* **Get it out of the way instantly**: `Shift+Alt+H` collapses the panel;
  `Shift+Alt+C` makes the bar click-through. Change any shortcut under
  Settings → **Hotkeys**.

**Did it work?** Settings → **Server** → **Test connection** should say
`Server is ok. LLM configured: yes.` — then asking a question should answer.

## 5. Good to know

* **Privacy.** Speech is transcribed **on your computer**, and conversations are
  stored **on your computer** (`%LOCALAPPDATA%\OpenGirGit`). With Ollama,
  nothing leaves your machine at all; with a cloud provider, only your questions
  (and any screenshot you attach) are sent to that provider.
* **The first answer is slow** (10–30 s): the model loads into memory. Later
  answers are fast.
* **Updating:** download the newer installer/bundle and run/overwrite it — your
  settings and history are kept.
* **Uninstalling:** *Settings → Apps → OpenGirGit → Uninstall.*

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| Blue “Windows protected your PC” box | **More info → Run anyway.** The app is open-source and unsigned, so Windows is extra cautious — it asks once. |
| The floating bar never appears | Look for an error message in the **black window**. If it says the server “did not become healthy”, another copy may already be running — close everything and start once. |
| “cannot reach” / “connection refused” | The app's engine must be running: keep the black window open — closing it quits the app. |
| Asking a question shows an error | Ollama isn't running, or step 3c didn't work. Check with `ollama list` — `llama3.1:8b` should be listed. Fix and restart OpenGirGit. |
| No words appear while someone talks | Settings → **Speech**: pick the right device. Also check *Settings → Privacy → Microphone → Let desktop apps access your microphone*. |
| Screenshot answers don't work | Run `ollama pull llava`, then restart OpenGirGit. |
| Something else | Open an issue: <https://github.com/rajdeep-3305/opengirgit/issues> — a screenshot of the error window (or a terminal log) helps a lot. |

---

*Technical reader? [CONTRIBUTING.md](../CONTRIBUTING.md) covers running from
source, [CONFIGURATION.md](CONFIGURATION.md) lists every setting, and the
[main README](../README.md) has the full hotkey list. The
[Windows checklist](WINDOWS-CHECKLIST.md) goes deeper.*
