"""Runtime-profile metadata for supervised local TTS workers."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


class RuntimeProfileError(ValueError):
    """Raised when a runtime-profile definition is missing or invalid."""


@dataclass(frozen=True)
class RuntimeProfile:
    profile_id: str
    interpreter: str
    interpreter_env: str
    startup_timeout_seconds: float
    idle_timeout_seconds: float
    environment: dict[str, str]
    provisioning: dict[str, Any]

    def resolve_interpreter(self, project_root: Path) -> Path:
        override = os.getenv(self.interpreter_env, "").strip() if self.interpreter_env else ""
        raw = override or self.interpreter
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = project_root / candidate
        return candidate.resolve()

    def resolved_environment(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for key, value in self.environment.items():
            values[str(key)] = os.path.expandvars(str(value))
        return values


class RuntimeProfileCatalog:
    """Load dependency-compatible worker runtime families from one config file."""

    def __init__(self, path: Path | str | None = None) -> None:
        if path is None:
            project_root = Path(__file__).resolve().parents[3]
            path = project_root / "runtime" / "profiles" / "runtime_profiles.json"
        self.path = Path(path)
        self._profiles: dict[str, RuntimeProfile] = {}

    def load(self) -> "RuntimeProfileCatalog":
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeProfileError(f"Could not read runtime profiles from {self.path}: {exc}") from exc
        if int(raw.get("schema_version", 0)) != 1:
            raise RuntimeProfileError("runtime_profiles.json must use schema_version=1")
        profiles = raw.get("profiles")
        if not isinstance(profiles, dict) or not profiles:
            raise RuntimeProfileError("runtime_profiles.json requires a non-empty profiles object")

        resolved: dict[str, RuntimeProfile] = {}
        for profile_id, payload in profiles.items():
            if not isinstance(payload, dict):
                raise RuntimeProfileError(f"Runtime profile {profile_id!r} must be an object")
            clean_id = str(profile_id).strip()
            interpreter = str(payload.get("interpreter", "")).strip()
            if not clean_id or not interpreter:
                raise RuntimeProfileError(f"Runtime profile {profile_id!r} requires an interpreter")
            startup_timeout = float(payload.get("startup_timeout_seconds", 30.0))
            idle_timeout = float(payload.get("idle_timeout_seconds", 60.0))
            if startup_timeout <= 0 or idle_timeout < 0:
                raise RuntimeProfileError(f"Runtime profile {profile_id!r} has invalid timeout values")
            environment = payload.get("environment") or {}
            provisioning = payload.get("provisioning") or {}
            if not isinstance(environment, dict) or not isinstance(provisioning, dict):
                raise RuntimeProfileError(f"Runtime profile {profile_id!r} has invalid environment/provisioning metadata")
            resolved[clean_id] = RuntimeProfile(
                profile_id=clean_id,
                interpreter=interpreter,
                interpreter_env=str(payload.get("interpreter_env", "")).strip(),
                startup_timeout_seconds=startup_timeout,
                idle_timeout_seconds=idle_timeout,
                environment={str(k): str(v) for k, v in environment.items()},
                provisioning=dict(provisioning),
            )
        self._profiles = resolved
        return self

    def resolve(self, profile_id: str) -> RuntimeProfile:
        key = str(profile_id or "").strip()
        profile = self._profiles.get(key)
        if profile is None:
            raise KeyError(f"Unknown TTS runtime profile: {profile_id!r}")
        return profile

    def profiles(self) -> Iterable[RuntimeProfile]:
        return tuple(self._profiles.values())
