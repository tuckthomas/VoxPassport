"""
End-to-End Test for LiveTranslator Duplex Translation Pipeline.

Simulates:
1. Microphone Audio Ingestion (Physical Mic)
2. Outbound Translation Pipeline (EN -> RO)
3. Conference Audio Ingestion (Meet Audio Output)
4. Inbound Translation Pipeline (RO -> EN)
5. Caption Streaming Dispatch & Metrics
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from runtime.inference.adapters.asr.nemotron35_streaming_asr_adapter import Nemotron35StreamingAsrAdapter
from runtime.inference.adapters.translation.milmmt46_translation_adapter import MiLMMT46TranslationAdapter
from runtime.inference.adapters.tts.omnivoice_tts_adapter import OmniVoiceTtsAdapter
from runtime.inference.adapters.vad.silero_vad_adapter import SileroVadAdapter
from runtime.inference.metrics.latency_metrics import PipelineMetrics
from runtime.inference.model_registry.registry import ModelRegistry
from runtime.inference.pipeline.audio_capture import AudioCaptureEngine
from runtime.inference.pipeline.audio_playback import AudioPlaybackEngine
from runtime.inference.pipeline.duplex_orchestrator import DuplexOrchestrator
from runtime.inference.pipeline.inbound_pipeline import InboundTranslationPipeline
from runtime.inference.pipeline.outbound_pipeline import OutboundTranslationPipeline
from runtime.inference.pipeline.phrase_committer import PhraseCommitterConfig
from runtime.inference.pipeline.voice_profile_store import VoiceProfileStore
from runtime.inference.protocol import (
    AudioBus,
    CaptionEvent,
    PipelineMode,
    TtsMode,
)


class TestDuplexE2E(unittest.IsolatedAsyncioTestCase):
    """End-to-End Duplex Translation test suite."""

    async def asyncSetUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.reg_path = Path(self.tmp_dir.name) / "registry.json"
        self.registry = ModelRegistry(self.reg_path)
        self.registry.load()

        self.vad_adapter = SileroVadAdapter()
        self.asr_en = Nemotron35StreamingAsrAdapter()
        self.asr_ro = Nemotron35StreamingAsrAdapter()
        self.translation_adapter = MiLMMT46TranslationAdapter(model_size="1b")
        self.tts_ro = OmniVoiceTtsAdapter()
        self.tts_en = OmniVoiceTtsAdapter()

        self.captions_received: list[CaptionEvent] = []

        def on_caption(caption: CaptionEvent) -> None:
            self.captions_received.append(caption)

        self.metrics = PipelineMetrics()

        self.orchestrator = DuplexOrchestrator(
            model_registry=self.registry,
            metrics=self.metrics,
            vad_adapter=self.vad_adapter,
            asr_adapter_en=self.asr_en,
            asr_adapter_ro=self.asr_ro,
            mt_adapter=self.translation_adapter,
            tts_adapter_ro=self.tts_ro,
            tts_adapter_en=self.tts_en,
            caption_callback=on_caption,
            mode=PipelineMode.FULL_DUPLEX,
        )

    async def asyncTearDown(self):
        if self.orchestrator._is_active:
            await self.orchestrator.stop()
        self.tmp_dir.cleanup()

    async def test_full_duplex_e2e_lifecycle(self):
        """Test orchestrator start, frame injection, mode toggle, and shutdown."""
        await self.orchestrator.start()
        self.assertTrue(self.orchestrator._is_active)
        self.assertIsNotNone(self.orchestrator.outbound_pipeline)
        self.assertIsNotNone(self.orchestrator.inbound_pipeline)

        # Inject 10 frames of 20ms audio into Outbound (Physical Mic) and Inbound (Conference In)
        frame_20ms = b"\x01\x00" * 320
        for _ in range(10):
            if self.orchestrator.outbound_pipeline:
                self.orchestrator.outbound_pipeline.capture_engine.push_external_frame(frame_20ms)
            if self.orchestrator.inbound_pipeline:
                self.orchestrator.inbound_pipeline.capture_engine.push_external_frame(frame_20ms)
            await asyncio.sleep(0.01)

        # Toggle pipeline mode
        await self.orchestrator.set_mode(PipelineMode.CAPTIONS_ONLY)
        self.assertEqual(self.orchestrator.mode, PipelineMode.CAPTIONS_ONLY)

        await self.orchestrator.set_mode(PipelineMode.FULL_DUPLEX)
        self.assertEqual(self.orchestrator.mode, PipelineMode.FULL_DUPLEX)

        # Toggle TTS mode
        await self.orchestrator.set_tts_mode(TtsMode.CLONED)
        self.assertEqual(self.orchestrator.tts_mode, TtsMode.CLONED)

        # Stop orchestrator
        await self.orchestrator.stop()
        self.assertFalse(self.orchestrator._is_active)
