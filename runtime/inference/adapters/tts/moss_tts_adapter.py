"""VoxPassport — MOSS-TTS Local Transformer v1.5 Adapter.

Uses SGLang-Omni's native /v1/audio/speech streaming mode. Streaming responses
are raw 48 kHz mono signed-16 PCM, so chunks can be played immediately without
waiting for a complete WAV file.
"""

from __future__ import annotations

import base64
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


class MossTtsAdapter(TtsAdapter):
    ADAPTER_NAME = "MossTtsAdapter"
    _NATIVE_SAMPLE_RATE_HZ = 48000

    _LANGUAGE_NAMES = {
        LanguageCode.EN: "English",
        LanguageCode.RO: "Romanian",
    }

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
                "Ignoring shared_engine for MOSS-TTS; reusing OmniVoice was "
                "the previous routing bug."
            )
        self._model_path = (
            model_path or "OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5"
        )
        self._device = device
        self._endpoint_url = (
            endpoint_url
            or os.getenv("VOXPASSPORT_MOSS_TTS_URL", "http://127.0.0.1:8001")
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
            raise ValueError("Cloned MOSS streaming requires voice_profile_id.")
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

    def _language_name(self, language: LanguageCode) -> str:
        return self._LANGUAGE_NAMES.get(language, getattr(language, "value", str(language)))

    async def synthesize_stream(
        self,
        text: str,
        language: LanguageCode,
        voice: VoiceSpec,
    ) -> AsyncIterator[TtsAudioChunk]:
        """Yield native MOSS 48 kHz PCM chunks in real time."""
        if not self._loaded:
            raise RuntimeError("MossTtsAdapter is not loaded.")
        if not text or not text.strip():
            raise ValueError("Target TTS text must not be empty.")

        payload: dict[str, object] = {
            "model": self._model_path,
            "voice": "default",
            "input": text.strip(),
            "language": self._language_name(language),
            "stream": True,
            "response_format": "pcm",
            "initial_codec_chunk_frames": 5,
        }
        if voice.is_cloned:
            ref_audio, ref_text = self._profile_reference(voice)
            payload["ref_audio"] = self._audio_data_uri(ref_audio)
            payload["ref_text"] = ref_text

        utterance_id = str(uuid.uuid4())
        segment_id = str(uuid.uuid4())
        sequence = 0
        url = f"{self._endpoint_url}/v1/audio/speech"
        timeout = aiohttp.ClientTimeout(total=300, sock_read=180)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload) as response:
                    if response.status != 200:
                        body = await response.read()
                        detail = body.decode("utf-8", errors="replace")[:1500]
                        raise RuntimeError(
                            f"MOSS-TTS server returned HTTP {response.status}: {detail}"
                        )

                    sample_rate = int(
                        response.headers.get("x-sample-rate", self._NATIVE_SAMPLE_RATE_HZ)
                    )
                    channels = int(response.headers.get("x-channels", "1"))
                    bit_depth = int(response.headers.get("x-bit-depth", "16"))
                    if channels != 1 or bit_depth != 16:
                        raise RuntimeError(
                            "MOSS streaming returned unsupported PCM layout: "
                            f"{sample_rate} Hz, {channels} channel(s), {bit_depth}-bit."
                        )

                    carry = b""
                    emitted = False
                    async for network_chunk in response.content.iter_chunked(32768):
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
                        logger.warning("Dropping one trailing byte from MOSS PCM stream.")
                    if not emitted:
                        raise RuntimeError("MOSS-TTS stream returned no PCM audio.")

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
                "Real MOSS-TTS v1.5 streaming backend is not reachable. Start "
                "SGLang-Omni with `sgl-omni serve --model-path "
                "OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5 --port 8001`, "
                "or set VOXPASSPORT_MOSS_TTS_URL."
            ) from exc

    async def generate_cloned_audio(
        self,
        text: str,
        ref_audio_path: str,
        ref_text: str = "",
        num_step: int = 32,
        language: str = "Romanian",
    ) -> bytes:
        if not self._loaded:
            raise RuntimeError("MossTtsAdapter is not loaded.")
        if not text or not text.strip():
            raise ValueError("Target TTS text must not be empty.")

        payload: dict[str, object] = {
            "model": self._model_path,
            "voice": "default",
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
                "or set VOXPASSPORT_MOSS_TTS_URL."
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
