"""VoxPassport shared runtime protocol types.

These types are intentionally model-agnostic and are shared by adapters,
pipelines, the scheduler, and the local UI/API boundary.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Any, Optional


class LanguageCode(str, enum.Enum):
    """Language codes currently accepted by the runtime.

    MiLMMT supports a much larger set; this enum contains the languages exposed
    by the desktop UI plus common expansion targets.  `_missing_` also accepts a
    regional BCP-47 form such as ``pt-BR`` and resolves it to its base language.
    """

    EN = "en"
    RO = "ro"
    ES = "es"
    FR = "fr"
    DE = "de"
    IT = "it"
    PT = "pt"
    NL = "nl"
    PL = "pl"
    CS = "cs"
    HU = "hu"
    TR = "tr"
    RU = "ru"
    UK = "uk"
    BG = "bg"
    EL = "el"
    AR = "ar"
    HE = "he"
    HI = "hi"
    BN = "bn"
    FA = "fa"
    FI = "fi"
    SV = "sv"
    DA = "da"
    NO = "no"
    HR = "hr"
    SK = "sk"
    SL = "sl"
    ID = "id"
    MS = "ms"
    VI = "vi"
    TH = "th"
    TL = "tl"
    JA = "ja"
    KO = "ko"
    ZH = "zh"

    @classmethod
    def _missing_(cls, value: object) -> Optional["LanguageCode"]:
        if isinstance(value, str):
            base = value.split("-")[0].lower().strip()
            for member in cls:
                if member.value == base:
                    return member
        return None


class SampleFormat(str, enum.Enum):
    PCM_S16LE = "pcm_s16le"
    PCM_F32LE = "pcm_f32le"


@dataclass(slots=True)
class AudioFrame:
    stream_id: str
    sequence: int
    monotonic_timestamp_ns: int
    sample_rate_hz: int
    channels: int
    sample_format: SampleFormat
    data: bytes

    @staticmethod
    def now_ns() -> int:
        return time.monotonic_ns()


class AudioBus(str, enum.Enum):
    PHYSICAL_MIC = "BUS_PHYSICAL_MIC"
    REMOTE_CONFERENCE = "BUS_REMOTE_CONFERENCE"
    OUTBOUND_TRANSLATED_TTS = "BUS_OUTBOUND_TRANSLATED_TTS"
    INBOUND_TRANSLATED_TTS = "BUS_INBOUND_TRANSLATED_TTS"
    VIRTUAL_MIC = "BUS_VIRTUAL_MIC"
    LOCAL_MONITOR = "BUS_LOCAL_MONITOR"


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


class TranscriptState(str, enum.Enum):
    PARTIAL = "partial"
    STABLE = "stable"
    FINAL = "final"


@dataclass(slots=True)
class TranscriptEvent:
    utterance_id: str
    revision: int
    source_language: LanguageCode
    text: str
    state: TranscriptState
    start_ms: Optional[float] = None
    end_ms: Optional[float] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_partial(self) -> bool:
        return self.state == TranscriptState.PARTIAL

    @property
    def is_final(self) -> bool:
        return self.state == TranscriptState.FINAL


@dataclass(slots=True)
class TranslationContext:
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
    utterance_id: str
    segment_id: str
    source_language: LanguageCode
    target_language: LanguageCode
    source_text: str
    translated_text: str
    is_committed: bool
    created_monotonic_ns: int = field(default_factory=time.monotonic_ns)


@dataclass(slots=True)
class TtsAudioChunk:
    utterance_id: str
    segment_id: str
    sequence: int
    sample_rate_hz: int
    sample_format: SampleFormat
    data: bytes
    is_final_chunk: bool = False


class CaptionEventType(str, enum.Enum):
    """Caption event names.

    The alias members preserve compatibility with older pipeline code while the
    canonical wire values stay stable.
    """

    SOURCE_PARTIAL = "source_partial"
    SOURCE_FINAL = "source_final"
    TRANSLATION_PARTIAL = "translation_partial"
    TRANSLATION_FINAL = "translation_final"
    SYSTEM_STATUS = "system_status"
    LATENCY_UPDATE = "latency_update"
    ERROR = "error"

    # Backward-compatible aliases used by the existing duplex pipelines.
    PARTIAL_SOURCE = "source_partial"
    FINAL_SOURCE = "source_final"
    COMMITTED_TRANSLATION = "translation_final"


@dataclass(slots=True)
class CaptionEvent:
    """Caption payload compatible with both old and new field names."""

    event_type: CaptionEventType
    utterance_id: str
    language: LanguageCode
    text: str
    is_provisional: bool = True
    created_monotonic_ns: int = field(default_factory=time.monotonic_ns)
    metadata: dict[str, Any] = field(default_factory=dict)
    is_final: Optional[bool] = None
    monotonic_timestamp_ns: Optional[int] = None

    def __post_init__(self) -> None:
        if self.is_final is None:
            self.is_final = not self.is_provisional
        else:
            self.is_provisional = not self.is_final

        if self.monotonic_timestamp_ns is None:
            self.monotonic_timestamp_ns = self.created_monotonic_ns
        else:
            self.created_monotonic_ns = self.monotonic_timestamp_ns


@dataclass(slots=True)
class MetricsEvent:
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


@dataclass(slots=True)
class VoiceSpec:
    language: LanguageCode
    is_cloned: bool = False
    voice_profile_id: Optional[str] = None
