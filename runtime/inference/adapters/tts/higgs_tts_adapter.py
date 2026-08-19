"""VoxPassport — Higgs TTS 3 Adapter.

Uses the native SGLang-Omni /v1/audio/speech API for both batch WAV output and
true incremental 16-bit mono PCM streaming.  A cloned VoiceSpec resolves its
saved reference WAV/transcript from data/voice_profiles.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import uuid
from pathlib import Path
from typing import AsyncIterator, Optional

import aiohttp

from runtime.inference.adapters.base import TtsAdapter
from runtime.inference.protocol import (
    LanguageCode,
    SampleFormat,
    TtsAudioChunk,
    VoiceSpec,
)

logger = logging.getLogger(__name__)


class HiggsTtsAdapter(TtsAdapter):
    ADAPTER_NAME = "HiggsTtsAdapter"
    _NATIVE_SAMPLE_RATE_HZ = 24000

    def __init__(
        self,
        model_path: Optional[str] = None,
        device: str = "cuda",
        shared_engine: Optional[object] = None,
        endpoint_url: Optional[str] = None,
        profiles_root: Optional[Path] = None,
    ):
        if shared_engine is not None:
            logger.warning(
                "Ignoring shared_engine for Higgs TTS 3; reusing OmniVoice was "
                "the previous routing bug."
            )
        self._model_path = model_path or "bosonai/higgs-tts-3-4b"
        self._device = device
        self._endpoint_url = (
            endpoint_url
            or os.getenv("VOXPASSPORT_HIGGS_TTS_URL", "http://127.0.0.1:8095")
        ).rstrip("/")
        project_root = Path(__file__).resolve().parents[4]
        self._profiles_root = Path(profiles_root or project_root / "data" / "voice_profiles")
        self._loaded = True

    async def load(self) -> None:
        self._loaded = True

    async def unload(self) -> None:
        self._loaded = False

    @staticmethod
    def _audio_data_uri(path: Path | str) -> str:
        audio_path = Path(path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Reference audio does not exist: {audio_path}")
        encoded = base64.b64encode(audio_path.read_bytes()).decode("ascii")
        return f"data:audio/wav;base64,{encoded}"

    def _profile_reference(self, voice: VoiceSpec) -> tuple[Path, str]:
        if not voice.voice_profile_id:
            raise ValueError("Cloned Higgs streaming requires voice_profile_id.")
        profile_dir = self._profiles_root / voice.voice_profile_id
        ref_audio = profile_dir / "reference.wav"
        ref_text_file = profile_dir / "reference.txt"
        if not ref_audio.exists():
            raise FileNotFoundError(
                f"Voice profile '{voice.voice_profile_id}' has no reference.wav"
            )
        ref_text = (
            ref_text_file.read_text(encoding="utf-8").strip()
            if ref_text_file.exists()
            else ""
        )
        if not ref_text:
            raise ValueError(
                f"Voice profile '{voice.voice_profile_id}' has no reference transcript."
            )
        return ref_audio, ref_text

    async def synthesize_stream(
        self,
        text: str,
        language: LanguageCode,
        voice: VoiceSpec,
    ) -> AsyncIterator[TtsAudioChunk]:
        """Yield true Higgs PCM chunks as SGLang's vocoder emits them."""
        if not self._loaded:
            raise RuntimeError("HiggsTtsAdapter is not loaded.")
        if not text or not text.strip():
            raise ValueError("Target TTS text must not be empty.")

        payload: dict[str, object] = {
            "model": self._model_path,
            "voice": "default",
            "input": text.strip(),
            "stream": True,
            "response_format": "pcm",
            "initial_codec_chunk_frames": 20,
        }
        if voice.is_cloned:
            ref_audio, ref_text = self._profile_reference(voice)
            payload["references"] = [{
                "audio_path": self._audio_data_uri(ref_audio),
                "text": ref_text,
            }]

        utterance_id = str(uuid.uuid4())
        segment_id = str(uuid.uuid4())
        sequence = 0
        url = f"{self._endpoint_url}/v1/audio/speech"
        timeout = aiohttp.ClientTimeout(total=240, sock_read=120)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload) as response:
                    if response.status != 200:
                        body = await response.read()
                        detail = body.decode("utf-8", errors="replace")[:1500]
                        raise RuntimeError(
                            f"Higgs TTS 3 server returned HTTP {response.status}: {detail}"
                        )

                    sample_rate = int(
                        response.headers.get("x-sample-rate", self._NATIVE_SAMPLE_RATE_HZ)
                    )
                    channels = int(response.headers.get("x-channels", "1"))
                    bit_depth = int(response.headers.get("x-bit-depth", "16"))
                    if channels != 1 or bit_depth != 16:
                        raise RuntimeError(
                            "Higgs streaming returned unsupported PCM layout: "
                            f"{sample_rate} Hz, {channels} channel(s), {bit_depth}-bit."
                        )

                    carry = b""
                    emitted = False
                    async for network_chunk in response.content.iter_chunked(16384):
                        if not network_chunk:
                            continue
                        data = carry + network_chunk
                        even_len = len(data) - (len(data) % 2)
                        if even_len == 0:
                            carry = data
                            continue
                        pcm = data[:even_len]
                        carry = data[even_len:]
                        emitted = True
                        yield TtsAudioChunk(
                            utterance_id=utterance_id,
                            segment_id=segment_id,
                            sequence=sequence,
                            sample_rate_hz=sample_rate,
                            sample_format=SampleFormat.PCM_S16LE,
                            data=pcm,
                            is_final_chunk=False,
                        )
                        sequence += 1

                    if carry:
                        logger.warning("Dropping one trailing byte from Higgs PCM stream.")
                    if not emitted:
                        raise RuntimeError("Higgs TTS 3 stream returned no PCM audio.")

                    yield TtsAudioChunk(
                        utterance_id=utterance_id,
                        segment_id=segment_id,
                        sequence=sequence,
                        sample_rate_hz=sample_rate,
                        sample_format=SampleFormat.PCM_S16LE,
                        data=b"",
                        is_final_chunk=True,
                    )
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise RuntimeError(
                "Real Higgs TTS 3 streaming backend is not reachable. Start "
                "SGLang-Omni with `sgl-omni serve --model-path "
                "bosonai/higgs-tts-3-4b --port 8095`, or set "
                "VOXPASSPORT_HIGGS_TTS_URL."
            ) from exc

    async def generate_cloned_audio(
        self,
        text: str,
        ref_audio_path: str,
        ref_text: str = "",
        num_step: int = 32,
        language: str = "Romanian",
    ) -> bytes:
        """Generate a non-streaming WAV with the real Higgs backend."""
        if not self._loaded:
            raise RuntimeError("HiggsTtsAdapter is not loaded.")
        if not text or not text.strip():
            raise ValueError("Target TTS text must not be empty.")

        payload: dict[str, object] = {
            "model": self._model_path,
            "voice": "default",
            "input": text.strip(),
            "references": [{
                "audio_path": self._audio_data_uri(ref_audio_path),
                "text": (ref_text or "").strip(),
            }],
            "response_format": "wav",
        }
        timeout = aiohttp.ClientTimeout(total=240)
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
                "Real Higgs TTS 3 is not reachable. Start SGLang-Omni with "
                "`sgl-omni serve --model-path bosonai/higgs-tts-3-4b --port 8095`, "
                "or set VOXPASSPORT_HIGGS_TTS_URL."
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
