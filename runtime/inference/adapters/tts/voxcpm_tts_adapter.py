"""OpenBMB VoxCPM2 TTS adapter using the local vLLM-Omni speech API."""

from __future__ import annotations

import base64
import logging
import os
import uuid
from pathlib import Path
from typing import AsyncIterator, Optional

import aiohttp

from runtime.inference.adapters.base import TtsAdapter
from runtime.inference.adapters.tts.profile_reference import resolve_profile_reference
from runtime.inference.protocol import LanguageCode, SampleFormat, TtsAudioChunk, VoiceSpec

logger = logging.getLogger(__name__)


class VoxCpmTtsAdapter(TtsAdapter):
    ADAPTER_NAME = "VoxCpmTtsAdapter"
    _NATIVE_SAMPLE_RATE_HZ = 48000
    _SUPPORTED = {
        LanguageCode.AR, LanguageCode.DA, LanguageCode.NL, LanguageCode.EN,
        LanguageCode.FI, LanguageCode.FR, LanguageCode.DE, LanguageCode.EL,
        LanguageCode.HE, LanguageCode.HI, LanguageCode.ID, LanguageCode.IT,
        LanguageCode.JA, LanguageCode.KO, LanguageCode.MS, LanguageCode.NO,
        LanguageCode.PL, LanguageCode.PT, LanguageCode.RU, LanguageCode.ES,
        LanguageCode.SV, LanguageCode.TL, LanguageCode.TH, LanguageCode.TR,
        LanguageCode.VI, LanguageCode.ZH,
    }

    def __init__(
        self,
        model_path: Optional[str] = None,
        device: str = "cuda",
        shared_engine: Optional[object] = None,
        endpoint_url: Optional[str] = None,
        profiles_root: Optional[Path] = None,
    ) -> None:
        if shared_engine is not None:
            logger.warning("Ignoring shared_engine for VoxCPM2; TTS engines are isolated")
        self._model_path = model_path or "openbmb/VoxCPM2"
        self._device = device
        self._endpoint_url = (
            endpoint_url or os.getenv("VOXPASSPORT_VOXCPM_TTS_URL", "http://127.0.0.1:8097")
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
        return "data:audio/wav;base64," + base64.b64encode(audio_path.read_bytes()).decode("ascii")

    def _validate_language(self, language: LanguageCode | str) -> None:
        if isinstance(language, LanguageCode):
            code = language
        else:
            try:
                code = LanguageCode(str(language).lower())
            except ValueError as exc:
                raise ValueError(f"VoxCPM2 does not publish support for {language!r}") from exc
        if code not in self._SUPPORTED:
            raise ValueError(
                f"VoxCPM2 does not publish support for {code.value!r}; select a TTS engine that supports the target language"
            )

    def _profile_reference(self, voice: VoiceSpec) -> tuple[Path, str]:
        _, audio, text = resolve_profile_reference(
            self._profiles_root, voice.voice_profile_id, require_transcript=True
        )
        return audio, text

    async def synthesize_stream(
        self, text: str, language: LanguageCode, voice: VoiceSpec
    ) -> AsyncIterator[TtsAudioChunk]:
        if not self._loaded:
            raise RuntimeError("VoxCpmTtsAdapter is not loaded")
        clean = str(text).strip()
        if not clean:
            raise ValueError("Target TTS text must not be empty")
        self._validate_language(language)
        payload: dict[str, object] = {
            "model": self._model_path,
            "input": clean,
            "voice": "default",
            "stream": True,
            "stream_format": "audio",
            "response_format": "pcm",
        }
        if voice.is_cloned:
            ref_audio, ref_text = self._profile_reference(voice)
            payload["ref_audio"] = self._audio_data_uri(ref_audio)
            payload["ref_text"] = ref_text

        utterance_id, segment_id = str(uuid.uuid4()), str(uuid.uuid4())
        sequence = 0
        sample_rate = self._NATIVE_SAMPLE_RATE_HZ
        timeout = aiohttp.ClientTimeout(total=300, sock_read=180)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(f"{self._endpoint_url}/v1/audio/speech", json=payload) as response:
                    if response.status != 200:
                        detail = (await response.read()).decode("utf-8", errors="replace")[:1500]
                        raise RuntimeError(f"VoxCPM2 server returned HTTP {response.status}: {detail}")
                    sample_rate = int(response.headers.get("x-sample-rate", self._NATIVE_SAMPLE_RATE_HZ))
                    carry = b""
                    emitted = False
                    async for network_chunk in response.content.iter_chunked(32768):
                        if not network_chunk:
                            continue
                        data = carry + network_chunk
                        even = len(data) - len(data) % 2
                        if not even:
                            carry = data
                            continue
                        pcm, carry = data[:even], data[even:]
                        emitted = True
                        yield TtsAudioChunk(
                            utterance_id=utterance_id, segment_id=segment_id, sequence=sequence,
                            sample_rate_hz=sample_rate, sample_format=SampleFormat.PCM_S16LE,
                            data=pcm, is_final_chunk=False,
                        )
                        sequence += 1
                    if carry:
                        logger.warning("Dropping one trailing byte from VoxCPM2 PCM stream")
                    if not emitted:
                        raise RuntimeError("VoxCPM2 stream returned no PCM audio")
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise RuntimeError(
                "VoxCPM2 backend is not reachable on its configured local worker; start it on port 8097 or set VOXPASSPORT_VOXCPM_TTS_URL."
            ) from exc
        yield TtsAudioChunk(
            utterance_id=utterance_id, segment_id=segment_id, sequence=sequence,
            sample_rate_hz=sample_rate, sample_format=SampleFormat.PCM_S16LE,
            data=b"", is_final_chunk=True,
        )

    async def generate_cloned_audio(
        self, text: str, ref_audio_path: str, ref_text: str = "", num_step: int = 10,
        language: str = "English",
    ) -> bytes:
        if not self._loaded:
            raise RuntimeError("VoxCpmTtsAdapter is not loaded")
        clean = str(text).strip()
        if not clean:
            raise ValueError("Target TTS text must not be empty")
        if str(language or "").strip().lower() in {"romanian", "ro"}:
            raise ValueError("VoxCPM2 does not publish Romanian support")
        payload: dict[str, object] = {
            "model": self._model_path,
            "input": clean,
            "voice": "default",
            "ref_audio": self._audio_data_uri(ref_audio_path),
            "response_format": "wav",
        }
        clean_ref = str(ref_text or "").strip()
        if clean_ref:
            payload["ref_text"] = clean_ref
        timeout = aiohttp.ClientTimeout(total=240)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(f"{self._endpoint_url}/v1/audio/speech", json=payload) as response:
                    body = await response.read()
                    if response.status != 200:
                        detail = body.decode("utf-8", errors="replace")[:1500]
                        raise RuntimeError(f"VoxCPM2 server returned HTTP {response.status}: {detail}")
                    if len(body) < 500:
                        raise RuntimeError("VoxCPM2 returned an unexpectedly small audio payload")
                    return body
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise RuntimeError(
                "VoxCPM2 backend is not reachable on port 8097; set VOXPASSPORT_VOXCPM_TTS_URL to override."
            ) from exc

    async def supports_voice_cloning(self) -> bool:
        return True

    async def supports_language(self, language: LanguageCode) -> bool:
        return language in self._SUPPORTED

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
