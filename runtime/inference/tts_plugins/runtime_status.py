"""Synchronous diagnostic view of the local TTS runtime supervisor."""

from __future__ import annotations

import json
import urllib.request
from typing import Any

from runtime.inference.tts_plugins import runtime_supervisor as supervisor_module


def _worker_health(endpoint: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(endpoint.rstrip("/") + "/health", timeout=0.25) as response:
            body = json.loads(response.read().decode("utf-8"))
        return {
            "reachable": True,
            "status": body.get("status"),
            "loaded_model_id": body.get("loaded_model_id"),
            "driver_healthy": body.get("driver_healthy"),
        }
    except Exception:
        return {
            "reachable": False,
            "status": "unreachable",
            "loaded_model_id": None,
            "driver_healthy": False,
        }


def _backend_health(endpoint: str, health_path: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(endpoint.rstrip("/") + health_path, timeout=0.25) as response:
            response.read(256)
            status_code = int(getattr(response, "status", 200))
        return {
            "reachable": 200 <= status_code < 400,
            "status_code": status_code,
        }
    except Exception:
        return {"reachable": False, "status_code": None}


def tts_runtime_status_snapshot() -> dict[str, Any]:
    """Return best-effort profile/process/backend state without creating workers."""
    supervisor = supervisor_module._DEFAULT_SUPERVISOR
    if supervisor is None:
        return {
            "available": True,
            "active_profile_id": None,
            "active_model_id": None,
            "profiles": [],
            "backends": [],
        }

    profiles = []
    for profile in supervisor.profile_catalog.profiles():
        handle = supervisor._workers.get(profile.profile_id)
        running = bool(handle is not None and handle.process.poll() is None)
        unexpected_exit = bool(handle is not None and not running)
        health = _worker_health(handle.endpoint) if running else {
            "reachable": False,
            "status": "exited" if unexpected_exit else "stopped",
            "loaded_model_id": None,
            "driver_healthy": False,
        }
        interpreter = profile.resolve_interpreter(supervisor.project_root)
        profiles.append({
            "profile_id": profile.profile_id,
            "installed": interpreter.exists(),
            "running": running,
            "unexpected_exit": unexpected_exit,
            "exit_code": handle.process.returncode if unexpected_exit else None,
            "pid": handle.process.pid if running else None,
            "endpoint": handle.endpoint if running else None,
            "loaded_model_id": handle.loaded_model_id if handle else None,
            "idle_timeout_seconds": profile.idle_timeout_seconds,
            "health": health,
        })

    backends = []
    for model_id, handle in supervisor._backends.items():
        running = handle.process.poll() is None
        unexpected_exit = not running
        health = _backend_health(handle.endpoint, handle.health_path) if running else {
            "reachable": False,
            "status_code": None,
        }
        backends.append({
            "model_id": model_id,
            "backend_runtime_id": handle.backend_runtime_id,
            "runtime_profile": handle.profile_id,
            "managed": True,
            "running": running,
            "unexpected_exit": unexpected_exit,
            "exit_code": handle.process.returncode if unexpected_exit else None,
            "pid": handle.process.pid if running else None,
            "endpoint": handle.endpoint if running else None,
            "health_path": handle.health_path,
            "health": health,
        })

    return {
        "available": True,
        "active_profile_id": supervisor._active_profile_id,
        "active_model_id": supervisor._active_model_id,
        "profiles": profiles,
        "backends": backends,
    }
