"""
LiveTranslator — Diagnostics & System Health Engine
====================================================
Comprehensive diagnostic introspection and testing tools for conference readiness.

Features (Section 37 & 39):
- Diagnostic test tone generator (440Hz sine wave to test Virtual Mic routing)
- Test translated phrase generator ("Testing LiveTranslator audio routing")
- Full hardware & VRAM inspection
- Audio device conflict detection
- Subsystem health checks
"""

from __future__ import annotations

import logging
import math
import struct
import sys
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class DiagnosticsEngine:
    """
    Introspects hardware, tests audio routes, and validates end-to-end conference setup.
    """

    @staticmethod
    def generate_test_tone_pcm(frequency_hz: float = 440.0, duration_s: float = 1.0, sample_rate_hz: int = 16000) -> bytes:
        """Generate a 16-bit PCM test tone sine wave."""
        n_samples = int(duration_s * sample_rate_hz)
        pcm_bytes = bytearray()
        for i in range(n_samples):
            t = i / sample_rate_hz
            sample_val = int(math.sin(2.0 * math.pi * frequency_hz * t) * 16384.0)
            pcm_bytes.extend(struct.pack("<h", sample_val))
        return bytes(pcm_bytes)

    @staticmethod
    def get_system_diagnostics() -> Dict[str, any]:
        """Collect hardware, OS, and Python environment state."""
        diag = {
            "python_version": sys.version,
            "os_platform": sys.platform,
            "timestamp": time.time(),
            "cuda_available": False,
            "gpu_name": "None",
            "vram_total_gb": 0.0,
            "vram_used_gb": 0.0,
        }
        try:
            import torch
            if torch.cuda.is_available():
                diag["cuda_available"] = True
                diag["gpu_name"] = torch.cuda.get_device_name(0)
                props = torch.cuda.get_device_properties(0)
                diag["vram_total_gb"] = round(props.total_memory / (1024**3), 2)
                diag["vram_used_gb"] = round(torch.cuda.memory_allocated(0) / (1024**3), 2)
        except Exception:
            pass
        return diag

    @staticmethod
    def validate_audio_routing(mic_dev_name: str, loopback_dev_name: str, virtual_mic_name: str) -> List[str]:
        """Detect common audio routing misconfigurations."""
        warnings = []
        if mic_dev_name.lower() == virtual_mic_name.lower():
            warnings.append("Physical microphone is set to Virtual Mic! This will cause feedback loops.")
        if virtual_mic_name.lower() in loopback_dev_name.lower():
            warnings.append("Loopback capture device includes Virtual Mic! Echo cancellation required.")
        return warnings
