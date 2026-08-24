from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import jwt
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from account_api.config import Settings, get_settings
from account_api.database import get_db
from account_api.models import ProviderCredential, RefreshSession, User
from account_api.rate_limit import install_account_guard_middleware
from account_api.schemas import (
    AuthResponse,
    ChangePasswordRequest,
    LoginRequest,
    LogoutRequest,
    ProviderCredentialSummary,
    ProviderCredentialUpsert,
    RefreshRequest,
    SignupRequest,
    UserResponse,
)
from account_api.security import (
    burn_password_check,
    create_access_token,
    decode_access_token,
    encrypt_provider_secret,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    normalize_email,
    refresh_expiry,
    utcnow,
    verify_password,
)


REFRESH_COOKIE = "vp_refresh"
_PROVIDER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,78}[a-z0-9]$|^[a-z0-9]$")
bearer = HTTPBearer(auto_error=False)
settings = get_settings()

app = FastAPI(title="VoxPassport Accounts", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-VoxPassport-Client-Kind", "X-VoxPassport-Client-Label"],
)
install_account_guard_middleware(app, settings)


@dataclass(frozen=True)
class AuthContext:
    user: User
    session: RefreshSession


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or expired credentials")


def _client_kind(request: Request) -> str:
    value = request.headers.get("X-VoxPassport-Client-Kind", "web").strip().lower()
    return value if value in {"web", "native"} else "web"


def _client_label(request: Request) -> str | None:
    value = request.headers.get("X-VoxPassport-Client-Label", "").strip()
    return value[:160] or None


def _set_refresh_cookie(response: Response, token: str, config: Settings = settings) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=config.refresh_token_days * 24 * 60 * 60,
        httponly=True,
        secure=config.cookie_secure,
        samesite="lax",
        path="/v1/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path="/v1/auth")


def _create_session(db: Session, user: User, request: Request) -> tuple[RefreshSession, str]:
    raw = new_refresh_token()
    session = RefreshSession(
        user_id=user.id,
        token_hash=hash_refresh_token(raw),
        client_kind=_client_kind(request),
        client_label=_client_label(request),
        expires_at=refresh_expiry(settings),
    )
    db.add(session)
    db.flush()
    return session, raw


def _auth_payload(user: User, session: RefreshSession, raw_refresh: str, request: Request) -> AuthResponse:
    return AuthResponse(
        access_token=create_access_token(user_id=user.id, session_id=session.id, settings=settings),
        expires_in_seconds=settings.access_token_minutes * 60,
        refresh_token=raw_refresh if _client_kind(request) == "native" else None,
        user=UserResponse.model_validate(user),
    )


def _finish_auth_response(
    response: Response,
    user: User,
    session: RefreshSession,
    raw_refresh: str,
    request: Request,
) -> AuthResponse:
    if _client_kind(request) == "web":
        _set_refresh_cookie(response, raw_refresh)
    return _auth_payload(user, session, raw_refresh, request)


def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> AuthContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()
    try:
        claims = decode_access_token(credentials.credentials, settings)
        user_id = uuid.UUID(str(claims["sub"]))
        session_id = uuid.UUID(str(claims["sid"]))
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise _unauthorized()

    session = db.get(RefreshSession, session_id)
    now = utcnow()
    if (
        session is None
        or session.user_id != user_id
        or session.revoked_at is not None
        or session.expires_at <= now
    ):
        raise _unauthorized()
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _unauthorized()
    return AuthContext(user=user, session=session)


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, str | bool]:
    db.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "database": "postgresql",
        "accounts_enabled": settings.auth_enabled,
        "abuse_controls_enabled": settings.abuse_controls_enabled,
    }


@app.get("/v1/config")
def public_config() -> dict[str, bool]:
    return {
        "accounts_enabled": settings.auth_enabled,
        "local_only": settings.local_only,
        "abuse_controls_enabled": settings.abuse_controls_enabled,
    }


@app.post("/v1/auth/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> AuthResponse:
    email = normalize_email(str(payload.email))
    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name.strip() if payload.display_name else None,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="an account already exists for this email")

    session, raw_refresh = _create_session(db, user, request)
    user.last_login_at = utcnow()
    db.commit()
    db.refresh(user)
    return _finish_auth_response(response, user, session, raw_refresh, request)


@app.post("/v1/auth/login", response_model=AuthResponse)
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> AuthResponse:
    email = normalize_email(str(payload.email))
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        burn_password_check(payload.password)
        raise _unauthorized()
    valid, replacement = verify_password(payload.password, user.password_hash)
    if not valid or not user.is_active:
        raise _unauthorized()
    if replacement:
        user.password_hash = replacement

    session, raw_refresh = _create_session(db, user, request)
    user.last_login_at = utcnow()
    db.commit()
    db.refresh(user)
    return _finish_auth_response(response, user, session, raw_refresh, request)


def _refresh_token_from_request(payload: RefreshRequest | LogoutRequest | None, request: Request) -> str | None:
    if payload is not None and payload.refresh_token:
        return payload.refresh_token
    return request.cookies.get(REFRESH_COOKIE)


