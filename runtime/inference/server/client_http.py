"""aiohttp integration for the versioned Expo client contract."""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiohttp import web

from runtime.inference.live_translation_controller import (
    LiveTranslationController,
    LiveTranslationStartConfig,
)
from runtime.inference.native_audio_bridge import NativeAudioBridge
from runtime.inference.native_audio_routing import NativeAudioRoutingStore
from runtime.inference.provider_credentials import (
    DEFAULT_LABEL,
    KeyringProviderCredentialStore,
    LocalProviderCredentialResolver,
)
from runtime.inference.protocol import LanguageCode
from runtime.inference.server.client_contract import ClientOriginPolicy, build_client_bootstrap
from runtime.inference.translation_provider_catalog import (
    TranslationProviderCatalog,
    serialize_provider_catalog,
)


_ALLOWED_METHODS = "GET, POST, PUT, DELETE, OPTIONS"
_ALLOWED_HEADERS = "Accept, Authorization, Content-Type"
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_NATIVE_AUDIO_BRIDGE = NativeAudioBridge(project_root=_PROJECT_ROOT)
_DEFAULT_NATIVE_AUDIO_ROUTING = NativeAudioRoutingStore(
    _PROJECT_ROOT / "data" / "native_audio_routing.json",
    _DEFAULT_NATIVE_AUDIO_BRIDGE,
)


@dataclass(slots=True)
class RuntimeClientServices:
    translation_strategy_manager: Any
    live_translation_controller: LiveTranslationController
    audio_routing_store: NativeAudioRoutingStore
    language_pair_provider: Callable[[], tuple[LanguageCode, LanguageCode]]
    cascade_should_start_provider: Callable[[], bool]
    provider_credential_store: KeyringProviderCredentialStore | None = None
    provider_credential_resolver: LocalProviderCredentialResolver | None = None


_RUNTIME_CLIENT_SERVICES: RuntimeClientServices | None = None


def configure_runtime_client_services(services: RuntimeClientServices | None) -> None:
    global _RUNTIME_CLIENT_SERVICES
    _RUNTIME_CLIENT_SERVICES = services


def create_client_cors_middleware(policy: ClientOriginPolicy | None = None) -> web.middleware:
    origin_policy = policy or ClientOriginPolicy.from_environment()

    @web.middleware
    async def middleware(request: web.Request, handler):
        if not request.path.startswith("/api/"):
            return await handler(request)
        origin = request.headers.get("Origin")
        if origin and not origin_policy.allows(origin):
            return web.json_response({"error": "origin_not_allowed"}, status=403)
        response = web.Response(status=204) if request.method == "OPTIONS" else await handler(request)

        if request.path == "/api/status" and response.content_type == "application/json":
            services = _RUNTIME_CLIENT_SERVICES
            if services is not None:
                try:
                    payload = json.loads(response.body.decode("utf-8"))
                    if isinstance(payload, dict):
                        payload["translation_strategy"] = services.translation_strategy_manager.status_payload()
                        payload["live_translation_session"] = services.live_translation_controller.status_payload()
                        response = web.json_response(payload, status=response.status)
                except Exception:
                    pass

        if origin:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Methods"] = _ALLOWED_METHODS
            response.headers["Access-Control-Allow-Headers"] = _ALLOWED_HEADERS
            response.headers["Access-Control-Max-Age"] = "600"
        return response

    return middleware


def websocket_origin_allowed(origin: str | None, policy: ClientOriginPolicy | None = None) -> bool:
    if not origin:
        return True
    return (policy or ClientOriginPolicy.from_environment()).allows(origin)


def default_translation_strategies() -> dict[str, Any]:
    entries = TranslationProviderCatalog().load().entries()
    return {"schema_version": 1, "strategies": serialize_provider_catalog(entries)}


def _provider_descriptors(provider: str):
    provider_id = provider.strip().casefold()
    return [
        descriptor
        for descriptor in TranslationProviderCatalog().load().entries()
        if descriptor.provider.casefold() == provider_id
    ]


async def _local_provider_status(
    provider: str,
    *,
    resolver: LocalProviderCredentialResolver,
    label: str = DEFAULT_LABEL,
) -> dict[str, Any]:
    descriptors = _provider_descriptors(provider)
    if not descriptors:
        raise ValueError(f"unknown direct-speech provider {provider!r}")
    resolved = await resolver.resolve(descriptors[0], label=label)
    return {
        "provider": descriptors[0].provider,
        "label": label,
        "configured": resolved is not None,
        "source": resolved.source if resolved else None,
        "strategy_ids": [descriptor.strategy_id for descriptor in descriptors],
    }


