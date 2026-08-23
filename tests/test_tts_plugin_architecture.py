import asyncio
import json
from pathlib import Path

import pytest

from runtime.inference.adapters.tts.manifest_tts_adapter import ManifestTtsAdapter
from runtime.inference.model_registry.catalog import get_builtin_catalog
from runtime.inference.protocol import ModelCapability
from runtime.inference.tts_plugins.manifest import (
    TtsManifest,
    TtsManifestCatalog,
    TtsManifestError,
)
from runtime.workers.tts_host import server as tts_host_server
from runtime.workers.tts_host.driver_loader import load_driver_class
from runtime.workers.tts_host.protocol import TtsDriver, TtsDriverRequest

PROXY_ENTRYPOINT = "runtime.workers.tts_host.drivers.openai_proxy:OpenAiSpeechProxyDriver"
LOCAL_TTS_MODELS = {
    "omnivoice-stock",
    "higgs-tts-3",
    "higgs-tts-3-q4_k_m",
    "moss-tts-1.5",
    "voxcpm-2",
    "xtts-v2-romanian-v2",
}


class FakeDriver(TtsDriver):
    def __init__(self, manifest):
        super().__init__(manifest)
        self.loaded = False
        self.last_request = None

    def load(self) -> None:
        self.loaded = True

    def unload(self) -> None:
        self.loaded = False

    def synthesize_pcm(self, request: TtsDriverRequest):
        assert self.loaded
        assert request.text
        self.last_request = request
        yield b"\x00\x00" * 240
        yield b"\x01\x00" * 240

    def health_check(self) -> bool:
        return self.loaded

    def metrics(self) -> dict:
        return {"fake": True, "loaded": self.loaded}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _manifest_dir() -> Path:
    return _repo_root() / "runtime" / "tts_manifests"


def _fake_manifest_dict(entrypoint: str = PROXY_ENTRYPOINT) -> dict:
    return {
        "schema_version": 1,
        "model_id": "future-tts",
        "display_name": "Future TTS",
        "aliases": ["future"],
        "driver": {"entrypoint": entrypoint, "options": {}},
        "worker": {"base_url": "http://127.0.0.1:8098"},
        "capabilities": {
            "languages": ["en", "ro"],
            "streaming": True,
            "voice_cloning": True,
            "cross_lingual_voice_cloning": True,
        },
        "voice_cloning": {"reference_transcript_required": False},
        "audio": {"sample_rate_hz": 24000, "sample_format": "pcm_s16le"},
        "registry": {"provider": "test"},
    }


def test_all_local_tts_models_are_manifests():
    catalog = TtsManifestCatalog(_manifest_dir()).load()
    assert {manifest.model_id for manifest in catalog.manifests()} == LOCAL_TTS_MODELS
    assert all(entry.capability != ModelCapability.TTS for entry in get_builtin_catalog())


def test_manifest_catalog_resolves_models_and_aliases():
    catalog = TtsManifestCatalog(_manifest_dir()).load()
    assert catalog.resolve("omnivoice").model_id == "omnivoice-stock"
    assert catalog.resolve("higgs-native").model_id == "higgs-tts-3-q4_k_m"
    assert catalog.resolve("higgs").model_id == "higgs-tts-3"
    assert catalog.resolve("xtts-ro-v2").model_id == "xtts-v2-romanian-v2"
    assert catalog.resolve("moss").model_id == "moss-tts-1.5"
    assert catalog.resolve("openbmb/VoxCPM2").model_id == "voxcpm-2"


def test_every_local_tts_model_uses_one_main_process_adapter():
    catalog = TtsManifestCatalog(_manifest_dir()).load()
    adapters = [
        ManifestTtsAdapter(manifest, catalog=catalog)
        for manifest in catalog.manifests()
    ]
    assert {type(adapter) for adapter in adapters} == {ManifestTtsAdapter}
    endpoints = {adapter.manifest.worker_base_url for adapter in adapters}
    assert endpoints == {"http://127.0.0.1:8098", "http://127.0.0.1:8099"}


def test_voxcpm_language_restriction_is_manifest_data():
    manifest = TtsManifestCatalog(_manifest_dir()).load().resolve("voxcpm-2")
    assert "en" in manifest.languages
    assert "ro" not in manifest.languages


def test_openai_compatible_models_share_reusable_proxy_driver():
    catalog = TtsManifestCatalog(_manifest_dir()).load()
    models = [catalog.resolve(model_id) for model_id in ("moss-tts-1.5", "voxcpm-2", "higgs-tts-3")]
    assert {model.driver_entrypoint for model in models} == {PROXY_ENTRYPOINT}
    assert len({load_driver_class(model.driver_entrypoint) for model in models}) == 1


