"""
LiveTranslator — Extended Protocol Types
=========================================
ASR stream configuration and stream handle types referenced by adapters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AsrConfig:
    """Configuration for a single ASR stream session."""
    language: str            # BCP-47 language code, e.g. "en", "ro"
    sample_rate_hz: int = 16000
    channels: int = 1
    enable_partials: bool = True
    enable_punctuation: bool = True
    enable_capitalization: bool = True
    # Model-specific options passed through without interpretation
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AsrStream:
    """
    Opaque handle representing an open ASR stream.
    Adapters may subclass this or wrap it internally.
    The pipeline treats it as an opaque token.
    """
    stream_id: str
    language: str
    sample_rate_hz: int
    # Adapter-internal state — not accessed by pipeline code
    _adapter_state: Any = field(default=None, repr=False)
