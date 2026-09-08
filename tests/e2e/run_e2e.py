"""End-to-end test: mock LLM + real server + real client API layer.

Usage: ``python tests/e2e/run_e2e.py`` (from the repository root).

Boots
    1. ``tests/e2e/mock_llm.py``   — fake OpenAI-compatible model,
    2. ``server/run.py``           — the OpenGirGit server pointing at the mock,
then drives ``client/opengirgit/api.py`` exactly like the GUI does:
OTP sign-in → chat SSE → vision SSE → resume parse → STT token refusal.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for(url: str, *, timeout: float = 30.0, process: subprocess.Popen | None = None) -> None:
    import httpx

    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        if process is not None and process.poll() is not None:
            raise RuntimeError(f"process exited early with code {process.returncode}")
        try:
            response = httpx.get(url, timeout=2.0)
            if response.status_code < 500:
                return
        except Exception as exc:  # noqa: BLE001 - retry until the deadline
            last_error = exc
        time.sleep(0.25)
    raise RuntimeError(f"{url} did not become ready: {last_error}")


def main() -> int:
    sys.path.insert(0, str(ROOT / "client"))
    from opengirgit.api import ApiClient, ApiError  # noqa: PLC0415

    mock_port = free_port()
    server_port = free_port()
    data_dir = Path(tempfile.mkdtemp(prefix="opengirgit-e2e-"))

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    mock = subprocess.Popen(
        [sys.executable, str(ROOT / "tests/e2e/mock_llm.py"), "--port", str(mock_port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )

    server_env = env.copy()
    server_env.update(
        {
            "HOST": "127.0.0.1",
            "PORT": str(server_port),
            "DATA_DIR": str(data_dir),
            "LLM_BASE_URL": f"http://127.0.0.1:{mock_port}/v1",
            "LLM_API_KEY": "mock",
            "JWT_SECRET": "e2e-secret-e2e-secret-e2e-secret",
        }
    )
    server = subprocess.Popen(
        [sys.executable, "run.py"],
        cwd=ROOT / "server",
        env=server_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )

    try:
        base = f"http://127.0.0.1:{server_port}"
        wait_for(f"http://127.0.0.1:{mock_port}/healthz", process=mock)
        wait_for(f"{base}/api/health", process=server)
        print(f"mock llm on :{mock_port}, server on :{server_port}")

        client = ApiClient(base)
        sent = client.send_otp("e2e@example.com")
        code = sent.get("otp_code")
        assert code, f"expected a dev-mode OTP, got {sent}"

        verified = client.verify_otp("e2e@example.com", code)
        client.token = verified["access_token"]
        assert client.me()["email"] == "e2e@example.com"
        print("auth ok")

        seen: list[str] = []
        answer = client.chat_stream(
            "Explain goroutines",
            conversation_history=[{"role": "user", "content": "hi"}],
            context="=== CANDIDATE RESUME ===\nAda",
            on_chunk=seen.append,
        )
        assert seen, "no chunks received"
        assert answer == "".join(seen)
        assert "Explain goroutines" in answer
        print("chat streaming ok:", answer)

        vision = client.vision_stream("Solve the screenshot", ["aGVsbG8="], on_chunk=lambda _c: None)
        assert "Solve the screenshot" in vision
        print("vision streaming ok:", vision)

        parsed = client.parse_resume("Ada Lovelace — mathematician, python.")
        assert parsed["name"] == "Ada Lovelace"
        assert "python" in parsed["skills"]
        print("resume parsing ok")

        try:
            client.get_stt_token()
        except ApiError as exc:
            assert exc.status_code == 501, exc
            print("stt token refused without Deepgram key (expected)")
        else:
            raise AssertionError("expected 501 from /api/stt/token")

        try:
            ApiClient(base, token="garbage").me()
        except ApiError as exc:
            assert exc.status_code == 401, exc
        else:
            raise AssertionError("expected 401 for a bad token")
        print("auth failure paths ok")

        print("E2E PASSED")
        return 0
    finally:
        for process in (server, mock):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover
                process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
