"""Run the OpenGirGit API server: ``python run.py`` (inside server/)."""

from __future__ import annotations

import uvicorn
from app.config import get_settings


def main() -> None:
    settings = get_settings()
    print(f"OpenGirGit API {settings.app_version} → http://{settings.host}:{settings.port}")
    if not settings.smtp_configured and settings.allow_dev_otp_echo:
        print("[dev] SMTP is not configured: login codes are printed here and echoed by the API.")
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    main()
