"""Backward-compatible entrypoint for the manifest-driven TTS daemon.

The XTTS-specific daemon subclass was retired when TTS model routing moved to
runtime manifests. Existing shortcuts that invoke xtts_main.py continue to work.
"""

from __future__ import annotations

import asyncio

from runtime.inference.server.tts_plugin_main import LiveTranslatorApp, main

__all__ = ["LiveTranslatorApp", "main"]


if __name__ == "__main__":
    asyncio.run(main())
