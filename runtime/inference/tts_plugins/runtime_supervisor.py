"""Lifecycle supervisor for dependency-isolated local TTS runtime profiles."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import shlex
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, TextIO
from urllib.parse import urlsplit

import aiohttp

from runtime.inference.tts_plugins.backend_runtime import BackendRuntime, BackendRuntimeCatalog
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


@dataclass
class _BackendHandle:
    model_id: str
    backend_runtime_id: str
    profile_id: str
    process: subprocess.Popen
    endpoint: str
    port: int
    health_path: str
    startup_timeout_seconds: float
    log_file: TextIO
    started_monotonic: float


class TtsRuntimeSupervisor:
    """Own local TTS worker/backend processes, endpoints, and GPU residency."""

    def __init__(
        self,
        *,
        manifest_catalog: Optional[TtsManifestCatalog] = None,
        profile_catalog: Optional[RuntimeProfileCatalog] = None,
        backend_runtime_catalog: Optional[BackendRuntimeCatalog] = None,
        project_root: Optional[Path] = None,
        log_dir: Optional[Path] = None,
    ) -> None:
        self.project_root = Path(project_root or Path(__file__).resolve().parents[3]).resolve()
        self.backend_runtime_catalog = backend_runtime_catalog or BackendRuntimeCatalog().load()
        if manifest_catalog is None:
            self.manifest_catalog = TtsManifestCatalog(
                backend_runtime_catalog=self.backend_runtime_catalog
            ).load()
        else:
            self.manifest_catalog = manifest_catalog
            if self.manifest_catalog.backend_runtime_catalog is None:
                self.manifest_catalog.backend_runtime_catalog = self.backend_runtime_catalog
        self.profile_catalog = profile_catalog or RuntimeProfileCatalog().load()
        self.log_dir = Path(log_dir or self.project_root / "data" / "logs").resolve()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._workers: dict[str, _WorkerHandle] = {}
        self._backends: dict[str, _BackendHandle] = {}
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
    def _process_alive(handle: _WorkerHandle | _BackendHandle) -> bool:
        return handle.process.poll() is None

    @staticmethod
    def _safe_log_name(value: str) -> str:
        return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)

    @staticmethod
    def _is_loopback_url(value: str) -> bool:
        try:
            parsed = urlsplit(value)
            host = parsed.hostname
            if not host:
                raise ValueError(f"Backend URL has no hostname: {value!r}")
            if host.lower() == "localhost":
                return True
            try:
                return ipaddress.ip_address(host).is_loopback
            except ValueError:
                return False
        except Exception as exc:
            raise ValueError(f"Invalid TTS backend URL: {value!r}") from exc

    def _backend_runtime(self, manifest: TtsManifest) -> Optional[BackendRuntime]:
        if not manifest.backend_runtime:
            return None
        try:
            runtime = self.backend_runtime_catalog.resolve(manifest.backend_runtime)
        except KeyError as exc:
            raise RuntimeError(
                f"{manifest.display_name} references unknown backend runtime {manifest.backend_runtime!r}"
            ) from exc
        runtime.resolve_args(manifest.backend_args)
        return runtime

    @staticmethod
    def _configured_backend_url(runtime: BackendRuntime) -> str:
        env_name = runtime.remote_url_env
        if not env_name:
            return ""
        return os.getenv(env_name, "").strip().rstrip("/")

    def _managed_backend_required(self, manifest: TtsManifest) -> bool:
        runtime = self._backend_runtime(manifest)
        if runtime is None:
            return False
        configured_url = self._configured_backend_url(runtime)
        if configured_url:
            if self._is_loopback_url(configured_url):
                raise RuntimeError(
                    f"Backend runtime {runtime.backend_runtime_id!r} is configured with unmanaged local endpoint "
                    f"{configured_url}. Local TTS backend processes must be supervisor-owned."
                )
            return False
        return True

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

    async def _endpoint_healthy(self, endpoint: str, path: str, *, timeout: float = 2.0) -> bool:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
                async with session.get(f"{endpoint}{path}") as response:
                    await response.read()
                    return 200 <= response.status < 400
        except Exception:
            return False

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
            "--manifest-dir", str(self.manifest_catalog.manifest_dir.resolve()),
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

    def _backend_command(
        self,
        manifest: TtsManifest,
        runtime: BackendRuntime,
        profile: RuntimeProfile,
        *,
        host: str,
        port: int,
    ) -> list[str]:
        raw_command = os.getenv(runtime.command_env, "").strip() if runtime.command_env else ""
        command: list[str]
        if raw_command:
            try:
                parsed = json.loads(raw_command)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list) and parsed and all(isinstance(item, str) for item in parsed):
                command = list(parsed)
            else:
                command = shlex.split(raw_command, posix=os.name != "nt")
        elif runtime.command:
            command = list(runtime.command)
        else:
            env_hint = (
                f" Set {runtime.command_env} once for backend runtime {runtime.backend_runtime_id!r}."
                if runtime.command_env else ""
            )
            raise RuntimeError(
                f"Backend runtime {runtime.backend_runtime_id!r} has no local launch command configured.{env_hint}"
            )

        interpreter = profile.resolve_interpreter(self.project_root)
        resolved_args = runtime.resolve_args(manifest.backend_args)
        replacements = {
            "host": host,
            "port": str(port),
            "project_root": str(self.project_root),
            "model_id": manifest.model_id,
            "backend_runtime_id": runtime.backend_runtime_id,
            "python": str(interpreter),
            **{key: str(value) for key, value in resolved_args.items()},
        }
        try:
            return [part.format(**replacements) for part in command]
        except KeyError as exc:
            raise RuntimeError(
                f"Unknown backend command placeholder {exc.args[0]!r} for backend runtime "
                f"{runtime.backend_runtime_id!r}"
            ) from exc

    def _launch_backend(self, manifest: TtsManifest, runtime: BackendRuntime) -> _BackendHandle:
        profile = self.profile_catalog.resolve(runtime.runtime_profile)
        interpreter = profile.resolve_interpreter(self.project_root)
        if not interpreter.exists():
            raise RuntimeError(
                f"Backend runtime {runtime.backend_runtime_id!r} requires uninstalled runtime profile "
                f"{profile.profile_id!r}: interpreter not found at {interpreter}"
            )
        host = "127.0.0.1"
        port = self._free_port()
        endpoint = f"http://{host}:{port}"
        command = self._backend_command(manifest, runtime, profile, host=host, port=port)
        log_name = self._safe_log_name(f"{runtime.backend_runtime_id}-{manifest.model_id}")
        log_path = self.log_dir / f"tts-backend-{log_name}.log"
        log_file = log_path.open("a", encoding="utf-8", buffering=1)
        env = os.environ.copy()
        env.update(profile.resolved_environment())
        env.update(runtime.environment)
        env.setdefault("PYTHONUNBUFFERED", "1")
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
        logger.info(
            "Started managed TTS backend runtime %s for %s as PID %s on %s",
            runtime.backend_runtime_id,
            manifest.model_id,
            process.pid,
            endpoint,
        )
        return _BackendHandle(
            model_id=manifest.model_id,
            backend_runtime_id=runtime.backend_runtime_id,
            profile_id=profile.profile_id,
            process=process,
            endpoint=endpoint,
            port=port,
            health_path=runtime.health_path,
            startup_timeout_seconds=runtime.startup_timeout_seconds,
            log_file=log_file,
            started_monotonic=time.monotonic(),
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

    async def _wait_backend_healthy(self, handle: _BackendHandle) -> None:
        deadline = time.monotonic() + handle.startup_timeout_seconds
        while time.monotonic() < deadline:
            if not self._process_alive(handle):
                raise RuntimeError(
                    f"Managed TTS backend runtime {handle.backend_runtime_id!r} for {handle.model_id!r} "
                    f"exited during startup with code {handle.process.returncode}. See "
                    f"data/logs/tts-backend-{self._safe_log_name(handle.backend_runtime_id + '-' + handle.model_id)}.log"
                )
            if await self._endpoint_healthy(handle.endpoint, handle.health_path, timeout=1.5):
                return
            await asyncio.sleep(0.2)
        raise RuntimeError(
            f"Managed TTS backend runtime {handle.backend_runtime_id!r} for {handle.model_id!r} "
            f"did not become healthy within {handle.startup_timeout_seconds:.0f}s"
        )

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

    async def _ensure_backend_locked(self, manifest: TtsManifest) -> Optional[tuple[str, str]]:
        runtime = self._backend_runtime(manifest)
        if runtime is None:
            return None

        configured_url = self._configured_backend_url(runtime)
        if configured_url:
            if self._is_loopback_url(configured_url):
                raise RuntimeError(
                    f"Backend runtime {runtime.backend_runtime_id!r} is configured to use unmanaged local backend "
                    f"{configured_url}. Local TTS proxy backends must be launched by TtsRuntimeSupervisor."
                )
            await self._terminate_backend_locked(manifest.model_id)
            return configured_url, runtime.endpoint_driver_option

        handle = self._backends.get(manifest.model_id)
        if handle is not None and self._process_alive(handle):
            same_runtime = handle.backend_runtime_id == runtime.backend_runtime_id
            if same_runtime and await self._endpoint_healthy(handle.endpoint, handle.health_path, timeout=2.0):
                return handle.endpoint, runtime.endpoint_driver_option
            await self._terminate_backend_locked(manifest.model_id)
        elif handle is not None:
            await self._terminate_backend_locked(manifest.model_id)

        handle = self._launch_backend(manifest, runtime)
        self._backends[manifest.model_id] = handle
        try:
            await self._wait_backend_healthy(handle)
            return handle.endpoint, runtime.endpoint_driver_option
        except Exception:
            await self._terminate_backend_locked(manifest.model_id)
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

    @staticmethod
    def _terminate_process_tree_blocking(process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        try:
            import psutil

            parent = psutil.Process(process.pid)
            descendants = parent.children(recursive=True)
            for child in descendants:
                try:
                    child.terminate()
                except Exception:
                    pass
            try:
                parent.terminate()
            except Exception:
                pass
            _gone, alive = psutil.wait_procs([*descendants, parent], timeout=4)
            for item in alive:
                try:
                    item.kill()
                except Exception:
                    pass
            psutil.wait_procs(alive, timeout=2)
            return
        except Exception:
            pass
        try:
            process.terminate()
            process.wait(timeout=4)
        except Exception:
            try:
                process.kill()
                process.wait(timeout=2)
            except Exception:
                pass

    async def _terminate_worker_locked(self, profile_id: str) -> None:
        handle = self._workers.pop(profile_id, None)
        if handle is None:
            return
        if handle.idle_task and not handle.idle_task.done() and handle.idle_task is not asyncio.current_task():
            handle.idle_task.cancel()
        await asyncio.to_thread(self._terminate_process_tree_blocking, handle.process)
        try:
            handle.log_file.close()
        except Exception:
            pass
        logger.info("Stopped TTS runtime profile %s", profile_id)

    async def _terminate_backend_locked(self, model_id: str) -> None:
        handle = self._backends.pop(model_id, None)
        if handle is None:
            return
        await asyncio.to_thread(self._terminate_process_tree_blocking, handle.process)
        try:
            handle.log_file.close()
        except Exception:
            pass
        logger.info(
            "Stopped managed TTS backend runtime %s for %s",
            handle.backend_runtime_id,
            model_id,
        )

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

        if previous_manifest is not None and previous_manifest.model_id != manifest.model_id:
            previous_handle = self._workers.get(previous_profile_id or "")
            if previous_handle is not None:
                await self._unload_handle_locked(previous_handle, previous_manifest.model_id)
            await self._terminate_backend_locked(previous_manifest.model_id)
            if previous_handle is not None:
                if previous_profile_id != profile.profile_id:
                    await self._terminate_worker_locked(previous_profile_id or "")
                else:
                    self._schedule_idle_shutdown_locked(previous_handle)
            self._active_manifest = None
            self._active_model_id = None
            self._active_profile_id = None

        try:
            backend_binding = await self._ensure_backend_locked(manifest)
            handle = await self._ensure_worker_locked(profile)
            if handle.idle_task and not handle.idle_task.done():
                handle.idle_task.cancel()
                handle.idle_task = None
            load_payload: dict[str, object] = {"model_id": manifest.model_id}
            if backend_binding:
                backend_endpoint, endpoint_option = backend_binding
                load_payload["driver_options_override"] = {endpoint_option: backend_endpoint}
            body = await self._post_json(handle.endpoint, "/load", load_payload)
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
            await self._terminate_backend_locked(manifest.model_id)
            if failed_handle is not None:
                if previous_manifest is not None and previous_profile_id != profile.profile_id:
                    await self._terminate_worker_locked(profile.profile_id)
                else:
                    self._schedule_idle_shutdown_locked(failed_handle)
            if self._active_model_id == manifest.model_id:
                self._active_manifest = None
                self._active_model_id = None
                self._active_profile_id = None
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
            backend_ok = True
            if resolved.backend_runtime:
                runtime = self._backend_runtime(resolved)
                assert runtime is not None
                configured_url = self._configured_backend_url(runtime)
                if configured_url:
                    if self._is_loopback_url(configured_url):
                        backend_ok = False
                    else:
                        backend_ok = True
                else:
                    backend = self._backends.get(resolved.model_id)
                    backend_ok = bool(
                        backend is not None
                        and backend.backend_runtime_id == runtime.backend_runtime_id
                        and self._process_alive(backend)
                    )
                    if backend_ok and backend is not None:
                        backend_ok = await self._endpoint_healthy(
                            backend.endpoint,
                            backend.health_path,
                            timeout=1.5,
                        )
            healthy = False
            if (
                self._active_model_id == resolved.model_id
                and handle is not None
                and self._process_alive(handle)
                and backend_ok
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
            await self._terminate_backend_locked(resolved.model_id)
            if handle is not None:
                self._schedule_idle_shutdown_locked(handle)
            self._active_manifest = None
            self._active_model_id = None
            self._active_profile_id = None

    async def recover(self, manifest: TtsManifest | str) -> str:
        resolved = manifest if isinstance(manifest, TtsManifest) else self.manifest_catalog.resolve(str(manifest))
        async with self._lock:
            profile = self.profile_catalog.resolve(resolved.runtime_profile)
            await self._terminate_worker_locked(profile.profile_id)
            await self._terminate_backend_locked(resolved.model_id)
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
            backends = []
            for model_id, backend in self._backends.items():
                running = self._process_alive(backend)
                backends.append({
                    "model_id": model_id,
                    "backend_runtime_id": backend.backend_runtime_id,
                    "runtime_profile": backend.profile_id,
                    "managed": True,
                    "running": running,
                    "pid": backend.process.pid if running else None,
                    "endpoint": backend.endpoint if running else None,
                    "health_path": backend.health_path,
                    "exit_code": backend.process.returncode if not running else None,
                })
            return {
                "active_profile_id": self._active_profile_id,
                "active_model_id": self._active_model_id,
                "profiles": profiles,
                "backends": backends,
            }

    async def shutdown(self) -> None:
        async with self._lock:
            for profile_id in list(self._workers):
                handle = self._workers.get(profile_id)
                if handle is not None:
                    await self._unload_handle_locked(handle, handle.loaded_model_id)
            for model_id in list(self._backends):
                await self._terminate_backend_locked(model_id)
            for profile_id in list(self._workers):
                await self._terminate_worker_locked(profile_id)
            self._active_manifest = None
            self._active_model_id = None
            self._active_profile_id = None


_DEFAULT_SUPERVISOR: Optional[TtsRuntimeSupervisor] = None


def get_tts_runtime_supervisor(
    *,
    manifest_catalog: Optional[TtsManifestCatalog] = None,
    profile_catalog: Optional[RuntimeProfileCatalog] = None,
    backend_runtime_catalog: Optional[BackendRuntimeCatalog] = None,
) -> TtsRuntimeSupervisor:
    global _DEFAULT_SUPERVISOR
    if _DEFAULT_SUPERVISOR is None:
        _DEFAULT_SUPERVISOR = TtsRuntimeSupervisor(
            manifest_catalog=manifest_catalog,
            profile_catalog=profile_catalog,
            backend_runtime_catalog=backend_runtime_catalog,
        )
    return _DEFAULT_SUPERVISOR
