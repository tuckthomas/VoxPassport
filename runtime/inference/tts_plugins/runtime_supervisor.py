"""Lifecycle supervisor for dependency-isolated local TTS worker profiles."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, TextIO

import aiohttp

from runtime.inference.tts_plugins.manifest import TtsManifest, TtsManifestCatalog
from runtime.inference.tts_plugins.runtime_profiles import RuntimeProfile, RuntimeProfileCatalog

logger = logging.getLogger(__name__)


@dataclass
class _WorkerHandle:
    profile: RuntimeProfile
    process: subprocess.Popen
    endpoint: str
    port: int
    log_file: TextIO
    started_monotonic: float
    last_used_monotonic: float
    loaded_model_id: Optional[str] = None
    idle_task: Optional[asyncio.Task] = None


class TtsRuntimeSupervisor:
    """Own local TTS worker processes, endpoints, and cross-profile residency."""

    def __init__(
        self,
        *,
        manifest_catalog: Optional[TtsManifestCatalog] = None,
        profile_catalog: Optional[RuntimeProfileCatalog] = None,
        project_root: Optional[Path] = None,
        log_dir: Optional[Path] = None,
    ) -> None:
        self.project_root = Path(project_root or Path(__file__).resolve().parents[3]).resolve()
        self.manifest_catalog = manifest_catalog or TtsManifestCatalog().load()
        self.profile_catalog = profile_catalog or RuntimeProfileCatalog().load()
        self.log_dir = Path(log_dir or self.project_root / "data" / "logs").resolve()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._workers: dict[str, _WorkerHandle] = {}
        self._active_profile_id: Optional[str] = None
        self._active_model_id: Optional[str] = None
        self._active_manifest: Optional[TtsManifest] = None
        self._lock = asyncio.Lock()

    @staticmethod
    def _free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    @staticmethod
    def _process_alive(handle: _WorkerHandle) -> bool:
        return handle.process.poll() is None

    async def _get_json(self, endpoint: str, path: str, *, timeout: float = 3.0) -> dict:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.get(f"{endpoint}{path}") as response:
                body = await response.json(content_type=None)
                if response.status != 200:
                    raise RuntimeError(body.get("error") or f"TTS worker returned HTTP {response.status}")
                return body

    async def _post_json(self, endpoint: str, path: str, payload: dict, *, timeout: float = 300.0) -> dict:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout, sock_read=timeout)) as session:
            async with session.post(f"{endpoint}{path}", json=payload) as response:
                body = await response.json(content_type=None)
                if response.status != 200:
                    raise RuntimeError(body.get("error") or f"TTS worker returned HTTP {response.status}")
                return body

    def _launch_worker(self, profile: RuntimeProfile) -> _WorkerHandle:
        interpreter = profile.resolve_interpreter(self.project_root)
        if not interpreter.exists():
            raise RuntimeError(
                f"TTS runtime profile {profile.profile_id!r} is not installed: interpreter not found at {interpreter}. "
                f"Provision the profile before activating models that require it."
            )
        port = self._free_port()
        endpoint = f"http://127.0.0.1:{port}"
        log_path = self.log_dir / f"tts-worker-{profile.profile_id}.log"
        log_file = log_path.open("a", encoding="utf-8", buffering=1)
        env = os.environ.copy()
        env.update(profile.resolved_environment())
        env.setdefault("PYTHONUNBUFFERED", "1")
        command = [
            str(interpreter),
            str(self.project_root / "runtime" / "workers" / "tts_host" / "server.py"),
            "--host", "127.0.0.1",
            "--port", str(port),
            "--manifest-dir", str(self.project_root / "runtime" / "tts_manifests"),
        ]
        try:
            process = subprocess.Popen(
                command,
                cwd=str(self.project_root),
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
        except Exception:
            log_file.close()
            raise
        now = time.monotonic()
        logger.info("Started TTS runtime profile %s as PID %s on %s", profile.profile_id, process.pid, endpoint)
        return _WorkerHandle(
            profile=profile,
            process=process,
            endpoint=endpoint,
            port=port,
            log_file=log_file,
            started_monotonic=now,
            last_used_monotonic=now,
        )

    async def _wait_healthy(self, handle: _WorkerHandle) -> None:
        deadline = time.monotonic() + handle.profile.startup_timeout_seconds
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            if not self._process_alive(handle):
                raise RuntimeError(
                    f"TTS runtime profile {handle.profile.profile_id!r} exited during startup with code "
                    f"{handle.process.returncode}. See data/logs/tts-worker-{handle.profile.profile_id}.log"
                )
            try:
                body = await self._get_json(handle.endpoint, "/health", timeout=1.5)
                if body.get("status") in {"ok", "degraded"}:
                    return
            except Exception as exc:
                last_error = exc
            await asyncio.sleep(0.15)
        raise RuntimeError(
            f"TTS runtime profile {handle.profile.profile_id!r} did not become healthy within "
            f"{handle.profile.startup_timeout_seconds:.0f}s"
        ) from last_error

    async def _ensure_worker_locked(self, profile: RuntimeProfile) -> _WorkerHandle:
        handle = self._workers.get(profile.profile_id)
        if handle is not None and self._process_alive(handle):
            try:
                await self._get_json(handle.endpoint, "/health", timeout=2.0)
                handle.last_used_monotonic = time.monotonic()
                return handle
            except Exception:
                await self._terminate_worker_locked(profile.profile_id)
        elif handle is not None:
            await self._terminate_worker_locked(profile.profile_id)

        handle = self._launch_worker(profile)
        self._workers[profile.profile_id] = handle
        try:
            await self._wait_healthy(handle)
            return handle
        except Exception:
            await self._terminate_worker_locked(profile.profile_id)
            raise

    async def _unload_handle_locked(self, handle: _WorkerHandle, model_id: Optional[str] = None) -> None:
        if not self._process_alive(handle):
            handle.loaded_model_id = None
            return
        try:
            await self._post_json(
                handle.endpoint,
                "/unload",
                {"model_id": model_id or handle.loaded_model_id},
                timeout=20.0,
            )
        except Exception:
            logger.debug("TTS worker unload failed for profile %s", handle.profile.profile_id, exc_info=True)
        handle.loaded_model_id = None
        handle.last_used_monotonic = time.monotonic()

    async def _terminate_worker_locked(self, profile_id: str) -> None:
        handle = self._workers.pop(profile_id, None)
        if handle is None:
            return
        if handle.idle_task and not handle.idle_task.done() and handle.idle_task is not asyncio.current_task():
            handle.idle_task.cancel()
        if self._process_alive(handle):
            handle.process.terminate()
            try:
                await asyncio.to_thread(handle.process.wait, 5)
            except Exception:
                handle.process.kill()
                try:
                    await asyncio.to_thread(handle.process.wait, 2)
                except Exception:
                    pass
        try:
            handle.log_file.close()
        except Exception:
            pass
        logger.info("Stopped TTS runtime profile %s", profile_id)

    def _schedule_idle_shutdown_locked(self, handle: _WorkerHandle) -> None:
        if handle.idle_task and not handle.idle_task.done():
            handle.idle_task.cancel()
        if handle.profile.idle_timeout_seconds <= 0:
            handle.idle_task = asyncio.create_task(self._shutdown_if_idle(handle.profile.profile_id, 0.0))
        else:
            handle.idle_task = asyncio.create_task(
                self._shutdown_if_idle(handle.profile.profile_id, handle.profile.idle_timeout_seconds)
            )

    async def _shutdown_if_idle(self, profile_id: str, delay: float) -> None:
        try:
            if delay:
                await asyncio.sleep(delay)
            async with self._lock:
                handle = self._workers.get(profile_id)
                if handle is None or handle.loaded_model_id is not None:
                    return
                if time.monotonic() - handle.last_used_monotonic < delay:
                    return
                await self._terminate_worker_locked(profile_id)
        except asyncio.CancelledError:
            return

    async def _activate_locked(self, manifest: TtsManifest, *, allow_rollback: bool) -> tuple[str, dict]:
        profile = self.profile_catalog.resolve(manifest.runtime_profile)
        previous_manifest = self._active_manifest
        previous_profile_id = self._active_profile_id

        if self._active_model_id == manifest.model_id and previous_profile_id == profile.profile_id:
            handle = await self._ensure_worker_locked(profile)
            health = await self._get_json(handle.endpoint, "/health", timeout=3.0)
            if health.get("loaded_model_id") == manifest.model_id:
                handle.loaded_model_id = manifest.model_id
                handle.last_used_monotonic = time.monotonic()
                caps = await self._get_json(
                    handle.endpoint,
                    f"/v1/capabilities?model_id={manifest.model_id}",
                    timeout=3.0,
                )
                return handle.endpoint, caps

        if previous_manifest is not None and previous_manifest.model_id != manifest.model_id:
            previous_handle = self._workers.get(previous_profile_id or "")
            if previous_handle is not None:
                await self._unload_handle_locked(previous_handle, previous_manifest.model_id)
                if previous_profile_id != profile.profile_id:
                    await self._terminate_worker_locked(previous_profile_id or "")
                else:
                    self._schedule_idle_shutdown_locked(previous_handle)
            self._active_manifest = None
            self._active_model_id = None
            self._active_profile_id = None

        try:
            handle = await self._ensure_worker_locked(profile)
            if handle.idle_task and not handle.idle_task.done():
                handle.idle_task.cancel()
                handle.idle_task = None
            body = await self._post_json(handle.endpoint, "/load", {"model_id": manifest.model_id})
            if not body.get("success"):
                raise RuntimeError(body.get("error") or f"Could not load {manifest.display_name}")
            health = await self._get_json(handle.endpoint, "/health", timeout=3.0)
            if health.get("status") != "ok" or health.get("loaded_model_id") != manifest.model_id:
                raise RuntimeError(f"{manifest.display_name} failed supervised post-load health validation")
            handle.loaded_model_id = manifest.model_id
            handle.last_used_monotonic = time.monotonic()
            self._active_profile_id = profile.profile_id
            self._active_model_id = manifest.model_id
            self._active_manifest = manifest
            return handle.endpoint, dict(body.get("capabilities") or {})
        except Exception:
            failed_handle = self._workers.get(profile.profile_id)
            if failed_handle is not None:
                await self._unload_handle_locked(failed_handle, manifest.model_id)
                self._schedule_idle_shutdown_locked(failed_handle)
            if allow_rollback and previous_manifest is not None and previous_manifest.model_id != manifest.model_id:
                logger.warning("TTS activation failed for %s; attempting rollback to %s", manifest.model_id, previous_manifest.model_id)
                try:
                    await self._activate_locked(previous_manifest, allow_rollback=False)
                except Exception:
                    logger.exception("TTS runtime rollback also failed for %s", previous_manifest.model_id)
            raise

    async def activate(self, manifest: TtsManifest | str) -> tuple[str, dict]:
        resolved = manifest if isinstance(manifest, TtsManifest) else self.manifest_catalog.resolve(str(manifest))
        async with self._lock:
            return await self._activate_locked(resolved, allow_rollback=True)

    async def ensure_active(self, manifest: TtsManifest | str) -> str:
        resolved = manifest if isinstance(manifest, TtsManifest) else self.manifest_catalog.resolve(str(manifest))
        async with self._lock:
            profile = self.profile_catalog.resolve(resolved.runtime_profile)
            handle = self._workers.get(profile.profile_id)
            healthy = False
            if (
                self._active_model_id == resolved.model_id
                and handle is not None
                and self._process_alive(handle)
            ):
                try:
                    status = await self._get_json(handle.endpoint, "/health", timeout=2.0)
                    healthy = status.get("status") == "ok" and status.get("loaded_model_id") == resolved.model_id
                except Exception:
                    healthy = False
            if healthy:
                handle.last_used_monotonic = time.monotonic()
                return handle.endpoint
            endpoint, _caps = await self._activate_locked(resolved, allow_rollback=False)
            return endpoint

    async def release(self, manifest: TtsManifest | str) -> None:
        resolved = manifest if isinstance(manifest, TtsManifest) else self.manifest_catalog.resolve(str(manifest))
        async with self._lock:
            if self._active_model_id != resolved.model_id:
                return
            profile_id = self._active_profile_id
            handle = self._workers.get(profile_id or "")
            if handle is not None:
                await self._unload_handle_locked(handle, resolved.model_id)
                self._schedule_idle_shutdown_locked(handle)
            self._active_manifest = None
            self._active_model_id = None
            self._active_profile_id = None

    async def recover(self, manifest: TtsManifest | str) -> str:
        resolved = manifest if isinstance(manifest, TtsManifest) else self.manifest_catalog.resolve(str(manifest))
        async with self._lock:
            profile = self.profile_catalog.resolve(resolved.runtime_profile)
            await self._terminate_worker_locked(profile.profile_id)
            if self._active_profile_id == profile.profile_id:
                self._active_manifest = None
                self._active_model_id = None
                self._active_profile_id = None
            endpoint, _caps = await self._activate_locked(resolved, allow_rollback=False)
            return endpoint

    async def status(self) -> dict:
        async with self._lock:
            profiles = []
            for profile in self.profile_catalog.profiles():
                handle = self._workers.get(profile.profile_id)
                interpreter = profile.resolve_interpreter(self.project_root)
                profiles.append({
                    "profile_id": profile.profile_id,
                    "installed": interpreter.exists(),
                    "interpreter": str(interpreter),
                    "running": bool(handle and self._process_alive(handle)),
                    "pid": handle.process.pid if handle and self._process_alive(handle) else None,
                    "endpoint": handle.endpoint if handle and self._process_alive(handle) else None,
                    "loaded_model_id": handle.loaded_model_id if handle else None,
                    "idle_timeout_seconds": profile.idle_timeout_seconds,
                    "provisioning": dict(profile.provisioning),
                })
            return {
                "active_profile_id": self._active_profile_id,
                "active_model_id": self._active_model_id,
                "profiles": profiles,
            }

    async def shutdown(self) -> None:
        async with self._lock:
            for profile_id in list(self._workers):
                handle = self._workers.get(profile_id)
                if handle is not None:
                    await self._unload_handle_locked(handle, handle.loaded_model_id)
                await self._terminate_worker_locked(profile_id)
            self._active_manifest = None
            self._active_model_id = None
            self._active_profile_id = None


_DEFAULT_SUPERVISOR: Optional[TtsRuntimeSupervisor] = None


def get_tts_runtime_supervisor(
    *,
    manifest_catalog: Optional[TtsManifestCatalog] = None,
    profile_catalog: Optional[RuntimeProfileCatalog] = None,
) -> TtsRuntimeSupervisor:
    global _DEFAULT_SUPERVISOR
    if _DEFAULT_SUPERVISOR is None:
        _DEFAULT_SUPERVISOR = TtsRuntimeSupervisor(
            manifest_catalog=manifest_catalog,
            profile_catalog=profile_catalog,
        )
    return _DEFAULT_SUPERVISOR
