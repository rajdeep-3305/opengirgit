"""Frozen-desktop entry point: bundled API server + overlay client in one exe.

1. Client-only utility flags (``--check-render``, ``--print-settings``,
   ``--list-devices``, ``--help``) are handled directly, without starting the
   bundled server.
2. If something already answers ``/api/health`` on the configured host/port the
   launcher leaves it alone (so the exe can also attach to a server you run
   separately).
3. Otherwise the packaged FastAPI app is started in a daemon thread.
4. The normal client bootstrap then runs (login dialog, overlay, hotkeys).

Configuration is exactly the source-distribution one: environment variables or
a ``.env`` file next to the executable. ``DATA_DIR`` defaults to a writable
per-user location so the app works from read-only install directories.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import urllib.request
from pathlib import Path

_UTILITY_FLAGS = ("--check-render", "--print-settings", "--list-devices", "--help", "-h")


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


if not getattr(sys, "frozen", False):  # running from the source tree
    _root = _base_dir()
    for _sub in ("client", "server"):
        _path = str(_root / _sub)
        if _path not in sys.path:
            sys.path.insert(0, _path)


def _prepare_environment() -> str:
    """chdir next to the executable, fill in safe defaults, return server URL."""
    base = _base_dir()
    if getattr(sys, "frozen", False):
        try:
            os.chdir(base)
        except OSError:
            pass

    if not os.environ.get("DATA_DIR"):
        if sys.platform == "win32":
            root = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "OpenGirGit"
        else:
            root = Path.home() / ".local" / "share" / "opengirgit"
        os.environ["DATA_DIR"] = str(root / "data")

    host = os.environ.get("HOST", "127.0.0.1")
    port = os.environ.get("PORT", "8000")
    server_url = os.environ.get("OPENGIRGIT_SERVER_URL", f"http://{host}:{port}")
    os.environ.setdefault("OPENGIRGIT_SERVER_URL", server_url)
    return server_url


def _is_healthy(server_url: str, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(f"{server_url.rstrip('/')}/api/health", timeout=timeout):
            return True
    except Exception:  # noqa: BLE001 - any failure means "not healthy yet"
        return False


def _start_server_thread() -> None:
    import uvicorn
    from app.main import app as server_app

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    config = uvicorn.Config(server_app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="opengirgit-api", daemon=True)
    thread.start()


def main() -> int:
    if any(flag in sys.argv[1:] for flag in _UTILITY_FLAGS):
        # Same flag dispatch as `python -m opengirgit` — these never need the
        # bundled API server, and --check-render must work on a bare machine.
        from opengirgit.__main__ import _main as client_cli

        return client_cli()

    server_url = _prepare_environment()

    if not _is_healthy(server_url):
        print(f"OpenGirGit: starting the bundled API server on {server_url} …")
        _start_server_thread()
        deadline = time.time() + 30
        while time.time() < deadline and not _is_healthy(server_url):
            time.sleep(0.25)
        if _is_healthy(server_url):
            print("OpenGirGit: API server ready.")
        else:
            print(
                "OpenGirGit: warning — the API server did not become healthy; "
                "the client will still try to connect.",
                file=sys.stderr,
            )
    else:
        print(f"OpenGirGit: using the API server already running on {server_url}.")

    from opengirgit.app import main as client_main

    return client_main()


if __name__ == "__main__":
    raise SystemExit(main())
