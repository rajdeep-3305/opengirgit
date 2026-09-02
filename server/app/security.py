"""Authentication primitives: OTP hashing and JWT issuance.

Kept free of FastAPI imports so it can be unit-tested without the web stack.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time

import jwt


class TokenError(Exception):
    """Raised when a bearer token is invalid or expired."""


def generate_otp(length: int = 6) -> str:
    """Cryptographically random numeric OTP (no leading-zero bias)."""
    if length < 4:
        raise ValueError("OTP length must be >= 4")
    return "".join(str(secrets.randbelow(10)) for _ in range(length))


def hash_otp(code: str, secret: str) -> str:
    mac = hmac.new(secret.encode("utf-8"), code.encode("utf-8"), hashlib.sha256)
    return mac.hexdigest()


def verify_otp(code: str, code_hash: str, secret: str) -> bool:
    return hmac.compare_digest(hash_otp(code, secret), code_hash)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def create_token(
    email: str,
    secret: str,
    *,
    algorithm: str = "HS256",
    expires_minutes: int = 60 * 24 * 7,
    extra: dict | None = None,
) -> str:
    now = int(time.time())
    payload = {
        "sub": email.strip().lower(),
        "iat": now,
        "exp": now + max(1, expires_minutes) * 60,
        "jti": _b64url(secrets.token_bytes(12)),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, secret, algorithm=algorithm)


def decode_token(
    token: str,
    secret: str,
    *,
    algorithm: str = "HS256",
    leeway_seconds: int = 0,
) -> dict:
    """Decode and validate a token. Raises TokenError on any problem."""
    if not token:
        raise TokenError("missing token")
    try:
        return jwt.decode(
            token,
            secret,
            algorithms=[algorithm],
            leeway=leeway_seconds,
            options={"require": ["sub", "exp"]},
        )
    except jwt.ExpiredSignatureError as exc:  # pragma: no cover - trivial mapping
        raise TokenError("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError(f"invalid token: {exc}") from exc
