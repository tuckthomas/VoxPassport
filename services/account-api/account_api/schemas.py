from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    display_name: str | None = Field(default=None, min_length=1, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str | None = Field(default=None, min_length=20, max_length=512)


class LogoutRequest(RefreshRequest):
    pass


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    display_name: str | None
    email_verified: bool
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_seconds: int
    refresh_token: str | None = None
    user: UserResponse


class ProviderCredentialUpsert(BaseModel):
    secret: str = Field(min_length=1, max_length=8192)
    label: str = Field(default="default", min_length=1, max_length=80)

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if not normalized or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-_." for ch in normalized):
            raise ValueError("label may contain only letters, numbers, hyphen, underscore and period")
        return normalized


class ProviderCredentialSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    label: str
    key_version: int
    created_at: datetime
    updated_at: datetime
