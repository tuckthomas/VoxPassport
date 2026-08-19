"""
LiveTranslator - HuggingFace Model Installer
Downloads models from huggingface.co with resumable HTTP transfers,
SHA-256 checksum verification, file manifest validation, revision pinning,
and runtime compatibility check.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
from pathlib import Path
from typing import AsyncIterator, Optional

from runtime.inference.model_registry.installers.base import (
    InstallerBase,
    InstallProgress,
    ValidationResult,
)

logger = logging.getLogger(__name__)

_HF_ENDPOINT = "https://huggingface.co"
_CHUNK_SIZE = 1 << 20   # 1 MiB


def _hf_available() -> bool:
    return importlib.util.find_spec("huggingface_hub") is not None


class HuggingFaceInstaller(InstallerBase):
    """Downloads models from HuggingFace Hub with resumable transfers."""

    def __init__(
        self,
        model_store_dir: Path,
        staging_dir: Path,
        hf_token: Optional[str] = None,
        capability_hint: Optional[str] = None,
    ):
        super().__init__(model_store_dir, staging_dir)
        self.hf_token = hf_token or os.environ.get("HF_TOKEN")
        self.capability_hint = capability_hint

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    async def _download_to_staging(
        self,
        model_id: str,
        upstream_id: str,
        revision: str,
        stage_path: Path,
    ) -> AsyncIterator[InstallProgress]:
        stage_path.mkdir(parents=True, exist_ok=True)
        logger.info("[%s] HF download: %s @ %s", model_id, upstream_id, revision)

        if _hf_available():
            async for p in self._download_with_hf_hub(model_id, upstream_id, revision, stage_path):
                yield p
        else:
            async for p in self._download_raw_https(model_id, upstream_id, revision, stage_path):
                yield p

    async def _download_with_hf_hub(
        self,
        model_id: str,
        upstream_id: str,
        revision: str,
        stage_path: Path,
    ) -> AsyncIterator[InstallProgress]:
        """Use huggingface_hub.snapshot_download (preferred)."""
        from huggingface_hub import snapshot_download, list_repo_tree

        total_bytes = 0
        try:
            for item in list_repo_tree(upstream_id, revision=revision, token=self.hf_token, recursive=True):
                if hasattr(item, "size") and item.size:
                    total_bytes += item.size
        except Exception:
            total_bytes = 0

        yield InstallProgress(
            model_id=model_id,
            phase="downloading",
            bytes_total=total_bytes,
            message=f"Downloading {upstream_id} @ {revision}...",
        )

        loop = asyncio.get_event_loop()
        downloaded_path = await loop.run_in_executor(
            None,
            lambda: snapshot_download(
                repo_id=upstream_id,
                revision=revision,
                local_dir=str(stage_path),
                token=self.hf_token,
                local_dir_use_symlinks=False,
                resume_download=True,
            ),
        )

        actual_bytes = sum(f.stat().st_size for f in Path(downloaded_path).rglob("*") if f.is_file())
        yield InstallProgress(
            model_id=model_id,
            phase="downloading",
            bytes_downloaded=actual_bytes,
            bytes_total=actual_bytes,
            message="Download complete.",
        )

    async def _download_raw_https(
        self,
        model_id: str,
        upstream_id: str,
        revision: str,
        stage_path: Path,
    ) -> AsyncIterator[InstallProgress]:
        """Fallback: HF API file list + per-file Range-header resumption."""
        import urllib.request

        api_url = f"{_HF_ENDPOINT}/api/models/{upstream_id}/tree/{revision}"
        req_headers = {"Authorization": f"Bearer {self.hf_token}"} if self.hf_token else {}

        try:
            req = urllib.request.Request(api_url, headers=req_headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                file_list = json.loads(resp.read())
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch HF file list: {exc}") from exc

        files = [f for f in file_list if f.get("type") == "file"]
        total_bytes = sum(f.get("size", 0) for f in files)
        downloaded_bytes = 0

        for file_info in files:
            if self._cancelled:
                return

            rel_path = file_info["path"]
            file_size = file_info.get("size", 0)
            dest = stage_path / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)

            url = f"{_HF_ENDPOINT}/{upstream_id}/resolve/{revision}/{rel_path}"
            downloaded_bytes = await self._download_file_resumable(
                url=url, dest=dest, headers=req_headers,
                file_size=file_size, model_id=model_id,
                downloaded_so_far=downloaded_bytes, total_bytes=total_bytes,
            )

            yield InstallProgress(
                model_id=model_id,
                phase="downloading",
                bytes_downloaded=downloaded_bytes,
                bytes_total=total_bytes,
                message=f"Downloaded {rel_path}",
            )

    async def _download_file_resumable(
        self,
        url: str, dest: Path, headers: dict,
        file_size: int, model_id: str,
        downloaded_so_far: int, total_bytes: int,
    ) -> int:
        """Download single file with HTTP Range resumption."""
        import urllib.request

        existing_size = dest.stat().st_size if dest.exists() else 0
        if existing_size > 0 and existing_size == file_size:
            return downloaded_so_far + file_size

        req_headers = dict(headers)
        if existing_size > 0:
            req_headers["Range"] = f"bytes={existing_size}-"

        def _fetch():
            req = urllib.request.Request(url, headers=req_headers)
            mode = "ab" if existing_size > 0 else "wb"
            with urllib.request.urlopen(req, timeout=60) as resp, open(dest, mode) as f:
                while chunk := resp.read(_CHUNK_SIZE):
                    f.write(chunk)

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _fetch)
        return downloaded_so_far + file_size

    # ------------------------------------------------------------------
    # Validate
    # ------------------------------------------------------------------

    async def _validate(
        self,
        stage_path: Path,
        expected_revision: str,
        expected_checksums: Optional[dict[str, str]],
    ) -> ValidationResult:
        result = ValidationResult(ok=True)

        model_files = [f for f in stage_path.rglob("*") if f.is_file()]
        if not model_files:
            result.add_error("Staged directory is empty.")
            return result

        result.actual_size_gb = sum(f.stat().st_size for f in model_files) / 1e9

        # Checksum verification
        if expected_checksums:
            loop = asyncio.get_event_loop()
            for rel_path, expected_sha256 in expected_checksums.items():
                file_path = stage_path / rel_path
                if not file_path.exists():
                    result.add_error(f"Missing expected file: {rel_path}")
                    continue
                actual = await loop.run_in_executor(None, self.sha256_file, file_path)
                if actual != expected_sha256.lower():
                    result.add_error(
                        f"Checksum mismatch {rel_path}: expected {expected_sha256[:12]}... got {actual[:12]}..."
                    )
        else:
            result.add_warning("No checksums provided - skipping SHA-256 verification.")

        # Config file presence
        if not any((stage_path / c).exists() for c in ["config.json", "model_card.json"]):
            result.add_warning("No config.json found - non-standard model layout.")

        # Runtime compatibility
        try:
            import torch
            major, minor = (int(x) for x in torch.__version__.split(".")[:2])
            if (major, minor) < (2, 0):
                result.add_error(f"PyTorch {torch.__version__} is too old. Requires >= 2.0.0.")
        except ImportError:
            result.add_warning("PyTorch not importable - cannot verify runtime compatibility.")

        return result

    # ------------------------------------------------------------------
    # Smoke test
    # ------------------------------------------------------------------

    async def _smoke_test(self, stage_path: Path) -> tuple[bool, Optional[str]]:
        """
        Verify weight files exist and config is loadable.
        Does NOT log any audio content, transcripts, or translations.
        """
        loop = asyncio.get_event_loop()

        def _run():
            try:
                config_path = stage_path / "config.json"
                if config_path.exists():
                    with open(config_path) as f:
                        config = json.load(f)
                    arch = config.get("architectures", ["unknown"])[0]
                    logger.info("Smoke test: architecture=%s", arch)

                weight_files = (
                    list(stage_path.glob("*.safetensors")) +
                    list(stage_path.glob("*.bin")) +
                    list(stage_path.glob("*.pt")) +
                    list(stage_path.glob("*.nemo"))
                )
                if not weight_files:
                    return False, "No weight files found (.safetensors / .bin / .pt / .nemo)"

                logger.info(
                    "Smoke test passed: %d weight file(s), largest=%.1f MB",
                    len(weight_files),
                    max(f.stat().st_size for f in weight_files) / 1e6,
                )
                return True, None
            except Exception as exc:
                return False, f"Smoke test exception: {exc}"

        return await loop.run_in_executor(None, _run)
