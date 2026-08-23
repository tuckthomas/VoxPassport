import asyncio
import json
from pathlib import Path

import pytest

from runtime.inference.adapters.tts.manifest_tts_adapter import ManifestTtsAdapter
from runtime.inference.tts_plugins.manifest import (
    TtsManifest,
    TtsManifestCatalog,
    TtsManifestError,
)
from runtime.workers.tts_host.driver_loader import load_driver_class
from runtime.workers.tts_host.protocol import TtsDriver, TtsDriverRequest
from runtime.workers.tts_host.server import TtsDriverController


class FakeDriver(TtsDriver):
    def __init__(self, manifest):
        super().__init__(manifest)
        self.loaded = False

    def load(self) -> None:
        self.loaded = True

    def unload(self) -> None:
        self.loaded = False

    def synthesize_pcm(self, request: TtsDriverRequest):
        assert self.loaded
        assert request.text
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


def _fake_manifest_dict(entrypoint: str) -> dict:
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


def test_builtin_manifest_catalog_resolves_proof_models_and_aliases():
    catalog = TtsManifestCatalog(_manifest_dir()).load()
    assert catalog.resolve("xtts-v2-romanian-v2").model_id == "xtts-v2-romanian-v2"
    assert catalog.resolve("xtts-ro-v2").model_id == "xtts-v2-romanian-v2"
    assert catalog.resolve("moss").model_id == "moss-tts-1.5"
    assert catalog.resolve("openbmb/VoxCPM2").model_id == "voxcpm-2"


def test_proof_models_use_one_worker_protocol_and_generic_adapter():
    catalog = TtsManifestCatalog(_manifest_dir()).load()
    adapters = [
        ManifestTtsAdapter(catalog.resolve(model_id), catalog=catalog)
        for model_id in ("xtts-v2-romanian-v2", "moss-tts-1.5", "voxcpm-2")
    ]
    assert {type(adapter) for adapter in adapters} == {ManifestTtsAdapter}
    assert {adapter.manifest.worker_base_url for adapter in adapters} == {"http://127.0.0.1:8098"}


def test_voxcpm_language_restriction_is_data_not_adapter_code():
    manifest = TtsManifestCatalog(_manifest_dir()).load().resolve("voxcpm-2")
    assert "en" in manifest.languages
    assert "ro" not in manifest.languages


def test_openai_compatible_models_share_the_same_driver_class():
    catalog = TtsManifestCatalog(_manifest_dir()).load()
    moss = catalog.resolve("moss-tts-1.5")
    voxcpm = catalog.resolve("voxcpm-2")
    assert moss.driver_entrypoint == voxcpm.driver_entrypoint
    assert load_driver_class(moss.driver_entrypoint) is load_driver_class(voxcpm.driver_entrypoint)


def test_xtts_driver_import_is_lazy_and_does_not_import_coqui_during_discovery():
    manifest = TtsManifestCatalog(_manifest_dir()).load().resolve("xtts-v2-romanian-v2")
    driver_class = load_driver_class(manifest.driver_entrypoint)
    assert driver_class.__name__ == "XttsRomanianDriver"


def test_synthetic_new_manifest_routes_without_daemon_model_branch(tmp_path: Path):
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    path = manifest_dir / "future.json"
    path.write_text(json.dumps(_fake_manifest_dict(f"{__name__}:FakeDriver")), encoding="utf-8")
    catalog = TtsManifestCatalog(manifest_dir).load()
    manifest = catalog.resolve("future")
    adapter = ManifestTtsAdapter(manifest, profiles_root=tmp_path, catalog=catalog)
    assert adapter.manifest.model_id == "future-tts"
    daemon_source = (
        _repo_root() / "runtime" / "inference" / "server" / "tts_plugin_main.py"
    ).read_text(encoding="utf-8").lower()
    assert "future-tts" not in daemon_source
    assert "moss-tts" not in daemon_source
    assert "voxcpm" not in daemon_source
    assert "xtts-v2" not in daemon_source


def test_manifest_validation_rejects_missing_driver(tmp_path: Path):
    raw = _fake_manifest_dict(f"{__name__}:FakeDriver")
    raw.pop("driver")
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(TtsManifestError):
        TtsManifest.load(path)


def test_generic_controller_load_stream_wav_capabilities_and_unload(tmp_path: Path):
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    (manifest_dir / "future.json").write_text(
        json.dumps(_fake_manifest_dict(f"{__name__}:FakeDriver")),
        encoding="utf-8",
    )
    controller = TtsDriverController(TtsManifestCatalog(manifest_dir).load())

    async def exercise():
        capabilities = await controller.load("future")
        assert capabilities["protocol"] == "voxpassport.tts.v1"
        assert capabilities["voice_cloning"] is True
        request = TtsDriverRequest(text="Salut", language="ro")
        chunks = list(controller.pcm_iterator("future-tts", request))
        assert chunks and all(len(chunk) % 2 == 0 for chunk in chunks)
        wav = controller.wav_bytes("future-tts", request)
        assert wav[:4] == b"RIFF"
        assert controller.metrics()["fake"] is True
        await controller.unload("future-tts")
        assert controller.loaded_model_id is None

    asyncio.run(exercise())


def test_compatibility_adapter_names_are_thin_generic_subclasses():
    from runtime.inference.adapters.tts.moss_tts_adapter import MossTtsAdapter
    from runtime.inference.adapters.tts.voxcpm_tts_adapter import VoxCpmTtsAdapter
    from runtime.inference.adapters.tts.xtts_romanian_tts_adapter import XttsRomanianTtsAdapter

    assert issubclass(MossTtsAdapter, ManifestTtsAdapter)
    assert issubclass(VoxCpmTtsAdapter, ManifestTtsAdapter)
    assert issubclass(XttsRomanianTtsAdapter, ManifestTtsAdapter)
