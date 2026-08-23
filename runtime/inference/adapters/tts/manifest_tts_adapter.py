"""Generic TTS adapter for manifest-driven `voxpassport.tts.v1` workers."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import AsyncIterator, Optional

import aiohttp

from runtime.inference.adapters.base import TtsAdapter
from runtime.inference.adapters.tts.profile_reference import resolve_profile_reference
from runtime.inference.gpu_inference_coordinator import heavy_gpu_inference
from runtime.inference.protocol import LanguageCode, SampleFormat, TtsAudioChunk, VoiceSpec
from runtime.inference.tts_plugins.manifest import TtsManifest, TtsManifestCatalog

logger = logging.getLogger(__name__)


_LANGUAGE_ALIASES = {
    "english": "en",
    "romanian": "ro",
    "română": "ro",
    "romana": "ro",
}


class ManifestTtsAdapter(TtsAdapter):
    """One main-process adapter for every `voxpassport.tts.v1` TTS plugin."""

    ADAPTER_NAME = "ManifestTtsAdapter"

    def __init__(
        self,
        manifest: TtsManifest | str,
        *,
        profiles_root: Optional[Path] = None,
        catalog: Optional[TtsManifestCatalog] = None,
    ) -> None:
        if isinstance(manifest, TtsManifest):
            self.manifest = manifest
        else:
            self.manifest = (catalog or TtsManifestCatalog().load()).resolve(str(manifest))
        project_root = Path(__file__).resolve().parents[4]
        self._profiles_root = Path(profiles_root or project_root / "data" / "voice_profiles")
        self._endpoint_url = self.manifest.worker_base_url
        self._loaded = False
        self._runtime_capabilities: dict = {}

    @staticmethod
    def _language_value(language: LanguageCode | str) -> str:
        raw = str(getattr(language, "value", language)).strip().lower()
        return _LANGUAGE_ALIASES.get(raw, raw.split("-", 1)[0])

    def _profile_reference(self, voice: VoiceSpec, language: str) -> tuple[Path, str, Path | None]:
        _profile_id, audio, text = resolve_profile_reference(
            self._profiles_root,
            voice.voice_profile_id,
            require_transcript=self.manifest.transcript_required,
        )
        target = self.manifest.target_conditioning_path(audio.parent, language)
        return audio, text, target

    async def _post_json(self, path: str, payload: dict, *, timeout_seconds: int = 300) -> dict:
        timeout = aiohttp.ClientTimeout(total=timeout_seconds, sock_read=timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(f"{self._endpoint_url}{path}", json=payload) as response:
                body = await response.json(content_type=None)
                if response.status != 200:
                    raise RuntimeError(body.get("error") or f"TTS host returned HTTP {response.status}")
                return body

    async def load(self) -> None:
        try:
            body = await self._post_json("/load", {"model_id": self.manifest.model_id})
            if not body.get("success"):
                raise RuntimeError(body.get("error") or f"Could not load {self.manifest.display_name}")
            self._runtime_capabilities = dict(body.get("capabilities") or {})
            self._loaded = True
        except (aiohttp.ClientError, TimeoutError, OSError) as exc:
            raise RuntimeError(
                f"Generic TTS host is not reachable at {self._endpoint_url}. Start VoxPassport through run.bat."
            ) from exc

    async def unload(self) -> None:
        self._loaded = False
        try:
            await self._post_json("/unload", {"model_id": self.manifest.model_id}, timeout_seconds=30)
        except Exception:
            logger.debug("TTS host unload failed for %s", self.manifest.model_id, exc_info=True)

    def _synthesis_payload(self, text: str, language: str, voice: VoiceSpec, response_format: str) -> dict:
        clean = str(text).strip()
        if not clean:
            raise ValueError("Target TTS text must not be empty")
        if language not in self.manifest.languages and "*" not in self.manifest.languages:
            raise ValueError(f"{self.manifest.display_name} does not advertise language {language!r}")
        payload: dict[str, object] = {
            "model": self.manifest.model_id,
            "input": clean,
            "language": language,
            "response_format": response_format,
        }
        if voice.is_cloned:
            if not self.manifest.supports_voice_cloning:
                raise ValueError(f"{self.manifest.display_name} does not support voice cloning")
            audio, transcript, target = self._profile_reference(voice, language)
            payload["ref_audio_path"] = str(audio.resolve())
            if transcript:
                payload["ref_text"] = transcript
            if target is not None:
                payload["target_conditioning_path"] = str(target.resolve())
        return payload

    async def synthesize_stream(
        self,
        text: str,
        language: LanguageCode,
        voice: VoiceSpec,
    ) -> AsyncIterator[TtsAudioChunk]:
        if not self._loaded:
            raise RuntimeError(f"{self.manifest.display_name} adapter is not loaded")
        lang = self._language_value(language)
        payload = self._synthesis_payload(text, lang, voice, "pcm")
        utterance_id, segment_id = str(uuid.uuid4()), str(uuid.uuid4())
        sequence = 0
        sample_rate = self.manifest.native_sample_rate_hz
        timeout = aiohttp.ClientTimeout(total=300, sock_read=240)
        try:
            # The worker is a separate Python process, but the physical GPU is
            # shared with ASR. Keep the existing heavyweight-inference contract.
            with heavy_gpu_inference():
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(
                        f"{self._endpoint_url}/v1/audio/speech", json=payload
                    ) as response:
                        if response.status != 200:
                            detail = (await response.read()).decode("utf-8", errors="replace")[:1500]
                            raise RuntimeError(
                                f"{self.manifest.display_name} worker returned HTTP {response.status}: {detail}"
                            )
                        protocol = response.headers.get("X-VoxPassport-TTS-Protocol", "")
                        if protocol and protocol != "voxpassport.tts.v1":
                            raise RuntimeError(f"Unsupported TTS worker protocol: {protocol}")
                        sample_rate = int(response.headers.get("X-Sample-Rate", sample_rate))
                        channels = int(response.headers.get("X-Channels", "1"))
                        bit_depth = int(response.headers.get("X-Bit-Depth", "16"))
                        if channels != 1 or bit_depth != 16:
                            raise RuntimeError(
                                f"Unsupported TTS PCM layout: {sample_rate} Hz, {channels}ch, {bit_depth}-bit"
                            )
                        carry = b""
                        emitted = False
                        async for network_chunk in response.content.iter_chunked(32768):
                            if not network_chunk:
                                continue
                            data = carry + network_chunk
                            even = len(data) - (len(data) % 2)
                            if not even:
                                carry = data
                                continue
                            pcm, carry = data[:even], data[even:]
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
                            logger.warning("Dropping one trailing byte from %s PCM stream", self.manifest.model_id)
                        if not emitted:
                            raise RuntimeError(f"{self.manifest.display_name} returned no PCM audio")
        except (aiohttp.ClientError, TimeoutError, OSError) as exc:
            raise RuntimeError(
                f"Generic TTS host became unavailable while using {self.manifest.display_name}"
            ) from exc

        yield TtsAudioChunk(
            utterance_id=utterance_id,
            segment_id=segment_id,
            sequence=sequence,
            sample_rate_hz=sample_rate,
            sample_format=SampleFormat.PCM_S16LE,
            data=b"",
            is_final_chunk=True,
        )

    async def generate_cloned_audio(
        self,
        text: str,
        ref_audio_path: str,
        ref_text: str = "",
        num_step: int = 32,
        language: str = "English",
    ) -> bytes:
        del num_step
        if not self._loaded:
            raise RuntimeError(f"{self.manifest.display_name} adapter is not loaded")
        lang = self._language_value(language)
        reference = Path(ref_audio_path)
        if not reference.exists():
            raise FileNotFoundError(f"Reference audio does not exist: {reference}")
        if lang not in self.manifest.languages and "*" not in self.manifest.languages:
            raise ValueError(f"{self.manifest.display_name} does not advertise language {lang!r}")
        payload: dict[str, object] = {
            "model": self.manifest.model_id,
            "input": str(text).strip(),
            "language": lang,
            "response_format": "wav",
            "ref_audio_path": str(reference.resolve()),
        }
        clean_ref = str(ref_text or "").strip()
        if clean_ref:
            payload["ref_text"] = clean_ref
        target = self.manifest.target_conditioning_path(reference.parent, lang)
        if target is not None:
            payload["target_conditioning_path"] = str(target.resolve())

        try:
            with heavy_gpu_inference():
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as session:
                    async with session.post(
                        f"{self._endpoint_url}/v1/audio/speech", json=payload
                    ) as response:
                        body = await response.read()
                        if response.status != 200:
                            detail = body.decode("utf-8", errors="replace")[:1500]
                            raise RuntimeError(
                                f"{self.manifest.display_name} worker returned HTTP {response.status}: {detail}"
                            )
                        if len(body) <= 500:
                            raise RuntimeError(f"{self.manifest.display_name} returned an unexpectedly small WAV")
                        return body
        except (aiohttp.ClientError, TimeoutError, OSError) as exc:
            raise RuntimeError("Generic TTS host is not reachable") from exc

    async def supports_voice_cloning(self) -> bool:
        if self._runtime_capabilities:
            return bool(self._runtime_capabilities.get("voice_cloning", self.manifest.supports_voice_cloning))
        return self.manifest.supports_voice_cloning

    async def supports_language(self, language: LanguageCode) -> bool:
        code = self._language_value(language)
        languages = tuple(self._runtime_capabilities.get("languages") or self.manifest.languages)
        return code in languages or "*" in languages

    @property
    def native_sample_rate_hz(self) -> int:
        return int(self._runtime_capabilities.get("sample_rate_hz", self.manifest.native_sample_rate_hz))

    async def health_check(self) -> bool:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as session:
                async with session.get(f"{self._endpoint_url}/health") as response:
                    if response.status != 200:
                        return False
                    body = await response.json(content_type=None)
                    return (
                        body.get("status") == "ok"
                        and body.get("loaded_model_id") == self.manifest.model_id
                    )
        except Exception:
            return False
