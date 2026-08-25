from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

from account_api.config import Settings, get_settings


class MailDeliveryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OutboundMail:
    to: str
    subject: str
    text: str


class Mailer:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def send(self, message: OutboundMail) -> None:
        backend = self.settings.mail_backend
        if backend == "console":
            print(
                f"[VoxPassport mail] to={message.to!r} subject={message.subject!r}\n{message.text}",
                flush=True,
            )
            return
        if backend == "smtp":
            self._send_smtp(message)
            return
        raise MailDeliveryError(f"unsupported mail backend {backend!r}")

    def _send_smtp(self, message: OutboundMail) -> None:
        config = self.settings
        if not config.smtp_host:
            raise MailDeliveryError("SMTP host is not configured")

        email = EmailMessage()
        email["From"] = config.mail_from
        email["To"] = message.to
        email["Subject"] = message.subject
        email.set_content(message.text)

        try:
            with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=15) as client:
                if config.smtp_starttls:
                    client.starttls()
                if config.smtp_username:
                    client.login(config.smtp_username, config.smtp_password)
                client.send_message(email)
        except Exception as exc:
            raise MailDeliveryError("SMTP delivery failed") from exc


def verification_message(*, email: str, raw_token: str, settings: Settings | None = None) -> OutboundMail:
    config = settings or get_settings()
    url = f"{config.client_public_url.rstrip('/')}/verify-email?token={raw_token}"
    return OutboundMail(
        to=email,
        subject="Verify your VoxPassport email",
        text=(
            "Verify your VoxPassport email address by opening this link:\n\n"
            f"{url}\n\n"
            f"This link expires in {config.email_verification_token_hours} hours. "
            "If you did not create this account, you can ignore this message."
        ),
    )


def password_reset_message(*, email: str, raw_token: str, settings: Settings | None = None) -> OutboundMail:
    config = settings or get_settings()
    url = f"{config.client_public_url.rstrip('/')}/reset-password?token={raw_token}"
    return OutboundMail(
        to=email,
        subject="Reset your VoxPassport password",
        text=(
            "A password reset was requested for your VoxPassport account. Open this link to continue:\n\n"
            f"{url}\n\n"
            f"This link expires in {config.password_reset_token_minutes} minutes. "
            "If you did not request this reset, you can ignore this message."
        ),
    )
