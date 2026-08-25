"""Provider credential resolution for local/self-hosted inference.

Secrets never pass through model manifests or client discovery payloads. Local
credentials live in the operating-system credential vault through ``keyring``;
environment variables remain a non-persistent automation fallback. Cloud
credential stores can implement the same resolver contract later.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Protocol

from runtime.inference.translation_provider_catalog import TranslationProviderDescriptor


DEFAULT_LABEL = "default"
KEYRING_SERVICE = "VoxPassport Provider Credentials"


class ProviderCredentialError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ResolvedProviderCredential:
    secret: str
    source: str
    label: str = DEFAULT_LABEL


class ProviderCredentialResolver(Protocol):
    async def resolve(
        self,
        descriptor: TranslationProviderDescriptor,
        *,
        label: str = DEFAULT_LABEL,
    ) -> ResolvedProviderCredential | None:
        ...


class KeyringProviderCredentialStore:
    """OS credential-vault store keyed by provider and label."""

    def __init__(self, *, service_name: str = KEYRING_SERVICE) -> None:
        self.service_name = service_name

    @staticmethod
    def _account(provider: str, label: str) -> str:
        provider_id = provider.strip().casefold()
        label_id = label.strip().casefold() or DEFAULT_LABEL
        if not provider_id:
            raise ProviderCredentialError("provider identifier is required")
        return f"{provider_id}:{label_id}"

    async def available(self) -> bool:
        try:
            return await asyncio.to_thread(self._available_sync)
        except Exception:
            return False

    @staticmethod
    def _available_sync() -> bool:
        import keyring

        backend = keyring.get_keyring()
        priority = getattr(backend, "priority", 0)
        try:
            return float(priority) > 0
        except (TypeError, ValueError):
            return bool(priority)

    async def get_secret(self, provider: str, *, label: str = DEFAULT_LABEL) -> str | None:
        account = self._account(provider, label)
        try:
            value = await asyncio.to_thread(self._get_sync, account)
        except Exception as exc:
            raise ProviderCredentialError("operating-system credential vault lookup failed") from exc
        secret = str(value or "").strip()
        return secret or None

    def _get_sync(self, account: str) -> str | None:
        import keyring
        return keyring.get_password(self.service_name, account)

    async def set_secret(self, provider: str, secret: str, *, label: str = DEFAULT_LABEL) -> None:
        value = secret.strip()
        if not value:
            raise ProviderCredentialError("provider secret must not be empty")
        account = self._account(provider, label)
        try:
            await asyncio.to_thread(self._set_sync, account, value)
        except Exception as exc:
            raise ProviderCredentialError("operating-system credential vault write failed") from exc

    def _set_sync(self, account: str, secret: str) -> None:
        import keyring
        keyring.set_password(self.service_name, account, secret)

    async def delete_secret(self, provider: str, *, label: str = DEFAULT_LABEL) -> None:
        account = self._account(provider, label)
        try:
            await asyncio.to_thread(self._delete_sync, account)
        except Exception as exc:
            # keyring backends use different exception classes for missing items;
            # deleting an already-absent credential is intentionally idempotent.
            try:
                existing = await asyncio.to_thread(self._get_sync, account)
            except Exception:
                existing = None
            if existing:
                raise ProviderCredentialError("operating-system credential vault delete failed") from exc

    def _delete_sync(self, account: str) -> None:
        import keyring
        keyring.delete_password(self.service_name, account)


class LocalProviderCredentialResolver:
    """Resolve OS-vault credentials first, then manifest-declared env fallback."""

    def __init__(self, *, store: KeyringProviderCredentialStore | None = None) -> None:
        self.store = store or KeyringProviderCredentialStore()

    async def resolve(
        self,
        descriptor: TranslationProviderDescriptor,
        *,
        label: str = DEFAULT_LABEL,
    ) -> ResolvedProviderCredential | None:
        try:
            secret = await self.store.get_secret(descriptor.provider, label=label)
        except ProviderCredentialError:
            secret = None
        if secret:
            return ResolvedProviderCredential(secret=secret, source="os_keyring", label=label)

        if descriptor.auth_env:
            environment_secret = os.getenv(descriptor.auth_env, "").strip()
            if environment_secret:
                return ResolvedProviderCredential(
                    secret=environment_secret,
                    source=f"environment:{descriptor.auth_env}",
                    label=label,
                )
        return None

    async def status(
        self,
        descriptor: TranslationProviderDescriptor,
        *,
        label: str = DEFAULT_LABEL,
    ) -> dict[str, object]:
        resolved = await self.resolve(descriptor, label=label)
        return {
            "provider": descriptor.provider,
            "label": label,
            "configured": resolved is not None,
            "source": resolved.source if resolved else None,
            "strategy_ids": [descriptor.strategy_id],
        }
