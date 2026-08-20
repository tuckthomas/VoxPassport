from __future__ import annotations

import json
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_voxpassport_branding_assets_are_wired_into_user_facing_surfaces():
    root = _repo_root()
    companion = root / "apps" / "desktop-companion"
    assets = companion / "assets"
    studio = (companion / "model-manager" / "studio.html").read_text(encoding="utf-8")
    manager_index = (companion / "model-manager" / "index.html").read_text(
        encoding="utf-8"
    )
    overlay = (companion / "overlay" / "index.html").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")

    for filename in (
        "VoxPassport.ico",
        "VoxPassport_icon.svg",
        "VoxPassport_icon_256.png",
        "VoxPassport_icon_512.png",
        "VoxPassport_icon_1024.png",
    ):
        assert (assets / filename).is_file()

    assert "<title>VoxPassport</title>" in studio
    assert "<title>VoxPassport</title>" in manager_index
    assert 'title="VoxPassport"' in manager_index
    assert 'class="brand-mark" src="../assets/VoxPassport_icon.svg"' in studio
    assert "<span class=\"brand-title\">VoxPassport</span>" in studio
    assert "VoxPassport Studio" not in studio + manager_index
    assert 'href="../assets/VoxPassport_icon.svg"' in manager_index
    assert "<title>VoxPassport Subtitle Overlay</title>" in overlay
    assert 'class="brand-icon" src="../assets/VoxPassport_icon.svg"' in overlay
    assert readme.index("apps/desktop-companion/assets/VoxPassport_icon_256.png") < readme.index(
        "# VoxPassport"
    )


def test_extension_has_packaged_icon_sizes():
    root = _repo_root()
    extension = root / "apps" / "browser-extension"
    manifest = json.loads((extension / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["name"].startswith("VoxPassport")
    assert manifest["action"]["default_title"] == "VoxPassport Controls"
    assert manifest["icons"] == manifest["action"]["default_icon"]
    for icon_path in manifest["icons"].values():
        assert (extension / icon_path).is_file()


def test_model_discovery_runtime_module_is_not_mixed_with_agent_plans():
    root = _repo_root()
    server = (root / "runtime" / "inference" / "server" / "main.py").read_text(
        encoding="utf-8"
    )
    pipelines_test = (root / "tests" / "integration" / "test_pipelines.py").read_text(
        encoding="utf-8"
    )

    assert not (root / "agents").exists()
    assert (root / ".agents" / "plans").is_dir()
    assert (root / "runtime" / "inference" / "model_discovery_agent.py").is_file()
    expected_import = "from runtime.inference.model_discovery_agent import ModelDiscoveryAgent"
    assert expected_import in server
    assert expected_import in pipelines_test


def test_higgs_native_artifacts_are_in_permanent_locations():
    root = _repo_root()
    adapter = (
        root / "runtime" / "inference" / "adapters" / "tts" / "higgs_native_tts_adapter.py"
    ).read_text(encoding="utf-8")
    manager_api = (
        root / "runtime" / "inference" / "server" / "model_manager_api.py"
    ).read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")

    assert not (root / "temp_higgs_test").exists()
    assert (root / "native" / "audiocpp_engine.dll").is_file()
    assert (
        root / "benchmarks" / "tts" / "results" / "higgs_q4_rtx2070_vram.csv"
    ).is_file()
    assert "temp_higgs_test" not in adapter + manager_api + readme
