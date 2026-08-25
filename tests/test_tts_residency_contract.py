from __future__ import annotations

import json
from pathlib import Path

from runtime.inference.tts_plugins.backend_runtime import BackendRuntimeCatalog
from runtime.inference.tts_plugins.manifest import TtsManifestCatalog


REPO_ROOT = Path(__file__).resolve().parents[1]
PROXY_MODELS = {
    "higgs-tts-3": "higgs-openai-server",
    "moss-tts-1.5": "moss-openai-server",
    "voxcpm-2": "voxcpm-openai-server",
}


def test_production_proxy_manifests_reference_reusable_backend_runtimes():
    runtime_catalog = BackendRuntimeCatalog(REPO_ROOT / "runtime" / "tts_backend_runtimes").load()
    catalog = TtsManifestCatalog(
        REPO_ROOT / "runtime" / "tts_manifests",
        backend_runtime_catalog=runtime_catalog,
    ).load()
    for model_id, runtime_id in PROXY_MODELS.items():
        manifest = catalog.resolve(model_id)
        assert manifest.backend_runtime == runtime_id
        assert manifest.backend_args.get("checkpoint")
        options = manifest.driver_options
        assert "backend_url" not in options
        assert "backend_url_env" not in options
        assert "backend_process" not in options
        runtime = runtime_catalog.resolve(runtime_id)
        assert runtime.command_env.startswith("VOXPASSPORT_TTS_BACKEND_")
        assert runtime.remote_url_env.startswith("VOXPASSPORT_TTS_BACKEND_")
        serialized = json.dumps(manifest.raw)
        assert "_TTS_COMMAND" not in serialized
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
    assert "backendruntimecatalog" in source.replace("_", "")
    assert "backend_runtime_catalog.resolve" in source
    assert "driver_options_override" in source
    assert "unmanaged local" in source
    assert "backend_process" not in source


def test_runtime_diagnostics_replace_deleted_resource_monitor_ui():
    main = (REPO_ROOT / "runtime" / "inference" / "server" / "main.py").read_text(encoding="utf-8")
    runtime_screen = (
        REPO_ROOT / "apps" / "client" / "src" / "features" / "runtime" / "RuntimeScreen.tsx"
    ).read_text(encoding="utf-8")
    assert "resource_snapshot" in main or "runtime_resources" in main or "_resource" in main
    assert "model_residency" in runtime_screen
    assert "Models loaded" in runtime_screen
    assert "Active model slots" in runtime_screen
    assert not (
        REPO_ROOT / "apps" / "desktop-companion" / "model-manager" / "resource-monitor.js"
    ).exists()
