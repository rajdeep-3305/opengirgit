"""Speech-to-text support: mint short-lived Deepgram tokens.

The audio never transits this server — the client connects straight to Deepgram,
the same architecture as the original app. If no Deepgram key is configured the
client is expected to use its local (faster-whisper) engine instead.
"""

from __future__ import annotations

from urllib.parse import urlencode

import httpx

from .config import get_settings

_DEEPGRAM_TOKEN_URL = "https://api.deepgram.com/v1/auth/token"
_DEEPGRAM_WS_URL = "wss://api.deepgram.com/v1/listen"


class SttError(Exception):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


def deepgram_configured() -> bool:
    return bool(get_settings().deepgram_api_key)


def build_deepgram_url() -> str:
    settings = get_settings()
    params = {
        "model": settings.deepgram_model,
        "language": settings.deepgram_language,
        "encoding": "linear16",
        "sample_rate": 16000,
        "channels": 1,
        "interim_results": "true",
        "smart_format": "true",
        "vad_events": "true",
    }
    return f"{_DEEPGRAM_WS_URL}?{urlencode(params)}"


async def mint_deepgram_token() -> dict:
    """Create a temporary Deepgram token via Deepgram's token API."""
    settings = get_settings()
    if not deepgram_configured():
        raise SttError(
            "Deepgram is not configured on this server. "
            "Use the local (faster-whisper) STT engine.",
            status_code=501,
        )

    ttl = max(30, settings.deepgram_token_ttl_seconds)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=30.0)) as client:
            response = await client.post(
                _DEEPGRAM_TOKEN_URL,
                headers={
                    "Authorization": f"Token {settings.deepgram_api_key}",
                    "Content-Type": "application/json",
                },
                json={"ttl_seconds": ttl},
            )
    except httpx.HTTPError as exc:
        raise SttError(f"could not reach Deepgram: {exc}") from exc

    if response.status_code >= 400:
        detail = response.text.strip()[:300] or response.reason_phrase
        raise SttError(f"Deepgram rejected the token request: {detail}")

    data = response.json()
    token = data.get("access_token") or data.get("key")
    if not token:
        raise SttError("Deepgram returned no token")

    return {
        "provider": "deepgram",
        "token": token,
        "expires_in": int(data.get("expires_in") or ttl),
        "deepgram_url": build_deepgram_url(),
    }
