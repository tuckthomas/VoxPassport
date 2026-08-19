from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _adapter_source(filename: str) -> str:
    return (
        _repo_root() / "runtime" / "inference" / "adapters" / "tts" / filename
    ).read_text(encoding="utf-8")


def _server_source() -> str:
    return (
        _repo_root() / "runtime" / "inference" / "server" / "main.py"
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


def test_saved_voice_profile_preserves_selected_clone_model():
    source = _server_source()
    assert 'clone_model = "omnivoice"' in source
    assert 'staged_meta.get("clone_model", "omnivoice")' in source
    assert '"clone_model": clone_model' in source


def test_synthesize_routes_to_profile_selected_backend():
    source = _server_source()
    assert "request_override or profile_meta.get" in source
    assert "self._tts_engine_for_model(clone_model)" in source
    assert "tts_engine.generate_cloned_audio(" in source
    assert "self.tts_ro.generate_cloned_audio(" not in source


def test_server_never_reintroduces_two_step_or_silent_edge_fallback():
    source = _server_source().lower()
    assert "num_step=2" not in source
    assert "edge_tts" not in source
    assert '"x-voxpassport-tts-engine"' in source
