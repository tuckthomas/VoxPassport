"""VoxPassport daemon entrypoint with the optional XTTS Romanian worker adapter."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.inference.adapters.tts.xtts_romanian_tts_adapter import XttsRomanianTtsAdapter
from runtime.inference.model_registry.registry import ModelRegistryEntry
from runtime.inference.protocol import InstallationStatus, ModelCapability, RecommendationState
from runtime.inference.server.main import LiveTranslatorApp as BaseLiveTranslatorApp


XTTS_MODEL_ID = "xtts-v2-romanian-v2"


def _xtts_registry_entry(existing: ModelRegistryEntry | None = None) -> ModelRegistryEntry:
    """Create catalog metadata while preserving persistent user/runtime state."""
    entry = ModelRegistryEntry(
        model_id=XTTS_MODEL_ID,
        name="XTTS-v2 Romanian v2",
        family="xtts-v2",
        provider="eduardem / Coqui",
        capability=ModelCapability.TTS,
        upstream_id="eduardem/xtts-v2-romanian-v2",
        revision="main",
        supported_source_languages=[],
        supported_target_languages=["en", "ro"],
        supports_english=True,
        supports_romanian=True,
        streaming_support=True,
        voice_cloning_support=True,
        cross_lingual_voice_cloning=True,
        required_runtime="isolated_xtts_worker",
        min_runtime_version="coqui-tts>=0.27.5",
        quantization_options=["fp32/default"],
        estimated_download_size_gb=2.35,
        installed_size_gb=None,
        expected_vram_tiers={"default": "~3-4GB planning range; benchmark locally"},
        expected_ram_gb=6.0,
        license="Coqui Public Model License (CPML)",
        commercial_use="verify",
        redistribution="verify",
        trust_level="COMMUNITY_VERIFIED",
        recommendation_state=RecommendationState.RECOMMENDED_FOR_LOCAL_BENCHMARK,
    )
    if existing is not None:
        entry.installation_status = existing.installation_status
        entry.installed_size_gb = existing.installed_size_gb
        entry.last_used = existing.last_used
        entry.last_benchmarked = existing.last_benchmarked
        entry.is_active = existing.is_active
        entry.is_pinned = existing.is_pinned
        entry.eligible_for_cleanup = existing.eligible_for_cleanup
        entry.is_pipeline_enabled = existing.is_pipeline_enabled
        entry.local_benchmarks = dict(existing.local_benchmarks)
    return entry


class LiveTranslatorApp(BaseLiveTranslatorApp):
    """Adds XTTS without importing Coqui into the primary inference process."""

    def __init__(self, data_dir: Path) -> None:
        super().__init__(data_dir)
        self.tts_xtts_romanian = XttsRomanianTtsAdapter(profiles_root=self.profiles_dir)
        existing = self.registry.get_entry(XTTS_MODEL_ID)
        self.registry.register(_xtts_registry_entry(existing))

    @staticmethod
    def _normalize_clone_model(model_name: str | None) -> str:
        model = str(model_name or "omnivoice").strip().lower()
        if model in {
            "xtts-v2-romanian-v2", "xtts-romanian-v2", "xtts-ro-v2",
            "eduardem/xtts-v2-romanian-v2",
        } or ("xtts" in model and "roman" in model):
            return XTTS_MODEL_ID
        return BaseLiveTranslatorApp._normalize_clone_model(model_name)

    def _tts_engine_for_model(self, model_name: str | None):
        model = self._normalize_clone_model(model_name)
        if model == XTTS_MODEL_ID:
            return self.tts_xtts_romanian, "XTTS-v2 Romanian v2"
        return super()._tts_engine_for_model(model_name)


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
