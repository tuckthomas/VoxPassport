from __future__ import annotations

import base64
import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from account_api.config import Settings, get_settings


_password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16)
_dummy_hash = _password_hasher.hash("voxpassport-dummy-password-for-timing-equalization")


def normalize_email(value: str) -> str:
    return value.strip().casefold()


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> tuple[bool, str | None]:
    try:
        valid = _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False, None
    replacement = _password_hasher.hash(password) if valid and _password_hasher.check_needs_rehash(password_hash) else None
    return bool(valid), replacement


def burn_password_check(password: str) -> None:
    try:
        _password_hasher.verify(_dummy_hash, password)
    except VerifyMismatchError:
        pass


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_action_token() -> str:
    return secrets.token_urlsafe(48)


def hash_action_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def utcnow() -> datetime:
    return datetime.now(UTC)


def refresh_expiry(settings: Settings | None = None) -> datetime:
    config = settings or get_settings()
    return utcnow() + timedelta(days=config.refresh_token_days)


def email_verification_expiry(settings: Settings | None = None) -> datetime:
    config = settings or get_settings()
    return utcnow() + timedelta(hours=config.email_verification_token_hours)


def password_reset_expiry(settings: Settings | None = None) -> datetime:
    config = settings or get_settings()
    return utcnow() + timedelta(minutes=config.password_reset_token_minutes)


def create_access_token(*, user_id: uuid.UUID, session_id: uuid.UUID, settings: Settings | None = None) -> str:
    config = settings or get_settings()
    now = utcnow()
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "sid": str(session_id),
        "typ": "access",
        "iss": config.jwt_issuer,
        "aud": config.jwt_audience,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=config.access_token_minutes)).timestamp()),
    }
    return jwt.encode(payload, config.jwt_secret, algorithm="HS256")


def decode_access_token(token: str, settings: Settings | None = None) -> dict[str, Any]:
    config = settings or get_settings()
    payload = jwt.decode(
        token,
        config.jwt_secret,
        algorithms=["HS256"],
        audience=config.jwt_audience,
        issuer=config.jwt_issuer,
        options={"require": ["exp", "iat", "nbf", "sub", "sid", "typ"]},
    )
    if payload.get("typ") != "access":
        raise jwt.InvalidTokenError("unexpected token type")
    return payload


def _credential_key(settings: Settings | None = None) -> bytes:
    config = settings or get_settings()
    return hashlib.sha256(config.credential_master_secret.encode("utf-8")).digest()


def credential_aad(*, user_id: uuid.UUID, provider: str, label: str) -> bytes:
    return f"voxpassport:v1:{user_id}:{provider.casefold()}:{label.casefold()}".encode("utf-8")


def encrypt_provider_secret(
    secret: str,
    *,
    user_id: uuid.UUID,
    provider: str,
    label: str,
    settings: Settings | None = None,
) -> tuple[bytes, bytes]:
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(_credential_key(settings)).encrypt(
        nonce,
        secret.encode("utf-8"),
        credential_aad(user_id=user_id, provider=provider, label=label),
    )
    return ciphertext, nonce


def decrypt_provider_secret(
    ciphertext: bytes,
    nonce: bytes,
    *,
    user_id: uuid.UUID,
    provider: str,
    label: str,
    settings: Settings | None = None,
) -> str:
    plaintext = AESGCM(_credential_key(settings)).decrypt(
        nonce,
        ciphertext,
        credential_aad(user_id=user_id, provider=provider, label=label),
    )
    return plaintext.decode("utf-8")


def secret_fingerprint(secret: str) -> str:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest[:9]).decode("ascii").rstrip("=")
