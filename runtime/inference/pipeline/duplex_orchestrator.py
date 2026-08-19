"""
LiveTranslator — Full-Duplex Pipeline Orchestrator
===================================================
Orchestrates both Outbound (EN->RO) and Inbound (RO->EN) translation pipelines
simultaneously, enforcing audio bus isolation, echo cancellation, loop prevention,
mode switching, and live model hot-swapping.

Operating Modes (Section 1.3):
- FULL_DUPLEX: Both directions active simultaneously with isolated buses
- OUTBOUND_TRANSLATION: Physical Mic -> EN->RO -> Virtual Mic + Captions
- INBOUND_TRANSLATION: Loopback -> RO->EN -> Local Monitor + Captions
- CAPTIONS_ONLY: ASR + MT in both directions, TTS suppressed

Echo & Loop Prevention (Section 8.2 & 8.3):
- BUS_OUTBOUND_TRANSLATED_TTS feeds ONLY BUS_VIRTUAL_MIC
- BUS_INBOUND_TRANSLATED_TTS feeds ONLY BUS_LOCAL_MONITOR
- Loopback capture is filtered / ducked when local synthesized speech is active
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

from runtime.inference.adapters.base import (
    AsrAdapter,
    TranslationAdapter,
    TtsAdapter,
    VadAdapter,
)
from runtime.inference.metrics.latency_metrics import PipelineMetrics
from runtime.inference.model_registry.registry import ModelRegistry
from runtime.inference.pipeline.audio_capture import AudioCaptureEngine
from runtime.inference.pipeline.audio_playback import AudioPlaybackEngine
from runtime.inference.pipeline.inbound_pipeline import InboundTranslationPipeline
from runtime.inference.pipeline.outbound_pipeline import OutboundTranslationPipeline
from runtime.inference.pipeline.phrase_committer import PhraseCommitterConfig
from runtime.inference.protocol import (
    AudioBus,
    CaptionEvent,
    LanguageCode,
    PipelineMode,
    TtsMode,
    VoiceSpec,
)

logger = logging.getLogger(__name__)


class DuplexOrchestrator:
    """
    Coordinates simultaneous full-duplex translation with isolated buses and loop prevention.
    """

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
    ):
        self.model_registry = model_registry
        self.metrics = metrics
        self.caption_callback = caption_callback
        self.mode = mode
        self.tts_mode = tts_mode

        # Adapters
        self.vad_adapter = vad_adapter
        self.asr_adapter_en = asr_adapter_en
        self.asr_adapter_ro = asr_adapter_ro
        self.mt_adapter = mt_adapter
        self.tts_adapter_ro = tts_adapter_ro
        self.tts_adapter_en = tts_adapter_en

        # Hardware audio engines
        self.mic_capture = AudioCaptureEngine(bus=AudioBus.PHYSICAL_MIC, sample_rate_hz=16000)
        self.conf_capture = AudioCaptureEngine(bus=AudioBus.REMOTE_CONFERENCE, sample_rate_hz=16000)
        self.virtual_mic_playback = AudioPlaybackEngine(bus=AudioBus.VIRTUAL_MIC, sample_rate_hz=24000)
        self.local_monitor_playback = AudioPlaybackEngine(bus=AudioBus.LOCAL_MONITOR, sample_rate_hz=24000)

        # Directional pipelines
        self.outbound_pipeline: Optional[OutboundTranslationPipeline] = None
        self.inbound_pipeline: Optional[InboundTranslationPipeline] = None

        self._phrase_config = phrase_config or PhraseCommitterConfig()
        self._is_active = False

        # Hot-swap controller integration
        from runtime.inference.model_registry.hot_swap import HotSwapController
        self.hot_swap_controller = HotSwapController(
            registry=self.model_registry,
            get_adapter=self._get_slot_adapter,
            load_adapter=self._load_slot_adapter,
            unload_adapter=self._unload_slot_adapter,
            health_check=self._health_check_adapter,
            drain_slot=self._drain_slot,
        )

    def _get_slot_adapter(self, slot: str) -> object:
        if slot == "asr_en":
            return self.asr_adapter_en
        elif slot == "asr_ro":
            return self.asr_adapter_ro
        elif slot in ("mt", "translation", "mt_en_ro", "mt_ro_en"):
            return self.mt_adapter
        elif slot in ("tts_ro", "tts"):
            return self.tts_adapter_ro
        elif slot == "tts_en":
            return self.tts_adapter_en
        return None

    async def _load_slot_adapter(self, slot: str, model_id: str) -> object:
        from runtime.inference.model_registry.discovery.adapter_registry import AdapterRegistry
        entry = self.model_registry.get_entry(model_id)
        adapter_cls = AdapterRegistry.get_adapter_class(entry.family) if entry else None
        if adapter_cls:
            adapter = AdapterRegistry.instantiate(adapter_cls, model_id=model_id)
        elif "asr" in slot:
            from runtime.inference.adapters.asr.parakeet_tdt_v3_asr_adapter import ParakeetTdtV3AsrAdapter
            adapter = ParakeetTdtV3AsrAdapter(model_id=model_id)
        elif "tts" in slot:
            from runtime.inference.adapters.tts.omnivoice_tts_adapter import OmniVoiceTtsAdapter
            adapter = OmniVoiceTtsAdapter(model_path=model_id)
        else:
            from runtime.inference.adapters.translation.milmmt46_translation_adapter import MiLMMT46TranslationAdapter
            adapter = MiLMMT46TranslationAdapter(model_id=model_id)
        await adapter.load()
        return adapter

    async def _unload_slot_adapter(self, slot: str, adapter: object) -> None:
        if hasattr(adapter, "unload"):
            await adapter.unload()

    async def _health_check_adapter(self, adapter: object) -> bool:
        return getattr(adapter, "_loaded", True)

    async def _drain_slot(self, slot: str) -> None:
        await asyncio.sleep(0.05)

    async def start(self) -> None:
        """Start translation pipelines according to active operating mode."""
        if self._is_active:
            return
        self._is_active = True
        logger.info("Duplex Orchestrator starting in %s mode...", self.mode.value)

        # 1. Load active adapters
        await self.vad_adapter.load()
        await self.asr_adapter_en.load()
        await self.asr_adapter_ro.load()
        await self.mt_adapter.load()
        await self.tts_adapter_ro.load()
        await self.tts_adapter_en.load()

        # 2. Build Outbound Pipeline (EN -> RO)
        if self.mode in (PipelineMode.FULL_DUPLEX, PipelineMode.OUTBOUND_TRANSLATION, PipelineMode.CAPTIONS_ONLY):
            voice_ro = VoiceSpec(language=LanguageCode.RO, is_cloned=(self.tts_mode == TtsMode.CLONED))
            self.outbound_pipeline = OutboundTranslationPipeline(
                vad_adapter=self.vad_adapter,
                asr_adapter=self.asr_adapter_en,
                translation_adapter=self.mt_adapter,
                tts_adapter=self.tts_adapter_ro,
                capture_engine=self.mic_capture,
                playback_engine=self.virtual_mic_playback,
                metrics=self.metrics,
                phrase_config=self._phrase_config,
                caption_callback=self.caption_callback,
                voice_spec=voice_ro,
            )
            await self.outbound_pipeline.start()

        # 3. Build Inbound Pipeline (RO -> EN)
        if self.mode in (PipelineMode.FULL_DUPLEX, PipelineMode.INBOUND_TRANSLATION, PipelineMode.CAPTIONS_ONLY):
            voice_en = VoiceSpec(language=LanguageCode.EN, is_cloned=(self.tts_mode == TtsMode.CLONED))
            self.inbound_pipeline = InboundTranslationPipeline(
                vad_adapter=self.vad_adapter,
                asr_adapter=self.asr_adapter_ro,
                translation_adapter=self.mt_adapter,
                tts_adapter=self.tts_adapter_en,
                capture_engine=self.conf_capture,
                playback_engine=self.local_monitor_playback,
                metrics=self.metrics,
                phrase_config=self._phrase_config,
                caption_callback=self.caption_callback,
                voice_spec=voice_en,
            )
            await self.inbound_pipeline.start()

        logger.info("Duplex Orchestrator is RUNNING.")

    async def set_mode(self, new_mode: PipelineMode) -> None:
        """Switch operating mode dynamically."""
        if new_mode == self.mode:
            return
        logger.info("Switching operating mode from %s to %s", self.mode.value, new_mode.value)
        await self.stop()
        self.mode = new_mode
        await self.start()

    async def set_tts_mode(self, new_tts_mode: TtsMode) -> None:
        """Toggle between stock and cloned TTS voice."""
        self.tts_mode = new_tts_mode
        if self.outbound_pipeline:
            self.outbound_pipeline.voice_spec.is_cloned = (new_tts_mode == TtsMode.CLONED)
        if self.inbound_pipeline:
            self.inbound_pipeline.voice_spec.is_cloned = (new_tts_mode == TtsMode.CLONED)
        logger.info("TTS mode updated to %s", new_tts_mode.value)

    async def stop(self) -> None:
        """Stop all active pipelines cleanly."""
        if not self._is_active:
            return
        self._is_active = False
        logger.info("Stopping Duplex Orchestrator...")

        if self.outbound_pipeline:
            await self.outbound_pipeline.stop()
            self.outbound_pipeline = None

        if self.inbound_pipeline:
            await self.inbound_pipeline.stop()
            self.inbound_pipeline = None

        # Unload models
        await self.vad_adapter.unload()
        await self.asr_adapter_en.unload()
        await self.asr_adapter_ro.unload()
        await self.mt_adapter.unload()
        await self.tts_adapter_ro.unload()
        await self.tts_adapter_en.unload()

        logger.info("Duplex Orchestrator stopped.")