@app.post("/v1/auth/refresh", response_model=AuthResponse)
def refresh(
    request: Request,
    response: Response,
    payload: RefreshRequest | None = None,
    db: Session = Depends(get_db),
) -> AuthResponse:
    raw = _refresh_token_from_request(payload, request)
    if not raw:
        raise _unauthorized()
    existing = db.scalar(select(RefreshSession).where(RefreshSession.token_hash == hash_refresh_token(raw)))
    now = utcnow()
    if existing is None or existing.expires_at <= now:
        raise _unauthorized()
    if existing.revoked_at is not None:
        db.execute(
            update(RefreshSession)
            .where(RefreshSession.user_id == existing.user_id, RefreshSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        db.commit()
        raise _unauthorized()
    user = db.get(User, existing.user_id)
    if user is None or not user.is_active:
        raise _unauthorized()

    replacement, raw_replacement = _create_session(db, user, request)
    existing.revoked_at = now
    existing.last_used_at = now
    existing.replaced_by_session_id = replacement.id
    db.commit()
    return _finish_auth_response(response, user, replacement, raw_replacement, request)


@app.post("/v1/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    payload: LogoutRequest | None = None,
    db: Session = Depends(get_db),
) -> Response:
    raw = _refresh_token_from_request(payload, request)
    if raw:
        session = db.scalar(select(RefreshSession).where(RefreshSession.token_hash == hash_refresh_token(raw)))
        if session is not None and session.revoked_at is None:
            session.revoked_at = utcnow()
            db.commit()
    _clear_refresh_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@app.post("/v1/auth/logout-all", status_code=status.HTTP_204_NO_CONTENT)
def logout_all(
    response: Response,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> Response:
    db.execute(
        update(RefreshSession)
        .where(RefreshSession.user_id == auth.user.id, RefreshSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    db.commit()
    _clear_refresh_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@app.get("/v1/auth/me", response_model=UserResponse)
def me(auth: AuthContext = Depends(require_auth)) -> UserResponse:
    return UserResponse.model_validate(auth.user)


@app.post("/v1/auth/change-password", response_model=AuthResponse)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    response: Response,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> AuthResponse:
    valid, _ = verify_password(payload.current_password, auth.user.password_hash)
    if not valid:
        raise _unauthorized()
    auth.user.password_hash = hash_password(payload.new_password)
    now = utcnow()
    db.execute(
        update(RefreshSession)
        .where(RefreshSession.user_id == auth.user.id, RefreshSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    replacement, raw_refresh = _create_session(db, auth.user, request)
    db.commit()
    return _finish_auth_response(response, auth.user, replacement, raw_refresh, request)


def _normalize_provider(provider: str) -> str:
    normalized = provider.strip().casefold()
    if not _PROVIDER_RE.fullmatch(normalized):
        raise HTTPException(status_code=400, detail="invalid provider identifier")
    return normalized


@app.get("/v1/provider-credentials", response_model=list[ProviderCredentialSummary])
def list_provider_credentials(
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> list[ProviderCredentialSummary]:
    rows = db.scalars(
        select(ProviderCredential)
        .where(ProviderCredential.user_id == auth.user.id)
        .order_by(ProviderCredential.provider, ProviderCredential.label)
    ).all()
    return [ProviderCredentialSummary.model_validate(row) for row in rows]


@app.put("/v1/provider-credentials/{provider}", response_model=ProviderCredentialSummary)
def put_provider_credential(
    provider: str,
    payload: ProviderCredentialUpsert,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> ProviderCredentialSummary:
    provider_id = _normalize_provider(provider)
    existing = db.scalar(
        select(ProviderCredential).where(
            ProviderCredential.user_id == auth.user.id,
            ProviderCredential.provider == provider_id,
            ProviderCredential.label == payload.label,
        )
    )
    ciphertext, nonce = encrypt_provider_secret(
        payload.secret,
        user_id=auth.user.id,
        provider=provider_id,
        label=payload.label,
        settings=settings,
    )
    if existing is None:
        existing = ProviderCredential(
            user_id=auth.user.id,
            provider=provider_id,
            label=payload.label,
            secret_ciphertext=ciphertext,
            secret_nonce=nonce,
            key_version=1,
        )
        db.add(existing)
    else:
        existing.secret_ciphertext = ciphertext
        existing.secret_nonce = nonce
        existing.key_version = 1
        existing.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(existing)
    return ProviderCredentialSummary.model_validate(existing)


@app.delete("/v1/provider-credentials/{provider}", status_code=status.HTTP_204_NO_CONTENT)
def delete_provider_credential(
    provider: str,
    response: Response,
    label: str = "default",
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> Response:
    provider_id = _normalize_provider(provider)
    normalized_label = label.strip().casefold()
    existing = db.scalar(
        select(ProviderCredential).where(
            ProviderCredential.user_id == auth.user.id,
            ProviderCredential.provider == provider_id,
            ProviderCredential.label == normalized_label,
        )
    )
    if existing is not None:
        db.delete(existing)
        db.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
