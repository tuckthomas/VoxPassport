"""Gemini Live Translate direct speech strategy.

Provider wire-format details are contained here. The rest of VoxPassport only
sees the provider-neutral ``SpeechTranslationStrategyAdapter`` and session event
contract.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import aiohttp

from runtime.inference.protocol import AudioFrame, LanguageCode, SampleFormat
from runtime.inference.translation_provider_catalog import (
    TranslationProviderCatalog,
    TranslationStrategyKind,
)
from runtime.inference.translation_session import (
    BufferedSpeechTranslationSession,
    SpeechTranslationEvent,
    SpeechTranslationEventType,
    SpeechTranslationOutputMode,
    SpeechTranslationSession,
    SpeechTranslationSessionConfig,
    SpeechTranslationSessionState,
    SpeechTranslationStrategyAdapter,
    TranslatedAudioChunk,
)


DEFAULT_MODEL_ID = "gemini-3.5-live-translate-preview"
DEFAULT_WEBSOCKET_URL = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
)
DEFAULT_API_KEY_ENV = "GEMINI_API_KEY"
OUTPUT_SAMPLE_RATE_HZ = 24000


class GeminiLiveTranslateError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GeminiMappedEvent:
    event_type: SpeechTranslationEventType
    text: str | None = None
    audio: TranslatedAudioChunk | None = None
    state: SpeechTranslationSessionState | None = None
    error_code: str | None = None
    recoverable: bool | None = None
    metadata: dict[str, Any] | None = None


def build_gemini_setup_message(
    config: SpeechTranslationSessionConfig,
    *,
    model_id: str = DEFAULT_MODEL_ID,
    echo_target_language: bool = True,
) -> dict[str, Any]:
    generation_config: dict[str, Any] = {
        "responseModalities": ["AUDIO"],
        "translationConfig": {
            "targetLanguageCode": config.target_language.value,
            "echoTargetLanguage": bool(echo_target_language),
        },
    }
    if config.request_source_transcript:
        generation_config["inputAudioTranscription"] = {}
    if config.output_mode in {
        SpeechTranslationOutputMode.TRANSLATED_TEXT,
        SpeechTranslationOutputMode.TEXT_AND_AUDIO,
    }:
        generation_config["outputAudioTranscription"] = {}

    return {
        "setup": {
            "model": f"models/{model_id}",
            "generationConfig": generation_config,
        }
    }


def build_gemini_audio_message(frame: AudioFrame) -> dict[str, Any]:
    if frame.sample_format != SampleFormat.PCM_S16LE:
        raise GeminiLiveTranslateError(
            "Gemini Live Translate audio transport currently requires PCM_S16LE input"
        )
    if frame.channels != 1:
        raise GeminiLiveTranslateError(
            "Gemini Live Translate audio transport currently requires mono input"
        )
    encoded = base64.b64encode(frame.data).decode("ascii")
    return {
        "realtimeInput": {
            "audio": {
                "data": encoded,
                "mimeType": f"audio/pcm;rate={frame.sample_rate_hz}",
            }
        }
    }


def build_gemini_audio_stream_end_message() -> dict[str, Any]:
    return {"realtimeInput": {"audioStreamEnd": True}}


def map_gemini_server_message(
    payload: dict[str, Any],
    *,
    emit_source_text: bool,
    emit_translation_text: bool,
    emit_audio: bool,
    audio_sequence: int,
) -> list[GeminiMappedEvent]:
    """Map one provider message without maintaining turn accumulators.

    Partial transcript chunks are emitted immediately. Final transcript events
    are produced by ``GeminiLiveTranslateSession`` on turn completion after it
    accumulates the provider chunks for that turn.
    """

    events: list[GeminiMappedEvent] = []
    if "setupComplete" in payload:
        events.append(GeminiMappedEvent(
            event_type=SpeechTranslationEventType.STATE,
            state=SpeechTranslationSessionState.READY,
        ))

    server = payload.get("serverContent")
    if isinstance(server, dict):
        input_transcription = server.get("inputTranscription")
        if emit_source_text and isinstance(input_transcription, dict):
            text = str(input_transcription.get("text") or "")
            if text:
                events.append(GeminiMappedEvent(
                    event_type=SpeechTranslationEventType.SOURCE_PARTIAL,
                    text=text,
                ))

        output_transcription = server.get("outputTranscription")
        if emit_translation_text and isinstance(output_transcription, dict):
            text = str(output_transcription.get("text") or "")
            if text:
                events.append(GeminiMappedEvent(
                    event_type=SpeechTranslationEventType.TRANSLATION_PARTIAL,
                    text=text,
                ))

        model_turn = server.get("modelTurn")
        if emit_audio and isinstance(model_turn, dict):
            for part in model_turn.get("parts") or []:
                if not isinstance(part, dict):
                    continue
                inline = part.get("inlineData")
                if not isinstance(inline, dict):
                    continue
                encoded = inline.get("data")
                if not isinstance(encoded, str) or not encoded:
                    continue
                try:
                    audio = base64.b64decode(encoded, validate=True)
                except Exception as exc:
                    raise GeminiLiveTranslateError("Gemini returned invalid base64 audio") from exc
                events.append(GeminiMappedEvent(
                    event_type=SpeechTranslationEventType.TRANSLATED_AUDIO,
                    audio=TranslatedAudioChunk(
                        sequence=audio_sequence,
                        sample_rate_hz=OUTPUT_SAMPLE_RATE_HZ,
                        channels=1,
                        sample_format=SampleFormat.PCM_S16LE,
                        data=audio,
                        is_final_chunk=bool(server.get("turnComplete", False)),
                    ),
                ))
                audio_sequence += 1

        if server.get("interrupted"):
            events.append(GeminiMappedEvent(
                event_type=SpeechTranslationEventType.STATE,
                state=SpeechTranslationSessionState.LISTENING,
                metadata={"interrupted": True, "flush_playback": True},
            ))

    if "goAway" in payload:
        go_away = payload.get("goAway")
        metadata = dict(go_away) if isinstance(go_away, dict) else {}
        events.append(GeminiMappedEvent(
            event_type=SpeechTranslationEventType.ERROR,
            error_code="provider_go_away",
            recoverable=True,
            metadata=metadata,
        ))

    return events


class GeminiLiveTranslateStrategy(SpeechTranslationStrategyAdapter):
    def __init__(
        self,
        *,
        model_id: str = DEFAULT_MODEL_ID,
        api_key_env: str = DEFAULT_API_KEY_ENV,
        websocket_url: str = DEFAULT_WEBSOCKET_URL,
        echo_target_language: bool = True,
        setup_timeout_seconds: float = 20.0,
    ) -> None:
        self.model_id = model_id
        self.api_key_env = api_key_env
        self.websocket_url = websocket_url
        self.echo_target_language = bool(echo_target_language)
        self.setup_timeout_seconds = float(setup_timeout_seconds)
        self._loaded = False
        self._descriptor = TranslationProviderCatalog().load().resolve(
            "gemini-3.5-live-translate"
        )

    @property
    def strategy_id(self) -> str:
        return self._descriptor.strategy_id

    @property
    def kind(self) -> TranslationStrategyKind:
        return TranslationStrategyKind.DIRECT_SPEECH_TRANSLATION

    async def load(self) -> None:
        if not self.websocket_url.startswith("wss://"):
            raise GeminiLiveTranslateError("Gemini Live Translate endpoint must use wss://")
        self._loaded = True

    async def unload(self) -> None:
        self._loaded = False

    async def health_check(self) -> bool:
        return self._loaded and bool(os.getenv(self.api_key_env, "").strip())

    async def supports_language_pair(
        self,
        source_language: LanguageCode,
        target_language: LanguageCode,
    ) -> bool:
        if source_language == target_language:
            return False
        confirmed = set(self._descriptor.confirmed_languages)
        if not confirmed:
            return True
        return source_language.value in confirmed and target_language.value in confirmed

    async def open_session(
        self,
        config: SpeechTranslationSessionConfig,
    ) -> SpeechTranslationSession:
        if not self._loaded:
            await self.load()
        if not await self.supports_language_pair(config.source_language, config.target_language):
            raise GeminiLiveTranslateError(
                f"Gemini Live Translate language pair not confirmed by this manifest: "
                f"{config.source_language.value}->{config.target_language.value}"
            )
        if config.input_sample_format != SampleFormat.PCM_S16LE or config.input_channels != 1:
            raise GeminiLiveTranslateError("Gemini adapter requires mono PCM_S16LE input")

        api_key = os.getenv(self.api_key_env, "").strip()
        if not api_key:
            raise GeminiLiveTranslateError(
                f"Gemini API key is not configured in {self.api_key_env}"
            )

        client = aiohttp.ClientSession()
        query = urlencode({"key": api_key})
        websocket = None
        try:
            websocket = await client.ws_connect(
                f"{self.websocket_url}?{query}",
                heartbeat=30,
                max_msg_size=16 * 1024 * 1024,
            )
            await websocket.send_json(build_gemini_setup_message(
                config,
                model_id=self.model_id,
                echo_target_language=self.echo_target_language,
            ))
            await _wait_for_setup_complete(
                websocket,
                timeout_seconds=self.setup_timeout_seconds,
            )
            session = GeminiLiveTranslateSession(
                config,
                websocket=websocket,
                http_session=client,
            )
            await session.start()
            return session
        except Exception as exc:
            if websocket is not None:
                await websocket.close()
            await client.close()
            if isinstance(exc, GeminiLiveTranslateError):
                raise
            # aiohttp connection exceptions may include the request URL, whose
            # query string contains the API key. Do not expose that exception.
            raise GeminiLiveTranslateError(
                f"Gemini Live Translate connection/setup failed ({type(exc).__name__})"
            ) from None


async def _wait_for_setup_complete(
    websocket: aiohttp.ClientWebSocketResponse,
    *,
    timeout_seconds: float,
) -> None:
    async def wait() -> None:
        async for message in websocket:
            if message.type == aiohttp.WSMsgType.TEXT:
                payload = json.loads(message.data)
                if "setupComplete" in payload:
                    return
                if "goAway" in payload:
                    raise GeminiLiveTranslateError("Gemini closed the session during setup")
            elif message.type in {
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.ERROR,
            }:
                raise GeminiLiveTranslateError("Gemini WebSocket closed before setup completed")
        raise GeminiLiveTranslateError("Gemini WebSocket ended before setup completed")

    try:
        await asyncio.wait_for(wait(), timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        raise GeminiLiveTranslateError("Timed out waiting for Gemini setupComplete") from exc


class GeminiLiveTranslateSession(BufferedSpeechTranslationSession):
    def __init__(
        self,
        config: SpeechTranslationSessionConfig,
        *,
        websocket: aiohttp.ClientWebSocketResponse,
        http_session: aiohttp.ClientSession,
    ) -> None:
        super().__init__(config)
        self._websocket = websocket
        self._http_session = http_session
        self._send_task: asyncio.Task | None = None
        self._receive_task: asyncio.Task | None = None
        self._provider_closing = False
        self._event_sequence = 0
        self._audio_sequence = 0
        self._source_turn_parts: list[str] = []
        self._translation_turn_parts: list[str] = []

    async def start(self) -> None:
        await self._emit_state(SpeechTranslationSessionState.READY)
        self._send_task = asyncio.create_task(
            self._send_loop(), name=f"gemini-live-send-{self.session_id}"
        )
        self._receive_task = asyncio.create_task(
            self._receive_loop(), name=f"gemini-live-receive-{self.session_id}"
        )

    def _next_event_sequence(self) -> int:
        value = self._event_sequence
        self._event_sequence += 1
        return value

    async def _emit_state(
        self,
        state: SpeechTranslationSessionState,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await self.emit(SpeechTranslationEvent(
            event_type=SpeechTranslationEventType.STATE,
            sequence=self._next_event_sequence(),
            state=state,
            metadata=dict(metadata or {}),
        ))

    async def _send_loop(self) -> None:
        try:
            while True:
                frame = await self.next_audio()
                if frame is None:
                    break
                await self._websocket.send_json(build_gemini_audio_message(frame))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._emit_provider_error("provider_send_failed", exc, recoverable=True)

    async def _receive_loop(self) -> None:
        try:
            async for message in self._websocket:
                if message.type == aiohttp.WSMsgType.TEXT:
                    payload = json.loads(message.data)
                    await self._handle_provider_payload(payload)
                elif message.type in {
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                }:
                    break
            if not self._provider_closing:
                await self._emit_provider_error(
                    "provider_closed",
                    GeminiLiveTranslateError("Gemini Live Translate WebSocket closed"),
                    recoverable=True,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not self._provider_closing:
                await self._emit_provider_error("provider_receive_failed", exc, recoverable=True)

    async def _handle_provider_payload(self, payload: dict[str, Any]) -> None:
        server = payload.get("serverContent")
        if isinstance(server, dict):
            input_transcription = server.get("inputTranscription")
            if self.config.request_source_transcript and isinstance(input_transcription, dict):
                text = str(input_transcription.get("text") or "")
                if text:
                    self._source_turn_parts.append(text)

            output_transcription = server.get("outputTranscription")
            if self.config.output_mode in {
                SpeechTranslationOutputMode.TRANSLATED_TEXT,
                SpeechTranslationOutputMode.TEXT_AND_AUDIO,
            } and isinstance(output_transcription, dict):
                text = str(output_transcription.get("text") or "")
                if text:
                    self._translation_turn_parts.append(text)

        mapped = map_gemini_server_message(
            payload,
            emit_source_text=self.config.request_source_transcript,
            emit_translation_text=self.config.output_mode in {
                SpeechTranslationOutputMode.TRANSLATED_TEXT,
                SpeechTranslationOutputMode.TEXT_AND_AUDIO,
            },
            emit_audio=self.config.output_mode in {
                SpeechTranslationOutputMode.TRANSLATED_AUDIO,
                SpeechTranslationOutputMode.TEXT_AND_AUDIO,
            },
            audio_sequence=self._audio_sequence,
        )
        for item in mapped:
            if item.audio is not None:
                self._audio_sequence = max(self._audio_sequence, item.audio.sequence + 1)
            await self.emit(SpeechTranslationEvent(
                event_type=item.event_type,
                sequence=self._next_event_sequence(),
                text=item.text,
                audio=item.audio,
                state=item.state,
                error_code=item.error_code,
                recoverable=item.recoverable,
                metadata=dict(item.metadata or {}),
            ))

        if isinstance(server, dict) and server.get("turnComplete"):
            await self._emit_final_turn_text()
            await self._emit_state(SpeechTranslationSessionState.LISTENING)

    async def _emit_final_turn_text(self) -> None:
        if self.config.request_source_transcript and self._source_turn_parts:
            await self.emit(SpeechTranslationEvent(
                event_type=SpeechTranslationEventType.SOURCE_FINAL,
                sequence=self._next_event_sequence(),
                text="".join(self._source_turn_parts),
            ))
        if self.config.output_mode in {
            SpeechTranslationOutputMode.TRANSLATED_TEXT,
            SpeechTranslationOutputMode.TEXT_AND_AUDIO,
        } and self._translation_turn_parts:
            await self.emit(SpeechTranslationEvent(
                event_type=SpeechTranslationEventType.TRANSLATION_FINAL,
                sequence=self._next_event_sequence(),
                text="".join(self._translation_turn_parts),
            ))
        self._source_turn_parts.clear()
        self._translation_turn_parts.clear()

    async def _emit_provider_error(
        self,
        code: str,
        exc: Exception,
        *,
        recoverable: bool,
    ) -> None:
        try:
            await self.emit(SpeechTranslationEvent(
                event_type=SpeechTranslationEventType.ERROR,
                sequence=self._next_event_sequence(),
                error_code=code,
                recoverable=recoverable,
                metadata={"message": str(exc)},
            ))
        except Exception:
            pass

    async def _close_provider(self) -> None:
        self._provider_closing = True
        try:
            if not self._websocket.closed:
                await self._websocket.send_json(build_gemini_audio_stream_end_message())
        except Exception:
            pass
        for task in (self._send_task, self._receive_task):
            if task is not None and not task.done():
                task.cancel()
        for task in (self._send_task, self._receive_task):
            if task is not None:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass
        self._send_task = None
        self._receive_task = None
        try:
            await self._websocket.close()
        finally:
            await self._http_session.close()
