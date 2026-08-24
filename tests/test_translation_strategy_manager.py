from pathlib import Path

import pytest

from runtime.inference.protocol import LanguageCode
from runtime.inference.translation_provider_catalog import TranslationStrategyKind
from runtime.inference.translation_session import (
    SpeechTranslationSessionConfig,
    SpeechTranslationStrategyAdapter,
)
from runtime.inference.translation_strategy_manager import (
    CASCADE_STRATEGY_ID,
    TranslationStrategyManager,
    TranslationStrategyTransitionError,
)


class FakeDirectAdapter(SpeechTranslationStrategyAdapter):
    def __init__(self, strategy_id="fake-direct", *, healthy=True, supported=True):
        self._strategy_id = strategy_id
        self.healthy = healthy
        self.supported = supported
        self.loaded = False
        self.unloaded = False

    @property
    def strategy_id(self):
        return self._strategy_id

    @property
    def kind(self):
        return TranslationStrategyKind.DIRECT_SPEECH_TRANSLATION

    async def load(self):
        self.loaded = True

    async def unload(self):
        self.unloaded = True
        self.loaded = False

    async def health_check(self):
        return self.loaded and self.healthy

    async def supports_language_pair(self, source_language, target_language):
        return self.supported and source_language != target_language

    async def open_session(self, config):
        raise NotImplementedError


class FakeCatalog:
    def resolve(self, strategy_id):
        class Descriptor:
            kind = TranslationStrategyKind.DIRECT_SPEECH_TRANSLATION
            confirmed_languages = ("en", "ro")
            auth_env = None
        if strategy_id != "fake-direct":
            raise ValueError("unknown direct strategy")
        return Descriptor()


class CascadeHarness:
    def __init__(self, active=True):
        self.active = active
        self.starts = 0
        self.stops = 0

    async def start(self):
        self.starts += 1
        self.active = True

    async def stop(self):
        self.stops += 1
        self.active = False


def manager(tmp_path: Path, cascade: CascadeHarness, adapter: FakeDirectAdapter):
    return TranslationStrategyManager(
        state_path=tmp_path / "strategy.json",
        stop_cascade=cascade.stop,
        start_cascade=cascade.start,
        cascade_is_active=lambda: cascade.active,
        catalog=FakeCatalog(),
        adapter_loader=lambda strategy_id, **_: adapter,
    )


@pytest.mark.asyncio
async def test_direct_activation_validates_before_stopping_cascade_and_persists(tmp_path):
    cascade = CascadeHarness(active=True)
    adapter = FakeDirectAdapter()
    subject = manager(tmp_path, cascade, adapter)

    state = await subject.activate(
        strategy_id="fake-direct",
        source_language=LanguageCode.EN,
        target_language=LanguageCode.RO,
    )

    assert adapter.loaded
    assert cascade.stops == 1
    assert cascade.active is False
    assert state.strategy_id == "fake-direct"
    assert subject.status_payload()["direct_loaded"] is True
    assert '"strategy_id": "fake-direct"' in (tmp_path / "strategy.json").read_text()


@pytest.mark.asyncio
async def test_unhealthy_candidate_never_disrupts_working_cascade(tmp_path):
    cascade = CascadeHarness(active=True)
    adapter = FakeDirectAdapter(healthy=False)
    subject = manager(tmp_path, cascade, adapter)

    with pytest.raises(TranslationStrategyTransitionError, match="not healthy"):
        await subject.activate(
            strategy_id="fake-direct",
            source_language=LanguageCode.EN,
            target_language=LanguageCode.RO,
        )

    assert cascade.active is True
    assert cascade.stops == 0
    assert subject.state.strategy_id == CASCADE_STRATEGY_ID
    assert adapter.unloaded is True


@pytest.mark.asyncio
async def test_return_to_cascade_starts_pipeline_and_unloads_direct(tmp_path):
    cascade = CascadeHarness(active=True)
    adapter = FakeDirectAdapter()
    subject = manager(tmp_path, cascade, adapter)
    await subject.activate(
        strategy_id="fake-direct",
        source_language=LanguageCode.EN,
        target_language=LanguageCode.RO,
    )

    state = await subject.activate(
        strategy_id=CASCADE_STRATEGY_ID,
        source_language=LanguageCode.EN,
        target_language=LanguageCode.RO,
    )

    assert state.kind == TranslationStrategyKind.MODULAR_PIPELINE
    assert cascade.active is True
    assert cascade.starts == 1
    assert adapter.unloaded is True
    assert subject.direct_adapter is None


@pytest.mark.asyncio
async def test_language_validation_rejects_before_mutation(tmp_path):
    cascade = CascadeHarness(active=True)
    adapter = FakeDirectAdapter()
    subject = manager(tmp_path, cascade, adapter)

    validation = await subject.validate(
        strategy_id="fake-direct",
        source_language=LanguageCode.EN,
        target_language=LanguageCode.ES,
    )
    assert validation.valid is False
    assert cascade.stops == 0


@pytest.mark.asyncio
async def test_restore_falls_back_to_cascade_when_direct_is_no_longer_healthy(tmp_path):
    cascade = CascadeHarness(active=True)
    good = FakeDirectAdapter()
    first = manager(tmp_path, cascade, good)
    await first.activate(
        strategy_id="fake-direct",
        source_language=LanguageCode.EN,
        target_language=LanguageCode.RO,
    )

    cascade.active = False
    bad = FakeDirectAdapter(healthy=False)
    restored = manager(tmp_path, cascade, bad)
    state = await restored.restore(
        source_language=LanguageCode.EN,
        target_language=LanguageCode.RO,
        start_cascade_if_selected=True,
    )
    assert state.strategy_id == CASCADE_STRATEGY_ID
    assert cascade.active is True
