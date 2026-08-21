from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.inference.server.resource_monitor import ResourceSnapshotCollector


GIB = 1024**3


class FakePsutil:
    def __init__(self) -> None:
        self.cpu_calls = 0

    def cpu_percent(self, interval=None):
        self.cpu_calls += 1
        return 0.0 if self.cpu_calls == 1 else 37.5

    @staticmethod
    def cpu_count(logical=True):
        return 16 if logical else 8

    @staticmethod
    def virtual_memory():
        return SimpleNamespace(
            total=32 * GIB,
            available=12 * GIB,
            percent=62.5,
        )


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_resource_snapshot_reports_system_and_nvidia_metrics():
    def fake_run(command, **kwargs):
        assert command[0] == "nvidia-smi"
        assert "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu" in command
        assert kwargs["timeout"] == 1.5
        return SimpleNamespace(
            stdout="NVIDIA GeForce RTX 2070, 32, 6280, 8192, 62\n"
        )

    collector = ResourceSnapshotCollector(
        psutil_module=FakePsutil(),
        command_runner=fake_run,
        nvidia_smi_path="nvidia-smi",
    )

    snapshot = collector.snapshot()

    assert snapshot["cpu"] == {"usage_percent": 37.5, "logical_cores": 16}
    assert snapshot["memory"] == {
        "used_gb": 20.0,
        "total_gb": 32.0,
        "usage_percent": 62.5,
    }
    assert snapshot["gpu"]["available"] is True
    assert snapshot["gpu"]["name"] == "NVIDIA GeForce RTX 2070"
    assert snapshot["gpu"]["usage_percent"] == 32.0
    assert snapshot["gpu"]["memory_used_gb"] == pytest.approx(6.13)
    assert snapshot["gpu"]["memory_total_gb"] == 8.0
    assert snapshot["gpu"]["memory_percent"] == pytest.approx(76.7)
    assert snapshot["gpu"]["temperature_c"] == 62.0


def test_resource_monitor_is_a_standalone_collapsible_component():
    root = _repo_root()
    manager = root / "apps" / "desktop-companion" / "model-manager"
    script = (manager / "resource-monitor.js").read_text(encoding="utf-8")
    styles = (manager / "resource-monitor.css").read_text(encoding="utf-8")
    studio = (manager / "studio.html").read_text(encoding="utf-8")
    server = (root / "runtime" / "inference" / "server" / "main.py").read_text(
        encoding="utf-8"
    )

    assert "class ResourceMonitor" in script
    assert "POLL_INTERVAL_MS = 2000" in script
    assert "/ws/resources" in script
    assert "new WebSocket" in script
    assert "Resource monitor disabled" in script
    assert "voxpassport.resourceMonitor.collapsed" in script
    assert "voxpassport.resourceMonitor.enabled" in script
    assert "voxpassport.resourceMonitor.compactVramMode" in script
    assert "voxpassport.resourceMonitor.compactRamMode" in script
    assert "toggleCompactMode('vram')" in script
    assert "toggleCompactMode('ram')" in script
    assert "data-resource-power" in script
    assert 'data-tooltip="Disable resource monitor"' in script
    assert "data-resource-collapse" in script
    assert "data-resource-expand" in script
    assert "data-resource-compact-vram-toggle" in script
    assert "data-resource-compact-ram-toggle" in script
    assert "data-resource-compact-gpu" in script
    assert "data-resource-compact-vram" in script
    assert "data-resource-compact-cpu" in script
    assert "data-resource-compact-ram" in script
    assert "data-resource-compact-hint" not in script
    assert "Live · 2s refresh" not in script
    assert "GPU_TEMP_WARNING_C = 70" in script
    assert "GPU_TEMP_CRITICAL_C = 85" in script
    assert '.resource-monitor[data-enabled="true"] .resource-monitor__power-button' in styles
    assert ".resource-monitor__power-button:hover" in styles
    assert '.resource-monitor__temperature[data-level="warning"]' in styles
    assert '.resource-monitor__temperature[data-level="critical"]' in styles
    assert '.resource-monitor[data-collapsed="true"]' in styles
    assert 'href="./resource-monitor.css?v=1.5"' in studio
    assert 'src="./resource-monitor.js?v=1.5"' in studio
    assert 'app.router.add_get("/api/resources", api_resources)' in server
    assert 'app.router.add_get("/ws/resources", ws_resources)' in server
    assert 'app.router.add_static("/assets", path=str(assets_dir), show_index=False)' in server
