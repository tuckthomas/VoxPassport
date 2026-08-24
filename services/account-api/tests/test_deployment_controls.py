from fastapi import FastAPI
from fastapi.testclient import TestClient

from account_api.config import Settings
from account_api.rate_limit import install_account_guard_middleware


def make_app(settings: Settings) -> FastAPI:
    app = FastAPI()
    install_account_guard_middleware(app, settings)

    @app.post("/v1/auth/login")
    def login():
        return {"ok": True}

    @app.get("/v1/config")
    def config():
        return {
            "accounts_enabled": settings.auth_enabled,
            "local_only": settings.local_only,
            "abuse_controls_enabled": settings.abuse_controls_enabled,
        }

    return app


def test_local_only_forces_auth_and_abuse_controls_off():
    settings = Settings(
        environment="test",
        local_only=True,
        auth_enabled=True,
        abuse_controls_enabled=True,
    )
    assert settings.auth_enabled is False
    assert settings.abuse_controls_enabled is False

    client = TestClient(make_app(settings))
    assert client.post("/v1/auth/login").status_code == 404
    config = client.get("/v1/config")
    assert config.status_code == 200
    assert config.json() == {
        "accounts_enabled": False,
        "local_only": True,
        "abuse_controls_enabled": False,
    }


def test_non_local_login_rate_limit_returns_retry_after():
    settings = Settings(
        environment="test",
        local_only=False,
        auth_enabled=True,
        abuse_controls_enabled=True,
        login_attempts_per_5_minutes=2,
    )
    client = TestClient(make_app(settings))

    assert client.post("/v1/auth/login").status_code == 200
    assert client.post("/v1/auth/login").status_code == 200
    limited = client.post("/v1/auth/login")
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) >= 1


def test_abuse_controls_can_be_disabled_without_disabling_accounts():
    settings = Settings(
        environment="test",
        local_only=False,
        auth_enabled=True,
        abuse_controls_enabled=False,
        login_attempts_per_5_minutes=1,
    )
    client = TestClient(make_app(settings))
    for _ in range(4):
        assert client.post("/v1/auth/login").status_code == 200
