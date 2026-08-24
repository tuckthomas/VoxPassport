"""aiohttp integration for the versioned Expo client contract."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from aiohttp import web

from runtime.inference.native_audio_bridge import NativeAudioBridge
from runtime.inference.native_audio_routing import NativeAudioRoutingStore
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


def create_client_cors_middleware(
    policy: ClientOriginPolicy | None = None,
) -> web.middleware:
    """Create restricted CORS middleware for local `/api/` calls."""

    origin_policy = policy or ClientOriginPolicy.from_environment()

    @web.middleware
    async def middleware(request: web.Request, handler):
        if not request.path.startswith("/api/"):
            return await handler(request)
        origin = request.headers.get("Origin")
        if origin and not origin_policy.allows(origin):
            return web.json_response({"error": "origin_not_allowed"}, status=403)
        if request.method == "OPTIONS":
            response = web.Response(status=204)
        else:
            response = await handler(request)
        if origin:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Methods"] = _ALLOWED_METHODS
            response.headers["Access-Control-Allow-Headers"] = _ALLOWED_HEADERS
            response.headers["Access-Control-Max-Age"] = "600"
        return response

    return middleware


def websocket_origin_allowed(
    origin: str | None,
    policy: ClientOriginPolicy | None = None,
) -> bool:
    if not origin:
        return True
    return (policy or ClientOriginPolicy.from_environment()).allows(origin)


def default_translation_strategies() -> dict[str, Any]:
    entries = TranslationProviderCatalog().load().entries()
    return {"schema_version": 1, "strategies": serialize_provider_catalog(entries)}


def register_client_contract_routes(
    app: web.Application,
    *,
    capabilities_provider: Callable[[], Iterable[str]] | Iterable[str],
    app_version: str | None = None,
    audio_status_provider: Callable[[], dict[str, Any]] | None = None,
    audio_devices_provider: Callable[[], dict[str, Any]] | None = None,
    translation_strategies_provider: Callable[[], dict[str, Any]] | None = None,
    audio_routing_store: NativeAudioRoutingStore | None = None,
) -> None:
    """Register stable Expo-facing runtime discovery/control routes."""

    routing_store = audio_routing_store or _DEFAULT_NATIVE_AUDIO_ROUTING

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


async def _resolve_provider(provider):
    value = provider() if callable(provider) else provider
    if inspect.isawaitable(value):
        value = await value
    return value
