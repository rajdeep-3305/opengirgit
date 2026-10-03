"""OpenGirGit server — FastAPI application.

Implemented surface (see docs/API.md):

    GET  /                          banner
    GET  /api/health                readiness
    GET  /api/version               version metadata
    POST /api/auth/otp/send         email one-time code
    POST /api/auth/otp/verify       code -> JWT
    POST /api/auth/refresh          silent re-issue
    GET  /api/auth/me               current profile
    GET  /api/auth/user-exists/{email}
    GET  /api/auth/profile/{email}
    POST /api/auth/profile          store profile
    POST /api/llm/chat/stream       SSE chat completion
    POST /api/llm/vision/stream     SSE vision completion
    WS   /api/llm/ws                optional WebSocket transport (same events)
    POST /api/resume/parse          resume text -> JSON
    POST /api/stt/token             optional Deepgram temp token
    POST /api/feedback/submit       feedback

There is deliberately no billing, payment or subscription code anywhere.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError

from . import db, llm, stt
from . import resume as resume_mod
from .config import get_settings
from .mailer import send_otp_email
from .prompts import build_chat_messages, build_vision_messages
from .security import (
    TokenError,
    create_token,
    decode_token,
    generate_otp,
    hash_otp,
    verify_otp,
)

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    yield


app = FastAPI(
    title="OpenGirGit API",
    version=settings.app_version,
    description="Open-source interview-copilot backend. No billing, no telemetry.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list or ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# Auth dependency
# --------------------------------------------------------------------------- #


def current_user(authorization: str = Header(default="")) -> str:
    """Extract and validate the bearer token; returns the user's email."""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="missing bearer token")
    try:
        payload = decode_token(token.strip(), settings.jwt_secret, algorithm=settings.jwt_algorithm)
    except TokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    email = str(payload.get("sub") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=401, detail="token has no subject")
    return email


def _require_self(email: str, user: str) -> None:
    if email.strip().lower() != user:
        raise HTTPException(status_code=403, detail="you can only access your own profile")


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #


class OtpSendRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class OtpVerifyRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    otp: str = Field(min_length=4, max_length=12)


class ProfileRequest(BaseModel):
    profile: dict[str, Any] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=32_000)
    conversation_history: list[dict[str, Any]] = Field(default_factory=list)
    context: str = Field(default="", max_length=100_000)
    model: str | None = None


class VisionRequest(BaseModel):
    prompt: str = Field(default="", max_length=8_000)
    images: list[str] = Field(default_factory=list, max_length=5)
    image: str | None = None  # single-image convenience field
    conversation_history: list[dict[str, Any]] = Field(default_factory=list)
    context: str = Field(default="", max_length=100_000)
    model: str | None = None


class ResumeRequest(BaseModel):
    resume_text: str = Field(min_length=1, max_length=200_000)
    model: str | None = None


class FeedbackRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8_000)
    email: str | None = None
    phone: str | None = None
    app_version: str | None = None


# --------------------------------------------------------------------------- #
# Basic endpoints
# --------------------------------------------------------------------------- #


@app.get("/")
def banner() -> dict[str, Any]:
    return {"message": "OpenGirGit API", "version": settings.app_version, "status": "running"}


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "llm_configured": settings.llm_configured,
        "llm_model": settings.llm_chat_model,
        "stt_provider": "deepgram" if stt.deepgram_configured() else "local",
        "email_configured": settings.smtp_configured,
    }


@app.get("/api/version")
def version() -> dict[str, Any]:
    return {
        "version": settings.app_version,
        "download_url": "",
        "release_notes": "OpenGirGit — no automatic updates; pull from git.",
        "mandatory": False,
        "windows": "",
        "mac": "",
    }


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #


@app.post("/api/auth/otp/send")
def otp_send(request: OtpSendRequest) -> dict[str, Any]:
    email = request.email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="invalid email address")

    existing = db.get_otp(email)
    now = time.time()
    if existing and now - float(existing["last_sent_at"]) < settings.otp_rate_limit_seconds:
        wait = int(settings.otp_rate_limit_seconds - (now - float(existing["last_sent_at"])))
        raise HTTPException(status_code=429, detail=f"please wait {max(wait, 1)}s before requesting a new code")

    code = generate_otp()
    delivered = send_otp_email(settings, email, code)
    db.put_otp(
        email,
        hash_otp(code, settings.jwt_secret),
        expires_at=now + settings.otp_ttl_seconds,
        sent_at=now,
    )

    response: dict[str, Any] = {
        "success": True,
        "message": "OTP sent" if delivered else "OTP generated (no SMTP configured)",
        "expires_in": settings.otp_ttl_seconds,
    }
    if settings.dev_otp_echo:
        response["otp_code"] = code
        print(f"[dev] OTP for {email}: {code}")
    return response


