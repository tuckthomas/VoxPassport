"""
LiveTranslator - Adapter Compatibility and Version Checking (Section 16F)
Defines AdapterMetadata and enforces version compatibility before loading.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Current application adapter API version
APP_ADAPTER_API_VERSION = (1, 0)


@dataclass
class AdapterMetadata:
    """Metadata every adapter must declare."""
    adapter_name: str
    adapter_version: tuple[int, int]        # (major, minor)
    supported_model_families: list[str]
    supported_capabilities: list[str]       # ["ASR", "TTS", etc.]
    runtime_requirements: dict[str, str]    # e.g. {"pytorch": ">=2.0", "nemo": ">=1.20"}
    min_app_api_version: tuple[int, int]    # minimum (major, minor) this adapter needs
    max_app_api_version: Optional[tuple[int, int]] = None   # None = no upper bound


class CompatibilityError(Exception):
    """Raised when an adapter is incompatible with the current runtime."""


def check_adapter_compatibility(meta: AdapterMetadata) -> None:
    """
    Raise CompatibilityError if the adapter cannot be loaded.

    Checks:
      1. Adapter minimum API version <= current APP_ADAPTER_API_VERSION
      2. Adapter maximum API version (if set) >= current APP_ADAPTER_API_VERSION
      3. Runtime library versions where importable
    """
    current = APP_ADAPTER_API_VERSION

    if meta.min_app_api_version > current:
        raise CompatibilityError(
            f"Adapter '{meta.adapter_name}' requires app API "
            f">= {meta.min_app_api_version}, but current is {current}. "
            "Update the application."
        )

    if meta.max_app_api_version and meta.max_app_api_version < current:
        raise CompatibilityError(
            f"Adapter '{meta.adapter_name}' only supports app API "
            f"<= {meta.max_app_api_version}, but current is {current}. "
            "Update or replace the adapter."
        )

    # Check runtime library requirements
    for lib_name, version_req in meta.runtime_requirements.items():
        _check_library(meta.adapter_name, lib_name, version_req)

    logger.info(
        "Adapter '%s' v%s.%s is compatible with app API v%s.%s",
        meta.adapter_name, *meta.adapter_version, *current,
    )


def _check_library(adapter_name: str, lib_name: str, version_req: str) -> None:
    """Verify that a required library is present and satisfies the version constraint."""
    import importlib
    import importlib.metadata

    try:
        mod = importlib.import_module(lib_name.replace("-", "_"))
        installed_version_str = getattr(mod, "__version__", None)
        if installed_version_str is None:
            try:
                installed_version_str = importlib.metadata.version(lib_name)
            except Exception:
                logger.warning(
                    "Adapter '%s': cannot determine version of '%s' — proceeding.",
                    adapter_name, lib_name,
                )
                return

        installed = _parse_version(installed_version_str)

        if version_req.startswith(">="):
            required = _parse_version(version_req[2:].strip())
            if installed < required:
                raise CompatibilityError(
                    f"Adapter '{adapter_name}' requires {lib_name}{version_req}, "
                    f"but {installed_version_str} is installed."
                )
        elif version_req.startswith("=="):
            required = _parse_version(version_req[2:].strip())
            if installed != required:
                raise CompatibilityError(
                    f"Adapter '{adapter_name}' requires {lib_name}{version_req}, "
                    f"but {installed_version_str} is installed."
                )

    except ImportError:
        raise CompatibilityError(
            f"Adapter '{adapter_name}' requires library '{lib_name}' which is not installed."
        )


def _parse_version(version_str: str) -> tuple[int, ...]:
    """Parse a version string like '2.1.0' into a comparable tuple."""
    parts = []
    for part in version_str.split(".")[:3]:
        try:
            parts.append(int(part.split("+")[0].split("a")[0].split("b")[0].split("rc")[0]))
        except ValueError:
            parts.append(0)
    return tuple(parts)