def test_model_library_drivers_import_without_loading_heavy_libraries():
    catalog = TtsManifestCatalog(_manifest_dir()).load()
    expected = {
        "xtts-v2-romanian-v2": "XttsRomanianDriver",
        "omnivoice-stock": "OmniVoiceDriver",
        "higgs-tts-3-q4_k_m": "HiggsNativeDriver",
    }
    for model_id, class_name in expected.items():
        assert load_driver_class(catalog.resolve(model_id).driver_entrypoint).__name__ == class_name


def test_main_daemon_has_no_local_tts_model_dispatch_or_concrete_adapters():
    source = (
        _repo_root() / "runtime" / "inference" / "server" / "main.py"
    ).read_text(encoding="utf-8")
    lowered = source.lower()
    assert "ManifestTtsAdapter" in source
    assert "TtsManifestCatalog" in source
    for legacy_class in (
        "OmniVoiceTtsAdapter", "HiggsTtsAdapter", "HiggsNativeTtsAdapter",
        "MossTtsAdapter", "VoxCpmTtsAdapter", "XttsRomanianTtsAdapter",
    ):
        assert legacy_class not in source
    assert "if any(k in model" not in source
    assert "selected_model != \"omnivoice\"" not in source
    assert "reference_transcript_required" not in lowered  # server reads manifest.transcript_required instead
    assert "manifest.transcript_required" in source


def test_orchestrator_tts_hot_swap_is_manifest_only():
    source = (
        _repo_root() / "runtime" / "inference" / "pipeline" / "duplex_orchestrator.py"
    ).read_text(encoding="utf-8")
    assert "ManifestTtsAdapter" in source
    assert "TtsManifestCatalog" in source
    for old_module in (
        "higgs_native_tts_adapter", "higgs_tts_adapter", "moss_tts_adapter",
        "voxcpm_tts_adapter", "omnivoice_tts_adapter",
    ):
        assert old_module not in source
    assert "await previous.unload()" in source


def test_obsolete_concrete_tts_adapter_files_are_removed():
    tts_dir = _repo_root() / "runtime" / "inference" / "adapters" / "tts"
    assert {path.name for path in tts_dir.glob("*_tts_adapter.py")} == {"manifest_tts_adapter.py"}
    assert not (_repo_root() / "runtime" / "inference" / "server" / "tts_plugin_main.py").exists()
    assert not (_repo_root() / "runtime" / "inference" / "server" / "xtts_main.py").exists()
    assert not (_repo_root() / "runtime" / "workers" / "xtts_romanian" / "server.py").exists()


def test_synthetic_new_manifest_routes_without_daemon_model_branch(tmp_path: Path):
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    path = manifest_dir / "future.json"
    path.write_text(json.dumps(_fake_manifest_dict()), encoding="utf-8")
    catalog = TtsManifestCatalog(manifest_dir).load()
    manifest = catalog.resolve("future")
    adapter = ManifestTtsAdapter(manifest, profiles_root=tmp_path, catalog=catalog)
    assert adapter.manifest.model_id == "future-tts"
    daemon_source = (
        _repo_root() / "runtime" / "inference" / "server" / "main.py"
    ).read_text(encoding="utf-8").lower()
    assert "future-tts" not in daemon_source


def test_manifest_validation_rejects_missing_driver(tmp_path: Path):
    raw = _fake_manifest_dict()
    raw.pop("driver")
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(TtsManifestError):
        TtsManifest.load(path)


def test_generic_controller_load_stream_wav_capabilities_clone_reference_and_unload(tmp_path: Path, monkeypatch):
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    (manifest_dir / "future.json").write_text(
        json.dumps(_fake_manifest_dict()),
        encoding="utf-8",
    )
    created_drivers = []

    def create_fake_driver(manifest):
        driver = FakeDriver(manifest)
        created_drivers.append(driver)
        return driver

    monkeypatch.setattr(tts_host_server, "create_driver", create_fake_driver)
    controller = tts_host_server.TtsDriverController(TtsManifestCatalog(manifest_dir).load())
    reference = tmp_path / "reference.wav"
    target_conditioning = tmp_path / "conditioning-ro.wav"
    reference.write_bytes(b"RIFFfake-reference")
    target_conditioning.write_bytes(b"RIFFfake-conditioning")

    async def exercise():
        capabilities = await controller.load("future")
        assert capabilities["protocol"] == "voxpassport.tts.v1"
        assert capabilities["voice_cloning"] is True
        request = TtsDriverRequest(
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


def test_run_script_uses_generic_hosts_and_single_daemon():
    run_script = (_repo_root() / "run.bat").read_text(encoding="utf-8")
    assert "tts_host\\server.py --port 8098" in run_script
    assert "tts_host\\server.py --port 8099" in run_script
    assert "inference\\server\\main.py" in run_script
    assert "tts_plugin_main.py" not in run_script
    assert "xtts_main.py" not in run_script
