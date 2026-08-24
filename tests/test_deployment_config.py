import json

from runtime.config.deployment import DeploymentConfig


def test_local_only_json_disables_accounts_and_abuse_controls(tmp_path, monkeypatch):
    path = tmp_path / "deployment.json"
    path.write_text(json.dumps({
        "local": {"only": True},
        "accounts": {"enabled": True, "api_url": "https://accounts.example"},
        "security": {"abuse_controls_enabled": True},
    }), encoding="utf-8")
    monkeypatch.setenv("VOXPASSPORT_DEPLOYMENT_CONFIG", str(path))
    monkeypatch.delenv("VOXPASSPORT_LOCAL_ONLY", raising=False)
    monkeypatch.delenv("VOXPASSPORT_AUTH_ENABLED", raising=False)
    monkeypatch.delenv("VOXPASSPORT_ABUSE_CONTROLS_ENABLED", raising=False)

    config = DeploymentConfig.load()
    assert config.local_only is True
    assert config.accounts_enabled is False
    assert config.abuse_controls_enabled is False
    assert config.client_payload()["accounts"]["api_url"] is None


def test_environment_overrides_json(tmp_path, monkeypatch):
    path = tmp_path / "deployment.json"
    path.write_text(json.dumps({
        "local": {"only": True},
        "accounts": {"enabled": False},
        "security": {"abuse_controls_enabled": False},
    }), encoding="utf-8")
    monkeypatch.setenv("VOXPASSPORT_DEPLOYMENT_CONFIG", str(path))
    monkeypatch.setenv("VOXPASSPORT_LOCAL_ONLY", "false")
    monkeypatch.setenv("VOXPASSPORT_AUTH_ENABLED", "true")
    monkeypatch.setenv("VOXPASSPORT_ABUSE_CONTROLS_ENABLED", "true")
    monkeypatch.setenv("VOXPASSPORT_ACCOUNT_API_URL", "https://accounts.override.example/")

    config = DeploymentConfig.load()
    assert config.local_only is False
    assert config.accounts_enabled is True
    assert config.abuse_controls_enabled is True
    assert config.account_api_url == "https://accounts.override.example"


def test_local_only_env_wins_over_independent_auth_flags(tmp_path, monkeypatch):
    monkeypatch.setenv("VOXPASSPORT_DEPLOYMENT_CONFIG", str(tmp_path / "missing.json"))
    monkeypatch.setenv("VOXPASSPORT_LOCAL_ONLY", "true")
    monkeypatch.setenv("VOXPASSPORT_AUTH_ENABLED", "true")
    monkeypatch.setenv("VOXPASSPORT_ABUSE_CONTROLS_ENABLED", "true")

    config = DeploymentConfig.load()
    assert config.local_only
    assert not config.accounts_enabled
    assert not config.abuse_controls_enabled
