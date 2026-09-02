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
