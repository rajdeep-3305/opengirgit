"""OTP hashing and JWT issuance (pure functions, no network)."""

from __future__ import annotations

import time

import pytest
from app.security import (
    TokenError,
    create_token,
    decode_token,
    generate_otp,
    hash_otp,
    verify_otp,
)

SECRET = "unit-test-secret-that-is-long-enough-for-hs256"


def test_generate_otp_is_numeric_and_sized():
    code = generate_otp()
    assert len(code) == 6
    assert code.isdigit()
    assert generate_otp(8).isdigit()


def test_generate_otp_rejects_short_lengths():
    with pytest.raises(ValueError):
        generate_otp(3)


def test_hash_verify_round_trip():
    digest = hash_otp("123456", SECRET)
    assert digest != "123456"
    assert verify_otp("123456", digest, SECRET)
    assert not verify_otp("654321", digest, SECRET)
    assert not verify_otp("123456", digest, "other-secret")


def test_token_round_trip():
    token = create_token("a@b.c", SECRET, expires_minutes=5)
    payload = decode_token(token, SECRET)
    assert payload["sub"] == "a@b.c"


def test_token_is_normalised_and_carries_expiry():
    token = create_token("MixedCase@Example.COM ", SECRET, expires_minutes=5)
    payload = decode_token(token, SECRET)
    assert payload["sub"] == "mixedcase@example.com"
    assert payload["exp"] > time.time()


def test_wrong_secret_and_garbage_are_rejected():
    token = create_token("a@b.c", SECRET)
    with pytest.raises(TokenError):
        decode_token(token, "wrong-secret")
    with pytest.raises(TokenError):
        decode_token("not-a-token", SECRET)
    with pytest.raises(TokenError):
        decode_token("", SECRET)


def test_legacy_token_can_be_refreshed_with_leeway():
    import jwt as pyjwt

    now = int(time.time())
    expired = pyjwt.encode(
        {"sub": "a@b.c", "iat": now - 7200, "exp": now - 3600},
        SECRET,
        algorithm="HS256",
    )
    with pytest.raises(TokenError):
        decode_token(expired, SECRET)
    payload = decode_token(expired, SECRET, leeway_seconds=7200)
    assert payload["sub"] == "a@b.c"


# -- startup guard, CORS policy --------------------------------------------- #


def _settings(**overrides):
    from app.config import Settings

    base = {
        "host": "127.0.0.1",
        "jwt_secret": SECRET,
        "smtp_host": "smtp.example.com",
        "allow_dev_otp_echo": False,
    }
    base.update(overrides)
    return Settings(**base)


def test_non_loopback_bind_refuses_the_default_secret():
    from app.config import DEFAULT_JWT_SECRET
    from app.main import check_startup_security

    with pytest.raises(RuntimeError, match="JWT_SECRET is still the shipped default"):
        check_startup_security(_settings(host="0.0.0.0", jwt_secret=DEFAULT_JWT_SECRET))


def test_non_loopback_bind_refuses_a_short_secret():
    from app.main import check_startup_security

    with pytest.raises(RuntimeError, match="shorter than 32 characters"):
        check_startup_security(_settings(host="192.168.1.5", jwt_secret="short"))


def test_non_loopback_bind_refuses_the_dev_otp_echo_without_smtp():
    from app.main import check_startup_security

    with pytest.raises(RuntimeError, match="ALLOW_DEV_OTP_ECHO"):
        check_startup_security(
            _settings(host="0.0.0.0", smtp_host="", allow_dev_otp_echo=True)
        )


def test_loopback_bind_warns_but_starts(capsys):
    from app.main import check_startup_security

    check_startup_security(
        _settings(smtp_host="", allow_dev_otp_echo=True, jwt_secret="dev-secret-change-me-use-32-bytes-minimum")
    )
    assert "warning:" in capsys.readouterr().out


def test_non_loopback_bind_passes_with_a_real_secret_and_smtp():
    from app.main import check_startup_security

    check_startup_security(_settings(host="0.0.0.0"))


def test_smtp_configured_disables_the_dev_echo():
    assert _settings(smtp_host="smtp.example.com").dev_otp_echo is False
    assert _settings(smtp_host="", allow_dev_otp_echo=True).dev_otp_echo is True
    assert _settings(smtp_host="", allow_dev_otp_echo=False).dev_otp_echo is False


def test_cors_is_off_by_default():
    """No wildcard: a random website must not be able to drive the API."""
    from app.config import get_settings
    from app.main import app
    from fastapi.middleware.cors import CORSMiddleware

    if get_settings().cors_origin_list:
        pytest.skip("CORS origins configured in the environment")
    assert not any(m.cls is CORSMiddleware for m in app.user_middleware)
