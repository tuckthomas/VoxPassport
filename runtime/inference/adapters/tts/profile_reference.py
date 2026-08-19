"""Shared voice-profile reference resolution for TTS adapters."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


def resolve_profile_reference(
    profiles_root: Path,
    requested_profile_id: Optional[str],
    *,
    require_transcript: bool = True,
) -> tuple[str, Path, str]:
    """Resolve an explicit profile or the saved active profile.

    Voice profile identity is independent of the TTS engine.  Live duplex calls
    therefore normally pass no model-specific profile state; each adapter reads
    the common active_selection.json when no explicit profile ID is supplied.
    """

    profile_id = str(requested_profile_id or "").strip()
    if not profile_id or profile_id.lower() in {"active", "default"}:
        active_file = Path(profiles_root) / "active_selection.json"
        if active_file.exists():
            try:
                profile_id = str(
                    json.loads(active_file.read_text(encoding="utf-8")).get("active_id", "")
                ).strip()
            except Exception:
                profile_id = ""
    if not profile_id:
        raise ValueError("Cloned synthesis requires an active saved voice profile")

    profile_dir = Path(profiles_root) / profile_id
    ref_audio = profile_dir / "reference.wav"
    ref_text_path = profile_dir / "reference.txt"
    if not ref_audio.exists():
        raise FileNotFoundError(f"Voice profile {profile_id!r} has no reference.wav")
    ref_text = ref_text_path.read_text(encoding="utf-8").strip() if ref_text_path.exists() else ""
    if require_transcript and not ref_text:
        raise ValueError(f"Voice profile {profile_id!r} has no reference transcript")
    return profile_id, ref_audio, ref_text
