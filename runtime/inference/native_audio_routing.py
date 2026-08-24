"""Persistent stable-ID routing for native desktop audio."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from runtime.inference.native_audio_bridge import NativeAudioBridge, NativeAudioBridgeError


ROUTING_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class NativeAudioRouting:
    microphone_endpoint_id: str | None = None
    loopback_endpoint_id: str | None = None
    monitor_render_endpoint_id: str | None = None
    virtual_microphone_render_endpoint_id: str | None = None
    virtual_microphone_capture_endpoint_id: str | None = None
    virtual_microphone_validated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": ROUTING_SCHEMA_VERSION,
            "microphone_endpoint_id": self.microphone_endpoint_id,
            "loopback_endpoint_id": self.loopback_endpoint_id,
            "monitor_render_endpoint_id": self.monitor_render_endpoint_id,
            "virtual_microphone_render_endpoint_id": self.virtual_microphone_render_endpoint_id,
            "virtual_microphone_capture_endpoint_id": self.virtual_microphone_capture_endpoint_id,
            "virtual_microphone_validated": self.virtual_microphone_validated,
        }


class NativeAudioRoutingStore:
    def __init__(self, path: Path, bridge: NativeAudioBridge) -> None:
        self.path = Path(path)
        self.bridge = bridge
        self._routing = self._load()

    @property
    def routing(self) -> NativeAudioRouting:
        return self._routing

    async def payload(self) -> dict[str, Any]:
        devices_payload = await self.bridge.devices_payload()
        devices = devices_payload.get("devices") or []
        role_index = {(str(item.get("id")), str(item.get("role"))) for item in devices if isinstance(item, dict)}
        routing = self._routing.to_dict()
        routing["available"] = bool(devices)
        routing["selection_status"] = {
            "microphone": self._selection_exists(
                self._routing.microphone_endpoint_id, "physical_microphone", role_index
            ),
            "loopback": self._selection_exists(
                self._routing.loopback_endpoint_id, "loopback_source", role_index
            ),
            "monitor": self._selection_exists(
                self._routing.monitor_render_endpoint_id, "render_output", role_index
            ),
            "virtual_microphone_render": self._selection_exists(
                self._routing.virtual_microphone_render_endpoint_id, "render_output", role_index
            ),
            "virtual_microphone_capture": self._selection_exists(
                self._routing.virtual_microphone_capture_endpoint_id, "physical_microphone", role_index
            ),
        }
        routing["virtual_microphone_configured"] = bool(
            routing["selection_status"]["virtual_microphone_render"]
            and routing["selection_status"]["virtual_microphone_capture"]
        )
        # Human validation is intentionally separate from endpoint existence.
        routing["virtual_microphone_ready"] = bool(
            routing["virtual_microphone_configured"] and self._routing.virtual_microphone_validated
        )
        return routing

    async def update(self, data: dict[str, Any]) -> dict[str, Any]:
        devices_payload = await self.bridge.devices_payload()
        devices = devices_payload.get("devices") or []
        role_index = {(str(item.get("id")), str(item.get("role"))) for item in devices if isinstance(item, dict)}
        if not devices:
            raise NativeAudioBridgeError("native audio devices are unavailable")

        mapping = {
            "microphone_endpoint_id": "physical_microphone",
            "loopback_endpoint_id": "loopback_source",
            "monitor_render_endpoint_id": "render_output",
            "virtual_microphone_render_endpoint_id": "render_output",
            "virtual_microphone_capture_endpoint_id": "physical_microphone",
        }
        values = self._routing.to_dict()
        values.pop("schema_version", None)
        virtual_pair_changed = False
        for field, role in mapping.items():
            if field not in data:
                continue
            raw = data.get(field)
            value = str(raw).strip() if raw not in {None, ""} else None
            if value is not None and (value, role) not in role_index:
                raise ValueError(f"{field} does not reference an available {role} endpoint")
            if field.startswith("virtual_microphone_") and value != values.get(field):
                virtual_pair_changed = True
            values[field] = value
        if virtual_pair_changed:
            values["virtual_microphone_validated"] = False
        self._routing = NativeAudioRouting(**values)
        self._save()
        return await self.payload()

    async def confirm_virtual_microphone(self, confirmed: bool) -> dict[str, Any]:
        current = await self.payload()
        if confirmed and not current["virtual_microphone_configured"]:
            raise ValueError("configure both virtual microphone endpoint sides before validation")
        self._routing = replace(self._routing, virtual_microphone_validated=bool(confirmed))
        self._save()
        return await self.payload()

    @staticmethod
    def _selection_exists(endpoint_id: str | None, role: str, index: set[tuple[str, str]]) -> bool:
        return bool(endpoint_id and (endpoint_id, role) in index)

    def _load(self) -> NativeAudioRouting:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("schema_version") != ROUTING_SCHEMA_VERSION:
                return NativeAudioRouting()
            return NativeAudioRouting(
                microphone_endpoint_id=data.get("microphone_endpoint_id"),
                loopback_endpoint_id=data.get("loopback_endpoint_id"),
                monitor_render_endpoint_id=data.get("monitor_render_endpoint_id"),
                virtual_microphone_render_endpoint_id=data.get("virtual_microphone_render_endpoint_id"),
                virtual_microphone_capture_endpoint_id=data.get("virtual_microphone_capture_endpoint_id"),
                virtual_microphone_validated=bool(data.get("virtual_microphone_validated", False)),
            )
        except Exception:
            return NativeAudioRouting()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(self._routing.to_dict(), indent=2), encoding="utf-8")
        temp.replace(self.path)
