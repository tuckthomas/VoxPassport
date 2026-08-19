"""
LiveTranslator - Local Model Import
Imports a model from a local directory or archive into the model store.
Supports: directory copy, .zip/.tar.gz archives.
Runs the same validation + smoke test as the online installer.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import zipfile
import tarfile
from pathlib import Path
from typing import AsyncIterator, Optional

from runtime.inference.model_registry.installers.base import (
    InstallerBase,
    InstallProgress,
    ValidationResult,
)

logger = logging.getLogger(__name__)


class LocalImportInstaller(InstallerBase):
    """Imports a model from a local directory or compressed archive."""

    async def _download_to_staging(
        self,
        model_id: str,
        upstream_id: str,   # interpreted as local filesystem path
        revision: str,
        stage_path: Path,
    ) -> AsyncIterator[InstallProgress]:
        source = Path(upstream_id)
        if not source.exists():
            raise FileNotFoundError(f"Local import source not found: {source}")

        stage_path.mkdir(parents=True, exist_ok=True)
        loop = asyncio.get_event_loop()

        yield InstallProgress(
            model_id=model_id,
            phase="downloading",
            message=f"Importing from local path: {source}",
        )

        def _copy():
            if source.is_dir():
                if stage_path.exists():
                    shutil.rmtree(stage_path)
                shutil.copytree(source, stage_path)
            elif source.suffix == ".zip":
                with zipfile.ZipFile(source) as zf:
                    zf.extractall(stage_path)
            elif source.name.endswith(".tar.gz") or source.name.endswith(".tgz"):
                with tarfile.open(source, "r:gz") as tf:
                    tf.extractall(stage_path)
            else:
                shutil.copy2(source, stage_path)

        await loop.run_in_executor(None, _copy)

        all_files = [f for f in stage_path.rglob("*") if f.is_file()]
        total_bytes = sum(f.stat().st_size for f in all_files)
        yield InstallProgress(
            model_id=model_id,
            phase="downloading",
            bytes_downloaded=total_bytes,
            bytes_total=total_bytes,
            message="Local import complete.",
        )

    async def _validate(
        self,
        stage_path: Path,
        expected_revision: str,
        expected_checksums: Optional[dict[str, str]],
    ) -> ValidationResult:
        result = ValidationResult(ok=True)
        model_files = [f for f in stage_path.rglob("*") if f.is_file()]
        if not model_files:
            result.add_error("Imported directory is empty.")
            return result
        result.actual_size_gb = sum(f.stat().st_size for f in model_files) / 1e9

        if expected_checksums:
            loop = asyncio.get_event_loop()
            for rel_path, expected_sha256 in expected_checksums.items():
                fp = stage_path / rel_path
                if not fp.exists():
                    result.add_error(f"Missing expected file: {rel_path}")
                    continue
                actual = await loop.run_in_executor(None, self.sha256_file, fp)
                if actual != expected_sha256.lower():
                    result.add_error(f"Checksum mismatch for {rel_path}")
        return result

    async def _smoke_test(self, stage_path: Path) -> tuple[bool, Optional[str]]:
        weight_files = (
            list(stage_path.glob("*.safetensors")) +
            list(stage_path.glob("*.bin")) +
            list(stage_path.glob("*.pt")) +
            list(stage_path.glob("*.nemo"))
        )
        if not weight_files:
            return False, "No weight files found in local import."
        logger.info("Local import smoke test passed: %d weight file(s)", len(weight_files))
        return True, None
