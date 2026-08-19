"""
LiveTranslator — Outbound Translation Pipeline (English → Romanian)
====================================================================
End-to-end real-time outbound translation pipeline:
Physical Mic → VAD → EN ASR → PhraseCommitter → EN→RO MT → RO TTS → Virtual Mic + Captions

Features:
- Full asynchronous pipeline loop
- Real-time VAD speech detection & endpointing
- Streaming ASR partial transcript broadcast to captions
- Phrase stabilization via PhraseCommitter
- Contextual Machine Translation
- Streaming TTS synthesis chunk playback into Virtual Microphone
- Latency instrumentation on every stage (capture -> ASR -> MT -> TTS)
- Graceful stop and resource recovery
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Callable, Optional

from runtime.inference.adapters.base import (
    AsrAdapter,
    TranslationAdapter,
    TtsAdapter,
    VadAdapter,
)
from runtime.inference.adapters.vad.silero_vad_adapter import SileroVadAdapter, SileroVadState
from runtime.inference.asr_types import AsrConfig, AsrStream
from runtime.inference.metrics.latency_metrics import PipelineMetrics, UtteranceMetrics
from runtime.inference.pipeline.audio_capture import AudioCaptureEngine
from runtime.inference.pipeline.audio_playback import AudioPlaybackEngine
from runtime.inference.pipeline.phrase_committer import (
    CommittedPhrase,
    PhraseCommitter,
    PhraseCommitterConfig,
)
from runtime.inference.protocol import (
    AudioBus,
    AudioFrame,
    CaptionEvent,
    CaptionEventType,
    LanguageCode,
    TranscriptEvent,
    TranscriptState,
    TranslationEvent,
    TtsAudioChunk,
    VadEventType,
    VoiceSpec,
)

logger = logging.getLogger(__name__)


class OutboundTranslationPipeline:
    """
    Manages the live outbound translation pipeline (English -> Romanian).
    """

    def __init__(
        self,
        vad_adapter: VadAdapter,
        asr_adapter: AsrAdapter,
        translation_adapter: TranslationAdapter,
        tts_adapter: TtsAdapter,
        capture_engine: AudioCaptureEngine,
        playback_engine: AudioPlaybackEngine,
        metrics: PipelineMetrics,
        phrase_config: Optional[PhraseCommitterConfig] = None,
        caption_callback: Optional[Callable[[CaptionEvent], None]] = None,
        voice_spec: Optional[VoiceSpec] = None,
    ):
        self.vad_adapter = vad_adapter
        self.asr_adapter = asr_adapter
        self.translation_adapter = translation_adapter
        self.tts_adapter = tts_adapter
        self.capture_engine = capture_engine
        self.playback_engine = playback_engine
        self.metrics = metrics
        self.caption_callback = caption_callback
        self.voice_spec = voice_spec or VoiceSpec(language=LanguageCode.RO, is_cloned=False)

        # Phrase Committer
        self.phrase_committer = PhraseCommitter(
            config=phrase_config or PhraseCommitterConfig(),
            on_commit=self._on_phrase_committed,
            source_language=LanguageCode.EN,
        )

        self._is_running = False
        self._main_task: Optional[asyncio.Task] = None
        self._asr_events_task: Optional[asyncio.Task] = None
        self._current_asr_stream: Optional[AsrStream] = None
        self._vad_state: Optional[SileroVadState] = None

        # Tracking metrics for current utterance
        self._current_utterance_metrics: Optional[UtteranceMetrics] = None
        self._current_utterance_id: str = ""

    async def start(self) -> None:
        """Start the live outbound translation pipeline."""
        if self._is_running:
            return
        self._is_running = True
        logger.info("Starting Outbound Translation Pipeline (EN -> RO)...")

        # Start hardware audio I/O
        await self.capture_engine.start()
        await self.playback_engine.start()

        # Init ASR stream
        asr_config = AsrConfig(
            language="en",
            sample_rate_hz=self.capture_engine.sample_rate_hz,
            channels=self.capture_engine.channels,
            enable_partials=True,
        )
        self._current_asr_stream = await self.asr_adapter.start_stream(asr_config)

        # Init VAD state
        if isinstance(self.vad_adapter, SileroVadAdapter):
            self._vad_state = self.vad_adapter.create_stream_state(stream_id=self._current_asr_stream.stream_id)

        # Launch async workers
        self._main_task = asyncio.create_task(self._capture_and_vad_loop())
        self._asr_events_task = asyncio.create_task(self._asr_events_loop())
        logger.info("Outbound Translation Pipeline is ACTIVE.")

    async def _capture_and_vad_loop(self) -> None:
        """Reads mic frames, executes VAD, feeds ASR."""
        while self._is_running:
            frame: Optional[AudioFrame] = await self.capture_engine.get_frame(timeout=0.1)
            if frame is None:
                continue

            # Process VAD
            vad_events = []
            if isinstance(self.vad_adapter, SileroVadAdapter) and self._vad_state:
                try:
                    vad_events = self.vad_adapter.process_with_state(frame, self._vad_state)
                except Exception:
                    pass

            for ve in vad_events:
                if ve.event_type == VadEventType.SPEECH_START:
                    self._current_utterance_id = str(uuid.uuid4())
                    self._current_utterance_metrics = UtteranceMetrics(
                        utterance_id=self._current_utterance_id,
                        direction="outbound",
                        capture_timestamp_ns=frame.monotonic_timestamp_ns,
                        vad_speech_start_ns=ve.monotonic_timestamp_ns,
                    )
                elif ve.event_type == VadEventType.SPEECH_END:
                    if self._current_utterance_metrics:
                        self._current_utterance_metrics.vad_speech_end_ns = ve.monotonic_timestamp_ns
                    self.phrase_committer.on_endpoint_detected(
                        utterance_id=self._current_utterance_id,
                        timestamp_ns=ve.monotonic_timestamp_ns,
                    )

            # Push audio to ASR
            if self._current_asr_stream:
                try:
                    await self.asr_adapter.push_audio(self._current_asr_stream, frame)
                except Exception as e:
                    logger.debug("Error pushing audio to ASR: %s", e)

    async def _asr_events_loop(self) -> None:
        """Consumes transcript events from ASR, updates captions, feeds PhraseCommitter."""
        if not self._current_asr_stream:
            return

        async for event in self.asr_adapter.events(self._current_asr_stream):
            if not self._is_running:
                break

            now_ns = time.monotonic_ns()
            if self._current_utterance_metrics and self._current_utterance_metrics.asr_first_partial_ns is None:
                self._current_utterance_metrics.asr_first_partial_ns = now_ns

            if event.is_final and self._current_utterance_metrics:
                self._current_utterance_metrics.asr_final_ns = now_ns

            # Emit caption event for live source transcript
            if self.caption_callback:
                cap = CaptionEvent(
                    event_type=CaptionEventType.PARTIAL_SOURCE if event.is_partial else CaptionEventType.FINAL_SOURCE,
                    utterance_id=event.utterance_id,
                    language=LanguageCode.EN,
                    text=event.text,
                    is_final=event.is_final,
                    monotonic_timestamp_ns=now_ns,
                )
                self.caption_callback(cap)

            # Feed to PhraseCommitter
            self.phrase_committer.on_transcript_event(event)

    def _on_phrase_committed(self, phrase: CommittedPhrase) -> None:
        """Called by PhraseCommitter when a phrase is stabilized and ready for MT -> TTS."""
        asyncio.create_task(self._translate_and_synthesize(phrase))

    async def _translate_and_synthesize(self, phrase: CommittedPhrase) -> None:
        """Translates a committed phrase and streams the synthesized speech to Virtual Mic."""
        now_ns = time.monotonic_ns()
        try:
            # 1. Machine Translation (EN -> RO)
            t_mt_start = time.monotonic()
            mt_result = await self.translation_adapter.translate(
                text=phrase.text,
                source_language=phrase.source_language,
                target_language=LanguageCode.RO,
                context=phrase.context,
            )
            t_mt_end = time.monotonic()

            if self._current_utterance_metrics:
                self._current_utterance_metrics.mt_complete_ns = time.monotonic_ns()

            translated_text = mt_result.translated_text
            self.phrase_committer.add_translation_to_context(phrase.text, translated_text)

            # Emit caption event for committed translated text
            if self.caption_callback:
                cap = CaptionEvent(
                    event_type=CaptionEventType.COMMITTED_TRANSLATION,
                    utterance_id=phrase.utterance_id,
                    language=LanguageCode.RO,
                    text=translated_text,
                    is_final=True,
                    monotonic_timestamp_ns=time.monotonic_ns(),
                )
                self.caption_callback(cap)

            logger.info("Outbound MT: %r -> %r (%.1fms)", phrase.text, translated_text, (t_mt_end - t_mt_start) * 1000)

            # 2. Text-to-Speech (Romanian synthesis -> Virtual Mic)
            first_chunk = True
            async for chunk in self.tts_adapter.synthesize_stream(
                text=translated_text,
                language=LanguageCode.RO,
                voice=self.voice_spec,
            ):
                if first_chunk:
                    first_chunk = False
                    if self._current_utterance_metrics:
                        self._current_utterance_metrics.tts_first_chunk_ns = time.monotonic_ns()

                await self.playback_engine.enqueue_chunk(chunk)

            if self._current_utterance_metrics:
                self._current_utterance_metrics.tts_complete_ns = time.monotonic_ns()
                self.metrics.record_utterance(self._current_utterance_metrics)

        except Exception as e:
            logger.exception("Error in outbound translate and synthesize: %s", e)

    async def stop(self) -> None:
        """Stop the outbound pipeline and flush committer."""
        if not self._is_running:
            return
        self._is_running = False
        logger.info("Stopping Outbound Translation Pipeline...")

        self.phrase_committer.flush_all()

        if self._current_asr_stream:
            try:
                await self.asr_adapter.close_stream(self._current_asr_stream)
            except Exception:
                pass

        if self._main_task:
            self._main_task.cancel()
        if self._asr_events_task:
            self._asr_events_task.cancel()

        await self.capture_engine.stop()
        await self.playback_engine.stop()
        logger.info("Outbound Translation Pipeline stopped.")
