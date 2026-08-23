"""Generic TTS adapter for supervisor-managed `voxpassport.tts.v1` workers."""

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
from runtime.inference.tts_plugins.runtime_supervisor import (
    TtsRuntimeSupervisor,
    get_tts_runtime_supervisor,
)

logger = logging.getLogger(__name__)


_LANGUAGE_ALIASES = {
    "english": "en",
    "romanian": "ro",
    "română": "ro",
    "romana": "ro",
}


class ManifestTtsAdapter(TtsAdapter):
    """One main-process adapter for every supervised local TTS plugin."""

    ADAPTER_NAME = "ManifestTtsAdapter"

    def __init__(
        self,
        manifest: TtsManifest | str,
        *,
        profiles_root: Optional[Path] = None,
        catalog: Optional[TtsManifestCatalog] = None,
        supervisor: Optional[TtsRuntimeSupervisor] = None,
    ) -> None:
        if isinstance(manifest, TtsManifest):
            self.manifest = manifest
        else:
            self.manifest = (catalog or TtsManifestCatalog().load()).resolve(str(manifest))
        project_root = Path(__file__).resolve().parents[4]
        self._profiles_root = Path(profiles_root or project_root / "data" / "voice_profiles")
        self._catalog = catalog or TtsManifestCatalog().load()
        self._supervisor = supervisor or get_tts_runtime_supervisor(manifest_catalog=self._catalog)
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

    async def load(self) -> None:
        endpoint, capabilities = await self._supervisor.activate(self.manifest)
        if not endpoint:
            raise RuntimeError(f"Could not acquire a TTS runtime endpoint for {self.manifest.display_name}")
        self._runtime_capabilities = dict(capabilities or {})
        self._loaded = True

    async def unload(self) -> None:
        self._loaded = False
        try:
            await self._supervisor.release(self.manifest)
        except Exception:
            logger.debug("Supervised TTS unload failed for %s", self.manifest.model_id, exc_info=True)

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
        emitted_any = False

        for attempt in range(2):
            endpoint = await self._supervisor.ensure_active(self.manifest)
            timeout = aiohttp.ClientTimeout(total=300, sock_read=240)
            try:
                with heavy_gpu_inference():
                    async with aiohttp.ClientSession(timeout=timeout) as session:
                        async with session.post(f"{endpoint}/v1/audio/speech", json=payload) as response:
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
                            emitted_this_attempt = False
                            async for network_chunk in response.content.iter_chunked(32768):
                                if not network_chunk:
                                    continue
                                data = carry + network_chunk
                                even = len(data) - (len(data) % 2)
                                if not even:
                                    carry = data
                                    continue
                                pcm, carry = data[:even], data[even:]
                                emitted_this_attempt = True
                                emitted_any = True
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
                            if not emitted_this_attempt:
                                raise RuntimeError(f"{self.manifest.display_name} returned no PCM audio")
                            break
            except (aiohttp.ClientError, TimeoutError, OSError) as exc:
                if attempt == 0 and not emitted_any:
                    logger.warning("TTS worker failed before audio for %s; restarting runtime profile", self.manifest.model_id)
                    await self._supervisor.recover(self.manifest)
                    continue
                raise RuntimeError(
                    f"Supervised TTS worker became unavailable while using {self.manifest.display_name}"
                ) from exc
        else:
            raise RuntimeError(f"{self.manifest.display_name} failed before producing audio")

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

        for attempt in range(2):
            endpoint = await self._supervisor.ensure_active(self.manifest)
            try:
                with heavy_gpu_inference():
                    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as session:
                        async with session.post(f"{endpoint}/v1/audio/speech", json=payload) as response:
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
                if attempt == 0:
                    await self._supervisor.recover(self.manifest)
                    continue
                raise RuntimeError("Supervised TTS worker is not reachable") from exc
        raise RuntimeError(f"{self.manifest.display_name} failed to synthesize cloned audio")

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
        if not self._loaded:
            return False
        try:
            await self._supervisor.ensure_active(self.manifest)
            return True
        except Exception:
            return False
