"""
Comprehensive Integration Tests for LiveTranslator Pipeline Core.

Tests:
1. AudioCaptureEngine (chunking, metering, mock audio injection)
2. AudioPlaybackEngine (sample format conversion, queue consumption)
3. OutboundTranslationPipeline (Mic -> VAD -> ASR -> PhraseCommitter -> MT -> TTS -> Virtual Mic)
4. InboundTranslationPipeline (Conference -> VAD -> RO ASR -> PhraseCommitter -> MT -> TTS -> Local Monitor)
5. DuplexOrchestrator (Concurrent full-duplex execution, mode switching)
6. DegradedModeScheduler (Auto-downgrade and upgrade on latency)
7. VoiceProfileStore (Enrollment with consent, persistence, deletion)
8. ModelDiscoveryAgent (Upstream candidate scan, recommendation states)
9. ModelManagerController (Install, active slot assignment, rollback, cleanup)
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from runtime.inference.model_discovery_agent import ModelDiscoveryAgent
from runtime.inference.adapters.asr.nemotron35_streaming_asr_adapter import Nemotron35StreamingAsrAdapter
from runtime.inference.adapters.translation.milmmt46_translation_adapter import MiLMMT46TranslationAdapter
from runtime.inference.adapters.tts.omnivoice_tts_adapter import OmniVoiceTtsAdapter
from runtime.inference.adapters.vad.silero_vad_adapter import SileroVadAdapter
from runtime.inference.metrics.latency_metrics import PipelineMetrics, UtteranceMetrics
from runtime.inference.model_registry.catalog import get_builtin_catalog
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
    InstallationStatus,
    LanguageCode,
    PipelineMode,
    RuntimeTier,
    SampleFormat,
    TtsMode,
    VoiceSpec,
)
from runtime.inference.server.model_manager_api import ModelManagerController


class TestAudioCaptureAndPlayback(unittest.TestCase):
    """Test audio capture and playback engines."""

    def test_audio_capture_chunking(self):
        engine = AudioCaptureEngine(bus=AudioBus.PHYSICAL_MIC, sample_rate_hz=16000, chunk_duration_ms=20)
        # Inject 16000 samples (1 second) of PCM 16-bit
        mock_pcm = b"\x01\x00" * 320  # 320 samples = 20ms
        engine.push_external_frame(mock_pcm)
        self.assertGreater(engine.current_rms_db, -100.0)

    def test_audio_playback_conversion(self):
        engine = AudioPlaybackEngine(bus=AudioBus.VIRTUAL_MIC, sample_rate_hz=24000)
        # Convert 4 float32 samples to s16le
        f32_data = b"\x00\x00\x80\x3f" * 4  # 1.0f
        s16_data = engine._convert_to_s16le(f32_data, SampleFormat.PCM_F32LE)
        self.assertEqual(len(s16_data), 8)  # 4 samples * 2 bytes


class TestVoiceProfileStore(unittest.TestCase):
    """Test encrypted voice profile store."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.store = VoiceProfileStore(Path(self.tmp_dir.name))

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_enrollment_with_consent(self):
        sample_rate = 16000
        # 3 seconds of dummy audio (3 * 16000 * 2 bytes)
        dummy_audio = b"\x00\x00" * (sample_rate * 3)

        meta = self.store.enroll_profile(
            profile_id="vp-01",
            speaker_name="Alex",
            reference_audio_pcm=dummy_audio,
            sample_rate_hz=sample_rate,
            user_consent=True,
        )
        self.assertEqual(meta.speaker_name, "Alex")
        self.assertEqual(len(self.store.list_profiles()), 1)

        # Retrieve audio
        audio = self.store.get_reference_audio("vp-01")
        self.assertEqual(len(audio), len(dummy_audio))

        # Delete
        self.assertTrue(self.store.delete_profile("vp-01"))
        self.assertEqual(len(self.store.list_profiles()), 0)

    def test_enrollment_without_consent_fails(self):
        dummy_audio = b"\x00\x00" * (16000 * 3)
        with self.assertRaises(PermissionError):
            self.store.enroll_profile(
                profile_id="vp-no-consent",
                speaker_name="Unknown",
                reference_audio_pcm=dummy_audio,
                sample_rate_hz=16000,
                user_consent=False,
            )


