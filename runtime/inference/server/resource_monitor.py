"""Live host resource snapshots for the local Studio monitor."""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from typing import Any

from runtime.inference.tts_plugins.runtime_status import tts_runtime_status_snapshot

_BYTES_PER_GIB = 1024**3
_MIB_PER_GIB = 1024


class ResourceSnapshotCollector:
    """Collect inexpensive system, GPU, and local TTS runtime snapshots."""

    def __init__(
        self,
        *,
        psutil_module: Any | None = None,
        command_runner: Callable[..., Any] | None = None,
        nvidia_smi_path: str | None = None,
    ) -> None:
        if psutil_module is None:
            import psutil

            psutil_module = psutil
        self._psutil = psutil_module
        self._run_command = command_runner or subprocess.run
        self._nvidia_smi_path = nvidia_smi_path or shutil.which("nvidia-smi")
        self._psutil.cpu_percent(interval=None)

    def snapshot(self) -> dict[str, Any]:
        memory = self._psutil.virtual_memory()
        total_ram_gb = memory.total / _BYTES_PER_GIB
        used_ram_gb = (memory.total - memory.available) / _BYTES_PER_GIB
        return {
            "sampled_at_ms": int(time.time() * 1000),
            "cpu": {
                "usage_percent": round(float(self._psutil.cpu_percent(interval=None)), 1),
                "logical_cores": int(self._psutil.cpu_count(logical=True) or 1),
            },
            "memory": {
                "used_gb": round(used_ram_gb, 2),
                "total_gb": round(total_ram_gb, 2),
                "usage_percent": round(float(memory.percent), 1),
            },
            "gpu": self._gpu_snapshot(),
            "tts_runtime": tts_runtime_status_snapshot(),
        }

    def _gpu_snapshot(self) -> dict[str, Any]:
        if self._nvidia_smi_path:
            try:
                creation_flags = (
                    getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    if sys.platform == "win32"
                    else 0
                )
                result = self._run_command(
                    [
                        self._nvidia_smi_path,
                        "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                        "--format=csv,noheader,nounits",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=1.5,
                    check=True,
                    creationflags=creation_flags,
                )
                first_line = next(
                    line.strip() for line in result.stdout.splitlines() if line.strip()
                )
                name, utilization, used_mib, total_mib, temperature = (
                    part.strip() for part in first_line.split(",", 4)
                )
                used_gb = float(used_mib) / _MIB_PER_GIB
                total_gb = float(total_mib) / _MIB_PER_GIB
                return {
                    "available": True,
                    "name": name,
                    "usage_percent": round(float(utilization), 1),
                    "memory_used_gb": round(used_gb, 2),
                    "memory_total_gb": round(total_gb, 2),
                    "memory_percent": round(
                        (used_gb / total_gb * 100.0) if total_gb else 0.0,
                        1,
                    ),
                    "temperature_c": round(float(temperature), 1),
                    "source": "nvidia-smi",
                }
            except (OSError, StopIteration, subprocess.SubprocessError, ValueError):
                pass

        try:
            import torch

            if torch.cuda.is_available():
                free_bytes, total_bytes = torch.cuda.mem_get_info(0)
                used_gb = (total_bytes - free_bytes) / _BYTES_PER_GIB
                total_gb = total_bytes / _BYTES_PER_GIB
                return {
                    "available": True,
                    "name": torch.cuda.get_device_name(0),
                    "usage_percent": None,
                    "memory_used_gb": round(used_gb, 2),
                    "memory_total_gb": round(total_gb, 2),
                    "memory_percent": round(
                        (used_gb / total_gb * 100.0) if total_gb else 0.0,
                        1,
                    ),
                    "temperature_c": None,
                    "source": "torch",
                }
        except Exception:
            pass

        return {
            "available": False,
            "name": "No compatible GPU detected",
            "usage_percent": None,
            "memory_used_gb": 0.0,
            "memory_total_gb": 0.0,
            "memory_percent": 0.0,
            "temperature_c": None,
            "source": "unavailable",
        }
