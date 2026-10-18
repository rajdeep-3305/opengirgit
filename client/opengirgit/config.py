"""Client settings: defaults, ``.env`` overrides and ``~/.opengirgit/config.json``."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

APP_DIR_NAME = ".opengirgit"
BASE_DIR = Path.home() / APP_DIR_NAME
CONFIG_PATH = BASE_DIR / "config.json"
CONFIG_VERSION = 2

DEFAULT_SCREENSHOT_PROMPT = (
    "Read the problem or task in this screenshot and answer it completely. "
    "If it is a coding problem: give a brief approach, then the full solution "
    "code, then complexity."
)

DEFAULT_HOTKEYS: dict[str, str] = {
    "collapse": "Shift+Alt+H",
    "ask": "Shift+Alt+A",
    "erase": "Shift+Alt+D",
    "screenshot": "Shift+Alt+S",
    "click_through": "Shift+Alt+C",
    "prev": "Shift+Alt+[",
    "next": "Shift+Alt+]",
    "scroll_up": "Shift+Alt+W",
    "scroll_down": "Shift+Alt+X",
    "move_up": "Shift+Alt+I",
    "move_down": "Shift+Alt+K",
    "move_left": "Shift+Alt+J",
    "move_right": "Shift+Alt+L",
    "opacity_down": "Shift+Alt+-",
    "opacity_up": "Shift+Alt+=",
}

_ENV_MAP = {
    "OPENGIRGIT_SERVER_URL": ("server_url", str),
    "OPENGIRGIT_STT_ENGINE": ("stt_engine", str),
    "OPENGIRGIT_WHISPER_MODEL": ("whisper_model", str),
    "OPENGIRGIT_WHISPER_COMPUTE_TYPE": ("whisper_compute_type", str),
    "OPENGIRGIT_AUDIO_SOURCE": ("audio_source", str),
    "OPENGIRGIT_AUDIO_DEVICE": ("audio_device", str),
    "OPENGIRGIT_AUTO_ASK": ("auto_ask", "bool"),
    "OPENGIRGIT_PARTIALS": ("partials", "bool"),
    "OPENGIRGIT_DECOY_CURSOR": ("decoy_cursor", "bool"),
    "OPENGIRGIT_WEB_RENDER": ("web_render", "bool"),
    "OPENGIRGIT_SILENCE_SECONDS": ("silence_seconds", float),
    "OPENGIRGIT_OPACITY": ("opacity", float),
    "OPENGIRGIT_SCREENSHOT_PROMPT": ("screenshot_prompt", str),
    "OPENGIRGIT_CHAT_TRANSPORT": ("chat_transport", str),
    "OPENGIRGIT_UI_SCALE": ("ui_scale", "int"),
}

#: Supported chat transports (``auto`` upgrades to WebSocket and falls back).
CHAT_TRANSPORTS = ("auto", "sse", "websocket")

#: UI scale presets in percent (0 = leave the system/session DPI alone).
UI_SCALES = (0, 100, 110, 125, 150, 175, 200)


@dataclass
class AppSettings:
    config_version: int = CONFIG_VERSION
    server_url: str = "http://127.0.0.1:8000"

    # Speech-to-text
    stt_engine: str = "local"  # "local" | "deepgram"
    whisper_model: str = "base.en"
    whisper_compute_type: str = "int8"
    silence_seconds: float = 0.9  # silence that ends an utterance (lower = snappier)

    # Audio capture
    audio_source: str = "system"  # "system" (loopback) | "microphone"
    audio_device: str = ""  # device id; empty = default

    # Behaviour
    auto_ask: bool = True
    partials: bool = True  # show live in-progress transcripts (local whisper re-runs)
    decoy_cursor: bool = True  # hide the real cursor during region selection
    web_render: bool = True  # render answers with the embedded web view
    opacity: float = 0.95
    screenshot_prompt: str = DEFAULT_SCREENSHOT_PROMPT

    # Transport / interface
    chat_transport: str = "auto"  # "auto" (WebSocket with SSE fallback) | "sse" | "websocket"
    ui_scale: int = 0  # percent (0 = follow the session/system DPI)

    hotkeys: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_HOTKEYS))

    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppSettings:
        data = dict(data or {})
        # v0.2.2 shipped 0.96 as the default; the original overlay uses 0.95.
        # Migrate untouched configs once, without touching any later choice.
        if "config_version" not in data and data.get("opacity") == 0.96:
            data["opacity"] = 0.95
        data["config_version"] = CONFIG_VERSION
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        clean = {k: v for k, v in data.items() if k in known}
        settings = cls(**clean)
        merged = dict(DEFAULT_HOTKEYS)
        merged.update({k: v for k, v in (clean.get("hotkeys") or {}).items() if isinstance(v, str)})
        settings.hotkeys = merged
        settings.opacity = min(max(float(settings.opacity), 0.3), 1.0)
        settings.silence_seconds = min(max(float(settings.silence_seconds), 0.2), 3.0)
        if settings.stt_engine not in ("local", "deepgram"):
            settings.stt_engine = "local"
        if settings.audio_source not in ("system", "microphone"):
            settings.audio_source = "system"
        if settings.chat_transport not in CHAT_TRANSPORTS:
            settings.chat_transport = "auto"
        try:
            scale = int(settings.ui_scale)
        except (TypeError, ValueError):
            scale = 0
        settings.ui_scale = scale if 80 <= scale <= 300 else 0
        return settings

    def apply_env(self) -> AppSettings:
        for env_name, (attr, kind) in _ENV_MAP.items():
            raw = os.environ.get(env_name)
            if raw is None or raw == "":
                continue
            try:
                if kind is bool or kind == "bool":
                    value: Any = raw.strip().lower() in ("1", "true", "yes", "on")
                elif kind is float:
                    value = float(raw)
                elif kind == "int":
                    value = int(float(raw))
                else:
                    value = raw
                setattr(self, attr, value)
            except ValueError:
                continue
        return self

    def save(self) -> None:
        BASE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        tmp.replace(CONFIG_PATH)

    @classmethod
    def load(cls) -> AppSettings:
        data: dict[str, Any] = {}
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
        settings = cls.from_dict(data).apply_env()
        try:
            settings.save()
        except OSError:
            pass  # read-only home — run with defaults
        return settings


def load_dotenv_if_present() -> None:
    """Optional: load ``.env`` from the current directory via python-dotenv."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(override=False)
