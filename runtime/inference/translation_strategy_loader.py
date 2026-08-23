"""Generic loader for manifest-owned direct speech strategy adapters."""

from __future__ import annotations

import importlib
import inspect
from typing import Type

from runtime.inference.translation_provider_catalog import (
    TranslationProviderCatalog,
    TranslationProviderDescriptor,
)
from runtime.inference.translation_session import SpeechTranslationStrategyAdapter


class TranslationStrategyLoadError(RuntimeError):
    pass


def load_translation_strategy_adapter(
    strategy_id: str,
    *,
    catalog: TranslationProviderCatalog | None = None,
) -> SpeechTranslationStrategyAdapter:
    """Instantiate one direct-speech adapter without provider-name branching."""

    provider_catalog = catalog or TranslationProviderCatalog().load()
    descriptor = provider_catalog.resolve(strategy_id)
    adapter_class = _resolve_adapter_class(descriptor)
    signature = inspect.signature(adapter_class)
    if "descriptor" in signature.parameters:
        adapter = adapter_class(descriptor=descriptor)
    else:
        adapter = adapter_class()
    if not isinstance(adapter, SpeechTranslationStrategyAdapter):
        raise TranslationStrategyLoadError(
            f"Translation adapter {descriptor.adapter_entrypoint!r} does not implement "
            "SpeechTranslationStrategyAdapter"
        )
    if adapter.strategy_id != descriptor.strategy_id:
        raise TranslationStrategyLoadError(
            f"Translation adapter strategy_id {adapter.strategy_id!r} does not match "
            f"manifest {descriptor.strategy_id!r}"
        )
    return adapter


def _resolve_adapter_class(
    descriptor: TranslationProviderDescriptor,
) -> Type[SpeechTranslationStrategyAdapter]:
    module_name, symbol_name = descriptor.adapter_entrypoint.rsplit(":", 1)
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        raise TranslationStrategyLoadError(
            f"Could not import translation adapter module {module_name!r}"
        ) from exc
    try:
        adapter_class = getattr(module, symbol_name)
    except AttributeError as exc:
        raise TranslationStrategyLoadError(
            f"Translation adapter symbol {symbol_name!r} not found in {module_name!r}"
        ) from exc
    if not isinstance(adapter_class, type):
        raise TranslationStrategyLoadError(
            f"Translation adapter entrypoint {descriptor.adapter_entrypoint!r} is not a class"
        )
    return adapter_class
