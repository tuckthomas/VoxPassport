"""Integrated VoxPassport runtime entrypoint.

This composes the legacy inference/control daemon with the new provider-neutral
strategy manager and native desktop audio media plane without duplicating the
large legacy HTTP route table. New deployments should launch this module.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from runtime.inference.live_translation_controller import LiveTranslationController
from runtime.inference.native_audio_bridge import NativeAudioBridge
from runtime.inference.native_audio_routing import NativeAudioRoutingStore
from runtime.inference.remote_runtime import RemoteAsrAdapter, RemoteTranslationAdapter
from runtime.inference.server.client_http import (
    RuntimeClientServices,
    configure_runtime_client_services,
)
from runtime.inference.server.main import LiveTranslatorApp, PROJECT_ROOT
from runtime.inference.translation_provider_catalog import TranslationStrategyKind
from runtime.inference.translation_strategy_manager import TranslationStrategyManager


logger = logging.getLogger("VoxPassportIntegratedDaemon")


class IntegratedLiveTranslatorApp(LiveTranslatorApp):
    """Compose strategy/native-media services around the existing daemon."""

    def __init__(self, data_dir: Path) -> None:
        super().__init__(data_dir)
        self.native_audio_bridge = NativeAudioBridge(project_root=PROJECT_ROOT)
        self.native_audio_routing = NativeAudioRoutingStore(
            self.data_dir / "native_audio_routing.json",
            self.native_audio_bridge,
        )
        self.translation_strategy_manager = TranslationStrategyManager(
            state_path=self.data_dir / "translation_strategy.json",
            stop_cascade=self._stop_cascade_runtime,
            start_cascade=self._start_cascade_runtime,
            cascade_is_active=lambda: bool(self.orchestrator._is_active),
        )
        self.live_translation_controller = LiveTranslationController(
            strategy_manager=self.translation_strategy_manager,
            audio_bridge=self.native_audio_bridge,
            routing_store=self.native_audio_routing,
        )
        configure_runtime_client_services(RuntimeClientServices(
            translation_strategy_manager=self.translation_strategy_manager,
            live_translation_controller=self.live_translation_controller,
            audio_routing_store=self.native_audio_routing,
            language_pair_provider=lambda: (
                self.orchestrator.user_language,
                self.orchestrator.remote_language,
            ),
            cascade_should_start_provider=lambda: self._runtime_residency == "ready",
        ))

    async def _start_cascade_runtime(self) -> None:
        if not self.orchestrator._is_active:
            await self.orchestrator.start()
        if not self.scheduler._is_monitoring:
            await self.scheduler.start()
        self._touch_runtime_activity()

    async def _stop_cascade_runtime(self) -> None:
        if self.scheduler._is_monitoring:
            await self.scheduler.stop()
        if self.orchestrator._is_active:
            await self.orchestrator.stop()

    async def _ensure_runtime_ready(self) -> None:
        """Load the modular pipeline only when it is the selected strategy."""

        self._touch_runtime_activity()
        if self.translation_strategy_manager.state.kind != TranslationStrategyKind.MODULAR_PIPELINE:
            raise RuntimeError(
                "modular pipeline is not active; switch Translation Engine to Local Modular first"
            )
        async with self._runtime_activity_lock:
            if not self.orchestrator._is_active:
                await self._start_cascade_runtime()
            self._touch_runtime_activity()
        if self._runtime_residency == "on_demand":
            self._schedule_runtime_idle_release()

    async def _release_runtime_when_idle(self) -> None:
        try:
            await asyncio.sleep(30.0)
            if (
                self._runtime_residency == "on_demand"
                and self.translation_strategy_manager.state.kind == TranslationStrategyKind.MODULAR_PIPELINE
                and self.orchestrator._is_active
                and not self.live_translation_controller.active
                and asyncio.get_running_loop().time() - self._runtime_last_activity >= 30.0
            ):
                await self._stop_cascade_runtime()
                logger.info("On Demand mode released idle modular inference models")
        except asyncio.CancelledError:
            return

    async def _set_runtime_residency(self, value: str) -> None:
        value = str(value).strip().lower()
        if value not in {"ready", "on_demand"}:
            raise ValueError("model_residency must be 'ready' or 'on_demand'")
        self._runtime_residency = value
        self._save_runtime_residency()

        if self.translation_strategy_manager.state.kind != TranslationStrategyKind.MODULAR_PIPELINE:
            # Direct provider residency is owned by its adapter/session rather
            # than the local model-residency policy.
            await self._stop_cascade_runtime()
            return

        if value == "ready":
            await self._start_cascade_runtime()
        else:
            if self._runtime_idle_task and not self._runtime_idle_task.done():
                self._runtime_idle_task.cancel()
            await self._stop_cascade_runtime()
            logger.info("On Demand mode released modular inference models")

    async def start(self) -> None:
        logger.info("Initializing integrated VoxPassport daemon")

        # Preserve the legacy daemon's persisted model restoration before any
        # strategy chooses whether the modular pipeline should be resident.
        saved_tts = self.model_manager.get_active_slots().get("TTS") or self._selected_tts_model
        persisted_tts = self._normalize_clone_model(saved_tts)
        persisted_tts_engine = self._tts_engine_for_model(persisted_tts)[0]
        self.orchestrator.tts_adapter_ro = persisted_tts_engine
        self.orchestrator.tts_adapter_en = persisted_tts_engine
        self._selected_tts_model = persisted_tts

        active_slots = self.model_manager.get_active_slots()
        persisted_asr = active_slots.get("ASR")
        remote_asr = self._remote_endpoint_for_model(persisted_asr, "ASR") if persisted_asr else None
        if remote_asr:
            self.asr_en, self.asr_ro = RemoteAsrAdapter(remote_asr), RemoteAsrAdapter(remote_asr)
            self.orchestrator.asr_adapter_en, self.orchestrator.asr_adapter_ro = self.asr_en, self.asr_ro
        persisted_translation = active_slots.get("TRANSLATION")
        remote_translation = (
            self._remote_endpoint_for_model(persisted_translation, "TRANSLATION")
            if persisted_translation else None
        )
        if remote_translation:
            self.mt = RemoteTranslationAdapter(remote_translation)
            self.orchestrator.mt_adapter = self.mt

        logger.info("Restored persisted TTS engine before strategy startup: %s", persisted_tts)
        await self.caption_server.start()

        await self.translation_strategy_manager.restore(
            source_language=self.orchestrator.user_language,
            target_language=self.orchestrator.remote_language,
            start_cascade_if_selected=self._runtime_residency == "ready",
        )

        await self._setup_http_server()
        await self._mark_default_runtime_models()
        await self.discovery_agent.start()
        logger.info(
            "Integrated VoxPassport daemon online: strategy=%s",
            self.translation_strategy_manager.state.strategy_id,
        )

    async def stop(self) -> None:
        try:
            await self.live_translation_controller.stop()
        finally:
            try:
                await self.translation_strategy_manager.unload()
            finally:
                configure_runtime_client_services(None)
        await super().stop()


async def main() -> None:
    parser = argparse.ArgumentParser(description="VoxPassport Integrated Runtime Daemon")
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args()
    app = IntegratedLiveTranslatorApp(Path(args.data_dir))
    await app.start()
    try:
        while True:
            await asyncio.sleep(1)
    except (asyncio.CancelledError, KeyboardInterrupt):
        await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
