from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from account_api.database import SessionLocal
from account_api.main import app
from account_api.models import ProviderCredential, RefreshSession, User


client = TestClient(app)
NATIVE_HEADERS = {
    "X-VoxPassport-Client-Kind": "native",
    "X-VoxPassport-Client-Label": "CI test client",
}


def setup_function() -> None:
    with SessionLocal() as db:
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
