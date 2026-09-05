"""OTP delivery: SMTP when configured, console + API echo in dev mode."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from .config import Settings


def send_otp_email(settings: Settings, email: str, code: str) -> bool:
    """Send the OTP by email. Returns True when accepted by the SMTP server."""
    if not settings.smtp_configured:
        return False

    message = EmailMessage()
    message["Subject"] = "Your OpenGirGit sign-in code"
    message["From"] = settings.smtp_from
    message["To"] = email
    message.set_content(
        f"Your sign-in code is: {code}\n\n"
        f"It expires in {settings.otp_ttl_seconds // 60} minutes.\n"
        "If you did not request this, you can ignore this email.\n"
    )

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            smtp.ehlo()
            if settings.smtp_starttls:
                smtp.starttls()
                smtp.ehlo()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)
        return True
    except (OSError, smtplib.SMTPException) as exc:
        print(f"[mailer] SMTP delivery failed for {email}: {exc}")
        return False
