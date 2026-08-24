"""VoxPassport full-duplex translation orchestrator."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Callable, Optional

from runtime.inference.adapters.base import AsrAdapter, TranslationAdapter, TtsAdapter, VadAdapter
from runtime.inference.metrics.latency_metrics import PipelineMetrics
from runtime.inference.model_registry.registry import ModelRegistry
from runtime.inference.pipeline.audio_capture import AudioCaptureEngine
from runtime.inference.pipeline.audio_playback import AudioPlaybackEngine
from runtime.inference.pipeline.inbound_pipeline import InboundTranslationPipeline
from runtime.inference.pipeline.outbound_pipeline import OutboundTranslationPipeline
from runtime.inference.pipeline.phrase_committer import PhraseCommitterConfig
from runtime.inference.protocol import AudioBus, CaptionEvent, LanguageCode, PipelineMode, TtsMode, VoiceSpec

logger = logging.getLogger(__name__)


class DuplexOrchestrator:
    """Coordinates both directions and keeps live pipeline references hot-swappable."""

    DIARIZATION_MODEL_ID = "nvidia-diar-streaming-sortformer-4spk-v2.1"

    def __init__(
        self,
        model_registry: ModelRegistry,
        metrics: PipelineMetrics,
        vad_adapter: VadAdapter,
        asr_adapter_en: AsrAdapter,
        asr_adapter_ro: AsrAdapter,
        mt_adapter: TranslationAdapter,
        tts_adapter_ro: TtsAdapter,
        tts_adapter_en: TtsAdapter,
        caption_callback: Optional[Callable[[CaptionEvent], None]] = None,
        phrase_config: Optional[PhraseCommitterConfig] = None,
        mode: PipelineMode = PipelineMode.FULL_DUPLEX,
        tts_mode: TtsMode = TtsMode.STOCK,
        user_language: LanguageCode = LanguageCode.EN,
        remote_language: LanguageCode = LanguageCode.RO,
    ) -> None:
        self.model_registry = model_registry
        self.metrics = metrics
        self.caption_callback = caption_callback
        self.mode = mode
        self.tts_mode = tts_mode
        self.user_language = user_language
        self.remote_language = remote_language

        self.vad_adapter = vad_adapter
        self.asr_adapter_en = asr_adapter_en
        self.asr_adapter_ro = asr_adapter_ro
        self.mt_adapter = mt_adapter
        self.tts_adapter_ro = tts_adapter_ro
        self.tts_adapter_en = tts_adapter_en
        self._tts_profiles_root = Path(
            getattr(tts_adapter_ro, "_profiles_root", Path("data") / "voice_profiles")
        )
        self.diarization_adapter: Optional[object] = None

        self.mic_capture = AudioCaptureEngine(bus=AudioBus.PHYSICAL_MIC, sample_rate_hz=16000)
        self.conf_capture = AudioCaptureEngine(bus=AudioBus.REMOTE_CONFERENCE, sample_rate_hz=16000)
        self.virtual_mic_playback = AudioPlaybackEngine(bus=AudioBus.VIRTUAL_MIC, sample_rate_hz=24000)
        self.local_monitor_playback = AudioPlaybackEngine(bus=AudioBus.LOCAL_MONITOR, sample_rate_hz=24000)
        self.outbound_pipeline: Optional[OutboundTranslationPipeline] = None
        self.inbound_pipeline: Optional[InboundTranslationPipeline] = None
        self._phrase_config = phrase_config or PhraseCommitterConfig()
        self._is_active = False

        from runtime.inference.model_registry.hot_swap import HotSwapController
        self.hot_swap_controller = HotSwapController(
            registry=self.model_registry,
            get_adapter=self._get_slot_adapter,
            set_adapter=self._set_slot_adapter,
            load_adapter=self._load_slot_adapter,
            unload_adapter=self._unload_slot_adapter,
            health_check=self._health_check_adapter,
            drain_slot=self._drain_slot,
        )

    @staticmethod
    async def _load_unique(adapters: list[object]) -> None:
        seen: set[int] = set()
        for adapter in adapters:
            if adapter is None or id(adapter) in seen:
                continue
            seen.add(id(adapter))
            await adapter.load()

    @staticmethod
    async def _unload_unique(adapters: list[object]) -> None:
        seen: set[int] = set()
        for adapter in adapters:
            if adapter is None or id(adapter) in seen:
                continue
            seen.add(id(adapter))
            try:
                await adapter.unload()
            except Exception:
                logger.exception("Adapter unload failed")

    def _get_slot_adapter(self, slot: str) -> object:
        return {
            "asr_en": self.asr_adapter_en,
            "asr_ro": self.asr_adapter_ro,
            "translation_en_ro": self.mt_adapter,
            "translation_ro_en": self.mt_adapter,
            "tts_ro": self.tts_adapter_ro,
            "tts_en": self.tts_adapter_en,
            "vad": self.vad_adapter,
        }.get(slot)

    def _set_slot_adapter(self, slot: str, adapter: object) -> None:
        if slot == "asr_en":
            self.asr_adapter_en = adapter
            if self.outbound_pipeline:
                self.outbound_pipeline.asr_adapter = adapter
        elif slot == "asr_ro":
            self.asr_adapter_ro = adapter
            if self.inbound_pipeline:
                self.inbound_pipeline.asr_adapter = adapter
        elif slot in {"translation_en_ro", "translation_ro_en"}:
            self.mt_adapter = adapter
            if self.outbound_pipeline:
                self.outbound_pipeline.translation_adapter = adapter
            if self.inbound_pipeline:
                self.inbound_pipeline.translation_adapter = adapter
        elif slot == "tts_ro":
            self.tts_adapter_ro = adapter
            if self.outbound_pipeline:
                self.outbound_pipeline.tts_adapter = adapter
        elif slot == "tts_en":
            self.tts_adapter_en = adapter
            if self.inbound_pipeline:
                self.inbound_pipeline.tts_adapter = adapter
        elif slot == "vad":
            self.vad_adapter = adapter
            if self.outbound_pipeline:
                self.outbound_pipeline.vad_adapter = adapter
            if self.inbound_pipeline:
                self.inbound_pipeline.vad_adapter = adapter
        else:
            raise ValueError(f"Unknown runtime slot: {slot}")

    async def _load_slot_adapter(self, slot: str, model_id: str) -> object:
        mid = str(model_id).lower()
        if slot.startswith("tts_"):
            from runtime.inference.adapters.tts.manifest_tts_adapter import ManifestTtsAdapter
            from runtime.inference.tts_plugins.manifest import TtsManifestCatalog

            catalog = TtsManifestCatalog().load()
            manifest = catalog.resolve(model_id)
            adapter = ManifestTtsAdapter(
                manifest,
                profiles_root=self._tts_profiles_root,
                catalog=catalog,
            )
        elif slot.startswith("asr_"):
            if "parakeet" not in mid:
                raise ValueError(f"No production streaming ASR adapter is implemented for {model_id!r}")
            from runtime.inference.adapters.asr.parakeet_tdt_v3_asr_adapter import ParakeetTdtV3AsrAdapter
            adapter = ParakeetTdtV3AsrAdapter(model_id=model_id)
        elif slot.startswith("translation_"):
            if "milmmt" not in mid:
                raise ValueError(f"No production translation adapter is implemented for {model_id!r}")
            from runtime.inference.adapters.translation.milmmt46_translation_adapter import MiLMMT46TranslationAdapter
            adapter = MiLMMT46TranslationAdapter(model_size="4b" if "4b" in mid else "1b")
        elif slot == "vad":
            if "silero" not in mid:
                raise ValueError(f"No production VAD adapter is implemented for {model_id!r}")
            from runtime.inference.adapters.vad.silero_vad_adapter import SileroVadAdapter
            adapter = SileroVadAdapter()
        else:
            raise ValueError(f"Unsupported runtime slot: {slot}")
        await adapter.load()
        return adapter

    async def _unload_slot_adapter(self, slot: str, adapter: object) -> None:
        for other in (
            "asr_en", "asr_ro", "translation_en_ro", "translation_ro_en",
            "tts_ro", "tts_en", "vad",
        ):
            if other != slot and self._get_slot_adapter(other) is adapter:
                return
        if hasattr(adapter, "unload"):
            await adapter.unload()

    async def _health_check_adapter(self, adapter: object) -> bool:
        if hasattr(adapter, "health_check"):
            try:
                return bool(await adapter.health_check())
            except Exception:
                return False
        return bool(getattr(adapter, "_loaded", True))

    async def _drain_slot(self, slot: str) -> None:
        await asyncio.sleep(0)

    async def set_tts_adapter(self, adapter: TtsAdapter) -> None:
        await adapter.load()
        old = [self.tts_adapter_ro, self.tts_adapter_en]
        self._set_slot_adapter("tts_ro", adapter)
        self._set_slot_adapter("tts_en", adapter)
        for previous in {id(a): a for a in old if a is not None and a is not adapter}.values():
            try:
                await previous.unload()
            except Exception:
                logger.exception("Failed to unload previous TTS adapter")

    async def set_translation_adapter(self, adapter: TranslationAdapter) -> None:
        await adapter.load()
        previous = self.mt_adapter
        self._set_slot_adapter("translation_en_ro", adapter)
        if previous is not adapter:
            try:
                await previous.unload()
            except Exception:
                logger.exception("Failed to unload previous translation adapter")

    async def set_asr_adapters(self, adapter_en: AsrAdapter, adapter_ro: Optional[AsrAdapter] = None) -> None:
        adapter_ro = adapter_ro or adapter_en
        was_active = self._is_active
        if was_active:
            await self.stop()
        self.asr_adapter_en = adapter_en
        self.asr_adapter_ro = adapter_ro
        if was_active:
            await self.start()

    async def set_vad_adapter(self, adapter: VadAdapter) -> None:
        was_active = self._is_active
        if was_active:
            await self.stop()
        self.vad_adapter = adapter
        if was_active:
            await self.start()

    async def set_language_pair(self, user_language: LanguageCode, remote_language: LanguageCode) -> None:
        if user_language == self.user_language and remote_language == self.remote_language:
            return
        was_active = self._is_active
        if was_active:
            await self.stop()
        self.user_language = user_language
        self.remote_language = remote_language
        if was_active:
            await self.start()

    async def _maybe_load_diarization_sidecar(self) -> Optional[object]:
        mode = os.getenv("VOXPASSPORT_DIARIZATION", "auto").strip().lower()
        if mode in {"0", "off", "false", "disabled", "none"}:
            return None
        project_root = Path(__file__).resolve().parents[3]
        model_path = project_root / "models" / self.DIARIZATION_MODEL_ID
        if not model_path.exists():
            if mode in {"1", "on", "true", "enabled", "force"}:
                logger.warning(
                    "Diarization requested but %s is not downloaded; continuing without it",
                    model_path,
                )
            return None
        try:
            from runtime.inference.adapters.diarization import SortformerStreamingDiarizationAdapter
            adapter = SortformerStreamingDiarizationAdapter(model_path=model_path)
            await adapter.load()
            logger.info("Parallel inbound speaker diarization enabled")
            return adapter
        except Exception:
            logger.warning("Could not start optional Sortformer diarization sidecar", exc_info=True)
            return None

    def _voice_spec_for_current_mode(self, language: LanguageCode) -> VoiceSpec:
        if self.tts_mode == TtsMode.CLONED:
            return VoiceSpec(language=language, voice_profile_id="active", is_cloned=True)
        return VoiceSpec(language=language, voice_profile_id="default", is_cloned=False)

    async def start(self) -> None:
        if self._is_active:
            return
        self._is_active = True
        await self._load_unique([
            self.vad_adapter, self.asr_adapter_en, self.asr_adapter_ro,
            self.mt_adapter, self.tts_adapter_ro, self.tts_adapter_en,
        ])
        self.diarization_adapter = await self._maybe_load_diarization_sidecar()
        synthesize_audio = self.mode != PipelineMode.CAPTIONS_ONLY

        if self.mode in (PipelineMode.FULL_DUPLEX, PipelineMode.OUTBOUND_TRANSLATION, PipelineMode.CAPTIONS_ONLY):
            self.outbound_pipeline = OutboundTranslationPipeline(
                vad_adapter=self.vad_adapter,
                asr_adapter=self.asr_adapter_en,
                translation_adapter=self.mt_adapter,
                tts_adapter=self.tts_adapter_ro,
                capture_engine=self.mic_capture,
                playback_engine=self.virtual_mic_playback,
                metrics=self.metrics,
                caption_callback=self.caption_callback,
                phrase_config=self._phrase_config,
                voice_spec=self._voice_spec_for_current_mode(self.remote_language),
                source_language=self.user_language,
                target_language=self.remote_language,
                synthesize_audio=synthesize_audio,
            )
        if self.mode in (PipelineMode.FULL_DUPLEX, PipelineMode.INBOUND_TRANSLATION, PipelineMode.CAPTIONS_ONLY):
            self.inbound_pipeline = InboundTranslationPipeline(
                vad_adapter=self.vad_adapter,
                asr_adapter=self.asr_adapter_ro,
                translation_adapter=self.mt_adapter,
                tts_adapter=self.tts_adapter_en,
                capture_engine=self.conf_capture,
                playback_engine=self.local_monitor_playback,
                metrics=self.metrics,
                caption_callback=self.caption_callback,
                phrase_config=self._phrase_config,
                voice_spec=self._voice_spec_for_current_mode(self.user_language),
                source_language=self.remote_language,
                target_language=self.user_language,
                synthesize_audio=synthesize_audio,
                diarization_adapter=self.diarization_adapter,
            )
        await self.mic_capture.start()
        await self.conf_capture.start()
        await self.virtual_mic_playback.start()
        await self.local_monitor_playback.start()
        if self.outbound_pipeline:
            await self.outbound_pipeline.start()
        if self.inbound_pipeline:
            await self.inbound_pipeline.start()
        logger.info(
            "Duplex orchestrator started: mode=%s tts=%s pair=%s<->%s",
            self.mode.value, self.tts_mode.value, self.user_language.value, self.remote_language.value,
        )

    async def stop(self) -> None:
        if not self._is_active:
            return
        self._is_active = False
        if self.outbound_pipeline:
            await self.outbound_pipeline.stop()
        if self.inbound_pipeline:
            await self.inbound_pipeline.stop()
        self.outbound_pipeline = None
        self.inbound_pipeline = None
        await self._unload_unique([
            self.diarization_adapter, self.tts_adapter_ro, self.tts_adapter_en,
            self.mt_adapter, self.asr_adapter_en, self.asr_adapter_ro, self.vad_adapter,
        ])
        self.diarization_adapter = None
        await self.local_monitor_playback.stop()
        await self.virtual_mic_playback.stop()
        await self.conf_capture.stop()
        await self.mic_capture.stop()
        logger.info("Duplex orchestrator stopped")

    async def set_mode(self, mode: PipelineMode) -> None:
        if mode == self.mode:
            return
        was_active = self._is_active
        if was_active:
            await self.stop()
        self.mode = mode
        if was_active:
            await self.start()

    async def set_tts_mode(self, tts_mode: TtsMode) -> None:
        if tts_mode == self.tts_mode:
            return
        was_active = self._is_active
        if was_active:
            await self.stop()
        self.tts_mode = tts_mode
        if was_active:
            await self.start()
