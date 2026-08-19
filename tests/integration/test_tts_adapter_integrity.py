from pathlib import Path


def _adapter_source(filename: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (
        root / "runtime" / "inference" / "adapters" / "tts" / filename
    ).read_text(encoding="utf-8")


def test_non_omnivoice_adapters_do_not_route_through_omnivoice():
    """A selected TTS model must never secretly execute OmniVoice."""
    for filename in (
        "higgs_tts_adapter.py",
        "moss_tts_adapter.py",
        "voxcpm_tts_adapter.py",
    ):
        source = _adapter_source(filename).lower()
        assert "from omnivoice" not in source
        assert "omnivoicegenerationconfig" not in source
        assert "._model.create_voice_clone_prompt" not in source


def test_omnivoice_rejects_old_two_step_quality_shortcut():
    from runtime.inference.adapters.tts.omnivoice_tts_adapter import (
        OmniVoiceTtsAdapter,
    )

    assert OmniVoiceTtsAdapter._quality_steps(2) == 32
    assert OmniVoiceTtsAdapter._quality_steps(16) == 16
    assert OmniVoiceTtsAdapter._quality_steps(32) == 32


def test_voxcpm2_does_not_claim_romanian_support():
    source = _adapter_source("voxcpm_tts_adapter.py").lower()
    assert '"romanian"' in source
    assert "languagecode.ro" in source
