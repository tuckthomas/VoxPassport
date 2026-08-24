import struct
from pathlib import Path

import pytest

from runtime.inference.native_audio_bridge import (
    FRAME_HEADER,
    FRAME_MAGIC,
    NativeAudioBridge,
    NativeAudioBridgeError,
    NativeAudioCaptureConfig,
    parse_frame_header,
)
from runtime.inference.protocol import SampleFormat


def test_frame_header_contract_matches_native_helper_layout():
    header = FRAME_HEADER.pack(FRAME_MAGIC, 12, 34, 16000, 1, 1, 640)
    assert len(header) == 31
    sequence, timestamp, rate, channels, sample_format, payload = parse_frame_header(header)
    assert sequence == 12
    assert timestamp == 34
    assert rate == 16000
    assert channels == 1
    assert sample_format == SampleFormat.PCM_S16LE
    assert payload == 640


def test_frame_header_rejects_bad_magic_unknown_format_and_invalid_shape():
    with pytest.raises(NativeAudioBridgeError, match="magic"):
        parse_frame_header(FRAME_HEADER.pack(b"BAD!", 0, 0, 16000, 1, 1, 2))
    with pytest.raises(NativeAudioBridgeError, match="sample format"):
        parse_frame_header(FRAME_HEADER.pack(FRAME_MAGIC, 0, 0, 16000, 1, 99, 2))
    with pytest.raises(NativeAudioBridgeError, match="sample shape"):
        parse_frame_header(FRAME_HEADER.pack(FRAME_MAGIC, 0, 0, 0, 1, 1, 2))


def test_capture_config_rejects_unbounded_or_invalid_values():
    NativeAudioCaptureConfig().validate()
    with pytest.raises(ValueError, match="queue_capacity"):
        NativeAudioCaptureConfig(queue_capacity=0).validate()
    with pytest.raises(ValueError, match="chunk_duration"):
        NativeAudioCaptureConfig(chunk_duration_ms=0).validate()


@pytest.mark.asyncio
async def test_missing_helper_reports_conservative_capabilities(tmp_path: Path):
    bridge = NativeAudioBridge(project_root=tmp_path)
    assert bridge.resolve_helper_path() is None
    status = await bridge.status_payload()
    assert status["service_connected"] is False
    assert status["capabilities"] == {
        "device_enumeration": False,
        "physical_microphone_capture": False,
        "loopback_capture": False,
        "render_output": False,
        "virtual_microphone_output": False,
    }
    assert await bridge.devices_payload() == {"schema_version": 1, "devices": []}
