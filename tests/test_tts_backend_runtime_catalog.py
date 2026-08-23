from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.inference.tts_plugins.backend_runtime import (
    BackendRuntimeCatalog,
    BackendRuntimeError,
)


def _payload(runtime_id: str = "fake-server") -> dict:
    return {
        "schema_version": 1,
        "backend_runtime_id": runtime_id,
        "runtime_profile": "core",
        "launch": {
            "command": [
                "{python}",
                "server.py",
                "--host",
                "{host}",
                "--port",
                "{port}",
                "--model",
                "{checkpoint}",
            ]
        },
        "remote_url_env": "VOXPASSPORT_TEST_REMOTE_BACKEND",
        "health_path": "/v1/models",
        "startup_timeout_seconds": 10,
        "endpoint_driver_option": "backend_url",
        "arguments": {
            "checkpoint": {"required": True},
            "revision": {"default": "main"},
        },
    }


def _write(tmp_path: Path, payloads: list[dict]) -> BackendRuntimeCatalog:
    runtime_dir = tmp_path / "backend-runtimes"
    runtime_dir.mkdir()
    for index, payload in enumerate(payloads):
        (runtime_dir / f"runtime-{index}.json").write_text(json.dumps(payload), encoding="utf-8")
    return BackendRuntimeCatalog(runtime_dir).load()


def test_catalog_loads_runtime_and_resolves_declared_args(tmp_path: Path):
    catalog = _write(tmp_path, [_payload()])
    runtime = catalog.resolve("fake-server")
    assert runtime.runtime_profile == "core"
    assert runtime.health_path == "/v1/models"
    assert runtime.endpoint_driver_option == "backend_url"
    assert runtime.resolve_args({"checkpoint": "vendor/model"}) == {
        "checkpoint": "vendor/model",
        "revision": "main",
    }


def test_required_backend_arg_is_enforced(tmp_path: Path):
    runtime = _write(tmp_path, [_payload()]).resolve("fake-server")
    with pytest.raises(BackendRuntimeError, match="requires backend_args.checkpoint"):
        runtime.resolve_args({})


def test_unknown_backend_arg_is_rejected(tmp_path: Path):
    runtime = _write(tmp_path, [_payload()]).resolve("fake-server")
    with pytest.raises(BackendRuntimeError, match="unknown backend_args"):
        runtime.resolve_args({"checkpoint": "vendor/model", "invented": True})


def test_duplicate_backend_runtime_ids_are_rejected(tmp_path: Path):
    with pytest.raises(BackendRuntimeError, match="Duplicate backend_runtime_id"):
        _write(tmp_path, [_payload("same"), _payload("same")])


def test_backend_runtime_requires_a_launch_or_remote_strategy(tmp_path: Path):
    payload = _payload()
    payload["launch"] = {}
    payload["remote_url_env"] = ""
    runtime_dir = tmp_path / "backend-runtimes"
    runtime_dir.mkdir()
    path = runtime_dir / "bad.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BackendRuntimeError, match="launch.command"):
        BackendRuntimeCatalog(runtime_dir).load()
