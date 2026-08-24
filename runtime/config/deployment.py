"""Deployment-level product configuration.

Environment variables override JSON so packaged/local deployments can use a
static config file while containers/cloud deployments can inject settings.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "configs" / "deployment.json"


def _bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    raise ValueError(f"invalid boolean value {value!r}")


@dataclass(frozen=True, slots=True)
class DeploymentConfig:
    local_only: bool = False
    accounts_enabled: bool = True
    account_api_url: str = "http://127.0.0.1:8780"
    abuse_controls_enabled: bool = True

    @classmethod
    def load(cls) -> "DeploymentConfig":
        path = Path(os.getenv("VOXPASSPORT_DEPLOYMENT_CONFIG", str(DEFAULT_CONFIG_PATH))).expanduser()
        data: dict[str, Any] = {}
        if path.is_file():
            parsed = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(parsed, dict):
                raise ValueError("deployment config must be a JSON object")
            data = parsed

        local_cfg = data.get("local") if isinstance(data.get("local"), dict) else {}
        accounts_cfg = data.get("accounts") if isinstance(data.get("accounts"), dict) else {}
        security_cfg = data.get("security") if isinstance(data.get("security"), dict) else {}

        local_only = _bool(
            os.getenv("VOXPASSPORT_LOCAL_ONLY", local_cfg.get("only")),
            False,
        )
        accounts_enabled = _bool(
            os.getenv("VOXPASSPORT_AUTH_ENABLED", accounts_cfg.get("enabled")),
            True,
        )
        abuse_controls = _bool(
            os.getenv("VOXPASSPORT_ABUSE_CONTROLS_ENABLED", security_cfg.get("abuse_controls_enabled")),
            True,
        )
        account_api_url = str(
            os.getenv(
                "VOXPASSPORT_ACCOUNT_API_URL",
                accounts_cfg.get("api_url", "http://127.0.0.1:8780"),
            )
        ).strip().rstrip("/")

        # Single-user local deployments must not accidentally require or expose
        # the multi-user account surface.
        if local_only:
            accounts_enabled = False
            abuse_controls = False

        return cls(
            local_only=local_only,
            accounts_enabled=accounts_enabled,
            account_api_url=account_api_url,
            abuse_controls_enabled=abuse_controls,
        )

    def client_payload(self) -> dict[str, Any]:
        return {
            "local_only": self.local_only,
            "accounts": {
                "enabled": self.accounts_enabled,
                "api_url": self.account_api_url if self.accounts_enabled else None,
            },
            "security": {
                "abuse_controls_enabled": self.abuse_controls_enabled,
            },
        }
