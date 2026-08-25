from __future__ import annotations

import re

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

import account_api.main as account_main
from account_api.database import SessionLocal
from account_api.main import app
from account_api.models import AccountActionToken, ProviderCredential, RefreshSession, User


client = TestClient(app)
NATIVE_HEADERS = {
    "X-VoxPassport-Client-Kind": "native",
    "X-VoxPassport-Client-Label": "CI test client",
}


def setup_function() -> None:
    with SessionLocal() as db:
        db.execute(delete(AccountActionToken))
        db.execute(delete(ProviderCredential))
        db.execute(delete(RefreshSession))
        db.execute(delete(User))
        db.commit()


def signup(email: str = "test@example.com", password: str = "correct horse battery staple") -> dict:
    response = client.post(
        "/v1/auth/signup",
        headers=NATIVE_HEADERS,
        json={"email": email, "password": password, "display_name": "Test User"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def auth_header(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def capture_mail_tokens(monkeypatch) -> list[str]:
    messages: list[str] = []
    monkeypatch.setattr(account_main.mailer, "send", lambda message: messages.append(message.text))
    return messages


def token_from_mail(text: str, route: str) -> str:
    match = re.search(rf"/{re.escape(route)}\?token=([^\s]+)", text)
    assert match, text
    return match.group(1)


def test_signup_login_me_and_duplicate_email() -> None:
    created = signup("Mixed.Case@Example.com")
    assert created["user"]["email"] == "mixed.case@example.com"
    assert created["refresh_token"]
    assert created["access_token"]

    me = client.get("/v1/auth/me", headers=auth_header(created["access_token"]))
    assert me.status_code == 200
    assert me.json()["display_name"] == "Test User"

    duplicate = client.post(
        "/v1/auth/signup",
        headers=NATIVE_HEADERS,
        json={
            "email": "MIXED.CASE@example.com",
            "password": "another long password value",
        },
    )
    assert duplicate.status_code == 409

    bad_login = client.post(
        "/v1/auth/login",
        headers=NATIVE_HEADERS,
        json={"email": "mixed.case@example.com", "password": "wrong-password"},
    )
    assert bad_login.status_code == 401

    login = client.post(
        "/v1/auth/login",
        headers=NATIVE_HEADERS,
        json={"email": "mixed.case@example.com", "password": "correct horse battery staple"},
    )
    assert login.status_code == 200
    assert login.json()["refresh_token"]


def test_refresh_rotates_and_replay_revokes_active_sessions() -> None:
    created = signup()
    first_refresh = created["refresh_token"]

    rotated = client.post(
        "/v1/auth/refresh",
        headers=NATIVE_HEADERS,
        json={"refresh_token": first_refresh},
    )
    assert rotated.status_code == 200, rotated.text
    second_refresh = rotated.json()["refresh_token"]
    assert second_refresh and second_refresh != first_refresh

    replay = client.post(
        "/v1/auth/refresh",
        headers=NATIVE_HEADERS,
        json={"refresh_token": first_refresh},
    )
    assert replay.status_code == 401

    after_replay = client.post(
        "/v1/auth/refresh",
        headers=NATIVE_HEADERS,
        json={"refresh_token": second_refresh},
    )
    assert after_replay.status_code == 401


def test_password_change_revokes_old_session_and_returns_new_session() -> None:
    created = signup()
    changed = client.post(
        "/v1/auth/change-password",
        headers={**NATIVE_HEADERS, **auth_header(created["access_token"])},
        json={
            "current_password": "correct horse battery staple",
            "new_password": "a new sufficiently long passphrase",
        },
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["refresh_token"]

    old_access = client.get("/v1/auth/me", headers=auth_header(created["access_token"]))
    assert old_access.status_code == 401

    old_password = client.post(
        "/v1/auth/login",
        headers=NATIVE_HEADERS,
        json={"email": "test@example.com", "password": "correct horse battery staple"},
    )
    assert old_password.status_code == 401

    new_password = client.post(
        "/v1/auth/login",
        headers=NATIVE_HEADERS,
        json={"email": "test@example.com", "password": "a new sufficiently long passphrase"},
    )
    assert new_password.status_code == 200


def test_provider_credentials_are_encrypted_and_never_returned() -> None:
    created = signup()
    headers = {**NATIVE_HEADERS, **auth_header(created["access_token"])}
    secret = "AIza-test-provider-key-that-must-not-be-stored-plainly"

    saved = client.put(
        "/v1/provider-credentials/google",
        headers=headers,
        json={"label": "default", "secret": secret},
    )
    assert saved.status_code == 200, saved.text
    assert "secret" not in saved.json()

    listed = client.get("/v1/provider-credentials", headers=headers)
    assert listed.status_code == 200
    assert listed.json()[0]["provider"] == "google"
    assert "secret" not in listed.text
    assert secret not in listed.text

    with SessionLocal() as db:
        row = db.scalar(select(ProviderCredential))
        assert row is not None
        assert secret.encode("utf-8") not in row.secret_ciphertext
        assert len(row.secret_nonce) == 12

    deleted = client.delete(
        "/v1/provider-credentials/google?label=default",
        headers=headers,
    )
    assert deleted.status_code == 204
    assert client.get("/v1/provider-credentials", headers=headers).json() == []


def test_email_verification_is_one_time_and_token_is_hashed(monkeypatch) -> None:
    messages = capture_mail_tokens(monkeypatch)
    created = signup("verify@example.com")
    assert created["user"]["email_verified"] is False
    assert messages
    raw = token_from_mail(messages[-1], "verify-email")

    with SessionLocal() as db:
        row = db.scalar(select(AccountActionToken).where(AccountActionToken.purpose == "email_verification"))
        assert row is not None
        assert raw != row.token_hash
        assert raw.encode("utf-8") not in row.token_hash.encode("utf-8")

    confirmed = client.post("/v1/auth/email-verification/confirm", json={"token": raw})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["email_verified"] is True

    replay = client.post("/v1/auth/email-verification/confirm", json={"token": raw})
    assert replay.status_code == 400


def test_verification_request_is_non_enumerating_and_replaces_old_token(monkeypatch) -> None:
    messages = capture_mail_tokens(monkeypatch)
    signup("verify-again@example.com")
    first = token_from_mail(messages[-1], "verify-email")

    unknown = client.post(
        "/v1/auth/email-verification/request",
        json={"email": "nobody@example.com"},
    )
    existing = client.post(
        "/v1/auth/email-verification/request",
        json={"email": "verify-again@example.com"},
    )
    assert unknown.status_code == existing.status_code == 202
    assert unknown.json() == existing.json() == {"accepted": True}
    second = token_from_mail(messages[-1], "verify-email")
    assert second != first

    old = client.post("/v1/auth/email-verification/confirm", json={"token": first})
    assert old.status_code == 400
    current = client.post("/v1/auth/email-verification/confirm", json={"token": second})
    assert current.status_code == 200


def test_password_reset_is_non_enumerating_one_time_and_revokes_sessions(monkeypatch) -> None:
    messages = capture_mail_tokens(monkeypatch)
    created = signup("reset@example.com")
    old_refresh = created["refresh_token"]

    unknown = client.post("/v1/auth/password-reset/request", json={"email": "nobody@example.com"})
    existing = client.post("/v1/auth/password-reset/request", json={"email": "reset@example.com"})
    assert unknown.status_code == existing.status_code == 202
    assert unknown.json() == existing.json() == {"accepted": True}
    raw = token_from_mail(messages[-1], "reset-password")

    reset = client.post(
        "/v1/auth/password-reset/confirm",
        json={"token": raw, "new_password": "replacement password is long enough"},
    )
    assert reset.status_code == 204, reset.text

    replay = client.post(
        "/v1/auth/password-reset/confirm",
        json={"token": raw, "new_password": "another replacement password"},
    )
    assert replay.status_code == 400

    old_session = client.post(
        "/v1/auth/refresh",
        headers=NATIVE_HEADERS,
        json={"refresh_token": old_refresh},
    )
    assert old_session.status_code == 401

    old_password = client.post(
        "/v1/auth/login",
        headers=NATIVE_HEADERS,
        json={"email": "reset@example.com", "password": "correct horse battery staple"},
    )
    assert old_password.status_code == 401
    new_password = client.post(
        "/v1/auth/login",
        headers=NATIVE_HEADERS,
        json={"email": "reset@example.com", "password": "replacement password is long enough"},
    )
    assert new_password.status_code == 200
