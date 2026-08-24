from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "drivers" / "windows" / "virtual-audio"
PINNED_COMMIT = "717778a20ba4dd2440fe609f69153a1f8a64f597"


def read(relative: str) -> str:
    return (DRIVER / relative).read_text(encoding="utf-8")


def test_virtual_driver_upstream_is_pinned_and_not_floating():
    data = json.loads(read("upstream.json"))
    assert data["repository"] == "microsoft/Windows-driver-samples"
    assert data["commit"] == PINNED_COMMIT
    assert data["sample_path"] == "audio/simpleaudiosample"
    assert data["license"] == "MS-PL"
    assert data["hardware_id"] == r"ROOT\VoxPassportVirtualAudio"
    assert data["render_endpoint_name"] == "VoxPassport Translation Sink"
    assert data["capture_endpoint_name"] == "VoxPassport Virtual Microphone"


def test_prepare_script_is_guarded_and_rebuilds_from_pristine_source():
    script = read("prepare.ps1")
    assert "function Replace-Exact" in script
    assert "expected exactly one match" in script
    assert "Remove-Item -Recurse -Force $PreparedRoot" in script
    assert "MICROSOFT-LICENSE.txt" in script
    assert "ROOT\\VoxPassportVirtualAudio" in script
    assert "VoxPassport Translation Sink" in script
    assert "VoxPassport Virtual Microphone" in script
    assert "MICARRAY_BITS_PER_SAMPLE_PCM" in script
    assert "192000" in script
    assert "vp_audio_bridge.cpp" in script


def test_kernel_bridge_is_bounded_nonallocating_and_low_latency():
    source = read("overlay/vp_audio_bridge.cpp")
    assert "VP_BRIDGE_CAPACITY = 64 * 1024" in source
    assert "VpAudioBridgeWrite" in source
    assert "VpAudioBridgeRead" in source
    assert "KeAcquireSpinLock" in source
    assert "RtlZeroMemory(Destination, ByteCount)" in source
    assert "g_ReadOffset = (g_ReadOffset + drop)" in source  # drop oldest on overflow
    assert "ExAllocate" not in source
    assert "new " not in source


def test_cable_validator_requires_real_pcm_crossing():
    validator = (ROOT / "scripts" / "validate_virtual_audio.py").read_text(encoding="utf-8")
    assert "VoxPassport Translation Sink" in validator
    assert "VoxPassport Virtual Microphone" in validator
    assert "NativeAudioRender.open" in validator
    assert "open_microphone_capture" in validator
    assert "Captured RMS" in validator
    assert "did not cross the virtual cable" in validator


def test_generated_microsoft_tree_is_not_vendored():
    assert not (DRIVER / ".work").exists()
    assert not (DRIVER / "out").exists()
    # VoxPassport owns only its overlay/build tooling in source control; the
    # pinned Microsoft source is materialized during preparation.
    assert not (DRIVER / "SimpleAudioSample.sln").exists()
