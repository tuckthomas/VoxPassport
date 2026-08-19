"""
VoxPassport — MOSS-TTS Local Transformer v1.5 Adapter
=====================================================
Real OpenMOSS MOSS-TTS v1.5 voice-cloning client.

The old implementation routed MOSS selections into OmniVoice. This adapter uses
MOSS-TTS's own SGLang-Omni /v1/audio/speech endpoint, including the explicit
language hint recommended by the v1.5 model card.
"""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from typing import AsyncIterator, Optional

import aiohttp

from runtime.inference.adapters.base import TtsAdapter
from runtime.inference.protocol import LanguageCode, TtsAudioChunk, VoiceSpec

logger = logging.getLogger(__name__)


class MossTtsAdapter(TtsAdapter):
    """Client for a real MOSS-TTS Local Transformer v1.5 server."""

    ADAPTER_NAME = "MossTtsAdapter"
    _NATIVE_SAMPLE_RATE_HZ = 48000

    def __init__(
        self,
        model_path: Optional[str] = None,
        device: str = "cuda",
        shared_engine: Optional[object] = None,
        endpoint_url: Optional[str] = None,
    ):
        if shared_engine is not None:
            logger.warning(
                "Ignoring shared_engine for MOSS-TTS. Reusing OmniVoice here was "
                "the previous model-routing bug."
            )
        self._model_path = (
            model_path or "OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5"
        )
        self._device = device
        self._endpoint_url = (
            endpoint_url
            or os.getenv("VOXPASSPORT_MOSS_TTS_URL", "http://127.0.0.1:8001")
        ).rstrip("/")
        self._loaded = True

    async def load(self) -> None:
        self._loaded = True

    async def unload(self) -> None:
        self._loaded = False

    async def synthesize_stream(
        self,
        text: str,
        language: LanguageCode,
        voice: VoiceSpec,
    ) -> AsyncIterator[TtsAudioChunk]:
        raise NotImplementedError(
            "MOSS streaming transport is not wired into TtsAudioChunk yet."
        )
        yield  # pragma: no cover

    @staticmethod
    def _audio_data_uri(path: str) -> str:
        audio_path = Path(path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Reference audio does not exist: {path}")
        encoded = base64.b64encode(audio_path.read_bytes()).decode("ascii")
        return f"data:audio/wav;base64,{encoded}"

    async def generate_cloned_audio(
        self,
        text: str,
        ref_audio_path: str,
        ref_text: str = "",
        num_step: int = 32,
        language: str = "Romanian",
    ) -> bytes:
        """Generate a real MOSS-TTS v1.5 clone through SGLang-Omni."""
        if not self._loaded:
            raise RuntimeError("MossTtsAdapter is not loaded.")
        if not text or not text.strip():
            raise ValueError("Target TTS text must not be empty.")

        payload = {
            "input": text.strip(),
            "ref_audio": self._audio_data_uri(ref_audio_path),
            "language": language or None,
            "response_format": "wav",
        }
        clean_ref_text = (ref_text or "").strip()
        if clean_ref_text:
            payload["ref_text"] = clean_ref_text

        timeout = aiohttp.ClientTimeout(total=240)
        url = f"{self._endpoint_url}/v1/audio/speech"
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload) as response:
                    body = await response.read()
                    if response.status != 200:
                        detail = body.decode("utf-8", errors="replace")[:1500]
                        raise RuntimeError(
                            f"MOSS-TTS server returned HTTP {response.status}: {detail}"
                        )
                    if len(body) < 500:
                        raise RuntimeError(
                            "MOSS-TTS returned an unexpectedly small audio payload."
                        )
                    return body
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise RuntimeError(
                "Real MOSS-TTS v1.5 is not reachable. Start SGLang-Omni with "
                "`sgl-omni serve --model-path "
                "OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5 --port 8001`, "
                "or set VOXPASSPORT_MOSS_TTS_URL. VoxPassport will not silently "
                "fall back to OmniVoice."
            ) from exc

    async def supports_voice_cloning(self) -> bool:
        return True

    async def supports_language(self, language: LanguageCode) -> bool:
        return True

    @property
    def native_sample_rate_hz(self) -> int:
        return self._NATIVE_SAMPLE_RATE_HZ

    async def health_check(self) -> bool:
        try:
            timeout = aiohttp.ClientTimeout(total=2)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"{self._endpoint_url}/v1/models") as response:
                    return response.status < 500
        except Exception:
            return False
