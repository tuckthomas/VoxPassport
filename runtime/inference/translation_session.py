"""Provider-neutral streaming speech translation session contracts.

The communication transport (virtual microphone, conference integration, WebRTC,
etc.) is deliberately outside this module. A strategy consumes audio frames and
emits semantic translation/session events whether it is backed by the existing
ASR+NMT cascade or a direct audio-to-audio provider such as Gemini Live Translate.
"""

from __future__ import annotations

import enum
import time
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
    """One bidirectional-provider session for one source->target direction."""

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
