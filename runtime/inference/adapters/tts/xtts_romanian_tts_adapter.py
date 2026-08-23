"""XTTS-v2 Romanian adapter backed by the isolated local Python worker."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from pathlib import Path
from typing import AsyncIterator, Optional

import aiohttp

from runtime.inference.adapters.base import TtsAdapter
from runtime.inference.adapters.tts.profile_reference import resolve_profile_reference
from runtime.inference.gpu_inference_coordinator import heavy_gpu_inference
from runtime.inference.protocol import LanguageCode, SampleFormat, TtsAudioChunk, VoiceSpec
from runtime.workers.xtts_romanian.common import normalize_language, target_conditioning_reference

logger = logging.getLogger(__name__)


class XttsRomanianTtsAdapter(TtsAdapter):
    """Low-VRAM English/Romanian zero-shot voice cloning through XTTS."""

    ADAPTER_NAME = "XttsRomanianTtsAdapter"
    MODEL_ID = "xtts-v2-romanian-v2"
    _NATIVE_SAMPLE_RATE_HZ = 24000

    def __init__(
        self,
        endpoint_url: Optional[str] = None,
        profiles_root: Optional[Path] = None,
    ) -> None:
        self._endpoint_url = (
            endpoint_url or os.getenv("VOXPASSPORT_XTTS_URL", "http://127.0.0.1:8098")
        ).rstrip("/")
        project_root = Path(__file__).resolve().parents[4]
        self._profiles_root = Path(profiles_root or project_root / "data" / "voice_profiles")
        self._loaded = False

    @staticmethod
    def _language_value(language: LanguageCode | str) -> str:
        raw = getattr(language, "value", language)
        return normalize_language(str(raw))

    def _profile_references(self, voice: VoiceSpec, language: str) -> tuple[Path, Path | None]:
        _, canonical_audio, _ = resolve_profile_reference(
            self._profiles_root, voice.voice_profile_id, require_transcript=False
        )
        derived = target_conditioning_reference(canonical_audio.parent, language)
        return canonical_audio, derived

    async def _worker_post(self, path: str, **kwargs):
        timeout = kwargs.pop("timeout", aiohttp.ClientTimeout(total=300, sock_read=240))
        session: aiohttp.ClientSession | None = None
        try:
            session = aiohttp.ClientSession(timeout=timeout)
            response = await session.post(f"{self._endpoint_url}{path}", **kwargs)
            return session, response
        except Exception:
            if session is not None:
                await session.close()
            raise

    async def _wait_for_worker(self, attempts: int = 20, delay_seconds: float = 0.25) -> None:
        last_error: BaseException | None = None
        for _ in range(max(1, attempts)):
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=2)) as session:
                    async with session.get(f"{self._endpoint_url}/health") as response:
                        if response.status == 200:
                            return
            except (aiohttp.ClientError, TimeoutError, OSError) as exc:
                last_error = exc
            await asyncio.sleep(delay_seconds)
        raise RuntimeError(
            "XTTS Romanian worker is not reachable. Run install_xtts_worker.bat once, then start VoxPassport again."
        ) from last_error

    async def load(self) -> None:
        await self._wait_for_worker()
        # First activation may include a ~2.35 GB checkpoint download, so model
        # load has a deliberately long timeout while normal synthesis stays tight.
        session, response = await self._worker_post(
            "/load",
            json={},
            timeout=aiohttp.ClientTimeout(total=1800, sock_read=1800),
        )
        try:
            body = await response.json(content_type=None)
            if response.status != 200 or not body.get("success"):
                raise RuntimeError(body.get("error") or f"XTTS worker load returned HTTP {response.status}")
        finally:
            response.release()
            await session.close()
        self._loaded = True

    async def unload(self) -> None:
        self._loaded = False
        try:
            session, response = await self._worker_post(
                "/unload", json={}, timeout=aiohttp.ClientTimeout(total=30)
            )
            try:
                await response.read()
            finally:
                response.release()
                await session.close()
        except Exception:
            logger.debug("XTTS worker unload request failed", exc_info=True)

    async def synthesize_stream(
        self,
        text: str,
        language: LanguageCode,
        voice: VoiceSpec,
    ) -> AsyncIterator[TtsAudioChunk]:
        if not self._loaded:
            raise RuntimeError("XttsRomanianTtsAdapter is not loaded")
        clean = str(text).strip()
        if not clean:
            raise ValueError("Target TTS text must not be empty")
        lang = self._language_value(language)
        payload: dict[str, object] = {
            "model": self.MODEL_ID,
            "input": clean,
            "language": lang,
            "response_format": "pcm",
        }
        if voice.is_cloned:
            canonical, target_reference = self._profile_references(voice, lang)
            payload["ref_audio_path"] = str(canonical.resolve())
            if target_reference is not None:
                payload["target_conditioning_path"] = str(target_reference.resolve())

        utterance_id, segment_id = str(uuid.uuid4()), str(uuid.uuid4())
        sequence = 0
        sample_rate = self._NATIVE_SAMPLE_RATE_HZ
        timeout = aiohttp.ClientTimeout(total=300, sock_read=240)
        try:
            # Holding the existing coordinator while the worker executes keeps
            # Parakeet and XTTS from launching heavyweight kernels concurrently
            # on the same 8 GB GPU, even though XTTS lives in another process.
            with heavy_gpu_inference():
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(f"{self._endpoint_url}/v1/audio/speech", json=payload) as response:
                        if response.status != 200:
                            detail = (await response.read()).decode("utf-8", errors="replace")[:1500]
                            raise RuntimeError(f"XTTS Romanian worker returned HTTP {response.status}: {detail}")
                        sample_rate = int(response.headers.get("X-Sample-Rate", self._NATIVE_SAMPLE_RATE_HZ))
                        channels = int(response.headers.get("X-Channels", "1"))
                        bit_depth = int(response.headers.get("X-Bit-Depth", "16"))
                        if channels != 1 or bit_depth != 16:
                            raise RuntimeError(
                                f"Unsupported XTTS PCM layout: {sample_rate} Hz, {channels}ch, {bit_depth}-bit"
                            )
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
                            logger.warning("Dropping one trailing byte from XTTS PCM stream")
                        if not emitted:
                            raise RuntimeError("XTTS Romanian worker returned no PCM audio")
        except (aiohttp.ClientError, TimeoutError, OSError) as exc:
            raise RuntimeError("XTTS Romanian worker became unavailable during synthesis") from exc

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
        language: str = "Romanian",
    ) -> bytes:
        del ref_text, num_step  # XTTS conditions directly on audio.
        if not self._loaded:
            raise RuntimeError("XttsRomanianTtsAdapter is not loaded")
        lang = self._language_value(language)
        canonical = Path(ref_audio_path)
        if not canonical.exists():
            raise FileNotFoundError(f"Reference audio does not exist: {canonical}")
        target_reference = target_conditioning_reference(canonical.parent, lang)
        payload: dict[str, object] = {
            "model": self.MODEL_ID,
            "input": str(text).strip(),
            "language": lang,
            "response_format": "wav",
            "ref_audio_path": str(canonical.resolve()),
        }
        if target_reference is not None:
            payload["target_conditioning_path"] = str(target_reference.resolve())

        try:
            with heavy_gpu_inference():
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as session:
                    async with session.post(f"{self._endpoint_url}/v1/audio/speech", json=payload) as response:
                        body = await response.read()
                        if response.status != 200:
                            detail = body.decode("utf-8", errors="replace")[:1500]
                            raise RuntimeError(f"XTTS Romanian worker returned HTTP {response.status}: {detail}")
                        if len(body) <= 500:
                            raise RuntimeError("XTTS Romanian worker returned an unexpectedly small WAV")
                        return body
        except (aiohttp.ClientError, TimeoutError, OSError) as exc:
            raise RuntimeError("XTTS Romanian worker is not reachable") from exc

    async def supports_voice_cloning(self) -> bool:
        return True

    async def supports_language(self, language: LanguageCode) -> bool:
        return language in {LanguageCode.EN, LanguageCode.RO}

    @property
    def native_sample_rate_hz(self) -> int:
        return self._NATIVE_SAMPLE_RATE_HZ

    async def health_check(self) -> bool:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as session:
                async with session.get(f"{self._endpoint_url}/health") as response:
                    if response.status != 200:
                        return False
                    body = await response.json(content_type=None)
                    return body.get("status") == "ok" and bool(body.get("loaded"))
        except Exception:
            return False
