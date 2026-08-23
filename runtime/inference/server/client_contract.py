"""Stable client-facing contracts for the VoxPassport local runtime.

This module deliberately contains no aiohttp route registration. It owns the
versioned payload shapes and origin policy so they can be tested independently
from the large local daemon and reused by future runtime/service entrypoints.
"""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlparse


CLIENT_PROTOCOL_VERSION = "voxpassport.client.v1"
AUDIO_CONTRACT_VERSION = 1
DEFAULT_API_BASE_URL = "http://127.0.0.1:8766"
DEFAULT_CAPTIONS_WS_URL = "ws://127.0.0.1:8765/ws/captions"
DEFAULT_RESOURCES_WS_URL = "ws://127.0.0.1:8766/ws/resources"

# Expo/Metro commonly chooses 8081. Expo web development can use other local
# ports, so default policy is host-based for loopback origins rather than tied
# to one development port. Non-loopback origins require an explicit env allow.
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_ALLOWED_SCHEMES = frozenset({"http", "https"})


@dataclass(frozen=True, slots=True)
class ClientOriginPolicy:
    """Restricted origin policy for the local runtime's browser/PWA API."""

    extra_origins: frozenset[str] = frozenset()

    @classmethod
    def from_environment(cls) -> "ClientOriginPolicy":
        raw = os.getenv("VOXPASSPORT_CLIENT_ORIGINS", "")
        values = frozenset(
            normalized
            for item in raw.split(",")
            if (normalized := normalize_origin(item)) is not None
        )
        return cls(extra_origins=values)

    def allows(self, origin: str | None) -> bool:
        if not origin:
            return False
        normalized = normalize_origin(origin)
        if normalized is None:
            return False
        parsed = urlparse(normalized)
        if parsed.hostname in _LOOPBACK_HOSTS:
            return True
        return normalized in self.extra_origins


def normalize_origin(value: str | None) -> str | None:
    """Return a canonical origin, rejecting paths, credentials and unsafe schemes."""

    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
    except ValueError:
        return None
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        return None
    if not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    host = parsed.hostname.lower()
    host_text = f"[{host}]" if ":" in host else host
    authority = host_text if port is None else f"{host_text}:{port}"
    return f"{parsed.scheme.lower()}://{authority}"


def build_client_bootstrap(
    *,
    capabilities: Iterable[str],
    api_base_url: str = DEFAULT_API_BASE_URL,
    captions_websocket_url: str = DEFAULT_CAPTIONS_WS_URL,
    resources_websocket_url: str = DEFAULT_RESOURCES_WS_URL,
    app_version: str | None = None,
) -> dict:
    """Build the stable bootstrap document consumed by the Expo client."""

    base = api_base_url.rstrip("/")
    payload = {
        "protocol_version": CLIENT_PROTOCOL_VERSION,
        "runtime": "local",
        "api_base_url": base,
        "captions_websocket_url": captions_websocket_url,
        "resources_websocket_url": resources_websocket_url,
        "capabilities": sorted({str(value) for value in capabilities if str(value).strip()}),
        "audio_status_url": f"{base}/api/audio/status",
        "audio_devices_url": f"{base}/api/audio/devices",
        "translation_strategies_url": f"{base}/api/translation/strategies",
    }
    if app_version:
        payload["app_version"] = str(app_version)
    return payload


def build_desktop_audio_status(
    *,
    service_connected: bool = False,
    platform_name: str | None = None,
    device_enumeration: bool = False,
    physical_microphone_capture: bool = False,
    loopback_capture: bool = False,
    virtual_microphone_output: bool = False,
    note: str | None = None,
) -> dict:
    """Build conservative native-audio status.

    No capability becomes true merely because a Rust implementation exists in
    source. The runtime/service integration must explicitly report it.
    """

    platform_value = str(platform_name or platform.system() or "unknown").lower()
    if note is None and not service_connected:
        note = "native desktop audio service is not connected"
    return {
        "schema_version": AUDIO_CONTRACT_VERSION,
        "transport": "runtime_native_service",
        "platform": platform_value,
        "service_connected": bool(service_connected),
        "capabilities": {
            "device_enumeration": bool(device_enumeration),
            "physical_microphone_capture": bool(physical_microphone_capture),
            "loopback_capture": bool(loopback_capture),
            "virtual_microphone_output": bool(virtual_microphone_output),
        },
        "note": note or "",
    }


def build_audio_devices(*, devices: Iterable[dict] = ()) -> dict:
    """Return the versioned device-list envelope expected by the Expo client."""

    return {
        "schema_version": AUDIO_CONTRACT_VERSION,
        "devices": [dict(device) for device in devices],
    }
