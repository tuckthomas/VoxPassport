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
    login_attempts_per_5_minutes: int = 20
    signup_attempts_per_10_minutes: int = 8
    refresh_attempts_per_minute: int = 90
    authenticated_requests_per_minute: int = 240

    @field_validator("environment")
    @classmethod
    def normalize_environment(cls, value: str) -> str:
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
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")

        if self.environment in {"production", "prod"} and self.auth_enabled:
            if self.jwt_secret.startswith("dev-only-"):
                raise ValueError("VOXPASSPORT_ACCOUNTS_JWT_SECRET must be configured for production")
            if self.credential_master_secret.startswith("dev-only-"):
                raise ValueError(
                    "VOXPASSPORT_ACCOUNTS_CREDENTIAL_MASTER_SECRET must be configured for production"
                )
            if not self.cookie_secure:
                raise ValueError("VOXPASSPORT_ACCOUNTS_COOKIE_SECURE must be true in production")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
