"""Compatibility shim for the manifest-driven XTTS Romanian TTS plugin."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from runtime.inference.adapters.tts.manifest_tts_adapter import ManifestTtsAdapter
from runtime.inference.tts_plugins.manifest import TtsManifestCatalog


class XttsRomanianTtsAdapter(ManifestTtsAdapter):
    """Deprecated concrete name; behavior is provided by ManifestTtsAdapter."""

    ADAPTER_NAME = "XttsRomanianTtsAdapter"
    MODEL_ID = "xtts-v2-romanian-v2"

    def __init__(
        self,
        endpoint_url: Optional[str] = None,
        profiles_root: Optional[Path] = None,
    ) -> None:
        catalog = TtsManifestCatalog().load()
        super().__init__(catalog.resolve(self.MODEL_ID), profiles_root=profiles_root, catalog=catalog)
        if endpoint_url:
            # Preserve compatibility with callers that explicitly supplied the
            # old XTTS worker URL; it now points at the generic TTS host.
            self._endpoint_url = str(endpoint_url).rstrip("/")
