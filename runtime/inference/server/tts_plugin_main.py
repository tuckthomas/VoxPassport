"""VoxPassport daemon entrypoint with manifest-driven TTS plugin routing."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.inference.adapters.tts.manifest_tts_adapter import ManifestTtsAdapter
from runtime.inference.server.main import LiveTranslatorApp as BaseLiveTranslatorApp
from runtime.inference.tts_plugins import TtsManifestCatalog, manifest_registry_entry


class LiveTranslatorApp(BaseLiveTranslatorApp):
    """Adds arbitrary manifest-driven TTS models without per-model daemon code."""

    def __init__(self, data_dir: Path) -> None:
        super().__init__(data_dir)
        self.tts_manifest_catalog = TtsManifestCatalog().load()
        self._manifest_tts_adapters: dict[str, ManifestTtsAdapter] = {}
        for manifest in self.tts_manifest_catalog.manifests():
            existing = self.registry.get_entry(manifest.model_id)
            self.registry.register(manifest_registry_entry(manifest, existing))
            # Canonicalization for install/activate/uninstall comes from the
            # manifest rather than another set of model-manager constants.
            for alias in (manifest.model_id, *manifest.aliases):
                self.model_manager._ALIASES[str(alias).strip().lower()] = manifest.model_id

    def _manifest_for_model(self, model_name: str | None):
        return self.tts_manifest_catalog.resolve_optional(model_name)

    def _normalize_clone_model(self, model_name: str | None) -> str:
        manifest = self._manifest_for_model(model_name)
        if manifest is not None:
            return manifest.model_id

        # Preserve old fuzzy aliases for compatibility, but immediately feed the
        # legacy normalization result back through the manifest catalog. This
        # guarantees an old spelling such as a MOSS/OpenMOSS variant still lands
        # on the generic plugin path instead of the inherited concrete branch.
        legacy = super()._normalize_clone_model(model_name)
        manifest = self._manifest_for_model(legacy)
        return manifest.model_id if manifest is not None else legacy

    def _tts_engine_for_model(self, model_name: str | None):
        manifest = self._manifest_for_model(self._normalize_clone_model(model_name))
        if manifest is not None:
            adapter = self._manifest_tts_adapters.get(manifest.model_id)
            if adapter is None:
                adapter = ManifestTtsAdapter(
                    manifest,
                    profiles_root=self.profiles_dir,
                    catalog=self.tts_manifest_catalog,
                )
                self._manifest_tts_adapters[manifest.model_id] = adapter
            return adapter, manifest.display_name
        return super()._tts_engine_for_model(model_name)

    def _register_external_tts_if_needed(self, canonical: str) -> None:
        manifest = self._manifest_for_model(canonical)
        if manifest is not None:
            existing = self.registry.get_entry(manifest.model_id)
            self.registry.register(manifest_registry_entry(manifest, existing))
            return
        super()._register_external_tts_if_needed(canonical)


async def main() -> None:
    parser = argparse.ArgumentParser(description="VoxPassport Runtime Daemon")
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args()
    app = LiveTranslatorApp(Path(args.data_dir))
    await app.start()
    try:
        while True:
            await asyncio.sleep(1)
    except (asyncio.CancelledError, KeyboardInterrupt):
        await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
