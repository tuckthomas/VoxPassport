"""
LiveTranslator — Installer Base
================================
Abstract contract for all model download/installation providers.

Every installer must:
  1. Download weights into a staging directory (never directly into the model store).
  2. Validate the download (checksum, file manifest, revision, runtime compatibility).
  3. Run a minimal smoke test to confirm the model loads and runs inference.
  4. Atomically promote validated weights into the installed-model store.
  5. Clean up staging on failure.

Do NOT store raw audio, transcripts, or translations during smoke testing.
"""

from __future__ import annotations

import abc
import hashlib
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Progress event
# ---------------------------------------------------------------------------

@dataclass
class InstallProgress:
    """Streamed during a model installation so callers can display progress."""
    model_id: str
    phase: str          # "downloading" | "validating" | "smoke_testing" | "promoting" | "done" | "failed"
    bytes_downloaded: int = 0
    bytes_total: int = 0
    message: str = ""
    error: Optional[str] = None

    @property
    def percent(self) -> float:
        if self.bytes_total > 0:
            return min(100.0, 100.0 * self.bytes_downloaded / self.bytes_total)
        return 0.0


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    actual_revision: Optional[str] = None
    actual_size_gb: Optional[float] = None

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.ok = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


# ---------------------------------------------------------------------------
# Installer base
# ---------------------------------------------------------------------------

class InstallerBase(abc.ABC):
    """
    Abstract base for all model installation providers.

    Subclasses implement: _download_to_staging(), _validate(), _smoke_test().
    The public install() orchestrates the full pipeline.
    """

    def __init__(
        self,
        model_store_dir: Path,
        staging_dir: Path,
    ):
        self.model_store_dir = Path(model_store_dir)
        self.staging_dir = Path(staging_dir)
        self.model_store_dir.mkdir(parents=True, exist_ok=True)
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self._cancelled = False

    def cancel(self) -> None:
        """Signal the installation to abort at the next checkpoint."""
        self._cancelled = True
        logger.info("Installation cancellation requested.")

    async def install(
        self,
        model_id: str,
        upstream_id: str,
        revision: str,
        expected_checksums: Optional[dict[str, str]] = None,
    ) -> AsyncIterator[InstallProgress]:
        """
        Full install pipeline: download → validate → smoke test → promote.
        Yields InstallProgress events throughout.
        Cleans staging on any failure.
        """
        stage_path = self.staging_dir / model_id
        install_path = self.model_store_dir / model_id

        try:
            # --- Download ---
            async for progress in self._download_to_staging(
                model_id, upstream_id, revision, stage_path
            ):
                if self._cancelled:
                    yield InstallProgress(model_id=model_id, phase="failed", error="Cancelled by user.")
                    self._cleanup_staging(stage_path)
                    return
                yield progress

            # --- Validate ---
            yield InstallProgress(model_id=model_id, phase="validating", message="Validating download…")
            result = await self._validate(stage_path, revision, expected_checksums)
            if not result.ok:
                error_msg = "; ".join(result.errors)
                yield InstallProgress(model_id=model_id, phase="failed", error=error_msg)
                self._cleanup_staging(stage_path)
                return
            for w in result.warnings:
                logger.warning("[%s] Validation warning: %s", model_id, w)

            # --- Smoke test ---
            yield InstallProgress(model_id=model_id, phase="smoke_testing", message="Running smoke test…")
            ok, smoke_error = await self._smoke_test(stage_path)
            if not ok:
                yield InstallProgress(model_id=model_id, phase="failed", error=smoke_error)
                self._cleanup_staging(stage_path)
                return

            # --- Atomic promotion ---
            yield InstallProgress(model_id=model_id, phase="promoting", message="Promoting to model store…")
            self._promote(stage_path, install_path)
            yield InstallProgress(model_id=model_id, phase="done", message="Installation complete.")
            logger.info("[%s] Installation complete at: %s", model_id, install_path)

        except Exception as exc:
            logger.exception("[%s] Installation failed: %s", model_id, exc)
            yield InstallProgress(model_id=model_id, phase="failed", error=str(exc))
            self._cleanup_staging(stage_path)

    # ------------------------------------------------------------------
    # Abstract methods — implement per provider
    # ------------------------------------------------------------------

    @abc.abstractmethod
    async def _download_to_staging(
        self,
        model_id: str,
        upstream_id: str,
        revision: str,
        stage_path: Path,
    ) -> AsyncIterator[InstallProgress]:
        """Download model files into stage_path. Must support HTTP Range resumption."""
        ...

    @abc.abstractmethod
    async def _validate(
        self,
        stage_path: Path,
        expected_revision: str,
        expected_checksums: Optional[dict[str, str]],
    ) -> ValidationResult:
        """Verify checksums, file manifest, revision, and runtime compatibility."""
        ...

    @abc.abstractmethod
    async def _smoke_test(self, stage_path: Path) -> tuple[bool, Optional[str]]:
        """
        Load the model from stage_path and run a minimal inference call.
        Must NOT log raw audio, transcripts, or translations.
        Returns (success, error_message_or_None).
        """
        ...

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    @staticmethod
    def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
        """Compute SHA-256 of a file without loading it fully into memory."""
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(chunk_size):
                h.update(chunk)
        return h.hexdigest()

    def _promote(self, stage_path: Path, install_path: Path) -> None:
        """Atomically move staged model into the model store."""
        if install_path.exists():
            shutil.rmtree(install_path)
        shutil.move(str(stage_path), str(install_path))
        logger.info("Promoted staging → %s", install_path)

    def _cleanup_staging(self, stage_path: Path) -> None:
        if stage_path.exists():
            try:
                shutil.rmtree(stage_path)
                logger.info("Cleaned staging: %s", stage_path)
            except Exception:
                logger.warning("Failed to clean staging: %s", stage_path, exc_info=True)

    def get_install_path(self, model_id: str) -> Path:
        return self.model_store_dir / model_id

    def is_installed(self, model_id: str) -> bool:
        return self.get_install_path(model_id).exists()

    async def uninstall(self, model_id: str) -> bool:
        """Delete a model's weight files from the model store."""
        install_path = self.get_install_path(model_id)
        if not install_path.exists():
            logger.warning("[%s] Uninstall: model not found.", model_id)
            return False
        shutil.rmtree(install_path)
        logger.info("[%s] Uninstalled.", model_id)
        return True
