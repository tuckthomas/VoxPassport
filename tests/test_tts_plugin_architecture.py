from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from runtime.inference.adapters.tts.manifest_tts_adapter import ManifestTtsAdapter
from runtime.inference.tts_plugins.controller import TtsPluginController
from runtime.inference.tts_plugins.driver_loader import load_driver_class
from runtime.inference.tts_plugins.manifest import TtsManifestCatalog, TtsManifestError
from runtime.inference.tts_plugins.runtime_profiles import RuntimeProfileCatalog
from runtime.workers.tts_host.protocol import SpeechRequest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _manifest_payload(model_id: str, profile: str = "core") -> dict:
    return {
        "schema_version": 3,
        "model_id": model_id,
        "display_name": model_id,
        "aliases": [],
        "runtime_profile": profile,
        "driver": {
            "entrypoint": "tests.fake_tts_driver:FakeTtsDriver",
            "options": {},
        },
        "capabilities": {
            "languages": ["en", "ro"],
            "streaming": True,
            "voice_cloning": True,
            "cross_lingual_voice_cloning": True,
        },
        "audio": {"sample_rate_hz": 24000, "sample_format": "pcm_s16le"},
    }


def test_all_local_tts_models_are_manifests():
    catalog = TtsManifestCatalog().load()
    ids = {manifest.model_id for manifest in catalog.manifests()}
    assert {
        "omnivoice-stock",
        "higgs-tts-3",
        "higgs-tts-3-q4_k_m",
        "moss-tts-1.5",
        "voxcpm-2",
        "xtts-v2-romanian-v2",
    }.issubset(ids)


def test_backend_runtime_catalog_is_reusable_and_separate_from_models():
    from runtime.inference.tts_plugins.backend_runtime import BackendRuntimeCatalog

    catalog = BackendRuntimeCatalog().load()
    ids = {runtime.runtime_id for runtime in catalog.runtimes()}
    assert {"higgs-openai-server", "moss-openai-server", "voxcpm-openai-server"}.issubset(ids)


def test_direct_worker_models_do_not_invent_backend_runtimes():
    catalog = TtsManifestCatalog().load()
    assert catalog.resolve("omnivoice-stock").backend_runtime is None
    assert catalog.resolve("higgs-tts-3-q4_k_m").backend_runtime is None
    assert catalog.resolve("xtts-v2-romanian-v2").backend_runtime is None


def test_manifest_catalog_resolves_models_aliases_and_runtime_profiles():
    catalog = TtsManifestCatalog().load()
    assert catalog.resolve("omnivoice").model_id == "omnivoice-stock"
    assert catalog.resolve("xtts-romanian").model_id == "xtts-v2-romanian-v2"
    assert catalog.resolve("higgs-q4").runtime_profile == "core"
    assert catalog.resolve("xtts-romanian").runtime_profile == "coqui-xtts"


def test_runtime_profile_catalog_groups_dependency_families():
    profiles = RuntimeProfileCatalog().load()
    assert profiles.resolve("core").profile_id == "core"
    assert profiles.resolve("coqui-xtts").profile_id == "coqui-xtts"


def test_every_local_tts_model_uses_one_main_process_adapter():
    catalog = TtsManifestCatalog().load()
    for manifest in catalog.manifests():
        adapter = ManifestTtsAdapter(manifest, profiles_root=Path("data/voice_profiles"), catalog=catalog)
        assert adapter.model_id == manifest.model_id


def test_voxcpm_language_restriction_is_manifest_data():
    manifest = TtsManifestCatalog().load().resolve("voxcpm-2")
    assert manifest.languages == ("en", "zh")


def test_openai_compatible_models_share_reusable_proxy_driver():
    catalog = TtsManifestCatalog().load()
    entrypoints = {
        catalog.resolve("higgs-tts-3").driver_entrypoint,
        catalog.resolve("moss-tts-1.5").driver_entrypoint,
        catalog.resolve("voxcpm-2").driver_entrypoint,
    }
    assert entrypoints == {"runtime.workers.tts_host.drivers.openai_speech_proxy:OpenAiSpeechProxyDriver"}


def test_model_library_drivers_import_without_loading_heavy_libraries():
    catalog = TtsManifestCatalog().load()
    for manifest in catalog.manifests():
        cls = load_driver_class(manifest.driver_entrypoint)
        assert cls is not None


def test_main_daemon_has_no_local_tts_model_dispatch_or_concrete_adapters():
    source = (_repo_root() / "runtime" / "inference" / "server" / "main.py").read_text(encoding="utf-8")
    assert "HiggsNativeTtsAdapter" not in source
    assert "OmniVoiceTtsAdapter" not in source
    assert "XttsRomanianTtsAdapter" not in source
    assert "if model_id ==" not in source


def test_orchestrator_tts_hot_swap_is_manifest_only():
    source = (_repo_root() / "runtime" / "inference" / "pipeline" / "duplex_orchestrator.py").read_text(encoding="utf-8")
    assert "TtsManifestCatalog" in source
    assert "ManifestTtsAdapter" in source
    assert "higgs" not in source.lower()
    assert "omnivoice" not in source.lower()
    assert "xtts" not in source.lower()


