"""Transactional cascade/direct-speech strategy selection."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Any

from runtime.inference.protocol import LanguageCode
from runtime.inference.translation_provider_catalog import (
    TranslationProviderCatalog,
    TranslationStrategyKind,
)
from runtime.inference.translation_session import (
    SpeechTranslationSession,
    SpeechTranslationSessionConfig,
    SpeechTranslationStrategyAdapter,
)
from runtime.inference.translation_strategy_loader import load_translation_strategy_adapter


CASCADE_STRATEGY_ID = "modular-pipeline"
STATE_SCHEMA_VERSION = 1


class TranslationStrategyTransitionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TranslationStrategyState:
    kind: TranslationStrategyKind = TranslationStrategyKind.MODULAR_PIPELINE
    strategy_id: str = CASCADE_STRATEGY_ID

    def to_dict(self) -> dict[str, str | int]:
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "kind": self.kind.value,
            "strategy_id": self.strategy_id,
        }


@dataclass(frozen=True, slots=True)
class TranslationStrategyValidation:
    valid: bool
    strategy_id: str
    kind: TranslationStrategyKind
    reason: str = ""
    auth_configured: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "strategy_id": self.strategy_id,
            "kind": self.kind.value,
            "reason": self.reason,
            "auth_configured": self.auth_configured,
        }


class TranslationStrategyManager:
    """Owns mutually-exclusive cascade/direct strategy residency.

    The cascade callbacks deliberately abstract the existing orchestrator. A
    direct candidate is loaded and validated before the cascade is stopped.
    State persistence occurs only after the target is healthy. Failures restore
    the prior runtime state.
    """

    def __init__(
        self,
        *,
        state_path: Path,
        stop_cascade: Callable[[], Awaitable[None]],
        start_cascade: Callable[[], Awaitable[None]],
        cascade_is_active: Callable[[], bool],
        catalog: TranslationProviderCatalog | None = None,
        adapter_loader: Callable[..., SpeechTranslationStrategyAdapter] = load_translation_strategy_adapter,
    ) -> None:
        self.state_path = Path(state_path)
        self.stop_cascade = stop_cascade
        self.start_cascade = start_cascade
        self.cascade_is_active = cascade_is_active
        self.catalog = catalog or TranslationProviderCatalog().load()
        self.adapter_loader = adapter_loader
        self._state = self._load_state()
        self._direct_adapter: SpeechTranslationStrategyAdapter | None = None
        self._transition_lock = asyncio.Lock()

    @property
    def state(self) -> TranslationStrategyState:
        return self._state

    @property
    def direct_adapter(self) -> SpeechTranslationStrategyAdapter | None:
        return self._direct_adapter

    def status_payload(self) -> dict[str, Any]:
        return {
            **self._state.to_dict(),
            "transitioning": self._transition_lock.locked(),
            "direct_loaded": self._direct_adapter is not None,
            "cascade_active": bool(self.cascade_is_active()),
        }

    async def validate(
        self,
        *,
        strategy_id: str,
        source_language: LanguageCode,
        target_language: LanguageCode,
    ) -> TranslationStrategyValidation:
        if source_language == target_language:
            return TranslationStrategyValidation(
                valid=False,
                strategy_id=strategy_id,
                kind=self._kind_for(strategy_id),
                reason="source and target languages must differ",
            )
        if strategy_id == CASCADE_STRATEGY_ID:
            return TranslationStrategyValidation(
                valid=True,
                strategy_id=strategy_id,
                kind=TranslationStrategyKind.MODULAR_PIPELINE,
            )
        try:
            descriptor = self.catalog.resolve(strategy_id)
        except Exception as exc:
            return TranslationStrategyValidation(
                valid=False,
                strategy_id=strategy_id,
                kind=TranslationStrategyKind.DIRECT_SPEECH_TRANSLATION,
                reason=str(exc),
            )
        confirmed = set(descriptor.confirmed_languages)
        if confirmed and (
            source_language.value not in confirmed or target_language.value not in confirmed
        ):
            return TranslationStrategyValidation(
                valid=False,
                strategy_id=strategy_id,
                kind=descriptor.kind,
                reason=f"language pair {source_language.value}->{target_language.value} is not confirmed",
                auth_configured=None,
            )
        auth_configured = None
        if descriptor.auth_env:
            import os
            auth_configured = bool(os.getenv(descriptor.auth_env, "").strip())
        return TranslationStrategyValidation(
            valid=True,
            strategy_id=strategy_id,
            kind=descriptor.kind,
            auth_configured=auth_configured,
            reason=(
                f"credential environment variable {descriptor.auth_env} is not configured"
                if auth_configured is False
                else ""
            ),
        )

    async def activate(
        self,
        *,
        strategy_id: str,
        source_language: LanguageCode,
        target_language: LanguageCode,
        start_cascade_when_selected: bool = True,
    ) -> TranslationStrategyState:
        async with self._transition_lock:
            validation = await self.validate(
                strategy_id=strategy_id,
                source_language=source_language,
                target_language=target_language,
            )
            if not validation.valid:
                raise TranslationStrategyTransitionError(validation.reason or "strategy is invalid")
            if strategy_id == self._state.strategy_id:
                if strategy_id == CASCADE_STRATEGY_ID and start_cascade_when_selected and not self.cascade_is_active():
                    await self.start_cascade()
                return self._state
            if strategy_id == CASCADE_STRATEGY_ID:
                return await self._activate_cascade(start_cascade=start_cascade_when_selected)
            return await self._activate_direct(
                strategy_id=strategy_id,
                source_language=source_language,
                target_language=target_language,
            )

    async def _activate_direct(
        self,
        *,
        strategy_id: str,
        source_language: LanguageCode,
        target_language: LanguageCode,
    ) -> TranslationStrategyState:
        previous_state = self._state
        previous_adapter = self._direct_adapter
        cascade_was_active = self.cascade_is_active()
        candidate: SpeechTranslationStrategyAdapter | None = None
        cascade_stopped = False
        try:
            candidate = self.adapter_loader(strategy_id, catalog=self.catalog)
            await candidate.load()
            if not await candidate.health_check():
                raise TranslationStrategyTransitionError(
                    f"direct strategy {strategy_id!r} is not healthy; verify provider credentials/runtime"
                )
            if not await candidate.supports_language_pair(source_language, target_language):
                raise TranslationStrategyTransitionError(
                    f"direct strategy {strategy_id!r} does not support "
                    f"{source_language.value}->{target_language.value}"
                )

            if cascade_was_active:
                await self.stop_cascade()
                cascade_stopped = True

            new_state = TranslationStrategyState(
                kind=TranslationStrategyKind.DIRECT_SPEECH_TRANSLATION,
                strategy_id=strategy_id,
            )
            self._direct_adapter = candidate
            self._state = new_state
            self._persist_state()
            candidate = None

            if previous_adapter is not None and previous_adapter is not self._direct_adapter:
                await previous_adapter.unload()
            return new_state
        except Exception as exc:
            if candidate is not None:
                try:
                    await candidate.unload()
                except Exception:
                    pass
            self._state = previous_state
            self._direct_adapter = previous_adapter
            if cascade_stopped and cascade_was_active and not self.cascade_is_active():
                try:
                    await self.start_cascade()
                except Exception as rollback_exc:
                    raise TranslationStrategyTransitionError(
                        f"strategy transition failed ({exc}); cascade rollback also failed ({rollback_exc})"
                    ) from exc
            if isinstance(exc, TranslationStrategyTransitionError):
                raise
            raise TranslationStrategyTransitionError(str(exc)) from exc

    async def _activate_cascade(self, *, start_cascade: bool) -> TranslationStrategyState:
        previous_state = self._state
        previous_adapter = self._direct_adapter
        try:
            if start_cascade and not self.cascade_is_active():
                await self.start_cascade()
            new_state = TranslationStrategyState()
            self._state = new_state
            self._direct_adapter = None
            self._persist_state()
            if previous_adapter is not None:
                await previous_adapter.unload()
            return new_state
        except Exception as exc:
            self._state = previous_state
            self._direct_adapter = previous_adapter
            raise TranslationStrategyTransitionError(str(exc)) from exc

    async def restore(
        self,
        *,
        source_language: LanguageCode,
        target_language: LanguageCode,
        start_cascade_if_selected: bool,
    ) -> TranslationStrategyState:
        """Restore persisted direct residency or fall back safely to cascade."""
        if self._state.strategy_id == CASCADE_STRATEGY_ID:
            if start_cascade_if_selected and not self.cascade_is_active():
                await self.start_cascade()
            return self._state
        persisted = self._state.strategy_id
        # Treat the persisted state as desired state, then reset in-memory state
        # so activate() actually performs validation/load.
        self._state = TranslationStrategyState()
        try:
            return await self.activate(
                strategy_id=persisted,
                source_language=source_language,
                target_language=target_language,
                start_cascade_when_selected=start_cascade_if_selected,
            )
        except Exception:
            self._state = TranslationStrategyState()
            self._direct_adapter = None
            self._persist_state()
            if start_cascade_if_selected and not self.cascade_is_active():
                await self.start_cascade()
            return self._state

    async def open_direct_session(
        self,
        config: SpeechTranslationSessionConfig,
    ) -> SpeechTranslationSession:
        if self._state.kind != TranslationStrategyKind.DIRECT_SPEECH_TRANSLATION:
            raise TranslationStrategyTransitionError("active strategy is the modular cascade")
        adapter = self._direct_adapter
        if adapter is None:
            raise TranslationStrategyTransitionError("active direct strategy is not loaded")
        if not await adapter.supports_language_pair(config.source_language, config.target_language):
            raise TranslationStrategyTransitionError("active direct strategy does not support language pair")
        return await adapter.open_session(config)

    async def unload(self) -> None:
        async with self._transition_lock:
            adapter, self._direct_adapter = self._direct_adapter, None
            if adapter is not None:
                await adapter.unload()

    def _kind_for(self, strategy_id: str) -> TranslationStrategyKind:
        return (
            TranslationStrategyKind.MODULAR_PIPELINE
            if strategy_id == CASCADE_STRATEGY_ID
            else TranslationStrategyKind.DIRECT_SPEECH_TRANSLATION
        )

    def _load_state(self) -> TranslationStrategyState:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            if data.get("schema_version") != STATE_SCHEMA_VERSION:
                return TranslationStrategyState()
            kind = TranslationStrategyKind(str(data.get("kind", "modular_pipeline")))
            strategy_id = str(data.get("strategy_id") or CASCADE_STRATEGY_ID)
            if kind == TranslationStrategyKind.MODULAR_PIPELINE:
                strategy_id = CASCADE_STRATEGY_ID
            elif strategy_id == CASCADE_STRATEGY_ID:
                return TranslationStrategyState()
            return TranslationStrategyState(kind=kind, strategy_id=strategy_id)
        except Exception:
            return TranslationStrategyState()

    def _persist_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temporary.write_text(json.dumps(self._state.to_dict(), indent=2), encoding="utf-8")
        temporary.replace(self.state_path)
