"""XTTS Romanian driver for the generic VoxPassport TTS host."""

from __future__ import annotations

import os
from pathlib import Path

from runtime.workers.tts_host.protocol import TtsDriver, TtsDriverRequest


class XttsRomanianDriver(TtsDriver):
    """Model-specific XTTS behavior isolated behind the generic driver API."""

    def __init__(self, manifest) -> None:
        super().__init__(manifest)
        self._runtime = None

    def _runtime_instance(self):
        if self._runtime is not None:
            return self._runtime
        # Keep NumPy, Coqui, Torch, and XTTS imports out of manifest discovery
        # and out of the primary Python environment's integrity tests.
        from runtime.workers.tts_host.drivers.xtts_runtime import XttsRomanianRuntime

        project_root = Path(__file__).resolve().parents[4]
        options = self.manifest.driver_options
        model_dir = Path(
            os.getenv(
                "VOXPASSPORT_XTTS_MODEL_DIR",
                str(options.get("model_dir") or project_root / "models" / "xtts-v2-romanian-v2"),
            )
        )
        device = os.getenv("VOXPASSPORT_XTTS_DEVICE", str(options.get("device", "cuda")))
        cache_size = int(options.get("conditioning_cache_size", 4))
        self._runtime = XttsRomanianRuntime(model_dir, device=device, cache_size=cache_size)
        return self._runtime

    def load(self) -> None:
        self._runtime_instance().load()

    def unload(self) -> None:
        if self._runtime is not None:
            self._runtime.unload()

    def synthesize_pcm(self, request: TtsDriverRequest):
        runtime = self._runtime_instance()
        if not runtime.loaded:
            runtime.load()
        for pcm, _mode in runtime.stream(
            text=request.text,
            language=request.language,
            canonical_reference=request.reference_audio,
            target_reference=request.target_conditioning_audio,
        ):
            if pcm:
                yield pcm

    def metrics(self) -> dict:
        if self._runtime is None:
            return {"loaded": False}
        data = dict(self._runtime.memory_snapshot())
        data["loaded"] = bool(self._runtime.loaded)
        return data

    def health_check(self) -> bool:
        return self._runtime is not None and bool(self._runtime.loaded)