def test_runtime_supervisor_owns_dynamic_ports_and_has_no_model_name_dispatch():
    source = (_repo_root() / "runtime" / "inference" / "tts_plugins" / "runtime_supervisor.py").read_text(encoding="utf-8")
    assert "_free_port" in source
    assert "backend_runtime" in source
    for name in ("higgs", "moss", "voxcpm", "omnivoice", "xtts"):
        assert f'== "{name}' not in source.lower()


def test_unused_runtime_profiles_do_not_spawn_workers():
    source = (_repo_root() / "runtime" / "inference" / "tts_plugins" / "runtime_supervisor.py").read_text(encoding="utf-8")
    assert "create_subprocess_exec" in source
    assert "for profile in" not in source[source.index("async def start"):source.index("async def shutdown")] if "async def start" in source else True


def test_obsolete_concrete_tts_adapter_files_are_removed():
    root = _repo_root() / "runtime" / "inference" / "adapters" / "tts"
    obsolete = {
        "omnivoice_tts_adapter.py",
        "higgs_tts_adapter.py",
        "higgs_native_tts_adapter.py",
        "moss_tts_adapter.py",
        "voxcpm_tts_adapter.py",
        "xtts_romanian_tts_adapter.py",
    }
    assert not any((root / name).exists() for name in obsolete)


def test_synthetic_new_manifest_routes_without_daemon_model_branch(tmp_path: Path):
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    (manifest_dir / "future.json").write_text(json.dumps(_manifest_payload("future-tts")), encoding="utf-8")
    catalog = TtsManifestCatalog(manifest_dir, validate_backend_runtimes=False).load()
    manifest = catalog.resolve("future-tts")
    assert manifest.model_id == "future-tts"
    assert "future-tts" not in (_repo_root() / "runtime" / "inference" / "server" / "main.py").read_text(encoding="utf-8")


def test_manifest_validation_rejects_missing_driver_worker_and_backend_topology(tmp_path: Path):
    bad = _manifest_payload("bad")
    bad.pop("driver")
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(TtsManifestError):
        TtsManifestCatalog(tmp_path, validate_backend_runtimes=False).load()

    old_worker = _manifest_payload("old-worker")
    old_worker["worker"] = {"command": ["python", "worker.py"]}
    path = tmp_path / "old-worker.json"
    path.write_text(json.dumps(old_worker), encoding="utf-8")
    with pytest.raises(TtsManifestError):
        TtsManifestCatalog(tmp_path, validate_backend_runtimes=False).load()

    old_backend = _manifest_payload("old-backend")
    old_backend["driver"]["options"]["backend_url_env"] = "OLD_URL"
    path = tmp_path / "old-backend.json"
    path.write_text(json.dumps(old_backend), encoding="utf-8")
    with pytest.raises(TtsManifestError):
        TtsManifestCatalog(tmp_path, validate_backend_runtimes=False).load()


def test_generic_controller_load_stream_wav_capabilities_clone_reference_and_unload(tmp_path: Path, monkeypatch):
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    (manifest_dir / "future.json").write_text(json.dumps(_manifest_payload("future-tts")), encoding="utf-8")
    catalog = TtsManifestCatalog(manifest_dir, validate_backend_runtimes=False).load()

    created_drivers = []

    class FakeDriver:
        def __init__(self, *args, **kwargs):
            self.last_request = None
            created_drivers.append(self)
        def load(self, *args, **kwargs): pass
        def unload(self): pass
        def capabilities(self): return {"fake": True}
        def metrics(self): return {"fake": True}
        def synthesize(self, request):
            self.last_request = request
            return [b"\x00\x00" * 100]

    monkeypatch.setattr("runtime.inference.tts_plugins.controller.load_driver_class", lambda _: FakeDriver)
    controller = TtsPluginController(catalog=catalog)

    async def exercise():
        await controller.load("future-tts")
        assert controller.loaded_model_id == "future-tts"
        assert controller.capabilities()["fake"] is True
        reference = tmp_path / "reference.wav"
        reference.write_bytes(b"RIFF")
        target_conditioning = tmp_path / "target.wav"
        target_conditioning.write_bytes(b"RIFF")
        request = SpeechRequest(
            text="Salut",
            language="ro",
            reference_audio=reference,
            reference_text="Reference transcript",
            target_conditioning_audio=target_conditioning,
        )
        chunks = list(controller.pcm_iterator("future-tts", request))
        assert chunks and all(len(chunk) % 2 == 0 for chunk in chunks)
        active_driver = created_drivers[-1]
        assert active_driver.last_request is not None
        assert active_driver.last_request.reference_audio == reference
        assert active_driver.last_request.reference_text == "Reference transcript"
        assert active_driver.last_request.target_conditioning_audio == target_conditioning
        wav = controller.wav_bytes("future-tts", request)
        assert wav[:4] == b"RIFF"
        assert controller.metrics()["fake"] is True
        await controller.unload("future-tts")
        assert controller.loaded_model_id is None

    asyncio.run(exercise())


def test_run_script_starts_only_daemon_and_supervisor_starts_tts_on_demand():
    run_script = (_repo_root() / "run.bat").read_text(encoding="utf-8")
    assert "runtime.inference.server.integrated_main" in run_script
    assert "tts_host\\server.py" not in run_script
    assert "8098" not in run_script
    assert "8099" not in run_script
    assert "runtime-profile supervisor" in run_script
    assert not (_repo_root() / "install_xtts_worker.bat").exists()
    assert (_repo_root() / "scripts" / "manage_runtime_profile.py").exists()
