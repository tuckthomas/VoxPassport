"""Reusable lifecycle definitions for local/remote TTS backend server families."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


class BackendRuntimeError(ValueError):
    """Raised when a backend runtime definition or model argument set is invalid."""


@dataclass(frozen=True)
class BackendRuntime:
    path: Path
    raw: dict[str, Any]

    @property
    def schema_version(self) -> int:
        return int(self.raw["schema_version"])

    @property
    def backend_runtime_id(self) -> str:
        return str(self.raw["backend_runtime_id"])

    @property
    def runtime_profile(self) -> str:
        return str(self.raw["runtime_profile"])

    @property
    def command(self) -> tuple[str, ...]:
        value = self.raw.get("launch", {}).get("command", [])
        return tuple(str(item) for item in value) if isinstance(value, list) else ()

    @property
    def command_env(self) -> str:
        return str(self.raw.get("launch", {}).get("command_env", "")).strip()

    @property
    def environment(self) -> dict[str, str]:
        value = self.raw.get("launch", {}).get("environment", {})
        return {str(k): str(v) for k, v in value.items()} if isinstance(value, dict) else {}

    @property
    def remote_url_env(self) -> str:
        return str(self.raw.get("remote_url_env", "")).strip()

    @property
    def health_path(self) -> str:
        value = str(self.raw.get("health_path", "/v1/models")).strip()
        return value if value.startswith("/") else "/" + value

    @property
    def startup_timeout_seconds(self) -> float:
        return float(self.raw.get("startup_timeout_seconds", 90.0))

    @property
    def endpoint_driver_option(self) -> str:
        return str(self.raw.get("endpoint_driver_option", "backend_url")).strip() or "backend_url"

    @property
    def argument_contract(self) -> dict[str, dict[str, Any]]:
        value = self.raw.get("arguments", {})
        return {str(k): dict(v) for k, v in value.items()} if isinstance(value, dict) else {}

    def resolve_args(self, provided: Optional[dict[str, Any]]) -> dict[str, Any]:
        supplied = dict(provided or {})
        contract = self.argument_contract
        unknown = sorted(set(supplied) - set(contract))
        if unknown:
            raise BackendRuntimeError(
                f"Backend runtime {self.backend_runtime_id!r} received unknown backend_args: {', '.join(unknown)}"
            )
        resolved: dict[str, Any] = {}
        for name, spec in contract.items():
            if name in supplied:
                resolved[name] = supplied[name]
            elif "default" in spec:
                resolved[name] = spec["default"]
            elif bool(spec.get("required", False)):
                raise BackendRuntimeError(
                    f"Backend runtime {self.backend_runtime_id!r} requires backend_args.{name}"
                )
        return resolved

    @classmethod
    def load(cls, path: Path | str) -> "BackendRuntime":
        runtime_path = Path(path)
        try:
            raw = json.loads(runtime_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise BackendRuntimeError(f"Could not read backend runtime {runtime_path}: {exc}") from exc
        validate_backend_runtime(raw, runtime_path)
        return cls(path=runtime_path, raw=raw)


def _require(mapping: dict[str, Any], key: str, *, where: str) -> Any:
    if key not in mapping:
        raise BackendRuntimeError(f"Missing required {where}.{key}")
    return mapping[key]


def validate_backend_runtime(raw: dict[str, Any], path: Path | str = "<memory>") -> None:
    if not isinstance(raw, dict):
        raise BackendRuntimeError(f"Backend runtime {path} must contain a JSON object")
    if int(_require(raw, "schema_version", where="backend_runtime")) != 1:
        raise BackendRuntimeError(f"Unsupported backend runtime schema in {path}; expected schema_version=1")
    runtime_id = str(_require(raw, "backend_runtime_id", where="backend_runtime")).strip()
    runtime_profile = str(_require(raw, "runtime_profile", where="backend_runtime")).strip()
    if not runtime_id or not runtime_profile:
        raise BackendRuntimeError(
            f"Backend runtime {path} requires non-empty backend_runtime_id and runtime_profile"
        )
    launch = raw.get("launch", {})
    if not isinstance(launch, dict):
        raise BackendRuntimeError(f"backend_runtime.launch in {path} must be an object")
    command = launch.get("command")
    if command is not None and (
        not isinstance(command, list)
        or not command
        or not all(isinstance(item, str) and item for item in command)
    ):
        raise BackendRuntimeError(f"backend_runtime.launch.command in {path} must be a non-empty string list")
    command_env = str(launch.get("command_env", "")).strip()
    remote_url_env = str(raw.get("remote_url_env", "")).strip()
    if command is None and not command_env and not remote_url_env:
        raise BackendRuntimeError(
            f"Backend runtime {path} must provide launch.command, launch.command_env, or remote_url_env"
        )
    arguments = raw.get("arguments", {})
    if not isinstance(arguments, dict):
        raise BackendRuntimeError(f"backend_runtime.arguments in {path} must be an object")
    for name, spec in arguments.items():
        if not str(name).strip() or not isinstance(spec, dict):
            raise BackendRuntimeError(f"Invalid backend runtime argument contract in {path}: {name!r}")
        if "required" in spec and not isinstance(spec["required"], bool):
            raise BackendRuntimeError(f"arguments.{name}.required in {path} must be boolean")
    health_path = str(raw.get("health_path", "/v1/models")).strip()
    if not health_path:
        raise BackendRuntimeError(f"backend_runtime.health_path in {path} must not be empty")
    if float(raw.get("startup_timeout_seconds", 90.0)) <= 0:
        raise BackendRuntimeError(f"backend_runtime.startup_timeout_seconds in {path} must be positive")


class BackendRuntimeCatalog:
    """Loads reusable backend server family definitions by stable runtime ID."""

    def __init__(self, runtime_dir: Path | str | None = None) -> None:
        if runtime_dir is None:
            project_root = Path(__file__).resolve().parents[3]
            runtime_dir = project_root / "runtime" / "tts_backend_runtimes"
        self.runtime_dir = Path(runtime_dir)
        self._by_id: dict[str, BackendRuntime] = {}

    def load(self) -> "BackendRuntimeCatalog":
        self._by_id.clear()
        if not self.runtime_dir.exists():
            return self
        for path in sorted(self.runtime_dir.glob("*.json")):
            runtime = BackendRuntime.load(path)
            key = runtime.backend_runtime_id.lower()
            if key in self._by_id:
                raise BackendRuntimeError(
                    f"Duplicate backend_runtime_id: {runtime.backend_runtime_id}"
                )
            self._by_id[key] = runtime
        return self

    def runtimes(self) -> Iterable[BackendRuntime]:
        return tuple(self._by_id.values())

    def resolve(self, backend_runtime_id: str) -> BackendRuntime:
        key = str(backend_runtime_id or "").strip().lower()
        runtime = self._by_id.get(key)
        if runtime is None:
            raise KeyError(f"No TTS backend runtime registered for {backend_runtime_id!r}")
        return runtime

    def resolve_optional(self, backend_runtime_id: str | None) -> Optional[BackendRuntime]:
        if not backend_runtime_id:
            return None
        try:
            return self.resolve(str(backend_runtime_id))
        except KeyError:
            return None
