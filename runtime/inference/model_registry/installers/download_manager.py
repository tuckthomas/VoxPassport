"""
LiveTranslator - Download Manager
Manages concurrent model installations with progress tracking,
cancellation, and state persistence across restarts.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import AsyncIterator, Callable, Optional

from runtime.inference.model_registry.installers.base import InstallProgress

logger = logging.getLogger(__name__)


@dataclass
class DownloadTask:
    """Represents one active or queued model download."""
    model_id: str
    upstream_id: str
    revision: str
    provider: str           # "huggingface" | "local"
    started_at: float = field(default_factory=time.time)
    phase: str = "queued"
    bytes_downloaded: int = 0
    bytes_total: int = 0
    error: Optional[str] = None
    cancelled: bool = False

    @property
    def percent(self) -> float:
        if self.bytes_total > 0:
            return min(100.0, 100.0 * self.bytes_downloaded / self.bytes_total)
        return 0.0


class DownloadManager:
    """
    Manages model download/install tasks with:
    - Progress tracking per model_id
    - Cancellation support
    - WebSocket progress broadcast hook
    - Persistent task state (survives process restart mid-download)
    """

    def __init__(
        self,
        state_file: Optional[Path] = None,
        on_progress: Optional[Callable[[DownloadTask], None]] = None,
    ):
        self._tasks: dict[str, DownloadTask] = {}
        self._installers: dict[str, object] = {}   # model_id -> InstallerBase
        self._active_tasks: dict[str, asyncio.Task] = {}
        self._state_file = state_file
        self._on_progress = on_progress

        if self._state_file and self._state_file.exists():
            self._load_state()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_installer(self, model_id: str, installer) -> None:
        self._installers[model_id] = installer

    async def start_install(
        self,
        model_id: str,
        upstream_id: str,
        revision: str,
        provider: str = "huggingface",
        expected_checksums: Optional[dict[str, str]] = None,
    ) -> None:
        """Queue and begin a model installation asynchronously."""
        if model_id in self._active_tasks and not self._active_tasks[model_id].done():
            logger.warning("[%s] Installation already in progress.", model_id)
            return

        task = DownloadTask(
            model_id=model_id,
            upstream_id=upstream_id,
            revision=revision,
            provider=provider,
        )
        self._tasks[model_id] = task
        self._persist_state()

        installer = self._installers.get(model_id)
        if installer is None:
            task.phase = "failed"
            task.error = f"No installer registered for model_id={model_id!r}"
            self._persist_state()
            return

        async def _run():
            async for progress in installer.install(
                model_id=model_id,
                upstream_id=upstream_id,
                revision=revision,
                expected_checksums=expected_checksums,
            ):
                self._update_task(task, progress)

        self._active_tasks[model_id] = asyncio.create_task(_run())

    def cancel(self, model_id: str) -> bool:
        """Cancel an active installation."""
        installer = self._installers.get(model_id)
        if installer:
            installer.cancel()
        task = self._tasks.get(model_id)
        if task:
            task.cancelled = True
        at = self._active_tasks.get(model_id)
        if at and not at.done():
            at.cancel()
            return True
        return False

    def get_task(self, model_id: str) -> Optional[DownloadTask]:
        return self._tasks.get(model_id)

    def list_tasks(self) -> list[DownloadTask]:
        return list(self._tasks.values())

    def is_active(self, model_id: str) -> bool:
        at = self._active_tasks.get(model_id)
        return at is not None and not at.done()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _update_task(self, task: DownloadTask, progress: InstallProgress) -> None:
        task.phase = progress.phase
        task.bytes_downloaded = progress.bytes_downloaded
        task.bytes_total = progress.bytes_total
        if progress.error:
            task.error = progress.error
        self._persist_state()
        if self._on_progress:
            try:
                self._on_progress(task)
            except Exception:
                pass

    def _persist_state(self) -> None:
        if not self._state_file:
            return
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            data = {k: asdict(v) for k, v in self._tasks.items()}
            tmp = self._state_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2))
            tmp.replace(self._state_file)
        except Exception:
            logger.warning("Failed to persist download state.", exc_info=True)

    def _load_state(self) -> None:
        try:
            data = json.loads(self._state_file.read_text())
            for model_id, d in data.items():
                self._tasks[model_id] = DownloadTask(**d)
            logger.info("Loaded %d download task(s) from state file.", len(self._tasks))
        except Exception:
            logger.warning("Failed to load download state.", exc_info=True)
