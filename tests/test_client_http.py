import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from runtime.inference.server.client_contract import ClientOriginPolicy
from runtime.inference.server.client_http import (
    create_client_cors_middleware,
    register_client_contract_routes,
    websocket_origin_allowed,
)


async def _make_client(policy: ClientOriginPolicy | None = None) -> TestClient:
    app = web.Application(middlewares=[create_client_cors_middleware(policy)])
    register_client_contract_routes(
        app,
        capabilities_provider=lambda: ["ASR", "TTS", "DIRECT_SPEECH_TRANSLATION"],
        app_version="test-version",
    )
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


@pytest.mark.asyncio
async def test_bootstrap_route_allows_non_browser_local_client():
    client = await _make_client()
    try:
        response = await client.get("/api/client/bootstrap")
        assert response.status == 200
        payload = await response.json()
        assert payload["protocol_version"] == "voxpassport.client.v1"
        assert payload["app_version"] == "test-version"
        assert "DIRECT_SPEECH_TRANSLATION" in payload["capabilities"]
        assert payload["translation_strategies_url"].endswith("/api/translation/strategies")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_translation_strategy_route_is_backend_driven():
    client = await _make_client()
    try:
        response = await client.get("/api/translation/strategies")
        assert response.status == 200
        payload = await response.json()
        assert payload["schema_version"] == 1
        gemini = next(
            entry for entry in payload["strategies"]
            if entry["strategy_id"] == "gemini-3.5-live-translate"
        )
        assert gemini["provider"] == "google"
        assert gemini["execution_mode"] == "byo_api"
        assert gemini["capability"] == "DIRECT_SPEECH_TRANSLATION"
        assert {"en", "ro"}.issubset(gemini["confirmed_languages"])
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_loopback_browser_origin_gets_cors_headers():
    client = await _make_client()
    origin = "http://localhost:8081"
    try:
        response = await client.get(
            "/api/audio/status",
            headers={"Origin": origin},
        )
        assert response.status == 200
        assert response.headers["Access-Control-Allow-Origin"] == origin
        payload = await response.json()
        assert payload["service_connected"] is False
        assert payload["capabilities"]["virtual_microphone_output"] is False
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_non_allowlisted_remote_browser_origin_is_rejected():
    client = await _make_client(ClientOriginPolicy())
    try:
        response = await client.get(
            "/api/client/bootstrap",
            headers={"Origin": "https://evil.example.test"},
        )
        assert response.status == 403
        assert (await response.json())["error"] == "origin_not_allowed"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_explicit_remote_origin_is_allowed():
    origin = "https://client.example.test"
    client = await _make_client(ClientOriginPolicy(extra_origins=frozenset({origin})))
    try:
        response = await client.get(
            "/api/audio/devices",
            headers={"Origin": origin},
        )
        assert response.status == 200
        assert response.headers["Access-Control-Allow-Origin"] == origin
        assert (await response.json())["devices"] == []
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_preflight_is_answered_without_route_specific_options_handler():
    client = await _make_client()
    origin = "http://127.0.0.1:19006"
    try:
        response = await client.options(
            "/api/translate",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
        assert response.status == 204
        assert response.headers["Access-Control-Allow-Origin"] == origin
        assert "POST" in response.headers["Access-Control-Allow-Methods"]
    finally:
        await client.close()


def test_websocket_origin_policy_matches_http_policy():
    policy = ClientOriginPolicy(extra_origins=frozenset({"https://client.example.test"}))
    assert websocket_origin_allowed(None, policy)
    assert websocket_origin_allowed("http://localhost:8081", policy)
    assert websocket_origin_allowed("https://client.example.test", policy)
    assert not websocket_origin_allowed("https://other.example.test", policy)
