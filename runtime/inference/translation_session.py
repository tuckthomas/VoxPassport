"""Provider-neutral streaming speech translation session contracts.

The communication transport (virtual microphone, conference integration, WebRTC,
etc.) is deliberately outside this module. A strategy consumes audio frames and
emits semantic translation/session events whether it is backed by the existing
ASR+NMT cascade or a direct audio-to-audio provider such as Gemini Live Translate.
"""

from __future__ import annotations

import asyncio
import enum
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from runtime.inference.protocol import AudioFrame, LanguageCode, SampleFormat
from runtime.inference.translation_provider_catalog import TranslationStrategyKind


class SpeechTranslationOutputMode(str, enum.Enum):
    TRANSLATED_TEXT = "translated_text"
    TRANSLATED_AUDIO = "translated_audio"
    TEXT_AND_AUDIO = "text_and_audio"


class SpeechTranslationSessionState(str, enum.Enum):
    OPENING = "opening"
    READY = "ready"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    CLOSING = "closing"
    CLOSED = "closed"
    FAILED = "failed"


class SpeechTranslationEventType(str, enum.Enum):
    SOURCE_PARTIAL = "source_partial"
    SOURCE_FINAL = "source_final"
    TRANSLATION_PARTIAL = "translation_partial"
    TRANSLATION_FINAL = "translation_final"
    TRANSLATED_AUDIO = "translated_audio"
    STATE = "state"
    ERROR = "error"


class SpeechTranslationSessionError(RuntimeError):
    pass


class SpeechTranslationBackpressureError(SpeechTranslationSessionError):
    pass


class SpeechTranslationSessionClosedError(SpeechTranslationSessionError):
    pass


@dataclass(frozen=True, slots=True)
class SpeechTranslationSessionConfig:
    source_language: LanguageCode
    target_language: LanguageCode
    input_sample_rate_hz: int
    input_channels: int = 1
    input_sample_format: SampleFormat = SampleFormat.PCM_S16LE
    output_mode: SpeechTranslationOutputMode = SpeechTranslationOutputMode.TEXT_AND_AUDIO
    request_source_transcript: bool = True
    voice_profile_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.source_language == self.target_language:
            raise ValueError("source_language and target_language must differ")
        if self.input_sample_rate_hz <= 0:
            raise ValueError("input_sample_rate_hz must be positive")
        if self.input_channels <= 0:
            raise ValueError("input_channels must be positive")


@dataclass(frozen=True, slots=True)
class TranslatedAudioChunk:
    sequence: int
    sample_rate_hz: int
    channels: int
    sample_format: SampleFormat
    data: bytes
    is_final_chunk: bool = False

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("sequence must be non-negative")
        if self.sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be positive")
        if self.channels <= 0:
            raise ValueError("channels must be positive")


@dataclass(frozen=True, slots=True)
class SpeechTranslationEvent:
    event_type: SpeechTranslationEventType
    sequence: int
    monotonic_timestamp_ns: int = field(default_factory=time.monotonic_ns)
    text: str | None = None
    audio: TranslatedAudioChunk | None = None
    state: SpeechTranslationSessionState | None = None
    error_code: str | None = None
    recoverable: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("sequence must be non-negative")
        text_events = {
            SpeechTranslationEventType.SOURCE_PARTIAL,
            SpeechTranslationEventType.SOURCE_FINAL,
            SpeechTranslationEventType.TRANSLATION_PARTIAL,
            SpeechTranslationEventType.TRANSLATION_FINAL,
        }
        if self.event_type in text_events and self.text is None:
            raise ValueError(f"{self.event_type.value} requires text")
        if self.event_type == SpeechTranslationEventType.TRANSLATED_AUDIO and self.audio is None:
            raise ValueError("translated_audio requires an audio chunk")
        if self.event_type == SpeechTranslationEventType.STATE and self.state is None:
            raise ValueError("state event requires state")
        if self.event_type == SpeechTranslationEventType.ERROR and not self.error_code:
            raise ValueError("error event requires error_code")


class SpeechTranslationSession(ABC):
    """One provider session for one source->target direction."""

    @property
    @abstractmethod
    def session_id(self) -> str:
        ...

    @property
    @abstractmethod
    def config(self) -> SpeechTranslationSessionConfig:
        ...

    @abstractmethod
    async def push_audio(self, frame: AudioFrame) -> None:
        """Feed input audio while preserving capture ordering."""
        ...

    @abstractmethod
    def events(self) -> AsyncIterator[SpeechTranslationEvent]:
        """Yield source text, translated text/audio, state and error events."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Flush and close the session. Closed sessions must not be reused."""
        ...


