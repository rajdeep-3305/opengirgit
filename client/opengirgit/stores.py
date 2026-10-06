"""Local JSON stores under ``~/.opengirgit``.

All writes are atomic (tmp file + ``os.replace``) and bounded so a long-lived
install cannot grow without limit. Failures are non-fatal by design: history and
caches are conveniences, never a reason to crash the overlay.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import BASE_DIR

CREDENTIALS_PATH = BASE_DIR / "credentials.json"
CONTEXT_PATH = BASE_DIR / "context.json"
CONVERSATIONS_PATH = BASE_DIR / "conversations.json"
RESUME_CACHE_PATH = BASE_DIR / "resume_cache.json"

MAX_SESSIONS = 25
MAX_ITEMS_PER_SESSION = 200


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


# --------------------------------------------------------------------------- #
# Credentials
# --------------------------------------------------------------------------- #


class CredentialsStore:
    """Bearer token + email. Uses the OS keyring when available."""

    SERVICE = "OpenGirGit"
    KEY = "user_credentials"

    def __init__(self) -> None:
        self._keyring = None
        try:  # keyring is optional
            import keyring

            self._keyring = keyring
        except Exception:  # pragma: no cover - platform dependent
            self._keyring = None

    def load(self) -> dict[str, Any]:
        if self._keyring is not None:
            try:
                raw = self._keyring.get_password(self.SERVICE, self.KEY)
                if raw:
                    return json.loads(raw)
            except Exception:
                pass
        return _read_json(CREDENTIALS_PATH, {})

    def save(self, email: str, token: str, server_url: str) -> None:
        payload = {"email": email, "access_token": token, "server_url": server_url, "saved_at": _now()}
        if self._keyring is not None:
            try:
                self._keyring.set_password(self.SERVICE, self.KEY, json.dumps(payload))
                return
            except Exception:
                pass
        try:
            _atomic_write(CREDENTIALS_PATH, payload)
        except OSError:
            pass

    def clear(self) -> None:
        if self._keyring is not None:
            try:
                self._keyring.delete_password(self.SERVICE, self.KEY)
            except Exception:
                pass
        try:
            CREDENTIALS_PATH.unlink(missing_ok=True)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# Interview context (resume + JD + notes)
# --------------------------------------------------------------------------- #


class ContextStore:
    def load(self) -> dict[str, Any]:
        return _read_json(
            CONTEXT_PATH,
            {"resume": None, "company": "", "job_description": "", "anything_else": ""},
        )

    def save(self, data: dict[str, Any]) -> None:
        try:
            _atomic_write(CONTEXT_PATH, data)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# Resume cache
# --------------------------------------------------------------------------- #


class ResumeCache:
    def load(self) -> dict[str, Any]:
        return _read_json(RESUME_CACHE_PATH, {})

    def save(self, source_name: str, source_hash: str, parsed: dict[str, Any]) -> None:
        try:
            _atomic_write(
                RESUME_CACHE_PATH,
                {
                    "source_name": source_name,
                    "source_hash": source_hash,
                    "parsed": parsed,
                    "updated_at": _now(),
                },
            )
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# Conversations
# --------------------------------------------------------------------------- #


class ConversationStore:
    """Bounded local Q&A history (never sent anywhere)."""

    def __init__(self) -> None:
        data = _read_json(CONVERSATIONS_PATH, {"sessions": []})
        self._sessions: list[dict[str, Any]] = data.get("sessions") or []
        self._current_id: str | None = None

    # -- session lifecycle ------------------------------------------------ #

    def start_session(self, title: str = "Interview session") -> str:
        session_id = uuid.uuid4().hex[:12]
        self._sessions.insert(
            0,
            {"id": session_id, "title": title, "started_at": _now(), "items": []},
        )
        del self._sessions[MAX_SESSIONS:]
        self._current_id = session_id
        self._flush()
        return session_id

    def add_item(self, question: str, answer: str, kind: str = "chat") -> None:
        session = self._current()
        if session is None:
            self.start_session()
            session = self._current()
        if session is None:  # pragma: no cover - defensive
            return
        session["items"].append(
            {"question": question, "answer": answer, "kind": kind, "ts": _now()}
        )
        del session["items"][:-MAX_ITEMS_PER_SESSION]
        self._flush()

    def _current(self) -> dict[str, Any] | None:
        for session in self._sessions:
            if session.get("id") == self._current_id:
                return session
        return self._sessions[0] if self._sessions else None

    def sessions(self) -> list[dict[str, Any]]:
        return list(self._sessions)

    # -- export ------------------------------------------------------------- #

    def session_markdown(self, session: dict[str, Any]) -> str:
        """One session as Markdown (used by the history dialog / exporter)."""
        lines = [
            f"## {session.get('title') or 'Session'}",
            "",
            f"*{session.get('started_at', '')}*",
            "",
        ]
        for index, item in enumerate(session.get("items") or [], start=1):
            tag = " — screenshot" if item.get("kind") == "vision" else ""
            lines.append(f"### Q{index}{tag}")
            lines.append("")
            lines.append(f"**Q:** {str(item.get('question', '')).strip()}")
            lines.append("")
            lines.append(str(item.get("answer", "")).rstrip())
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def export_markdown(self, session_id: str | None = None) -> str:
        """Every stored session (or one) as a single Markdown document."""
        sessions = list(self._sessions)
        if session_id is not None:
            sessions = [s for s in sessions if s.get("id") == session_id]
        header = [
            "# OpenGirGit conversation export",
            "",
            f"_Exported {_now()} · {len(sessions)} session(s) · generated locally, nothing sent anywhere_",
            "",
        ]
        body = [self.session_markdown(s) for s in reversed(sessions)] or [
            "_No conversations stored yet._\n"
        ]
        return "\n".join(header + body)

    def _flush(self) -> None:
        try:
            _atomic_write(CONVERSATIONS_PATH, {"sessions": self._sessions})
        except OSError:
            pass
