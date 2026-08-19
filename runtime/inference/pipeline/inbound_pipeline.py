"""Inbound real-time speech translation pipeline."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Callable, Optional

from runtime.inference.adapters.base import AsrAdapter, TranslationAdapter, TtsAdapter, VadAdapter
from runtime.inference.adapters.vad.silero_vad_adapter import SileroVadAdapter, SileroVadState
from runtime.inference.asr_types import AsrConfig, AsrStream
from runtime.inference.metrics.latency_metrics import PipelineMetrics, UtteranceMetrics
from runtime.inference.pipeline.audio_capture import AudioCaptureEngine
from runtime.inference.pipeline.audio_playback import AudioPlaybackEngine
from runtime.inference.pipeline.phrase_committer import CommittedPhrase, PhraseCommitter, PhraseCommitterConfig
from runtime.inference.protocol import CaptionEvent, CaptionEventType, LanguageCode, VadEventType, VoiceSpec

logger = logging.getLogger(__name__)


class InboundTranslationPipeline:
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
        source_language: LanguageCode = LanguageCode.RO,
        target_language: LanguageCode = LanguageCode.EN,
        synthesize_audio: bool = True,
    ) -> None:
        self.vad_adapter = vad_adapter
        self.asr_adapter = asr_adapter
        self.translation_adapter = translation_adapter
        self.tts_adapter = tts_adapter
        self.capture_engine = capture_engine
        self.playback_engine = playback_engine
        self.metrics = metrics
        self.caption_callback = caption_callback
        self.source_language = source_language
        self.target_language = target_language
        self.synthesize_audio = synthesize_audio
        self.voice_spec = voice_spec or VoiceSpec(language=target_language, is_cloned=False)
        self.phrase_committer = PhraseCommitter(
            phrase_config or PhraseCommitterConfig(), self._on_phrase_committed, source_language
        )
        self._is_running = False
        self._main_task: Optional[asyncio.Task] = None
        self._asr_events_task: Optional[asyncio.Task] = None
        self._current_asr_stream: Optional[AsrStream] = None
        self._vad_state: Optional[SileroVadState] = None
        self._current_utterance_metrics: Optional[UtteranceMetrics] = None
        self._metric_utterance_id = ""
        self._last_asr_utterance_id = ""

    async def start(self) -> None:
        if self._is_running:
            return
        self._is_running = True
        await self.capture_engine.start()
        if self.synthesize_audio:
            await self.playback_engine.start()
        self._current_asr_stream = await self.asr_adapter.start_stream(
            AsrConfig(
                language=self.source_language.value,
                sample_rate_hz=self.capture_engine.sample_rate_hz,
                channels=self.capture_engine.channels,
                enable_partials=True,
            )
        )
        if isinstance(self.vad_adapter, SileroVadAdapter):
            self._vad_state = self.vad_adapter.create_stream_state(self._current_asr_stream.stream_id)
        self._main_task = asyncio.create_task(self._capture_and_vad_loop())
        self._asr_events_task = asyncio.create_task(self._asr_events_loop())
        logger.info("Inbound pipeline active: %s -> %s", self.source_language.value, self.target_language.value)

    async def _capture_and_vad_loop(self) -> None:
        while self._is_running:
            frame = await self.capture_engine.get_frame(timeout=0.1)
            if frame is None:
                continue
            vad_events = []
            if isinstance(self.vad_adapter, SileroVadAdapter) and self._vad_state:
                try:
                    vad_events = self.vad_adapter.process_with_state(frame, self._vad_state)
                except Exception:
                    logger.debug("Inbound VAD processing failed", exc_info=True)
            for ve in vad_events:
                if ve.event_type == VadEventType.SPEECH_START:
                    self._metric_utterance_id = str(uuid.uuid4())
                    self._current_utterance_metrics = UtteranceMetrics(
                        utterance_id=self._metric_utterance_id,
                        direction="inbound",
                        capture_timestamp_ns=frame.monotonic_timestamp_ns,
                        vad_speech_start_ns=ve.monotonic_timestamp_ns,
                    )
                elif ve.event_type == VadEventType.SPEECH_END:
                    if self._current_utterance_metrics:
                        self._current_utterance_metrics.vad_speech_end_ns = ve.monotonic_timestamp_ns
                    if self._current_asr_stream and hasattr(self.asr_adapter, "endpoint"):
                        try:
                            await self.asr_adapter.endpoint(self._current_asr_stream)
                        except Exception:
                            logger.exception("Inbound ASR endpoint decode failed")
                    elif self._last_asr_utterance_id:
                        self.phrase_committer.on_endpoint_detected(
                            self._last_asr_utterance_id, ve.monotonic_timestamp_ns
                        )
            if self._current_asr_stream:
                try:
                    await self.asr_adapter.push_audio(self._current_asr_stream, frame)
                except Exception:
                    logger.debug("Inbound ASR audio push failed", exc_info=True)

    async def _asr_events_loop(self) -> None:
        if not self._current_asr_stream:
            return
        async for event in self.asr_adapter.events(self._current_asr_stream):
            if not self._is_running:
                break
            self._last_asr_utterance_id = event.utterance_id
            now_ns = time.monotonic_ns()
            if self._current_utterance_metrics and self._current_utterance_metrics.asr_first_partial_ns is None:
                self._current_utterance_metrics.asr_first_partial_ns = now_ns
            if event.is_final and self._current_utterance_metrics:
                self._current_utterance_metrics.asr_final_ns = now_ns
            if self.caption_callback:
                self.caption_callback(
                    CaptionEvent(
                        event_type=CaptionEventType.SOURCE_PARTIAL if event.is_partial else CaptionEventType.SOURCE_FINAL,
                        utterance_id=event.utterance_id,
                        language=self.source_language,
                        text=event.text,
                        is_final=event.is_final,
                        monotonic_timestamp_ns=now_ns,
                    )
                )
            self.phrase_committer.on_transcript_event(event)

    def _on_phrase_committed(self, phrase: CommittedPhrase) -> None:
        asyncio.create_task(self._translate_and_synthesize(phrase))

    async def _translate_and_synthesize(self, phrase: CommittedPhrase) -> None:
        try:
            mt_result = await self.translation_adapter.translate(
                phrase.text,
                source_language=self.source_language,
                target_language=self.target_language,
                context=phrase.context,
            )
            if self._current_utterance_metrics:
                self._current_utterance_metrics.mt_complete_ns = time.monotonic_ns()
            translated = mt_result.translated_text
            self.phrase_committer.add_translation_to_context(phrase.text, translated)
            if self.caption_callback:
                self.caption_callback(
                    CaptionEvent(
                        event_type=CaptionEventType.TRANSLATION_FINAL,
                        utterance_id=phrase.utterance_id,
                        language=self.target_language,
                        text=translated,
                        is_final=True,
                    )
                )
            if not self.synthesize_audio:
                return
            first = True
            self.voice_spec.language = self.target_language
            async for chunk in self.tts_adapter.synthesize_stream(
                text=translated, language=self.target_language, voice=self.voice_spec
            ):
                if first:
                    first = False
                    if self._current_utterance_metrics:
                        self._current_utterance_metrics.tts_first_chunk_ns = time.monotonic_ns()
                await self.playback_engine.enqueue_chunk(chunk)
            if self._current_utterance_metrics:
                self._current_utterance_metrics.tts_complete_ns = time.monotonic_ns()
                self.metrics.record_utterance(self._current_utterance_metrics)
        except Exception:
            logger.exception("Inbound translate/synthesize failed")

    async def stop(self) -> None:
        if not self._is_running:
            return
        self._is_running = False
        self.phrase_committer.flush_all()
        if self._current_asr_stream:
            try:
                await self.asr_adapter.close_stream(self._current_asr_stream)
            except Exception:
                pass
            self._current_asr_stream = None
        for task in (self._main_task, self._asr_events_task):
            if task:
                task.cancel()
        self._main_task = self._asr_events_task = None
        await self.capture_engine.stop()
        if self.synthesize_audio:
            await self.playback_engine.stop()