@app.post("/api/auth/otp/verify")
def otp_verify(request: OtpVerifyRequest) -> dict[str, Any]:
    email = request.email.strip().lower()
    record = db.get_otp(email)
    if record is None:
        raise HTTPException(status_code=401, detail="no code was requested for this email")

    if time.time() > float(record["expires_at"]):
        db.delete_otp(email)
        raise HTTPException(status_code=401, detail="code expired, request a new one")

    if int(record["attempts"]) >= settings.otp_max_attempts:
        db.delete_otp(email)
        raise HTTPException(status_code=429, detail="too many attempts, request a new code")

    if not verify_otp(request.otp.strip(), record["code_hash"], settings.jwt_secret):
        attempts = db.bump_otp_attempts(email)
        left = max(settings.otp_max_attempts - attempts, 0)
        raise HTTPException(status_code=401, detail=f"incorrect code ({left} attempts left)")

    db.delete_otp(email)
    db.upsert_user(email)
    token = create_token(
        email,
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        expires_minutes=settings.jwt_expire_minutes,
    )
    return {"success": True, "access_token": token, "token_type": "bearer", "email": email}


@app.post("/api/auth/refresh")
def auth_refresh(authorization: str = Header(default="")) -> dict[str, Any]:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="missing bearer token")
    try:
        # Refresh tolerates a token that expired up to 24h ago.
        payload = decode_token(
            token.strip(),
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
            leeway_seconds=24 * 3600,
        )
    except TokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    email = str(payload.get("sub") or "").lower()
    if not db.user_exists(email):
        raise HTTPException(status_code=401, detail="unknown account")
    db.upsert_user(email)
    new_token = create_token(
        email,
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        expires_minutes=settings.jwt_expire_minutes,
    )
    return {"success": True, "access_token": new_token, "token_type": "bearer", "email": email}


@app.get("/api/auth/me")
def auth_me(user: str = Depends(current_user)) -> dict[str, Any]:
    account = db.get_user(user)
    if account is None:
        raise HTTPException(status_code=404, detail="account not found")
    return {"success": True, "email": account["email"], "profile": account["profile"]}


@app.get("/api/auth/user-exists/{email}")
def user_exists(email: str) -> dict[str, Any]:
    return {"exists": db.user_exists(email)}


@app.get("/api/auth/profile/{email}")
def get_profile(email: str, user: str = Depends(current_user)) -> dict[str, Any]:
    _require_self(email, user)
    account = db.get_user(email)
    if account is None:
        raise HTTPException(status_code=404, detail="account not found")
    return {
        "success": True,
        "email": account["email"],
        "profile": account["profile"],
        "updated_at": account["updated_at"],
    }


@app.post("/api/auth/profile")
def save_profile(request: ProfileRequest, user: str = Depends(current_user)) -> dict[str, Any]:
    db.upsert_user(user, request.profile)
    return {"success": True, "email": user, "profile": request.profile}


# --------------------------------------------------------------------------- #
# LLM proxy (SSE)
# --------------------------------------------------------------------------- #


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _sse_stream(chunks: AsyncIterator[str]) -> AsyncIterator[str]:
    yield ": open\n\n"
    try:
        async for chunk in chunks:
            yield _sse({"chunk": chunk})
        yield _sse({"done": True})
    except llm.LLMError as exc:
        yield _sse({"error": str(exc)})
    except Exception as exc:  # pragma: no cover - last-resort guard
        yield _sse({"error": f"internal error: {exc}"})


