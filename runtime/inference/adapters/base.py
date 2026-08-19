"""
LiveTranslator — Core Adapter Interfaces (Protocols)
=====================================================
These are the capability contracts that every model adapter must satisfy.
Business logic and pipeline code must ONLY reference these protocols —
never the concrete adapter classes.

Design rules:
- All adapters are async.
- No adapter imports model-specific libraries at module load time.
- Model-specific imports happen inside the adapter, lazily, during load().
- No prompt templates, model-specific branches, or hard-coded model names
  appear outside the adapter that owns them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from runtime.inference.protocol import (
        AudioFrame,
        AsrConfig,
        AsrStream,
        TranscriptEvent,
        TranslationContext,
        TranslationResult,
        TtsAudioChunk,
        VadEvent,
        VoiceSpec,
        LanguageCode,
    )


# ---------------------------------------------------------------------------
# VAD Adapter
# ---------------------------------------------------------------------------

class VadAdapter(ABC):
    """
    Voice Activity Detection adapter.

    Implementations must be stateless per-call or manage state internally.
    process() is synchronous because VAD must be low-latency and called
    inside the audio capture loop.
    """

    @abstractmethod
    async def load(self) -> None:
        """Load model into memory. Called once before use."""
        ...

    @abstractmethod
    async def unload(self) -> None:
        """Unload model and release resources."""
        ...

    @abstractmethod
    def process(self, frame: "AudioFrame") -> list["VadEvent"]:
        """
        Process a single audio frame synchronously.
        Returns zero or more VAD events (speech_start, speech_end, silence).
        Must not block for more than a few milliseconds.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the adapter is ready to process audio."""
        ...


# ---------------------------------------------------------------------------
# ASR Adapter
# ---------------------------------------------------------------------------

class AsrAdapter(ABC):
    """
    Automatic Speech Recognition adapter.

    The ASR adapter manages one or more streaming recognition sessions.
    Each session corresponds to one audio stream (e.g., one direction of a call).
    """

    @abstractmethod
    async def load(self) -> None:
        """Load model into memory. Called once before use."""
        ...

    @abstractmethod
    async def unload(self) -> None:
        """Unload model and release resources."""
        ...

    @abstractmethod
    async def start_stream(self, config: "AsrConfig") -> "AsrStream":
        """
        Open a new recognition stream.
        config specifies language, sample rate, and model-specific options.
        """
        ...

    @abstractmethod
    async def push_audio(self, stream: "AsrStream", frame: "AudioFrame") -> None:
        """
        Feed an audio frame into an open stream.
        Must not block significantly — audio capture is time-sensitive.
        """
        ...

    @abstractmethod
    def events(self, stream: "AsrStream") -> AsyncIterator["TranscriptEvent"]:
        """
        Async generator of transcript events for a stream.
        Yields PARTIAL, STABLE, and FINAL events as they are produced.
        """
        ...

    @abstractmethod
    async def close_stream(self, stream: "AsrStream") -> None:
        """
        Flush and close a recognition stream.
        After closing, the stream object must not be reused.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the adapter is ready to process audio."""
        ...


# ---------------------------------------------------------------------------
# Translation Adapter
# ---------------------------------------------------------------------------

class TranslationAdapter(ABC):
    """
    Machine Translation adapter.

    Translates committed text segments between language pairs.
    Context from recent segments can be passed to improve coherence.
    """

    @abstractmethod
    async def load(self) -> None:
        """Load model into memory."""
        ...

    @abstractmethod
    async def unload(self) -> None:
        """Unload model and release resources."""
        ...

    @abstractmethod
    async def translate(
        self,
        text: str,
        source_language: "LanguageCode",
        target_language: "LanguageCode",
        context: Optional["TranslationContext"] = None,
    ) -> "TranslationResult":
        """
        Translate text from source_language to target_language.
        Language codes are normalized to LanguageCode before entering this method.
        Prompt templates are internal to the adapter.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the adapter is ready to translate."""
        ...


# ---------------------------------------------------------------------------
# TTS Adapter
# ---------------------------------------------------------------------------

class TtsAdapter(ABC):
    """
    Text-to-Speech adapter.

    Supports both stock (non-cloned) and cloned voice synthesis.
    Audio is streamed in chunks to minimize time-to-first-audio.
    """

    @abstractmethod
    async def load(self) -> None:
        """Load model into memory."""
        ...

    @abstractmethod
    async def unload(self) -> None:
        """Unload model and release resources."""
        ...

    @abstractmethod
    def synthesize_stream(
        self,
        text: str,
        language: "LanguageCode",
        voice: "VoiceSpec",
    ) -> AsyncIterator["TtsAudioChunk"]:
        """
        Synthesize text and yield PCM audio chunks as they become available.
        The first chunk should arrive as quickly as possible (time-to-first-audio).
        Chunks may overlap with synthesis of later parts of the text.
        """
        ...

    @abstractmethod
    async def supports_voice_cloning(self) -> bool:
        """Return True if this adapter supports voice cloning."""
        ...

    @abstractmethod
    async def supports_language(self, language: "LanguageCode") -> bool:
        """Return True if this adapter can synthesize speech in the given language."""
        ...

    @property
    @abstractmethod
    def native_sample_rate_hz(self) -> int:
        """The sample rate of audio produced by this TTS adapter."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the adapter is ready to synthesize."""
        ...


# ---------------------------------------------------------------------------
# Direct Speech Translation Adapter (experimental)
# ---------------------------------------------------------------------------

class DirectSpeechTranslationAdapter(ABC):
    """
    An optional adapter for models that perform speech → text or speech → speech
    translation in a single model pass (e.g., Canary, SeamlessM4T).

    This is benchmarked as an alternative architecture, not the default path.
    """

    @abstractmethod
    async def load(self) -> None: ...

    @abstractmethod
    async def unload(self) -> None: ...

    @abstractmethod
    async def translate_audio(
        self,
        frame: "AudioFrame",
        source_language: "LanguageCode",
        target_language: "LanguageCode",
    ) -> "TranslationResult":
        """Translate audio directly to target-language text."""
        ...

    @abstractmethod
    async def health_check(self) -> bool: ...
