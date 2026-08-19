"""
LiveTranslator — Shared Protocol Types
=======================================
All wire-level and in-process data structures for the translation pipeline.
No model-specific code belongs here. These types are shared across all adapters,
the pipeline, the scheduler, and the IPC layer.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Language codes
# ---------------------------------------------------------------------------

class LanguageCode(str, enum.Enum):
    """BCP-47 language codes used in this application."""
    EN = "en"
    RO = "ro"

    @classmethod
    def _missing_(cls, value: object) -> Optional["LanguageCode"]:
        # Allow plain strings like "en-US" to fall back to base code
        if isinstance(value, str):
            base = value.split("-")[0].lower()
            for member in cls:
                if member.value == base:
                    return member
        return None


# ---------------------------------------------------------------------------
# Audio frame
# ---------------------------------------------------------------------------

class SampleFormat(str, enum.Enum):
    PCM_S16LE = "pcm_s16le"   # 16-bit signed little-endian
    PCM_F32LE = "pcm_f32le"   # 32-bit float little-endian


@dataclass(slots=True)
class AudioFrame:
    """A single block of raw PCM audio."""
    stream_id: str
    sequence: int
    monotonic_timestamp_ns: int
    sample_rate_hz: int
    channels: int
    sample_format: SampleFormat
    data: bytes  # Raw PCM payload — never base64, never JSON

    @staticmethod
    def now_ns() -> int:
        return time.monotonic_ns()


# ---------------------------------------------------------------------------
# Audio bus identifiers
# ---------------------------------------------------------------------------

class AudioBus(str, enum.Enum):
    """Logical audio buses. These names are used throughout the routing layer."""
    PHYSICAL_MIC = "BUS_PHYSICAL_MIC"
    REMOTE_CONFERENCE = "BUS_REMOTE_CONFERENCE"
    OUTBOUND_TRANSLATED_TTS = "BUS_OUTBOUND_TRANSLATED_TTS"
    INBOUND_TRANSLATED_TTS = "BUS_INBOUND_TRANSLATED_TTS"
    VIRTUAL_MIC = "BUS_VIRTUAL_MIC"
    LOCAL_MONITOR = "BUS_LOCAL_MONITOR"


# ---------------------------------------------------------------------------
# VAD events
# ---------------------------------------------------------------------------

class VadEventType(str, enum.Enum):
    SPEECH_START = "speech_start"
    SPEECH_END = "speech_end"
    SILENCE = "silence"


@dataclass(slots=True)
class VadEvent:
    event_type: VadEventType
    stream_id: str
    monotonic_timestamp_ns: int
    confidence: float = 1.0


# ---------------------------------------------------------------------------
# ASR / Transcript events
# ---------------------------------------------------------------------------

class TranscriptState(str, enum.Enum):
    PARTIAL = "partial"   # Revisionable hypothesis
    STABLE = "stable"     # Stable prefix, not yet final
    FINAL = "final"       # Endpoint reached; no further revisions


@dataclass(slots=True)
class TranscriptEvent:
    """Emitted by an ASR adapter for each partial/final recognition result."""
    utterance_id: str
    revision: int
    source_language: LanguageCode
    text: str
    state: TranscriptState
    start_ms: Optional[float] = None
    end_ms: Optional[float] = None
    # Optional model-specific metadata — never contains raw audio
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_partial(self) -> bool:
        return self.state == TranscriptState.PARTIAL

    @property
    def is_final(self) -> bool:
        return self.state == TranscriptState.FINAL


# ---------------------------------------------------------------------------
# Translation events
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class TranslationContext:
    """Recent committed source text to provide context to the translation model."""
    recent_source_segments: list[str] = field(default_factory=list)
    recent_translated_segments: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TranslationResult:
    translated_text: str
    source_language: LanguageCode
    target_language: LanguageCode
    latency_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TranslationEvent:
    """Published when a committed source segment has been translated."""
    utterance_id: str
    segment_id: str
    source_language: LanguageCode
    target_language: LanguageCode
    source_text: str
    translated_text: str
    is_committed: bool
    created_monotonic_ns: int = field(default_factory=time.monotonic_ns)


# ---------------------------------------------------------------------------
# TTS audio events
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class TtsAudioChunk:
    """A streaming chunk of synthesized PCM audio."""
    utterance_id: str
    segment_id: str
    sequence: int
    sample_rate_hz: int
    sample_format: SampleFormat
    data: bytes  # Raw PCM
    is_final_chunk: bool = False


# ---------------------------------------------------------------------------
# Caption events
# ---------------------------------------------------------------------------

class CaptionEventType(str, enum.Enum):
    SOURCE_PARTIAL = "source_partial"
    SOURCE_FINAL = "source_final"
    TRANSLATION_PARTIAL = "translation_partial"
    TRANSLATION_FINAL = "translation_final"
    SYSTEM_STATUS = "system_status"
    LATENCY_UPDATE = "latency_update"
    ERROR = "error"


@dataclass(slots=True)
class CaptionEvent:
    event_type: CaptionEventType
    utterance_id: str
    language: LanguageCode
    text: str
    is_provisional: bool = True
    created_monotonic_ns: int = field(default_factory=time.monotonic_ns)
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Metrics event
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class MetricsEvent:
    """Content-free performance metrics. Never contains speech content."""
    utterance_id: str
    capture_to_asr_partial_ms: Optional[float] = None
    endpoint_to_asr_final_ms: Optional[float] = None
    translation_ms: Optional[float] = None
    tts_time_to_first_audio_ms: Optional[float] = None
    tts_total_ms: Optional[float] = None
    capture_to_first_translated_audio_ms: Optional[float] = None
    caption_lag_ms: Optional[float] = None
    asr_queue_depth: int = 0
    mt_queue_depth: int = 0
    tts_queue_depth: int = 0
    cpu_percent: float = 0.0
    gpu_utilization_percent: float = 0.0
    vram_used_mb: float = 0.0
    dropped_audio_frames: int = 0


# ---------------------------------------------------------------------------
# Pipeline mode
# ---------------------------------------------------------------------------

class PipelineMode(str, enum.Enum):
    FULL_DUPLEX = "full_duplex"
    OUTBOUND_TRANSLATION = "outbound_translation"
    INBOUND_TRANSLATION = "inbound_translation"
    CAPTIONS_ONLY = "captions_only"


class TtsMode(str, enum.Enum):
    STOCK = "tts_no_clone"
    CLONED = "tts_cloned"


class RuntimeTier(str, enum.Enum):
    LOW_LATENCY_LIGHT = "low_latency_light"
    BALANCED = "balanced"
    QUALITY = "quality"
    DEGRADED_CAPTIONS_ONLY = "degraded_captions_only"


# ---------------------------------------------------------------------------
# Model capability
# ---------------------------------------------------------------------------

class ModelCapability(str, enum.Enum):
    ASR = "ASR"
    TRANSLATION = "TRANSLATION"
    TTS = "TTS"
    VAD = "VAD"
    DIRECT_SPEECH_TRANSLATION = "DIRECT_SPEECH_TRANSLATION"


class InstallationStatus(str, enum.Enum):
    NOT_INSTALLED = "not_installed"
    DOWNLOADING = "downloading"
    INSTALLING = "installing"
    INSTALLED = "installed"
    FAILED = "failed"


class HotSwapState(str, enum.Enum):
    REQUESTED = "REQUESTED"
    PRELOADING = "PRELOADING"
    READY = "READY"
    DRAINING_OLD_MODEL = "DRAINING_OLD_MODEL"
    ACTIVE = "ACTIVE"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


class RecommendationState(str, enum.Enum):
    IGNORE = "IGNORE"
    WATCH = "WATCH"
    CANDIDATE = "CANDIDATE"
    RECOMMENDED_FOR_LOCAL_BENCHMARK = "RECOMMENDED_FOR_LOCAL_BENCHMARK"
    RECOMMENDED_UPGRADE = "RECOMMENDED_UPGRADE"


# ---------------------------------------------------------------------------
# Voice specification
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class VoiceSpec:
    """Describes a voice for TTS synthesis."""
    language: LanguageCode
    is_cloned: bool = False
    # Voice profile ID — references persisted (encrypted) speaker conditioning data.
    # None means use the default stock voice for the language.
    voice_profile_id: Optional[str] = None
