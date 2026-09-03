"""SQLite storage — stdlib only, no ORM.

Tables:
    users     one row per account (email + arbitrary JSON profile)
    otps      pending one-time codes, hashed
    feedback  free-form feedback submissions
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import get_settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    email       TEXT PRIMARY KEY,
    profile     TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS otps (
    email         TEXT PRIMARY KEY,
    code_hash     TEXT NOT NULL,
    expires_at    REAL NOT NULL,
    attempts      INTEGER NOT NULL DEFAULT 0,
    last_sent_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email       TEXT,
    message     TEXT NOT NULL,
    app_version TEXT,
    created_at  TEXT NOT NULL
);
"""

_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _connect() -> sqlite3.Connection:
    settings = get_settings()
    conn = sqlite3.connect(settings.sqlite_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    """Open a connection, commit on success, always close."""
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _lock, db() as conn:
        conn.executescript(_SCHEMA)


# --- users -------------------------------------------------------------------


def upsert_user(email: str, profile: dict | None = None) -> None:
    email = email.strip().lower()
    with _lock, db() as conn:
        row = conn.execute("SELECT email FROM users WHERE email = ?", (email,)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO users (email, profile, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (email, json.dumps(profile or {}), _now_iso(), _now_iso()),
            )
        elif profile is not None:
            conn.execute(
                "UPDATE users SET profile = ?, updated_at = ? WHERE email = ?",
                (json.dumps(profile), _now_iso(), email),
            )


def get_user(email: str) -> dict | None:
    email = email.strip().lower()
    with db() as conn:
        row = conn.execute(
            "SELECT email, profile, created_at, updated_at FROM users WHERE email = ?",
            (email,),
        ).fetchone()
    if row is None:
        return None
    return {
        "email": row["email"],
        "profile": json.loads(row["profile"] or "{}"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def user_exists(email: str) -> bool:
    return get_user(email) is not None


# --- OTPs --------------------------------------------------------------------


def put_otp(email: str, code_hash: str, expires_at: float, sent_at: float) -> None:
    email = email.strip().lower()
    with _lock, db() as conn:
        conn.execute(
            """
            INSERT INTO otps (email, code_hash, expires_at, attempts, last_sent_at)
            VALUES (?, ?, ?, 0, ?)
            ON CONFLICT(email) DO UPDATE SET
                code_hash = excluded.code_hash,
                expires_at = excluded.expires_at,
                attempts = 0,
                last_sent_at = excluded.last_sent_at
            """,
            (email, code_hash, expires_at, sent_at),
        )


def get_otp(email: str) -> dict | None:
    email = email.strip().lower()
    with db() as conn:
        row = conn.execute(
            "SELECT code_hash, expires_at, attempts, last_sent_at FROM otps WHERE email = ?",
            (email,),
        ).fetchone()
    return dict(row) if row else None


def bump_otp_attempts(email: str) -> int:
    email = email.strip().lower()
    with _lock, db() as conn:
        conn.execute("UPDATE otps SET attempts = attempts + 1 WHERE email = ?", (email,))
        row = conn.execute("SELECT attempts FROM otps WHERE email = ?", (email,)).fetchone()
    return int(row["attempts"]) if row else 0


def delete_otp(email: str) -> None:
    email = email.strip().lower()
    with _lock, db() as conn:
        conn.execute("DELETE FROM otps WHERE email = ?", (email,))


# --- feedback ----------------------------------------------------------------


def add_feedback(message: str, email: str | None, app_version: str | None) -> None:
    with _lock, db() as conn:
        conn.execute(
            "INSERT INTO feedback (email, message, app_version, created_at) VALUES (?, ?, ?, ?)",
            (email, message, app_version, _now_iso()),
        )
