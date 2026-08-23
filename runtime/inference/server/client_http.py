"""aiohttp integration for the versioned Expo client contract."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable
from typing import Any

from aiohttp import web

from runtime.inference.server.client_contract import (
    ClientOriginPolicy,
    build_audio_devices,
    build_client_bootstrap,
    build_desktop_audio_status,
)
from runtime.inference.translation_provider_catalog import (
    TranslationProviderCatalog,
    serialize_provider_catalog,
)


_ALLOWED_METHODS = "GET, POST, DELETE, OPTIONS"
_ALLOWED_HEADERS = "Accept, Authorization, Content-Type"


def create_client_cors_middleware(
    policy: ClientOriginPolicy | None = None,
) -> web.middleware:
    """Create restricted CORS middleware for local `/api/` calls.

    Requests without an Origin header are left alone for CLI/native/local use.
    Browser origins must either be loopback or explicitly allow-listed via
    ``VOXPASSPORT_CLIENT_ORIGINS``.
    """

    origin_policy = policy or ClientOriginPolicy.from_environment()

    @web.middleware
    async def middleware(request: web.Request, handler):
        if not request.path.startswith("/api/"):
            return await handler(request)

        origin = request.headers.get("Origin")
        if origin and not origin_policy.allows(origin):
            return web.json_response(
                {"error": "origin_not_allowed"},
                status=403,
            )

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
    """Validate a browser WebSocket Origin using the same client policy."""

    # Native/non-browser WebSocket clients may omit Origin.
    if not origin:
        return True
    return (policy or ClientOriginPolicy.from_environment()).allows(origin)


def default_translation_strategies() -> dict[str, Any]:
    """Return backend-owned direct speech strategy metadata."""

    entries = TranslationProviderCatalog().load().entries()
    return {
        "schema_version": 1,
        "strategies": serialize_provider_catalog(entries),
    }


def register_client_contract_routes(
    app: web.Application,
    *,
    capabilities_provider: Callable[[], Iterable[str]] | Iterable[str],
    app_version: str | None = None,
    audio_status_provider: Callable[[], dict[str, Any]] | None = None,
    audio_devices_provider: Callable[[], dict[str, Any]] | None = None,
    translation_strategies_provider: Callable[[], dict[str, Any]] | None = None,
) -> None:
    """Register bootstrap, native-audio, and translation-strategy discovery routes.

    Providers can later be replaced with live native/service implementations
    without changing the Expo API contract.
    """

    async def client_bootstrap(_request: web.Request) -> web.Response:
        capabilities = await _resolve_provider(capabilities_provider)
        return web.json_response(
            build_client_bootstrap(
                capabilities=capabilities,
                app_version=app_version,
            )
        )

    async def audio_status(_request: web.Request) -> web.Response:
        if audio_status_provider is None:
            payload = build_desktop_audio_status()
        else:
            payload = await _resolve_provider(audio_status_provider)
        return web.json_response(payload)

    async def audio_devices(_request: web.Request) -> web.Response:
        if audio_devices_provider is None:
            payload = build_audio_devices()
        else:
            payload = await _resolve_provider(audio_devices_provider)
        return web.json_response(payload)

    async def translation_strategies(_request: web.Request) -> web.Response:
        provider = translation_strategies_provider or default_translation_strategies
        return web.json_response(await _resolve_provider(provider))

    app.router.add_get("/api/client/bootstrap", client_bootstrap)
    app.router.add_get("/api/audio/status", audio_status)
    app.router.add_get("/api/audio/devices", audio_devices)
    app.router.add_get("/api/translation/strategies", translation_strategies)


async def _resolve_provider(provider):
    value = provider() if callable(provider) else provider
    if inspect.isawaitable(value):
        value = await value
    return value
