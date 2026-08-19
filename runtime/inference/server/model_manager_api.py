"""
LiveTranslator — Model Manager API & Controller
================================================
Controller and REST interface for managing models, active capability slots,
installations, downloads, hot-swapping, known-good rollbacks, and storage cleanup.

Endpoints:
- GET  /api/models/installed      — List currently installed models
- GET  /api/models/available      — List all discoverable models from catalog
- GET  /api/models/active         — Current active model per capability slot
- POST /api/models/active         — Set active model for a slot (hot-swap)
- POST /api/models/install        — Install / download a model
- POST /api/models/uninstall      — Delete model weights and free disk space
- POST /api/models/rollback       — Roll back to previous known-good model set
- POST /api/models/known-good     — Snapshot current selection as known-good set
- GET  /api/models/cleanup        — List unused candidate models eligible for deletion
- POST /api/models/cleanup        — Run automatic storage cleanup
- POST /api/models/discover       — Trigger Model Discovery Agent scan
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from runtime.inference.model_registry.registry import (
    KnownGoodModelSet,
    ModelRegistry,
    ModelRegistryEntry,
)
from runtime.inference.model_registry.installers import (
    HuggingFaceInstaller,
    LocalImportInstaller,
    DownloadManager,
)
from runtime.inference.protocol import (
    InstallationStatus,
    ModelCapability,
    RecommendationState,
)

logger = logging.getLogger(__name__)


class ModelManagerController:
    """
    Core business logic controller for the Model Manager.
    Coordinates the ModelRegistry, real model installers, and the DownloadManager.
    """

    def __init__(
        self,
        registry: ModelRegistry,
        model_store_dir: Optional[str] = None,
        staging_dir: Optional[str] = None,
        on_progress=None,                   # Callable[[DownloadTask], None] for WS broadcast
    ):
        from pathlib import Path
        self.registry = registry
        self._model_store_dir = Path(model_store_dir) if model_store_dir else Path("models")
        self._staging_dir = Path(staging_dir) if staging_dir else Path("models") / ".staging"
        self._download_manager = DownloadManager(on_progress=on_progress)

    def list_installed(self) -> List[Dict[str, Any]]:
        """Return list of all installed models with metadata."""
        entries = self.registry.list_entries(installed_only=True)
        return [e.to_dict() for e in entries]

    def list_available(self) -> List[Dict[str, Any]]:
        """Return list of all catalog models (both installed and discoverable)."""
        entries = self.registry.list_entries()
        return [e.to_dict() for e in entries]

    def get_active_slots(self) -> Dict[str, Optional[str]]:
        """Return current active model for every capability slot."""
        return {
            slot: getattr(self.registry._active, slot)
            for slot in KnownGoodModelSet.SLOT_NAMES
        }

    def set_active_model(self, capability: str, model_id: str, language: Optional[str] = None, language_pair: Optional[str] = None) -> None:
        """Set active model for a capability slot."""
        self.registry.set_active_model(
            capability=capability,
            model_id=model_id,
            language=language,
            language_pair=language_pair,
        )

    async def install_model(
        self,
        model_id: str,
        upstream_id: Optional[str] = None,
        revision: Optional[str] = None,
        provider: str = "huggingface",
        expected_checksums: Optional[Dict[str, str]] = None,
    ) -> bool:
        """
        Download and install a model using the real installer pipeline:
          download -> validate -> smoke-test -> atomic promotion.
        Progress events are broadcast via the DownloadManager's on_progress callback.
        """
        from pathlib import Path
        entry = self.registry.get_entry(model_id)
        if not entry:
            raise KeyError(f"Model {model_id!r} not found in registry.")

        _upstream_id = upstream_id or entry.upstream_id
        _revision = revision or entry.revision

        if not _upstream_id:
            raise ValueError(f"Model {model_id!r} has no upstream_id configured.")

        # Create and register the installer
        if provider == "local":
            installer = LocalImportInstaller(
                model_store_dir=self._model_store_dir,
                staging_dir=self._staging_dir,
            )
        else:
            installer = HuggingFaceInstaller(
                model_store_dir=self._model_store_dir,
                staging_dir=self._staging_dir,
            )

        self._download_manager.register_installer(model_id, installer)
        self.registry.update_installation_status(model_id, InstallationStatus.DOWNLOADING)

        await self._download_manager.start_install(
            model_id=model_id,
            upstream_id=_upstream_id,
            revision=_revision,
            provider=provider,
            expected_checksums=expected_checksums,
        )
        logger.info("Installation queued for model %s.", model_id)
        return True

    def cancel_install(self, model_id: str) -> bool:
        """Cancel an in-progress installation."""
        cancelled = self._download_manager.cancel(model_id)
        if cancelled:
            self.registry.update_installation_status(model_id, InstallationStatus.NOT_INSTALLED)
        return cancelled

    def get_install_progress(self, model_id: str) -> Optional[Dict[str, Any]]:
        task = self._download_manager.get_task(model_id)
        if task is None:
            return None
        return {
            "model_id": task.model_id,
            "phase": task.phase,
            "percent": task.percent,
            "bytes_downloaded": task.bytes_downloaded,
            "bytes_total": task.bytes_total,
            "error": task.error,
        }

    def uninstall_model(self, model_id: str) -> bool:
        """Uninstall a model — deletes weight files and updates registry status."""
        entry = self.registry.get_entry(model_id)
        if not entry:
            return False
        if entry.is_active:
            raise ValueError(f"Cannot uninstall active model {model_id!r}. Switch active model first.")
        if entry.is_pinned:
            raise ValueError(f"Cannot uninstall pinned model {model_id!r}. Unpin it first.")

        # Delete files from disk
        from pathlib import Path
        install_path = self._model_store_dir / model_id
        if install_path.exists():
            import shutil
            shutil.rmtree(install_path)
            logger.info("Deleted model files: %s", install_path)

        self.registry.update_installation_status(
            model_id, InstallationStatus.NOT_INSTALLED, installed_size_gb=None,
        )
        logger.info("Uninstalled model %s", model_id)
        return True

    def pin_model(self, model_id: str, pinned: bool) -> bool:
        """Pin or unpin a model to prevent accidental cleanup/deletion."""
        entry = self.registry.get_entry(model_id)
        if not entry:
            return False
        entry.is_pinned = pinned
        self.registry._persist()
        logger.info("Model %s %s.", model_id, "pinned" if pinned else "unpinned")
        return True

    def save_known_good_set(self, version: str = "0.1.0") -> KnownGoodModelSet:
        return self.registry.save_known_good_set(app_version=version)

    def rollback_known_good(self, set_id: Optional[str] = None) -> Optional[KnownGoodModelSet]:
        return self.registry.rollback_to_known_good(set_id=set_id)

    def get_cleanup_candidates(self, n_days_unused: int = 30) -> List[Dict[str, Any]]:
        candidates = self.registry.get_cleanup_candidates(n_days_unused=n_days_unused)
        return [c.to_dict() for c in candidates]

    def execute_cleanup(self, n_days_unused: int = 30) -> Dict[str, Any]:
        """Delete unused, unpinned, non-active models. Returns freed GB and count."""
        candidates = self.registry.get_cleanup_candidates(n_days_unused=n_days_unused)
        freed_gb = 0.0
        count = 0
        for c in candidates:
            try:
                freed_gb += c.installed_size_gb or 0.0
                self.uninstall_model(c.model_id)
                count += 1
            except Exception as exc:
                logger.warning("Cleanup skipped %s: %s", c.model_id, exc)
        logger.info("Storage cleanup: uninstalled %d models, freed %.2f GB.", count, freed_gb)
        return {"count": count, "freed_gb": freed_gb}
