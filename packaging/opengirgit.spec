# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: one folder with the launcher exe (client + API server).

Build from the repository root:

    pip install pyinstaller
    pyinstaller packaging/opengirgit.spec --noconfirm --distpath dist --workpath build

Result: ``dist/OpenGirGit/OpenGirGit`` (``.exe`` on Windows). Ship the whole
``OpenGirGit`` folder. Runtime configuration is the usual environment /
``.env`` next to the executable; see ``packaging/README.md``.
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).resolve().parents[0]  # noqa: F821 - provided by PyInstaller

datas = []
binaries = []
hiddenimports = [
    "app.main",
    "app.config",
    "app.db",
    "app.security",
    "app.llm",
    "app.prompts",
    "app.resume",
    "app.stt",
    "opengirgit.app",
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
]

# Heavy scientific/STT stack: grab package data, shared libraries and modules.
for package in (
    "faster_whisper",
    "ctranslate2",
    "tokenizers",
    "huggingface_hub",
    "av",
    "websockets",
    "sounddevice",
):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    except Exception:  # noqa: BLE001 - optional dependency may be absent
        continue
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

if sys.platform == "win32":
    # WASAPI loopback capture (PyAudio fork); hook-contrib knows plain PyAudio.
    for package in ("pyaudiowpatch",):
        try:
            pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
        except Exception:  # noqa: BLE001
            continue
        datas += pkg_datas
        binaries += pkg_binaries
        hiddenimports += pkg_hidden

a = Analysis(  # noqa: F821 - provided by PyInstaller
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "client"), str(ROOT / "server"), str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="OpenGirGit",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # keeps server/OTP logs visible; see packaging/README.md
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="OpenGirGit",
)
