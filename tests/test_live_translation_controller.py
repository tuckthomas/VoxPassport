import asyncio
from types import SimpleNamespace

import pytest

from runtime.inference.live_translation_controller import (
    LiveTranslationController,
    LiveTranslationControllerError,
    LiveTranslationStartConfig,
)
from runtime.inference.protocol import LanguageCode
from runtime.inference.translation_provider_catalog import TranslationStrategyKind


class FakeCapture:
    def __init__(self):
        self.closed = asyncio.Event()

    async def frames(self):
        await self.closed.wait()
        if False:
            yield None

    async def close(self):
        self.closed.set()


class FakeBridge:
    def __init__(self):
        self.microphone_configs = []
        self.loopback_configs = []

    async def open_microphone_capture(self, config):
        self.microphone_configs.append(config)
        return FakeCapture()

    async def open_loopback_capture(self, config):
        self.loopback_configs.append(config)
        return FakeCapture()


class FakeSession:
    def __init__(self):
        self.closed = asyncio.Event()

    async def push_audio(self, _frame):
        return None

    async def events(self):
        await self.closed.wait()
        if False:
            yield None

    async def close(self):
        self.closed.set()


class FakeManager:
    def __init__(self):
        self.state = SimpleNamespace(
            kind=TranslationStrategyKind.DIRECT_SPEECH_TRANSLATION,
            strategy_id="fake-direct",
        )
        self.configs = []

    async def open_direct_session(self, config):
        self.configs.append(config)
        return FakeSession()


class FakeRoutingStore:
    def __init__(self, payload):
        self._payload = payload

    async def payload(self):
        return dict(self._payload)


def routing_payload(*, virtual_ready=True):
    return {
        "microphone_endpoint_id": "mic-1",
        "loopback_endpoint_id": "render-loop",
        "monitor_render_endpoint_id": "headphones",
        "virtual_microphone_render_endpoint_id": "virtual-cable-in",
        "virtual_microphone_capture_endpoint_id": "virtual-cable-out",
        "virtual_microphone_ready": virtual_ready,
        "selection_status": {
            "microphone": True,
            "loopback": True,
            "monitor": True,
            "virtual_microphone_render": True,
            "virtual_microphone_capture": True,
        },
    }


@pytest.mark.asyncio
async def test_full_duplex_opens_opposite_language_sessions_and_native_inputs():
    manager = FakeManager()
    bridge = FakeBridge()
    subject = LiveTranslationController(
        strategy_manager=manager,
        audio_bridge=bridge,
        routing_store=FakeRoutingStore(routing_payload()),
    )

    status = await subject.start(LiveTranslationStartConfig(
        source_language=LanguageCode.EN,
        target_language=LanguageCode.RO,
        mode="full_duplex",
    ))

    assert status["active"] is True
    assert status["mode"] == "full_duplex"
    assert len(manager.configs) == 2
    outbound, inbound = manager.configs
    assert (outbound.source_language, outbound.target_language) == (LanguageCode.EN, LanguageCode.RO)
    assert (inbound.source_language, inbound.target_language) == (LanguageCode.RO, LanguageCode.EN)
    assert bridge.microphone_configs[0].endpoint_id == "mic-1"
    assert bridge.loopback_configs[0].endpoint_id == "render-loop"

    stopped = await subject.stop()
    assert stopped["active"] is False
    assert stopped["state"] == "stopped"


@pytest.mark.asyncio
async def test_outbound_requires_human_validated_virtual_microphone_pair():
    subject = LiveTranslationController(
        strategy_manager=FakeManager(),
        audio_bridge=FakeBridge(),
        routing_store=FakeRoutingStore(routing_payload(virtual_ready=False)),
    )

    with pytest.raises(LiveTranslationControllerError, match="validate the virtual microphone"):
        await subject.start(LiveTranslationStartConfig(
            source_language=LanguageCode.EN,
            target_language=LanguageCode.RO,
            mode="outbound",
        ))


@pytest.mark.asyncio
async def test_inbound_does_not_require_virtual_microphone_pair():
    manager = FakeManager()
    bridge = FakeBridge()
    subject = LiveTranslationController(
        strategy_manager=manager,
        audio_bridge=bridge,
        routing_store=FakeRoutingStore(routing_payload(virtual_ready=False)),
    )

    status = await subject.start(LiveTranslationStartConfig(
        source_language=LanguageCode.EN,
        target_language=LanguageCode.RO,
        mode="inbound",
    ))
    assert status["active"] is True
    assert len(manager.configs) == 1
    assert not bridge.microphone_configs
    assert len(bridge.loopback_configs) == 1
    await subject.stop()


@pytest.mark.asyncio
async def test_live_session_requires_direct_strategy():
    manager = FakeManager()
    manager.state = SimpleNamespace(
        kind=TranslationStrategyKind.MODULAR_PIPELINE,
        strategy_id="modular-pipeline",
    )
    subject = LiveTranslationController(
        strategy_manager=manager,
        audio_bridge=FakeBridge(),
        routing_store=FakeRoutingStore(routing_payload()),
    )

    with pytest.raises(LiveTranslationControllerError, match="requires an active direct"):
        await subject.start(LiveTranslationStartConfig(
            source_language=LanguageCode.EN,
            target_language=LanguageCode.RO,
        ))
