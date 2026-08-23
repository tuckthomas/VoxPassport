"""Worker-side protocol implemented by TTS model-library drivers."""

from __future__ import annotations

import io
import wave
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional

from runtime.inference.tts_plugins.manifest import TtsManifest


@dataclass(frozen=True)
class TtsDriverRequest:
    text: str
    language: str
    reference_audio: Optional[Path] = None
    reference_text: str = ""
    target_conditioning_audio: Optional[Path] = None


class TtsDriver(ABC):
    """Narrow boundary between the generic worker host and a model library."""

    def __init__(self, manifest: TtsManifest) -> None:
        self.manifest = manifest

    @abstractmethod
    def load(self) -> None:
        ...

    @abstractmethod
    def unload(self) -> None:
        ...

    @abstractmethod
    def synthesize_pcm(self, request: TtsDriverRequest) -> Iterator[bytes]:
        """Yield mono signed 16-bit little-endian PCM chunks."""
        ...

    def synthesize_wav(self, request: TtsDriverRequest) -> bytes:
        chunks = list(self.synthesize_pcm(request))
        pcm = b"".join(chunks)
        if not pcm:
            raise RuntimeError(f"{self.manifest.display_name} generated no audio")
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self.manifest.native_sample_rate_hz)
            wav.writeframes(pcm)
        return buffer.getvalue()

    def capabilities(self) -> dict[str, Any]:
        return {
            "protocol": "voxpassport.tts.v1",
            "model_id": self.manifest.model_id,
            "display_name": self.manifest.display_name,
            "languages": list(self.manifest.languages),
            "streaming": bool(self.manifest.capabilities.get("streaming", True)),
            "voice_cloning": self.manifest.supports_voice_cloning,
            "cross_lingual_voice_cloning": self.manifest.cross_lingual_voice_cloning,
            "reference_transcript_required": self.manifest.transcript_required,
            "sample_rate_hz": self.manifest.native_sample_rate_hz,
            "sample_format": self.manifest.sample_format,
        }

    def metrics(self) -> dict[str, Any]:
        return {}

    def health_check(self) -> bool:
        return True
