"""
VoxPassport — VoxCPM 2 Adapter
==============================
Real OpenBMB VoxCPM2 voice-cloning client via vLLM-Omni.

VoxCPM2 does NOT currently list Romanian among its 30 supported languages. The
adapter therefore refuses Romanian instead of silently routing the request into
OmniVoice as the previous implementation did.
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


class VoxCpmTtsAdapter(TtsAdapter):
    """Client for a real openbmb/VoxCPM2 server."""

    ADAPTER_NAME = "VoxCpmTtsAdapter"
    _NATIVE_SAMPLE_RATE_HZ = 48000
    _UNSUPPORTED_LANGUAGE_NAMES = {"romanian", "ro"}

    def __init__(
        self,
        model_path: Optional[str] = None,
        device: str = "cuda",
        shared_engine: Optional[object] = None,
        endpoint_url: Optional[str] = None,
    ):
        if shared_engine is not None:
            logger.warning(
                "Ignoring shared_engine for VoxCPM2. Reusing OmniVoice here was "
                "the previous model-routing bug."
            )
        self._model_path = model_path or "openbmb/VoxCPM2"
        self._device = device
        self._endpoint_url = (
            endpoint_url
            or os.getenv("VOXPASSPORT_VOXCPM_TTS_URL", "http://127.0.0.1:8002")
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
            "VoxCPM2 streaming transport is not wired into TtsAudioChunk yet."
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
        num_step: int = 10,
        language: str = "English",
    ) -> bytes:
        """Generate a real VoxCPM2 clone for a supported language."""
        if not self._loaded:
            raise RuntimeError("VoxCpmTtsAdapter is not loaded.")
        if not text or not text.strip():
            raise ValueError("Target TTS text must not be empty.")
        if (language or "").strip().lower() in self._UNSUPPORTED_LANGUAGE_NAMES:
            raise ValueError(
                "VoxCPM2 does not currently list Romanian among its supported "
                "languages. Use MOSS-TTS v1.5, Higgs TTS 3, or OmniVoice for Romanian."
            )

        payload = {
            "model": self._model_path,
            "input": text.strip(),
            "voice": "default",
            "ref_audio": self._audio_data_uri(ref_audio_path),
            "response_format": "wav",
        }
        clean_ref_text = (ref_text or "").strip()
        if clean_ref_text:
            payload["ref_text"] = clean_ref_text

        timeout = aiohttp.ClientTimeout(total=180)
        url = f"{self._endpoint_url}/v1/audio/speech"
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload) as response:
                    body = await response.read()
                    if response.status != 200:
                        detail = body.decode("utf-8", errors="replace")[:1500]
                        raise RuntimeError(
                            f"VoxCPM2 server returned HTTP {response.status}: {detail}"
                        )
                    if len(body) < 500:
                        raise RuntimeError(
                            "VoxCPM2 returned an unexpectedly small audio payload."
                        )
                    return body
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise RuntimeError(
                "Real VoxCPM2 is not reachable. Start vLLM-Omni with "
                "`vllm serve openbmb/VoxCPM2 --omni --host 0.0.0.0 --port 8002`, "
                "or set VOXPASSPORT_VOXCPM_TTS_URL. VoxPassport will not silently "
                "fall back to OmniVoice."
            ) from exc

    async def supports_voice_cloning(self) -> bool:
        return True

    async def supports_language(self, language: LanguageCode) -> bool:
        # The current app enum prominently includes English/Romanian; Romanian is
        # explicitly not supported by VoxCPM2's published 30-language list.
        return language != LanguageCode.RO

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
