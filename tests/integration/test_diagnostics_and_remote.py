"""
Unit & Integration Tests for Diagnostics, Remote Inference, and Audio Routing.
"""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from runtime.inference.protocol import AudioBus, AudioFrame, SampleFormat
from runtime.inference.server.diagnostics import DiagnosticsEngine
from runtime.inference.server.remote_inference import RemoteInferenceClient


class TestDiagnosticsEngine(unittest.TestCase):
    """Test diagnostics and routing conflict detection."""

    def test_tone_generation(self):
        pcm = DiagnosticsEngine.generate_test_tone_pcm(frequency_hz=440.0, duration_s=0.5, sample_rate_hz=16000)
        self.assertEqual(len(pcm), 16000)  # 0.5s * 16000 samples * 2 bytes = 16000 bytes

    def test_system_diagnostics(self):
        diag = DiagnosticsEngine.get_system_diagnostics()
        self.assertIn("python_version", diag)
        self.assertIn("os_platform", diag)

    def test_audio_routing_conflict_detection(self):
        # Conflict: physical mic equals virtual mic
        warnings = DiagnosticsEngine.validate_audio_routing(
            mic_dev_name="VB-Audio Cable",
            loopback_dev_name="Speakers",
            virtual_mic_name="VB-Audio Cable",
        )
        self.assertTrue(len(warnings) > 0)

        # Clean routing:
        clean_warnings = DiagnosticsEngine.validate_audio_routing(
            mic_dev_name="Realtek High Definition Audio",
            loopback_dev_name="Realtek Stereo Mix",
            virtual_mic_name="VB-Audio Cable",
        )
        self.assertEqual(len(clean_warnings), 0)


class TestRemoteInferenceClient(unittest.TestCase):
    """Test remote inference client connection & frame pushing."""

    def test_client_push_frame(self):
        async def run():
            client = RemoteInferenceClient(server_url="wss://test-server:8766/v1/stream")
            await client.connect()
            self.assertTrue(client._is_connected)

            frame = AudioFrame(
                stream_id="test-remote-01",
                sequence=0,
                monotonic_timestamp_ns=1000,
                sample_rate_hz=16000,
                channels=1,
                sample_format=SampleFormat.PCM_S16LE,
                data=b"\x00\x00" * 320,
            )
            await client.push_audio_frame(frame)
            await client.disconnect()
            self.assertFalse(client._is_connected)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
