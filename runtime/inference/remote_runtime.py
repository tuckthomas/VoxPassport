"""Config and adapters for a user-operated remote VoxPassport worker.

The worker is deliberately vendor-neutral: it may run on Colab, AWS, a VPS, or
another machine.  Secrets stay outside the desktop registry; an endpoint names
the environment variable that contains its bearer token.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import AsyncIterator, Optional
from urllib.parse import urlparse

import aiohttp

from runtime.inference.adapters.base import AsrAdapter, TranslationAdapter, TtsAdapter
from runtime.inference.asr_types import AsrConfig, AsrStream
from runtime.inference.protocol import AudioFrame, LanguageCode, SampleFormat, TranscriptEvent, TranscriptState, TranslationContext, TranslationResult, TtsAudioChunk, VoiceSpec


@dataclass
class RemoteEndpoint:
    endpoint_id: str
    name: str
    base_url: str
    capabilities: list[str]
    auth_token_env: str = ""
    selected_model_id: str = ""
    created_at: float = field(default_factory=__import__("time").time)

    def headers(self) -> dict[str, str]:
        token = os.getenv(self.auth_token_env, "") if self.auth_token_env else ""
        return {"Authorization": f"Bearer {token}"} if token else {}


class RemoteEndpointStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._endpoints: dict[str, RemoteEndpoint] = {}
        self.load()

    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._endpoints = {x["endpoint_id"]: RemoteEndpoint(**x) for x in data.get("endpoints", [])}
        except FileNotFoundError:
            pass

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"schema_version": 1, "endpoints": [asdict(x) for x in self._endpoints.values()]}, indent=2), encoding="utf-8")

    def list(self) -> list[RemoteEndpoint]:
        return list(self._endpoints.values())

    def get(self, endpoint_id: str) -> Optional[RemoteEndpoint]:
        return self._endpoints.get(endpoint_id)

    def upsert(self, name: str, base_url: str, capabilities: list[str], auth_token_env: str = "", endpoint_id: str = "", selected_model_id: str = "") -> RemoteEndpoint:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            raise ValueError("base_url must be a complete http(s) URL")
        if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Remote endpoints must use HTTPS (HTTP is only permitted for localhost)")
        caps = sorted({str(x).upper() for x in capabilities} & {"ASR", "TRANSLATION", "TTS"})
        if not name.strip() or not caps:
            raise ValueError("A name and at least one of ASR, Translation, or TTS are required")
        if auth_token_env and not auth_token_env.replace("_", "").isalnum():
            raise ValueError("auth_token_env may contain only letters, numbers, and underscores")
        item = RemoteEndpoint(endpoint_id=endpoint_id or uuid.uuid4().hex[:12], name=name.strip(), base_url=base_url.rstrip("/"), capabilities=caps, auth_token_env=auth_token_env.strip(), selected_model_id=selected_model_id.strip())
        self._endpoints[item.endpoint_id] = item
        self.save()
        return item

    def delete(self, endpoint_id: str) -> bool:
        if endpoint_id not in self._endpoints:
            return False
        del self._endpoints[endpoint_id]
        self.save()
        return True


def remote_model_id(endpoint_id: str, capability: str) -> str:
    return f"remote::{endpoint_id}::{capability.upper()}"


class _RemoteBase:
    def __init__(self, endpoint: RemoteEndpoint) -> None:
        self.endpoint = endpoint
        self._loaded = False

    async def load(self) -> None:
        self._loaded = True

    async def unload(self) -> None:
        self._loaded = False

    async def health_check(self) -> bool:
        try:
            timeout = aiohttp.ClientTimeout(total=4)
            async with aiohttp.ClientSession(timeout=timeout, headers=self.endpoint.headers()) as session:
                async with session.get(f"{self.endpoint.base_url}/health") as response:
                    return response.status < 400
        except aiohttp.ClientError:
            return False


class RemoteTranslationAdapter(_RemoteBase, TranslationAdapter):
    async def translate(self, text: str, source_language: LanguageCode, target_language: LanguageCode, context: Optional[TranslationContext] = None) -> TranslationResult:
        payload = {"model": self.endpoint.selected_model_id or None, "text": text, "source_language": source_language.value, "target_language": target_language.value, "context": asdict(context) if context else None}
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout, headers=self.endpoint.headers()) as session:
            async with session.post(f"{self.endpoint.base_url}/v1/translation", json=payload) as response:
                body = await response.json(content_type=None)
                if response.status >= 400:
                    raise RuntimeError(f"Remote translation returned HTTP {response.status}: {body}")
        return TranslationResult(translated_text=str(body.get("translated_text", "")), source_language=source_language, target_language=target_language, latency_ms=float(body.get("latency_ms", 0)), metadata={"remote_endpoint": self.endpoint.name})


class RemoteTtsAdapter(_RemoteBase, TtsAdapter):
    _NATIVE_SAMPLE_RATE_HZ = 24000
    async def synthesize_stream(self, text: str, language: LanguageCode, voice: VoiceSpec) -> AsyncIterator[TtsAudioChunk]:
        payload = {"model": self.endpoint.selected_model_id or None, "input": text, "language": language.value, "voice_profile_id": voice.voice_profile_id, "is_cloned": voice.is_cloned, "stream": True, "response_format": "pcm"}
        timeout = aiohttp.ClientTimeout(total=120, sock_read=60)
        utterance_id, segment_id, sequence = str(uuid.uuid4()), str(uuid.uuid4()), 0
        async with aiohttp.ClientSession(timeout=timeout, headers=self.endpoint.headers()) as session:
            async with session.post(f"{self.endpoint.base_url}/v1/audio/speech", json=payload) as response:
                if response.status >= 400:
                    raise RuntimeError(f"Remote TTS returned HTTP {response.status}: {(await response.text())[:500]}")
                rate = int(response.headers.get("x-sample-rate", self._NATIVE_SAMPLE_RATE_HZ))
                async for chunk in response.content.iter_chunked(16384):
                    if chunk:
                        yield TtsAudioChunk(utterance_id, segment_id, sequence, rate, SampleFormat.PCM_S16LE, chunk)
                        sequence += 1
        yield TtsAudioChunk(utterance_id, segment_id, sequence, rate, SampleFormat.PCM_S16LE, b"", True)
    async def supports_voice_cloning(self) -> bool: return True
    async def supports_language(self, language: LanguageCode) -> bool: return True
    @property
    def native_sample_rate_hz(self) -> int: return self._NATIVE_SAMPLE_RATE_HZ


class _RemoteAsrState:
    def __init__(self, stream_id: str, config: AsrConfig) -> None:
        self.stream_id, self.config, self.queue, self.closed = stream_id, config, asyncio.Queue(), False
        self.pcm = bytearray()


class RemoteAsrAdapter(_RemoteBase, AsrAdapter):
    """Batched utterance ASR over HTTPS; VAD remains local and supplies endpoints."""
    async def start_stream(self, config: AsrConfig) -> AsrStream:
        state = _RemoteAsrState(str(uuid.uuid4()), config)
        return AsrStream(stream_id=state.stream_id, language=config.language, sample_rate_hz=config.sample_rate_hz, _adapter_state=state)
    async def push_audio(self, stream: AsrStream, frame: AudioFrame) -> None:
        state: _RemoteAsrState = stream._adapter_state
        if not state.closed: state.pcm.extend(frame.data)
    async def endpoint(self, stream: AsrStream) -> str:
        state: _RemoteAsrState = stream._adapter_state
        utterance_id = str(uuid.uuid4())
        language = LanguageCode(str(state.config.language))
        payload = {"model": self.endpoint.selected_model_id or None, "audio_base64": base64.b64encode(bytes(state.pcm)).decode(), "sample_rate_hz": state.config.sample_rate_hz, "channels": state.config.channels, "sample_format": "pcm_s16le", "language": language.value}
        state.pcm.clear()
        timeout = aiohttp.ClientTimeout(total=45)
        async with aiohttp.ClientSession(timeout=timeout, headers=self.endpoint.headers()) as session:
            async with session.post(f"{self.endpoint.base_url}/v1/asr/transcribe", json=payload) as response:
                body = await response.json(content_type=None)
                if response.status >= 400: raise RuntimeError(f"Remote ASR returned HTTP {response.status}: {body}")
        await state.queue.put(TranscriptEvent(utterance_id=utterance_id, revision=1, source_language=language, text=str(body.get("text", "")), state=TranscriptState.FINAL, metadata={"remote_endpoint": self.endpoint.name}))
        return utterance_id
    async def events(self, stream: AsrStream) -> AsyncIterator[TranscriptEvent]:
        state: _RemoteAsrState = stream._adapter_state
        while not state.closed:
            try: yield await asyncio.wait_for(state.queue.get(), .1)
            except asyncio.TimeoutError: continue
    async def close_stream(self, stream: AsrStream) -> None:
        state: _RemoteAsrState = stream._adapter_state
        if state.pcm: await self.endpoint(stream)
        state.closed = True
