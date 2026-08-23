"""Provider-agnostic translation strategy metadata.

Communication transport (Zoom/Meet/virtual audio/etc.) is deliberately separate
from inference strategy. Direct audio-to-audio providers are represented as
DIRECT_SPEECH_TRANSLATION strategies rather than being forced into ASR/NMT/TTS
slots.
"""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from runtime.inference.protocol import ModelCapability


SCHEMA_VERSION = 1
DEFAULT_MANIFEST_DIR = Path(__file__).resolve().parents[1] / "translation_provider_manifests"


class TranslationStrategyKind(str, enum.Enum):
    MODULAR_PIPELINE = "modular_pipeline"
    DIRECT_SPEECH_TRANSLATION = "direct_speech_translation"


class ExecutionMode(str, enum.Enum):
    LOCAL = "local"
    BYO_API = "byo_api"
    SELF_HOSTED = "self_hosted"
    MANAGED_CLOUD = "managed_cloud"


class ProviderAuthKind(str, enum.Enum):
    NONE = "none"
    API_KEY = "api_key"
    OAUTH = "oauth"
    SESSION_TOKEN = "session_token"


@dataclass(frozen=True, slots=True)
class TranslationProviderDescriptor:
    strategy_id: str
    display_name: str
    provider: str
    model_id: str
    kind: TranslationStrategyKind
    capability: ModelCapability
    execution_mode: ExecutionMode
    transport: str
    adapter_entrypoint: str
    auth_kind: ProviderAuthKind
    auth_env: str | None
    streaming: bool
    bidirectional: bool
    voice_preservation: bool
    language_discovery: str
    confirmed_languages: tuple[str, ...]
    lifecycle: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        # adapter_entrypoint is intentionally runtime-internal and is not exposed
        # through the client discovery contract.
        return {
            "strategy_id": self.strategy_id,
            "display_name": self.display_name,
            "provider": self.provider,
            "model_id": self.model_id,
            "kind": self.kind.value,
            "capability": self.capability.value,
            "execution_mode": self.execution_mode.value,
            "transport": self.transport,
            "auth_kind": self.auth_kind.value,
            "auth_env": self.auth_env,
            "streaming": self.streaming,
            "bidirectional": self.bidirectional,
            "voice_preservation": self.voice_preservation,
            "language_discovery": self.language_discovery,
            "confirmed_languages": list(self.confirmed_languages),
            "lifecycle": self.lifecycle,
            "metadata": dict(self.metadata),
        }


class TranslationProviderCatalogError(ValueError):
    pass


class TranslationProviderCatalog:
    def __init__(self, manifest_dir: Path | None = None) -> None:
        self.manifest_dir = Path(manifest_dir or DEFAULT_MANIFEST_DIR)
        self._entries: dict[str, TranslationProviderDescriptor] = {}

    def load(self) -> "TranslationProviderCatalog":
        entries: dict[str, TranslationProviderDescriptor] = {}
        if not self.manifest_dir.exists():
            self._entries = entries
            return self
        for path in sorted(self.manifest_dir.glob("*.json")):
            descriptor = self._load_manifest(path)
            if descriptor.strategy_id in entries:
                raise TranslationProviderCatalogError(
                    f"Duplicate translation strategy_id {descriptor.strategy_id!r}"
                )
            entries[descriptor.strategy_id] = descriptor
        self._entries = entries
        return self

    def entries(self) -> list[TranslationProviderDescriptor]:
        return list(self._entries.values())

    def resolve(self, strategy_id: str) -> TranslationProviderDescriptor:
        try:
            return self._entries[strategy_id]
        except KeyError as exc:
            raise TranslationProviderCatalogError(
                f"Unknown translation strategy {strategy_id!r}"
            ) from exc

    @staticmethod
    def _required(data: dict[str, Any], key: str, path: Path) -> Any:
        value = data.get(key)
        if value is None or value == "":
            raise TranslationProviderCatalogError(f"{path.name}: missing {key}")
        return value

    @staticmethod
    def _validate_adapter_entrypoint(value: Any, path: Path) -> str:
        entrypoint = str(value or "").strip()
        if not entrypoint or ":" not in entrypoint:
            raise TranslationProviderCatalogError(
                f"{path.name}: adapter must use 'python.module:ClassName' format"
            )
        module_name, symbol_name = entrypoint.rsplit(":", 1)
        if not module_name or not symbol_name or any(ch.isspace() for ch in entrypoint):
            raise TranslationProviderCatalogError(
                f"{path.name}: invalid adapter entrypoint {entrypoint!r}"
            )
        return entrypoint

    def _load_manifest(self, path: Path) -> TranslationProviderDescriptor:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise TranslationProviderCatalogError(f"{path.name}: invalid JSON: {exc}") from exc

        if data.get("schema_version") != SCHEMA_VERSION:
            raise TranslationProviderCatalogError(
                f"{path.name}: schema_version must be {SCHEMA_VERSION}"
            )
        capability = ModelCapability(self._required(data, "capability", path))
        if capability != ModelCapability.DIRECT_SPEECH_TRANSLATION:
            raise TranslationProviderCatalogError(
                f"{path.name}: provider catalog only accepts DIRECT_SPEECH_TRANSLATION"
            )
        kind = TranslationStrategyKind(self._required(data, "kind", path))
        if kind != TranslationStrategyKind.DIRECT_SPEECH_TRANSLATION:
            raise TranslationProviderCatalogError(
                f"{path.name}: kind must be direct_speech_translation"
            )

        auth = data.get("auth") or {}
        languages = data.get("languages") or {}
        features = data.get("features") or {}
        known = {
            "schema_version", "strategy_id", "display_name", "provider", "model_id",
            "kind", "capability", "execution_mode", "transport", "adapter", "auth",
            "languages", "features", "lifecycle", "metadata",
        }
        unknown = sorted(set(data) - known)
        if unknown:
            raise TranslationProviderCatalogError(
                f"{path.name}: unknown top-level fields: {', '.join(unknown)}"
            )

        return TranslationProviderDescriptor(
            strategy_id=str(self._required(data, "strategy_id", path)),
            display_name=str(self._required(data, "display_name", path)),
            provider=str(self._required(data, "provider", path)),
            model_id=str(self._required(data, "model_id", path)),
            kind=kind,
            capability=capability,
            execution_mode=ExecutionMode(self._required(data, "execution_mode", path)),
            transport=str(self._required(data, "transport", path)),
            adapter_entrypoint=self._validate_adapter_entrypoint(
                self._required(data, "adapter", path), path
            ),
            auth_kind=ProviderAuthKind(auth.get("kind", "none")),
            auth_env=str(auth["environment_variable"]) if auth.get("environment_variable") else None,
            streaming=bool(features.get("streaming", False)),
            bidirectional=bool(features.get("bidirectional", False)),
            voice_preservation=bool(features.get("voice_preservation", False)),
            language_discovery=str(languages.get("discovery", "manifest")),
            confirmed_languages=tuple(str(x) for x in languages.get("confirmed", [])),
            lifecycle=str(data.get("lifecycle", "available")),
            metadata=dict(data.get("metadata") or {}),
        )


def serialize_provider_catalog(
    entries: Iterable[TranslationProviderDescriptor],
) -> list[dict[str, Any]]:
    return [entry.to_dict() for entry in entries]
