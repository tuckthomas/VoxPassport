"""Native-audio media plane for active direct speech translation strategies.

Raw PCM stays between the Windows helper and provider sessions. The HTTP/Expo
surface only sees low-frequency state and captions.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from runtime.inference.native_audio_bridge import (
    NativeAudioBridge,
    NativeAudioCapture,
    NativeAudioCaptureConfig,
)
from runtime.inference.native_audio_output import NativeAudioRender, NativeAudioRenderConfig
from runtime.inference.native_audio_routing import NativeAudioRoutingStore
from runtime.inference.protocol import LanguageCode
from runtime.inference.translation_session import (
    SpeechTranslationEvent,
    SpeechTranslationEventType,
    SpeechTranslationOutputMode,
    SpeechTranslationSession,
    SpeechTranslationSessionConfig,
    SpeechTranslationSessionState,
)
from runtime.inference.translation_strategy_manager import TranslationStrategyManager


class LiveTranslationControllerError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class LiveTranslationStartConfig:
    source_language: LanguageCode
    target_language: LanguageCode
    mode: str = "full_duplex"  # full_duplex | outbound | inbound

    def validate(self) -> None:
        if self.source_language == self.target_language:
            raise ValueError("source and target languages must differ")
        if self.mode not in {"full_duplex", "outbound", "inbound"}:
            raise ValueError("mode must be full_duplex, outbound, or inbound")


class _DirectLeg:
    def __init__(
        self,
        *,
        name: str,
        session: SpeechTranslationSession,
        capture: NativeAudioCapture,
        bridge: NativeAudioBridge,
        render_endpoint_id: str,
        state_callback: Callable[[str, SpeechTranslationEvent], None],
    ) -> None:
        self.name = name
        self.session = session
        self.capture = capture
        self.bridge = bridge
        self.render_endpoint_id = render_endpoint_id
        self.state_callback = state_callback
        self.render: NativeAudioRender | None = None
        self.capture_task: asyncio.Task | None = None
        self.event_task: asyncio.Task | None = None
        self.frames_forwarded = 0
        self.audio_chunks_rendered = 0
        self._stopping = False

    async def start(self) -> None:
        self.capture_task = asyncio.create_task(self._capture_loop(), name=f"live-{self.name}-capture")
        self.event_task = asyncio.create_task(self._event_loop(), name=f"live-{self.name}-events")

    async def _capture_loop(self) -> None:
        try:
            async for frame in self.capture.frames():
                if self._stopping:
                    break
                await self.session.push_audio(frame)
                self.frames_forwarded += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.state_callback(self.name, SpeechTranslationEvent(
                event_type=SpeechTranslationEventType.ERROR,
                sequence=10_000_000 + self.frames_forwarded,
                error_code="native_capture_failed",
                recoverable=False,
                metadata={"detail": str(exc)},
            ))

    async def _event_loop(self) -> None:
        try:
            async for event in self.session.events():
                if self._stopping:
                    break
                self.state_callback(self.name, event)
                if event.event_type == SpeechTranslationEventType.STATE:
                    if event.metadata.get("flush_playback"):
                        await self._reset_render()
                    continue
                if event.event_type != SpeechTranslationEventType.TRANSLATED_AUDIO or event.audio is None:
                    continue
                chunk = event.audio
                if self.render is None:
                    self.render = await NativeAudioRender.open(
                        self.bridge,
                        NativeAudioRenderConfig(
                            endpoint_id=self.render_endpoint_id,
                            sample_rate_hz=chunk.sample_rate_hz,
                            channels=chunk.channels,
                            queue_capacity=16,
                        ),
                    )
                await self.render.write_translated_audio(chunk)
                self.audio_chunks_rendered += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.state_callback(self.name, SpeechTranslationEvent(
                event_type=SpeechTranslationEventType.ERROR,
                sequence=20_000_000 + self.audio_chunks_rendered,
                error_code="native_render_or_provider_event_failed",
                recoverable=False,
                metadata={"detail": str(exc)},
            ))

    async def _reset_render(self) -> None:
        current, self.render = self.render, None
        if current is not None:
            await current.close()

    async def stop(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        # Stop capture first so no more frames enter the provider while it is
        # being flushed/closed.
        await self.capture.close()
        try:
            await self.session.close()
        except Exception:
            pass
        for task in (self.capture_task, self.event_task):
            if task and not task.done():
                task.cancel()
        for task in (self.capture_task, self.event_task):
            if task:
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        await self._reset_render()


class LiveTranslationController:
    """Own one outbound, inbound, or full-duplex direct-speech session."""

    def __init__(
        self,
        *,
        strategy_manager: TranslationStrategyManager,
        audio_bridge: NativeAudioBridge,
        routing_store: NativeAudioRoutingStore,
    ) -> None:
        self.strategy_manager = strategy_manager
        self.audio_bridge = audio_bridge
        self.routing_store = routing_store
        self._lock = asyncio.Lock()
        self._legs: dict[str, _DirectLeg] = {}
        self._session_id: str | None = None
        self._config: LiveTranslationStartConfig | None = None
        self._state = "stopped"
        self._error: str | None = None
        self._source_caption = ""
        self._translated_caption = ""
        self._leg_captions: dict[str, dict[str, str]] = {}

    @property
    def active(self) -> bool:
        return bool(self._legs)

    def status_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "active": self.active,
            "session_id": self._session_id,
            "strategy_id": self.strategy_manager.state.strategy_id if self.active else None,
            "source_language": self._config.source_language.value if self._config else None,
            "target_language": self._config.target_language.value if self._config else None,
            "mode": self._config.mode if self._config else None,
            "frames_forwarded": sum(leg.frames_forwarded for leg in self._legs.values()),
            "translated_audio_chunks": sum(leg.audio_chunks_rendered for leg in self._legs.values()),
            "source_caption": self._source_caption,
            "translated_caption": self._translated_caption,
            "leg_captions": dict(self._leg_captions),
            "state": self._state,
            "error": self._error,
        }

    async def start(self, config: LiveTranslationStartConfig) -> dict[str, Any]:
        config.validate()
        async with self._lock:
            if self.active:
                raise LiveTranslationControllerError("a live translation session is already active")
            if self.strategy_manager.state.kind.value != "direct_speech_translation":
                raise LiveTranslationControllerError(
                    "live native direct session requires an active direct speech translation strategy"
                )

            routing = await self.routing_store.payload()
            self._validate_routing(config.mode, routing)
            self._session_id = f"live-{uuid.uuid4().hex}"
            self._config = config
            self._state = "opening"
            self._error = None
            self._source_caption = ""
            self._translated_caption = ""
            self._leg_captions = {}

            created: list[_DirectLeg] = []
            try:
                if config.mode in {"full_duplex", "outbound"}:
                    created.append(await self._create_outbound_leg(config, routing))
                if config.mode in {"full_duplex", "inbound"}:
                    created.append(await self._create_inbound_leg(config, routing))
                self._legs = {leg.name: leg for leg in created}
                for leg in created:
                    await leg.start()
                self._state = "listening"
                return self.status_payload()
            except Exception as exc:
                for leg in created:
                    await leg.stop()
                self._legs = {}
                self._state = "failed"
                self._error = str(exc)
                raise LiveTranslationControllerError(str(exc)) from exc

    async def _create_outbound_leg(self, config: LiveTranslationStartConfig, routing: dict[str, Any]) -> _DirectLeg:
        capture = await self.audio_bridge.open_microphone_capture(NativeAudioCaptureConfig(
            endpoint_id=routing["microphone_endpoint_id"],
            sample_rate_hz=16000,
            channels=1,
            chunk_duration_ms=20,
            queue_capacity=8,
        ))
        session = await self.strategy_manager.open_direct_session(SpeechTranslationSessionConfig(
            source_language=config.source_language,
            target_language=config.target_language,
            input_sample_rate_hz=16000,
            input_channels=1,
            output_mode=SpeechTranslationOutputMode.TEXT_AND_AUDIO,
            request_source_transcript=True,
            metadata={"direction": "outbound", "live_session_id": self._session_id},
        ))
        return _DirectLeg(
            name="outbound",
            session=session,
            capture=capture,
            bridge=self.audio_bridge,
            render_endpoint_id=routing["virtual_microphone_render_endpoint_id"],
            state_callback=self._on_event,
        )

    async def _create_inbound_leg(self, config: LiveTranslationStartConfig, routing: dict[str, Any]) -> _DirectLeg:
        capture = await self.audio_bridge.open_loopback_capture(NativeAudioCaptureConfig(
            endpoint_id=routing["loopback_endpoint_id"],
            sample_rate_hz=16000,
            channels=1,
            chunk_duration_ms=20,
            queue_capacity=8,
        ))
        session = await self.strategy_manager.open_direct_session(SpeechTranslationSessionConfig(
            source_language=config.target_language,
            target_language=config.source_language,
            input_sample_rate_hz=16000,
            input_channels=1,
            output_mode=SpeechTranslationOutputMode.TEXT_AND_AUDIO,
            request_source_transcript=True,
            metadata={"direction": "inbound", "live_session_id": self._session_id},
        ))
        return _DirectLeg(
            name="inbound",
            session=session,
            capture=capture,
            bridge=self.audio_bridge,
            render_endpoint_id=routing["monitor_render_endpoint_id"],
            state_callback=self._on_event,
        )

    @staticmethod
    def _validate_routing(mode: str, routing: dict[str, Any]) -> None:
        selection = routing.get("selection_status") or {}
        if mode in {"full_duplex", "outbound"}:
            if not selection.get("microphone"):
                raise LiveTranslationControllerError("select a physical microphone endpoint")
            if not routing.get("virtual_microphone_ready"):
                raise LiveTranslationControllerError(
                    "configure and validate the virtual microphone render/capture endpoint pair"
                )
        if mode in {"full_duplex", "inbound"}:
            if not selection.get("loopback"):
                raise LiveTranslationControllerError("select a system-loopback endpoint")
            if not selection.get("monitor"):
                raise LiveTranslationControllerError("select a local monitor render endpoint")

    def _on_event(self, leg_name: str, event: SpeechTranslationEvent) -> None:
        captions = self._leg_captions.setdefault(leg_name, {"source": "", "translation": ""})
        if event.event_type in {SpeechTranslationEventType.SOURCE_PARTIAL, SpeechTranslationEventType.SOURCE_FINAL}:
            captions["source"] = event.text or ""
        elif event.event_type in {SpeechTranslationEventType.TRANSLATION_PARTIAL, SpeechTranslationEventType.TRANSLATION_FINAL}:
            captions["translation"] = event.text or ""
        elif event.event_type == SpeechTranslationEventType.STATE and event.state is not None:
            self._state = event.state.value
        elif event.event_type == SpeechTranslationEventType.ERROR:
            self._error = event.error_code or "provider_error"
            if not event.recoverable:
                self._state = "failed"

        # Keep top-level captions useful for the common outbound-only UI while
        # retaining per-leg captions for full-duplex diagnostics.
        outbound = self._leg_captions.get("outbound") or captions
        self._source_caption = outbound.get("source", "")
        self._translated_caption = outbound.get("translation", "")

    async def stop(self) -> dict[str, Any]:
        async with self._lock:
            if not self.active:
                self._state = "stopped"
                return self.status_payload()
            self._state = "closing"
            legs, self._legs = list(self._legs.values()), {}
            for leg in legs:
                await leg.stop()
            self._state = "stopped"
            return self.status_payload()
