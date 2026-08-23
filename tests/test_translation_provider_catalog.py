import json
from pathlib import Path

import pytest

from runtime.inference.protocol import ModelCapability
from runtime.inference.translation_provider_catalog import (
    ExecutionMode,
    TranslationProviderCatalog,
    TranslationProviderCatalogError,
    TranslationStrategyKind,
)


def test_default_catalog_contains_gemini_live_translate():
    catalog = TranslationProviderCatalog().load()
    entry = catalog.resolve("gemini-3.5-live-translate")

    assert entry.provider == "google"
    assert entry.model_id == "gemini-3.5-live-translate-preview"
    assert entry.capability == ModelCapability.DIRECT_SPEECH_TRANSLATION
    assert entry.kind == TranslationStrategyKind.DIRECT_SPEECH_TRANSLATION
    assert entry.execution_mode == ExecutionMode.BYO_API
    assert entry.streaming is True
    assert entry.bidirectional is True
    assert entry.voice_preservation is True
    assert {"en", "ro"}.issubset(entry.confirmed_languages)


def test_catalog_rejects_non_direct_capability(tmp_path: Path):
    (tmp_path / "bad.json").write_text(
        json.dumps({
            "schema_version": 1,
            "strategy_id": "bad",
            "display_name": "Bad",
            "provider": "test",
            "model_id": "test/model",
            "kind": "direct_speech_translation",
            "capability": "TTS",
            "execution_mode": "local",
            "transport": "in_process"
        }),
        encoding="utf-8",
    )

    with pytest.raises(TranslationProviderCatalogError, match="DIRECT_SPEECH_TRANSLATION"):
        TranslationProviderCatalog(tmp_path).load()


def test_catalog_rejects_unknown_top_level_fields(tmp_path: Path):
    (tmp_path / "bad.json").write_text(
        json.dumps({
            "schema_version": 1,
            "strategy_id": "bad",
            "display_name": "Bad",
            "provider": "test",
            "model_id": "test/model",
            "kind": "direct_speech_translation",
            "capability": "DIRECT_SPEECH_TRANSLATION",
            "execution_mode": "local",
            "transport": "in_process",
            "mystery": true
        }).replace('true', 'true'),
        encoding="utf-8",
    )

    with pytest.raises(TranslationProviderCatalogError, match="unknown top-level fields"):
        TranslationProviderCatalog(tmp_path).load()
