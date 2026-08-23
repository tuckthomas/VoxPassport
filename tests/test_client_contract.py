from runtime.inference.server.client_contract import (
    CLIENT_PROTOCOL_VERSION,
    ClientOriginPolicy,
    build_audio_devices,
    build_client_bootstrap,
    build_desktop_audio_status,
    normalize_origin,
)


def test_normalize_origin_rejects_paths_credentials_and_non_http_schemes():
    assert normalize_origin("http://localhost:8081") == "http://localhost:8081"
    assert normalize_origin("HTTP://127.0.0.1:19006/") == "http://127.0.0.1:19006"
    assert normalize_origin("http://[::1]:8081") == "http://[::1]:8081"
    assert normalize_origin("https://example.com") == "https://example.com"
    assert normalize_origin("http://localhost:8081/path") is None
    assert normalize_origin("http://user:pass@localhost:8081") is None
    assert normalize_origin("file:///tmp/app") is None
    assert normalize_origin("javascript:alert(1)") is None


def test_origin_policy_allows_loopback_on_any_port_and_explicit_extra_origin():
    policy = ClientOriginPolicy(extra_origins=frozenset({"https://client.example.test"}))

    assert policy.allows("http://localhost:8081")
    assert policy.allows("http://127.0.0.1:19006")
    assert policy.allows("https://[::1]:443")
    assert policy.allows("https://client.example.test")
    assert not policy.allows("https://other.example.test")
    assert not policy.allows(None)


def test_client_bootstrap_is_versioned_and_exposes_audio_contract_urls():
    payload = build_client_bootstrap(
        capabilities=["TTS", "ASR", "DIRECT_SPEECH_TRANSLATION", "ASR"],
        app_version="0.1.0",
    )

    assert payload["protocol_version"] == CLIENT_PROTOCOL_VERSION
    assert payload["runtime"] == "local"
    assert payload["api_base_url"] == "http://127.0.0.1:8766"
    assert payload["audio_status_url"].endswith("/api/audio/status")
    assert payload["audio_devices_url"].endswith("/api/audio/devices")
    assert payload["capabilities"] == ["ASR", "DIRECT_SPEECH_TRANSLATION", "TTS"]
    assert payload["app_version"] == "0.1.0"


def test_audio_status_is_conservative_until_native_service_connects():
    payload = build_desktop_audio_status(platform_name="Windows")

    assert payload["platform"] == "windows"
    assert payload["service_connected"] is False
    assert payload["capabilities"] == {
        "device_enumeration": False,
        "physical_microphone_capture": False,
        "loopback_capture": False,
        "virtual_microphone_output": False,
    }
    assert "not connected" in payload["note"]


def test_audio_status_reports_only_explicitly_confirmed_capabilities():
    payload = build_desktop_audio_status(
        service_connected=True,
        platform_name="Windows",
        device_enumeration=True,
        physical_microphone_capture=True,
        loopback_capture=False,
        virtual_microphone_output=False,
        note="enumeration and microphone capture connected",
    )

    assert payload["service_connected"] is True
    assert payload["capabilities"]["device_enumeration"] is True
    assert payload["capabilities"]["physical_microphone_capture"] is True
    assert payload["capabilities"]["loopback_capture"] is False
    assert payload["capabilities"]["virtual_microphone_output"] is False


def test_audio_devices_have_versioned_envelope():
    payload = build_audio_devices(devices=[{
        "id": "mmdevice-id",
        "name": "Microphone",
        "role": "physical_microphone",
        "is_default": True,
    }])

    assert payload["schema_version"] == 1
    assert payload["devices"][0]["id"] == "mmdevice-id"
