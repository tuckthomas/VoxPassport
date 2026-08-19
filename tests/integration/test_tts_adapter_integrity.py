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


def _playback_source() -> str:
    return (
        _repo_root() / "runtime" / "inference" / "pipeline" / "audio_playback.py"
    ).read_text(encoding="utf-8")


def test_non_omnivoice_adapters_do_not_route_through_omnivoice():
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
    from runtime.inference.adapters.tts.omnivoice_tts_adapter import OmniVoiceTtsAdapter
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


def test_higgs_and_moss_use_true_pcm_streaming():
    for filename in ("higgs_tts_adapter.py", "moss_tts_adapter.py"):
        source = _adapter_source(filename)
        stream_body = source[source.index("async def synthesize_stream"):]
        assert '"stream": True' in stream_body
        assert '"response_format": "pcm"' in stream_body
        assert "response.content.iter_chunked" in stream_body
        assert "SampleFormat.PCM_S16LE" in stream_body
        assert "NotImplementedError" not in stream_body.split(
            "async def generate_cloned_audio", 1
        )[0]


def test_duplex_compatibility_dispatch_uses_saved_clone_model():
    source = _adapter_source("omnivoice_tts_adapter.py")
    stream_body = source[source.index("async def synthesize_stream"):]
    assert 'get("clone_model", "omnivoice")' in stream_body
    assert "await self._external_stream_engine(clone_model)" in stream_body
    assert "engine.synthesize_stream(" in stream_body
    assert 'data=b""' in stream_body


def test_playback_resamples_each_chunk_to_device_rate():
    source = _playback_source()
    assert "chunk.sample_rate_hz" in source
    assert "self.sample_rate_hz" in source
    assert "np.interp" in source
    assert "_convert_and_resample(chunk)" in source
