"""Compatibility shim for the manifest-driven VoxCPM2 TTS plugin."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from runtime.inference.adapters.tts.manifest_tts_adapter import ManifestTtsAdapter
from runtime.inference.tts_plugins.manifest import TtsManifestCatalog

logger = logging.getLogger(__name__)


class VoxCpmTtsAdapter(ManifestTtsAdapter):
    """Deprecated concrete name; behavior is provided by ManifestTtsAdapter."""

    ADAPTER_NAME = "VoxCpmTtsAdapter"
    MODEL_ID = "voxcpm-2"

    def __init__(
        self,
        model_path: Optional[str] = None,
        device: str = "cuda",
        shared_engine: Optional[object] = None,
        endpoint_url: Optional[str] = None,
        profiles_root: Optional[Path] = None,
    ) -> None:
        del model_path, device
        if shared_engine is not None:
            logger.warning("Ignoring shared_engine for manifest-driven VoxCPM2")
        catalog = TtsManifestCatalog().load()
        super().__init__(catalog.resolve(self.MODEL_ID), profiles_root=profiles_root, catalog=catalog)
        if endpoint_url:
            logger.warning(
                "VoxCpmTtsAdapter(endpoint_url=...) is deprecated; set VOXPASSPORT_VOXCPM_TTS_URL for the backend or VOXPASSPORT_TTS_HOST_URL for the generic host"
            )
