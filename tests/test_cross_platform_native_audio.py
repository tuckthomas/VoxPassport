from pathlib import Path

from runtime.inference import native_audio_bridge as bridge_module
from runtime.inference.native_audio_bridge import NativeAudioBridge


def test_linux_helper_discovery_uses_linux_crate(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(bridge_module.sys, "platform", "linux")
    helper = tmp_path / "crates" / "audio-linux" / "target" / "debug" / "voxpassport-audio-helper"
    helper.parent.mkdir(parents=True)
    helper.write_text("helper", encoding="utf-8")
    assert NativeAudioBridge(project_root=tmp_path).resolve_helper_path() == helper.resolve()


def test_macos_helper_discovery_uses_swift_package(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(bridge_module.sys, "platform", "darwin")
    helper = tmp_path / "native" / "macos" / "audio-helper" / ".build" / "release" / "voxpassport-audio-helper"
    helper.parent.mkdir(parents=True)
    helper.write_text("helper", encoding="utf-8")
    assert NativeAudioBridge(project_root=tmp_path).resolve_helper_path() == helper.resolve()


def test_windows_helper_discovery_keeps_exe_suffix(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(bridge_module.sys, "platform", "win32")
    helper = tmp_path / "crates" / "audio-windows" / "target" / "release" / "voxpassport-audio-helper.exe"
    helper.parent.mkdir(parents=True)
    helper.write_text("helper", encoding="utf-8")
    assert NativeAudioBridge(project_root=tmp_path).resolve_helper_path() == helper.resolve()