class BufferedSpeechTranslationSession(SpeechTranslationSession):
    """Reusable bounded queues for streaming provider implementations.

    Subclasses consume :meth:`next_audio` in their provider loop and call
    :meth:`emit`. Capture-side overflow raises immediately instead of silently
    growing memory or adding unbounded conversational latency.
    """

    _AUDIO_CLOSED = object()
    _EVENTS_CLOSED = object()

    def __init__(
        self,
        config: SpeechTranslationSessionConfig,
        *,
        session_id: str | None = None,
        max_pending_audio_frames: int = 100,
        max_pending_events: int = 256,
    ) -> None:
        if max_pending_audio_frames <= 0:
            raise ValueError("max_pending_audio_frames must be positive")
        if max_pending_events <= 0:
            raise ValueError("max_pending_events must be positive")
        self._config = config
        self._session_id = session_id or f"speech-{uuid.uuid4().hex}"
        self._audio_queue: asyncio.Queue[AudioFrame | object] = asyncio.Queue(
            maxsize=max_pending_audio_frames
        )
        self._event_queue: asyncio.Queue[SpeechTranslationEvent | object] = asyncio.Queue(
            maxsize=max_pending_events
        )
        self._closed = False
        self._last_input_sequence = -1
        self._last_event_sequence = -1

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def config(self) -> SpeechTranslationSessionConfig:
        return self._config

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def pending_audio_frames(self) -> int:
        return self._audio_queue.qsize()

    async def push_audio(self, frame: AudioFrame) -> None:
        if self._closed:
            raise SpeechTranslationSessionClosedError("speech translation session is closed")
        self._validate_audio_frame(frame)
        if frame.sequence <= self._last_input_sequence:
            raise SpeechTranslationSessionError(
                f"audio sequence must increase: {frame.sequence} <= {self._last_input_sequence}"
            )
        try:
            self._audio_queue.put_nowait(frame)
        except asyncio.QueueFull as exc:
            raise SpeechTranslationBackpressureError(
                "speech translation audio queue is full"
            ) from exc
        self._last_input_sequence = frame.sequence

    def _validate_audio_frame(self, frame: AudioFrame) -> None:
        if frame.sample_rate_hz != self._config.input_sample_rate_hz:
            raise SpeechTranslationSessionError(
                f"unexpected input sample rate {frame.sample_rate_hz}; "
                f"expected {self._config.input_sample_rate_hz}"
            )
        if frame.channels != self._config.input_channels:
            raise SpeechTranslationSessionError(
                f"unexpected input channels {frame.channels}; expected {self._config.input_channels}"
            )
        if frame.sample_format != self._config.input_sample_format:
            raise SpeechTranslationSessionError(
                f"unexpected input sample format {frame.sample_format.value}; "
                f"expected {self._config.input_sample_format.value}"
            )

    async def next_audio(self) -> AudioFrame | None:
        item = await self._audio_queue.get()
        if item is self._AUDIO_CLOSED:
            return None
        assert isinstance(item, AudioFrame)
        return item

    async def emit(self, event: SpeechTranslationEvent) -> None:
        if self._closed:
            raise SpeechTranslationSessionClosedError("speech translation session is closed")
        if event.sequence <= self._last_event_sequence:
            raise SpeechTranslationSessionError(
                f"event sequence must increase: {event.sequence} <= {self._last_event_sequence}"
            )
        try:
            self._event_queue.put_nowait(event)
        except asyncio.QueueFull as exc:
            raise SpeechTranslationBackpressureError(
                "speech translation event queue is full"
            ) from exc
        self._last_event_sequence = event.sequence

    async def emit_state(
        self,
        state: SpeechTranslationSessionState,
        *,
        sequence: int,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await self.emit(SpeechTranslationEvent(
            event_type=SpeechTranslationEventType.STATE,
            sequence=sequence,
            state=state,
            metadata=dict(metadata or {}),
        ))

    async def events(self) -> AsyncIterator[SpeechTranslationEvent]:
        while True:
            item = await self._event_queue.get()
            if item is self._EVENTS_CLOSED:
                break
            assert isinstance(item, SpeechTranslationEvent)
            yield item

    async def close(self) -> None:
        if self._closed:
            return
        await self._close_provider()
        self._closed = True
        self._force_queue_marker(self._audio_queue, self._AUDIO_CLOSED)
        self._force_queue_marker(self._event_queue, self._EVENTS_CLOSED)

    async def _close_provider(self) -> None:
        """Provider-specific close hook. Override when a transport must be closed."""

    @staticmethod
    def _force_queue_marker(queue: asyncio.Queue, marker: object) -> None:
        while queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        queue.put_nowait(marker)


class SpeechTranslationStrategyAdapter(ABC):
    """Executable strategy factory independent of communication transport."""

    @property
    @abstractmethod
    def strategy_id(self) -> str:
        ...

    @property
    @abstractmethod
    def kind(self) -> TranslationStrategyKind:
        ...

    @abstractmethod
    async def load(self) -> None:
        ...

    @abstractmethod
    async def unload(self) -> None:
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        ...

    @abstractmethod
    async def supports_language_pair(
        self,
        source_language: LanguageCode,
        target_language: LanguageCode,
    ) -> bool:
        ...

    @abstractmethod
    async def open_session(
        self,
        config: SpeechTranslationSessionConfig,
    ) -> SpeechTranslationSession:
        """Open a streaming session or reject unsupported configuration."""
        ...