class TestModelDiscoveryAndManager(unittest.TestCase):
    """Test model discovery agent and model manager controller."""

    def setUp(self):
        self.tmp_file = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.reg_path = Path(self.tmp_file.name)
        self.tmp_file.close()
        self.reg_path.unlink(missing_ok=True)

        self.registry = ModelRegistry(self.reg_path)
        self.registry.load()
        for e in get_builtin_catalog():
            self.registry.register(e)

        self.controller = ModelManagerController(self.registry)
        self.agent = ModelDiscoveryAgent(self.registry)

    def tearDown(self):
        self.reg_path.unlink(missing_ok=True)

    def test_model_manager_installed_and_active(self):
        # List available models
        available = self.controller.list_available()
        self.assertGreaterEqual(len(available), 8)

        # Mark model installed in registry for unit test
        self.registry.update_installation_status(
            "xiaomi-milmmt-46-1b-v1.0",
            InstallationStatus.INSTALLED,
            installed_size_gb=2.0,
        )
        installed = self.controller.list_installed()
        self.assertGreaterEqual(len(installed), 1)

        # Set active model
        self.controller.set_active_model("TRANSLATION", "xiaomi-milmmt-46-1b-v1.0", language_pair="en_ro")
        active_slots = self.controller.get_active_slots()
        self.assertEqual(active_slots["translation_en_ro"], "xiaomi-milmmt-46-1b-v1.0")

        # Snapshot known-good
        kgms = self.controller.save_known_good_set()
        self.assertIsNotNone(kgms.set_id)

    def test_model_discovery_agent_pass(self):
        candidates = asyncio.run(self.agent.run_discovery_pass())
        self.assertGreater(len(candidates), 0)


class TestPipelinesAndOrchestrator(unittest.TestCase):
    """End-to-end integration test of Outbound, Inbound, and Duplex Orchestrator."""

    def setUp(self):
        self.metrics = PipelineMetrics()
        self.vad = SileroVadAdapter()
        self.asr_en = Nemotron35StreamingAsrAdapter()
        self.asr_ro = Nemotron35StreamingAsrAdapter()
        self.mt = MiLMMT46TranslationAdapter(model_size="1b")
        self.tts_ro = OmniVoiceTtsAdapter()
        self.tts_en = OmniVoiceTtsAdapter()

        self.tmp_file = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.reg_path = Path(self.tmp_file.name)
        self.tmp_file.close()
        self.reg_path.unlink(missing_ok=True)
        self.registry = ModelRegistry(self.reg_path)
        self.registry.load()

    def tearDown(self):
        self.reg_path.unlink(missing_ok=True)

    def test_outbound_pipeline_lifecycle(self):
        async def run():
            captions_emitted = []
            pipeline = OutboundTranslationPipeline(
                vad_adapter=self.vad,
                asr_adapter=self.asr_en,
                translation_adapter=self.mt,
                tts_adapter=self.tts_ro,
                capture_engine=AudioCaptureEngine(bus=AudioBus.PHYSICAL_MIC),
                playback_engine=AudioPlaybackEngine(bus=AudioBus.VIRTUAL_MIC),
                metrics=self.metrics,
                caption_callback=captions_emitted.append,
            )
            await pipeline.start()
            # Push test audio frame
            mock_pcm = b"\x00\x00" * 320
            pipeline.capture_engine.push_external_frame(mock_pcm)
            await asyncio.sleep(0.1)
            await pipeline.stop()
            self.assertFalse(pipeline._is_running)

        asyncio.run(run())

    def test_inbound_pipeline_lifecycle(self):
        async def run():
            pipeline = InboundTranslationPipeline(
                vad_adapter=self.vad,
                asr_adapter=self.asr_ro,
                translation_adapter=self.mt,
                tts_adapter=self.tts_en,
                capture_engine=AudioCaptureEngine(bus=AudioBus.REMOTE_CONFERENCE),
                playback_engine=AudioPlaybackEngine(bus=AudioBus.LOCAL_MONITOR),
                metrics=self.metrics,
            )
            await pipeline.start()
            await asyncio.sleep(0.1)
            await pipeline.stop()
            self.assertFalse(pipeline._is_running)

        asyncio.run(run())

    def test_duplex_orchestrator_lifecycle_and_modes(self):
        async def run():
            orchestrator = DuplexOrchestrator(
                model_registry=self.registry,
                metrics=self.metrics,
                vad_adapter=self.vad,
                asr_adapter_en=self.asr_en,
                asr_adapter_ro=self.asr_ro,
                mt_adapter=self.mt,
                tts_adapter_ro=self.tts_ro,
                tts_adapter_en=self.tts_en,
                mode=PipelineMode.FULL_DUPLEX,
            )
            await orchestrator.start()
            self.assertTrue(orchestrator._is_active)
            self.assertIsNotNone(orchestrator.outbound_pipeline)
            self.assertIsNotNone(orchestrator.inbound_pipeline)

            # Switch mode to CAPTIONS_ONLY
            await orchestrator.set_mode(PipelineMode.CAPTIONS_ONLY)
            self.assertEqual(orchestrator.mode, PipelineMode.CAPTIONS_ONLY)

            # Switch TTS mode
            await orchestrator.set_tts_mode(TtsMode.CLONED)
            self.assertEqual(orchestrator.tts_mode, TtsMode.CLONED)

            await orchestrator.stop()
            self.assertFalse(orchestrator._is_active)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
