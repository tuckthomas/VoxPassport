"""Tiny TTS driver used by runtime-supervisor subprocess tests."""

from __future__ import annotations

import os
from pathlib import Path

from runtime.workers.tts_host.protocol import TtsDriver, TtsDriverRequest


class SupervisorFakeTtsDriver(TtsDriver):
    def __init__(self, manifest) -> None:
        super().__init__(manifest)
        self._loaded = False

    def load(self) -> None:
        if self.manifest.driver_options.get("fail_load"):
            raise RuntimeError("requested fake load failure")
        crash_marker = str(self.manifest.driver_options.get("crash_load_once_marker", "")).strip()
        if crash_marker:
            marker_path = Path(crash_marker)
            if not marker_path.exists():
                marker_path.parent.mkdir(parents=True, exist_ok=True)
                marker_path.write_text("crashed-during-load", encoding="utf-8")
                os._exit(90)
        self._loaded = True

    def unload(self) -> None:
        self._loaded = False

    def health_check(self) -> bool:
        return self._loaded

    def synthesize_pcm(self, request: TtsDriverRequest):
        if not self._loaded:
            raise RuntimeError("fake TTS driver is not loaded")
        marker = str(self.manifest.driver_options.get("crash_once_marker", "")).strip()
        if marker:
            marker_path = Path(marker)
            if not marker_path.exists():
                marker_path.parent.mkdir(parents=True, exist_ok=True)
                marker_path.write_text("crashed-during-synthesis", encoding="utf-8")
                os._exit(91)
        if not request.text:
            raise ValueError("text required")
        yield b"\x00\x00" * 480
        yield b"\x01\x00" * 480

    def metrics(self) -> dict:
        return {"fake": True, "pid": os.getpid(), "loaded": self._loaded}