_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@app.post("/api/llm/chat/stream")
def chat_stream(request: ChatRequest, user: str = Depends(current_user)) -> StreamingResponse:
    messages = build_chat_messages(
        request.message,
        request.conversation_history,
        request.context,
        base_prompt=settings.system_prompt,
    )
    return StreamingResponse(
        _sse_stream(llm.stream_chat(messages, model=request.model)),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@app.post("/api/llm/vision/stream")
def vision_stream(request: VisionRequest, user: str = Depends(current_user)) -> StreamingResponse:
    images = list(request.images)
    if request.image and request.image not in images:
        images.insert(0, request.image)
    if not images:
        raise HTTPException(status_code=400, detail="no image supplied")

    prompt = request.prompt.strip() or (
        "Read the problem or task visible in this screenshot and answer it completely."
    )
    messages = build_vision_messages(
        prompt,
        images,
        request.conversation_history,
        request.context,
        base_prompt=settings.system_prompt,
    )
    model = llm.vision_model_name(request.model)
    return StreamingResponse(
        _sse_stream(llm.stream_chat(messages, model=model)),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


# --------------------------------------------------------------------------- #
# LLM proxy (WebSocket — the same events as SSE, optional transport)
# --------------------------------------------------------------------------- #


def _ws_user(websocket: WebSocket) -> str | None:
    """Bearer token from the handshake headers; None when missing/invalid."""
    scheme, _, token = (websocket.headers.get("authorization") or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    try:
        payload = decode_token(
            token.strip(), settings.jwt_secret, algorithm=settings.jwt_algorithm
        )
    except TokenError:
        return None
    return str(payload.get("sub") or "").strip().lower() or None


async def _ws_send(websocket: WebSocket, event: dict[str, Any]) -> bool:
    """Send one JSON frame; False when the client already went away."""
    try:
        await websocket.send_json(event)
        return True
    except Exception:  # noqa: BLE001 - the peer disconnected mid-stream
        return False


async def _ws_answer(websocket: WebSocket, payload: dict[str, Any]) -> None:
    """Validate one request and stream the answer frame by frame."""
    try:
        if str(payload.get("kind") or "chat") == "vision":
            request = VisionRequest.model_validate(payload)
            images = list(request.images)
            if request.image and request.image not in images:
                images.insert(0, request.image)
            if not images:
                await _ws_send(websocket, {"error": "no image supplied"})
                return
            prompt = request.prompt.strip() or (
                "Read the problem or task visible in this screenshot and answer it completely."
            )
            messages = build_vision_messages(
                prompt,
                images,
                request.conversation_history,
                request.context,
                base_prompt=settings.system_prompt,
            )
            model = llm.vision_model_name(request.model)
        else:
            request = ChatRequest.model_validate(payload)
            messages = build_chat_messages(
                request.message,
                request.conversation_history,
                request.context,
                base_prompt=settings.system_prompt,
            )
            model = request.model
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        await _ws_send(websocket, {"error": f"invalid request: {first.get('msg', 'bad payload')}"})
        return

    try:
        async for chunk in llm.stream_chat(messages, model=model):
            if not await _ws_send(websocket, {"chunk": chunk}):
                return
        await _ws_send(websocket, {"done": True})
    except llm.LLMError as exc:
        await _ws_send(websocket, {"error": str(exc)})
    except Exception as exc:  # noqa: BLE001 - last-resort guard, mirroring SSE
        await _ws_send(websocket, {"error": f"internal error: {exc}"})


@app.websocket("/api/llm/ws")
async def llm_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    if _ws_user(websocket) is None:
        await websocket.close(code=4401)  # same meaning as the HTTP 401
        return
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                await _ws_send(websocket, {"error": "invalid JSON"})
                continue
            if not isinstance(payload, dict):
                await _ws_send(websocket, {"error": "invalid JSON"})
                continue
            await _ws_answer(websocket, payload)
    except WebSocketDisconnect:
        return


# --------------------------------------------------------------------------- #
# Resume / STT / feedback
# --------------------------------------------------------------------------- #


@app.post("/api/resume/parse")
async def resume_parse(request: ResumeRequest, user: str = Depends(current_user)) -> dict[str, Any]:
    try:
        parsed = await resume_mod.parse_resume(request.resume_text, model=request.model)
    except llm.LLMError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {"success": True, "resume": parsed}


@app.post("/api/stt/token")
async def stt_token(user: str = Depends(current_user)) -> dict[str, Any]:
    try:
        return await stt.mint_deepgram_token()
    except stt.SttError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post("/api/feedback/submit")
def feedback_submit(request: FeedbackRequest) -> dict[str, Any]:
    db.add_feedback(request.message.strip(), request.email, request.app_version)
    return {"success": True}


# --------------------------------------------------------------------------- #
# Entry point helper
# --------------------------------------------------------------------------- #


def dev_run() -> None:  # pragma: no cover - convenience only
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)
