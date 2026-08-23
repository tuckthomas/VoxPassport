"""Lazy import of worker-side TTS driver entrypoints."""

from __future__ import annotations

import importlib

from runtime.inference.tts_plugins.manifest import TtsManifest
from runtime.workers.tts_host.protocol import TtsDriver


def load_driver_class(entrypoint: str):
    module_name, sep, class_name = str(entrypoint).partition(":")
    if not sep or not module_name or not class_name:
        raise ValueError(f"Invalid TTS driver entrypoint {entrypoint!r}; expected module:ClassName")
    module = importlib.import_module(module_name)
    driver_class = getattr(module, class_name)
    if not isinstance(driver_class, type) or not issubclass(driver_class, TtsDriver):
        raise TypeError(f"TTS driver {entrypoint!r} must subclass TtsDriver")
    return driver_class


def create_driver(manifest: TtsManifest) -> TtsDriver:
    return load_driver_class(manifest.driver_entrypoint)(manifest)
