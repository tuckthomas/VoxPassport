from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VOXPASSPORT_ACCOUNTS_",
        case_sensitive=False,
        extra="ignore",
    )

    environment: str = "development"
    local_only: bool = False
    auth_enabled: bool = True
    abuse_controls_enabled: bool = True
    database_url: str = "postgresql+psycopg://voxpassport:voxpassport-dev@127.0.0.1:5432/voxpassport"
    jwt_secret: str = "dev-only-change-me-before-production"
    jwt_issuer: str = "voxpassport-accounts"
    jwt_audience: str = "voxpassport-client"
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    credential_master_secret: str = "dev-only-provider-credential-master-secret-change-me"
    allowed_origins: str = "http://localhost:8081,http://127.0.0.1:8081,http://localhost:19006,http://127.0.0.1:19006"
    cookie_secure: bool = False

    require_email_verification: bool = False
    email_verification_token_hours: int = 24
    password_reset_token_minutes: int = 30
    client_public_url: str = "http://127.0.0.1:8081"
    mail_backend: str = "console"  # console | smtp
    mail_from: str = "VoxPassport <no-reply@voxpassport.local>"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True

    login_attempts_per_5_minutes: int = 20
    signup_attempts_per_10_minutes: int = 8
    refresh_attempts_per_minute: int = 90
    authenticated_requests_per_minute: int = 240

    @field_validator("environment", "mail_backend")
    @classmethod
    def normalize_identifier(cls, value: str) -> str:
        return value.strip().lower()

    @property
    def allowed_origin_list(self) -> list[str]:
        return [item.strip().rstrip("/") for item in self.allowed_origins.split(",") if item.strip()]

    @model_validator(mode="after")
    def validate_deployment(self) -> "Settings":
        if self.local_only:
            self.auth_enabled = False
            self.abuse_controls_enabled = False

        for name in (
            "login_attempts_per_5_minutes",
            "signup_attempts_per_10_minutes",
            "refresh_attempts_per_minute",
            "authenticated_requests_per_minute",
            "email_verification_token_hours",
            "password_reset_token_minutes",
            "smtp_port",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")

        if self.mail_backend not in {"console", "smtp"}:
            raise ValueError("mail_backend must be 'console' or 'smtp'")
        if self.mail_backend == "smtp" and not self.smtp_host:
            raise ValueError("smtp_host is required when mail_backend='smtp'")

        if self.environment in {"production", "prod"} and self.auth_enabled:
            if self.jwt_secret.startswith("dev-only-"):
                raise ValueError("VOXPASSPORT_ACCOUNTS_JWT_SECRET must be configured for production")
            if self.credential_master_secret.startswith("dev-only-"):
                raise ValueError(
                    "VOXPASSPORT_ACCOUNTS_CREDENTIAL_MASTER_SECRET must be configured for production"
                )
            if not self.cookie_secure:
                raise ValueError("VOXPASSPORT_ACCOUNTS_COOKIE_SECURE must be true in production")
            if self.require_email_verification and self.mail_backend == "console":
                raise ValueError("production email verification requires an SMTP mail backend")
            if self.require_email_verification and not self.client_public_url.lower().startswith("https://"):
                raise ValueError("production email verification requires an HTTPS client_public_url")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
