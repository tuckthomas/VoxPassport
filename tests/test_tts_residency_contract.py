from __future__ import annotations

import json
from pathlib import Path

from runtime.inference.tts_plugins.manifest import TtsManifestCatalog


REPO_ROOT = Path(__file__).resolve().parents[1]
PROXY_MODELS = {
    "higgs-tts-3": "VOXPASSPORT_HIGGS_TTS_COMMAND",
    "moss-tts-1.5": "VOXPASSPORT_MOSS_TTS_COMMAND",
    "voxcpm-2": "VOXPASSPORT_VOXCPM_TTS_COMMAND",
}


def test_production_proxy_manifests_require_supervisor_owned_local_backends():
    catalog = TtsManifestCatalog(REPO_ROOT / "runtime" / "tts_manifests").load()
    for model_id, command_env in PROXY_MODELS.items():
        manifest = catalog.resolve(model_id)
        options = manifest.driver_options
        assert "backend_url" not in options
        assert options["backend_process"]["command_env"] == command_env
        assert options["backend_url_env"].endswith("_TTS_URL")
        serialized = json.dumps(manifest.raw)
        for legacy_port in ("8095", "8096", "8097"):
            assert legacy_port not in serialized


def test_supervisor_has_no_fixed_proxy_ports_or_model_name_dispatch():
    source = (
        REPO_ROOT / "runtime" / "inference" / "tts_plugins" / "runtime_supervisor.py"
    ).read_text(encoding="utf-8").lower()
    for legacy_port in ("8095", "8096", "8097", "8098", "8099"):
        assert legacy_port not in source
    for model_name in ("omnivoice", "higgs", "moss", "voxcpm", "xtts"):
        assert model_name not in source
    assert "backend_process" in source
    assert "driver_options_override" in source
    assert "unmanaged local backend" in source


def test_resource_monitor_marks_worker_and_backend_failures_broken():
    source = (
        REPO_ROOT / "apps" / "desktop-companion" / "model-manager" / "resource-monitor.js"
    ).read_text(encoding="utf-8")
    assert "profile.unexpected_exit" in source
    assert "runtime.backends" in source
    assert "backend.unexpected_exit" in source
    assert "activeBackend.state === 'broken'" in source