def register_client_contract_routes(
    app: web.Application,
    *,
    capabilities_provider: Callable[[], Iterable[str]] | Iterable[str],
    app_version: str | None = None,
    audio_status_provider: Callable[[], dict[str, Any]] | None = None,
    audio_devices_provider: Callable[[], dict[str, Any]] | None = None,
    translation_strategies_provider: Callable[[], dict[str, Any]] | None = None,
    audio_routing_store: NativeAudioRoutingStore | None = None,
    translation_strategy_manager: Any | None = None,
    live_translation_controller: LiveTranslationController | None = None,
    language_pair_provider: Callable[[], tuple[LanguageCode, LanguageCode]] | None = None,
    cascade_should_start_provider: Callable[[], bool] | None = None,
    provider_credential_store: KeyringProviderCredentialStore | None = None,
    provider_credential_resolver: LocalProviderCredentialResolver | None = None,
) -> None:
    """Register stable Expo-facing runtime discovery/control routes."""

    services = _RUNTIME_CLIENT_SERVICES
    routing_store = audio_routing_store or (services.audio_routing_store if services else None) or _DEFAULT_NATIVE_AUDIO_ROUTING
    strategy_manager = translation_strategy_manager or (services.translation_strategy_manager if services else None)
    live_controller = live_translation_controller or (services.live_translation_controller if services else None)
    pair_provider = language_pair_provider or (services.language_pair_provider if services else None)
    cascade_provider = cascade_should_start_provider or (services.cascade_should_start_provider if services else None)
    credential_store = provider_credential_store or (services.provider_credential_store if services else None)
    credential_resolver = provider_credential_resolver or (services.provider_credential_resolver if services else None)

    async def client_bootstrap(_request: web.Request) -> web.Response:
        capabilities = await _resolve_provider(capabilities_provider)
        return web.json_response(build_client_bootstrap(capabilities=capabilities, app_version=app_version))

    async def audio_status(_request: web.Request) -> web.Response:
        provider = audio_status_provider or _DEFAULT_NATIVE_AUDIO_BRIDGE.status_payload
        return web.json_response(await _resolve_provider(provider))

    async def audio_devices(_request: web.Request) -> web.Response:
        provider = audio_devices_provider or _DEFAULT_NATIVE_AUDIO_BRIDGE.devices_payload
        return web.json_response(await _resolve_provider(provider))

    async def audio_routing(request: web.Request) -> web.Response:
        if request.method == "GET":
            return web.json_response(await routing_store.payload())
        try:
            data = await request.json()
            if not isinstance(data, dict):
                raise ValueError("routing payload must be an object")
            if live_controller is not None and live_controller.active:
                return web.json_response(
                    {"error": "stop live translation before changing audio routing"},
                    status=409,
                )
            return web.json_response(await routing_store.update(data))
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=400)

    async def confirm_virtual_microphone(request: web.Request) -> web.Response:
        try:
            data = await request.json()
            confirmed = bool(data.get("confirmed", False)) if isinstance(data, dict) else False
            return web.json_response(await routing_store.confirm_virtual_microphone(confirmed))
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=400)

    async def translation_strategies(_request: web.Request) -> web.Response:
        provider = translation_strategies_provider or default_translation_strategies
        return web.json_response(await _resolve_provider(provider))

    app.router.add_get("/api/client/bootstrap", client_bootstrap)
    app.router.add_get("/api/audio/status", audio_status)
    app.router.add_get("/api/audio/devices", audio_devices)
    app.router.add_route("GET", "/api/audio/routing", audio_routing)
    app.router.add_route("PUT", "/api/audio/routing", audio_routing)
    app.router.add_post("/api/audio/routing/confirm-virtual-microphone", confirm_virtual_microphone)
    app.router.add_get("/api/translation/strategies", translation_strategies)

    if credential_store is not None and credential_resolver is not None:
        async def local_provider_credentials(_request: web.Request) -> web.Response:
            catalog = TranslationProviderCatalog().load()
            providers = sorted({descriptor.provider for descriptor in catalog.entries()})
            statuses = [
                await _local_provider_status(provider, resolver=credential_resolver)
                for provider in providers
            ]
            return web.json_response({
                "schema_version": 1,
                "keyring_available": await credential_store.available(),
                "credentials": statuses,
            })

        async def put_local_provider_credential(request: web.Request) -> web.Response:
            try:
                provider = request.match_info["provider"].strip().casefold()
                descriptors = _provider_descriptors(provider)
                if not descriptors:
                    raise ValueError(f"unknown direct-speech provider {provider!r}")
                data = await request.json()
                if not isinstance(data, dict):
                    raise ValueError("credential payload must be an object")
                secret = str(data.get("secret") or "").strip()
                label = str(data.get("label") or DEFAULT_LABEL).strip().casefold() or DEFAULT_LABEL
                await credential_store.set_secret(provider, secret, label=label)
                return web.json_response(
                    await _local_provider_status(provider, resolver=credential_resolver, label=label)
                )
            except Exception as exc:
                return web.json_response({"error": str(exc)}, status=400)

        async def delete_local_provider_credential(request: web.Request) -> web.Response:
            try:
                provider = request.match_info["provider"].strip().casefold()
                descriptors = _provider_descriptors(provider)
                if not descriptors:
                    raise ValueError(f"unknown direct-speech provider {provider!r}")
                label = str(request.query.get("label") or DEFAULT_LABEL).strip().casefold() or DEFAULT_LABEL
                await credential_store.delete_secret(provider, label=label)
                return web.json_response(
                    await _local_provider_status(provider, resolver=credential_resolver, label=label)
                )
            except Exception as exc:
                return web.json_response({"error": str(exc)}, status=400)

        app.router.add_get("/api/provider-credentials/local", local_provider_credentials)
        app.router.add_put("/api/provider-credentials/local/{provider}", put_local_provider_credential)
        app.router.add_delete("/api/provider-credentials/local/{provider}", delete_local_provider_credential)

    if strategy_manager is not None:
        if pair_provider is None:
            raise ValueError("language_pair_provider is required with translation_strategy_manager")

        async def strategy_status(_request: web.Request) -> web.Response:
            return web.json_response(strategy_manager.status_payload())

        async def strategy_validate(request: web.Request) -> web.Response:
            try:
                data = await request.json()
                strategy_id = str(data.get("strategy_id", "")).strip()
                if not strategy_id:
                    raise ValueError("strategy_id is required")
                default_source, default_target = pair_provider()
                source = LanguageCode(str(data.get("source_language") or default_source.value))
                target = LanguageCode(str(data.get("target_language") or default_target.value))
                result = await strategy_manager.validate(
                    strategy_id=strategy_id,
                    source_language=source,
                    target_language=target,
                )
                return web.json_response(result.to_dict())
            except Exception as exc:
                return web.json_response({"error": str(exc)}, status=400)

        async def strategy_activate(request: web.Request) -> web.Response:
            if live_controller is not None and live_controller.active:
                return web.json_response(
                    {"error": "stop live translation before changing strategy"},
                    status=409,
                )
            try:
                data = await request.json()
                strategy_id = str(data.get("strategy_id", "")).strip()
                if not strategy_id:
                    raise ValueError("strategy_id is required")
                default_source, default_target = pair_provider()
                source = LanguageCode(str(data.get("source_language") or default_source.value))
                target = LanguageCode(str(data.get("target_language") or default_target.value))
                should_start = True if cascade_provider is None else bool(cascade_provider())
                await strategy_manager.activate(
                    strategy_id=strategy_id,
                    source_language=source,
                    target_language=target,
                    start_cascade_when_selected=should_start,
                )
                return web.json_response(strategy_manager.status_payload())
            except Exception as exc:
                return web.json_response({"error": str(exc)}, status=400)

        app.router.add_get("/api/translation/strategy", strategy_status)
        app.router.add_post("/api/translation/strategy/validate", strategy_validate)
        app.router.add_post("/api/translation/strategy/activate", strategy_activate)

    if live_controller is not None:
        async def live_status(_request: web.Request) -> web.Response:
            return web.json_response(live_controller.status_payload())

        async def live_start(request: web.Request) -> web.Response:
            try:
                data = await request.json()
                default_source, default_target = (
                    pair_provider() if pair_provider is not None else (LanguageCode.EN, LanguageCode.RO)
                )
                source = LanguageCode(str(data.get("source_language") or default_source.value))
                target = LanguageCode(str(data.get("target_language") or default_target.value))
                mode = str(data.get("mode") or "full_duplex")
                payload = await live_controller.start(LiveTranslationStartConfig(
                    source_language=source,
                    target_language=target,
                    mode=mode,
                ))
                return web.json_response(payload)
            except Exception as exc:
                return web.json_response({"error": str(exc)}, status=400)

        async def live_stop(_request: web.Request) -> web.Response:
            return web.json_response(await live_controller.stop())

        app.router.add_get("/api/translation/live", live_status)
        app.router.add_post("/api/translation/live/start", live_start)
        app.router.add_post("/api/translation/live/stop", live_stop)


async def _resolve_provider(provider):
    value = provider() if callable(provider) else provider
    if inspect.isawaitable(value):
        value = await value
    return value
