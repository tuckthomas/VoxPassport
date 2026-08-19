"""
VoxPassport — Higgs TTS 3 Adapter
=================================
Real Boson AI Higgs TTS 3 voice-cloning client.

This adapter intentionally does not accept or reuse an OmniVoice engine. The old
implementation labeled OmniVoice output as "Higgs TTS 3", making A/B testing
invalid. Higgs now talks to its own vLLM-Omni /v1/audio/speech endpoint.
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


class HiggsTtsAdapter(TtsAdapter):
    """Client for a real Higgs TTS 3 server."""

    ADAPTER_NAME = "HiggsTtsAdapter"
    _NATIVE_SAMPLE_RATE_HZ = 24000

    def __init__(
        self,
        model_path: Optional[str] = None,
        device: str = "cuda",
        shared_engine: Optional[object] = None,
        endpoint_url: Optional[str] = None,
    ):
        if shared_engine is not None:
            logger.warning(
                "Ignoring shared_engine for Higgs TTS 3. Reusing OmniVoice here was "
                "the previous model-routing bug."
            )
        self._model_path = model_path or "bosonai/higgs-tts-3-4b"
        self._device = device
        self._endpoint_url = (
            endpoint_url
            or os.getenv("VOXPASSPORT_HIGGS_TTS_URL", "http://127.0.0.1:8095")
        ).rstrip("/")
        self._loaded = True

    async def load(self) -> None:
        # The model lives in the dedicated vLLM-Omni server process. Loading this
        # adapter only makes the client available.
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
            "Higgs streaming transport is not wired into TtsAudioChunk yet."
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
        """Generate a real Higgs TTS 3 clone through vLLM-Omni."""
        if not self._loaded:
            raise RuntimeError("HiggsTtsAdapter is not loaded.")
        if not text or not text.strip():
            raise ValueError("Target TTS text must not be empty.")

        clean_ref_text = (ref_text or "").strip()
        payload = {
            "model": self._model_path,
            "input": text.strip(),
            "ref_audio": self._audio_data_uri(ref_audio_path),
            "response_format": "wav",
        }
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
                            f"Higgs TTS 3 server returned HTTP {response.status}: {detail}"
                        )
                    if len(body) < 500:
                        raise RuntimeError(
                            "Higgs TTS 3 returned an unexpectedly small audio payload."
                        )
                    return body
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise RuntimeError(
                "Real Higgs TTS 3 is not reachable. Start its vLLM-Omni server, "
                "for example: `vllm-omni serve bosonai/higgs-tts-3-4b "
                "--host 0.0.0.0 --port 8095 --trust-remote-code --omni`, or set "
                "VOXPASSPORT_HIGGS_TTS_URL. VoxPassport will not silently fall "
                "back to OmniVoice."
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
