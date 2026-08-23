import json
from pathlib import Path

import pytest

from runtime.inference.adapters.direct.gemini_live_translate import GeminiLiveTranslateStrategy
from runtime.inference.translation_provider_catalog import (
    TranslationProviderCatalog,
    TranslationProviderCatalogError,
    serialize_provider_catalog,
)
from runtime.inference.translation_strategy_loader import (
    TranslationStrategyLoadError,
    load_translation_strategy_adapter,
)


def test_default_manifest_loads_gemini_adapter_without_provider_branch():
    catalog = TranslationProviderCatalog().load()
    descriptor = catalog.resolve("gemini-3.5-live-translate")
    adapter = load_translation_strategy_adapter(descriptor.strategy_id, catalog=catalog)

    assert isinstance(adapter, GeminiLiveTranslateStrategy)
    assert adapter.strategy_id == descriptor.strategy_id
    assert descriptor.adapter_entrypoint.endswith(":GeminiLiveTranslateStrategy")


def test_internal_adapter_entrypoint_is_not_exposed_to_client_catalog():
    catalog = TranslationProviderCatalog().load()
    public = serialize_provider_catalog(catalog.entries())

    assert public
    assert all("adapter" not in item for item in public)
    assert all("adapter_entrypoint" not in item for item in public)


def test_catalog_requires_valid_adapter_entrypoint(tmp_path: Path):
    manifest = {
        "schema_version": 1,
        "strategy_id": "broken",
        "display_name": "Broken",
        "provider": "test",
        "model_id": "test-model",
        "kind": "direct_speech_translation",
        "capability": "DIRECT_SPEECH_TRANSLATION",
        "execution_mode": "local",
        "transport": "in_process",
        "adapter": "not-a-valid-entrypoint",
    }
    (tmp_path / "broken.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(TranslationProviderCatalogError, match="python.module:ClassName"):
        TranslationProviderCatalog(tmp_path).load()


def test_loader_reports_missing_symbol_without_provider_specific_logic(tmp_path: Path):
    manifest = {
        "schema_version": 1,
        "strategy_id": "broken",
        "display_name": "Broken",
        "provider": "test",
        "model_id": "test-model",
        "kind": "direct_speech_translation",
        "capability": "DIRECT_SPEECH_TRANSLATION",
        "execution_mode": "local",
        "transport": "in_process",
        "adapter": "runtime.inference.translation_session:NoSuchAdapter",
    }
    (tmp_path / "broken.json").write_text(json.dumps(manifest), encoding="utf-8")
    catalog = TranslationProviderCatalog(tmp_path).load()

    with pytest.raises(TranslationStrategyLoadError, match="not found"):
        load_translation_strategy_adapter("broken", catalog=catalog)
