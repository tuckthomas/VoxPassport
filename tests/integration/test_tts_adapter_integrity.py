from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _adapter_source(filename: str) -> str:
    return (_repo_root() / "runtime" / "inference" / "adapters" / "tts" / filename).read_text(encoding="utf-8")


def _server_source() -> str:
    return (_repo_root() / "runtime" / "inference" / "server" / "main.py").read_text(encoding="utf-8")


def _playback_source() -> str:
    return (_repo_root() / "runtime" / "inference" / "pipeline" / "audio_playback.py").read_text(encoding="utf-8")


def test_non_omnivoice_adapters_do_not_route_through_omnivoice():
    for filename in ("higgs_tts_adapter.py", "moss_tts_adapter.py", "voxcpm_tts_adapter.py"):
        source = _adapter_source(filename).lower()
        assert "from omnivoice" not in source
        assert "omnivoicegenerationconfig" not in source
        assert "._model.create_voice_clone_prompt" not in source


def test_omnivoice_rejects_old_two_step_quality_shortcut():
    from runtime.inference.adapters.tts.omnivoice_tts_adapter import OmniVoiceTtsAdapter
    assert OmniVoiceTtsAdapter._quality_steps(2) == 32
    assert OmniVoiceTtsAdapter._quality_steps(16) == 16
    assert OmniVoiceTtsAdapter._quality_steps(32) == 32


def test_voxcpm2_explicitly_rejects_romanian():
    source = _adapter_source("voxcpm_tts_adapter.py").lower()
    assert "does not publish romanian support" in source
    assert '"romanian", "ro"' in source


def test_voice_profiles_are_not_bound_to_a_tts_engine():
    server = _server_source()
    assert '"last_preview_model": preview_model' in server
    assert 'profile_meta.get("clone_model"' not in server
    assert 'data.get("clone_model") or self._active_tts_model()' in server


def test_synthesize_uses_active_or_explicit_backend():
    server = _server_source()
    assert "self._active_tts_model()" in server
    assert "self._tts_engine_for_model(selected_model)" in server
    assert "engine.generate_cloned_audio(" in server


def test_server_never_reintroduces_two_step_or_silent_edge_fallback():
    source = _server_source().lower()
    assert "num_step=2" not in source
    assert "edge_tts" not in source
    assert '"x-voxpassport-tts-engine"' in source


def test_higgs_moss_and_voxcpm_use_real_pcm_streaming():
    for filename in ("higgs_tts_adapter.py", "moss_tts_adapter.py", "voxcpm_tts_adapter.py"):
        source = _adapter_source(filename)
        stream_body = source[source.index("async def synthesize_stream"):]
        assert '"stream": True' in stream_body
        assert '"response_format": "pcm"' in stream_body
        assert "response.content.iter_chunked" in stream_body
        assert "SampleFormat.PCM_S16LE" in stream_body
        assert "NotImplementedError" not in stream_body.split("async def generate_cloned_audio", 1)[0]
    assert '"stream_format": "audio"' in _adapter_source("voxcpm_tts_adapter.py")


def test_external_tts_engines_resolve_common_active_profile():
    helper = _adapter_source("profile_reference.py")
    assert '"active_selection.json"' in helper
    for filename in ("higgs_tts_adapter.py", "moss_tts_adapter.py", "voxcpm_tts_adapter.py"):
        assert "resolve_profile_reference(" in _adapter_source(filename)


def test_studio_preview_requests_are_cached_by_the_server():
    server = _server_source()
    studio = (
        _repo_root() / "apps" / "desktop-companion" / "model-manager" / "studio.html"
    ).read_text(encoding="utf-8")
    assert '"X-VoxPassport-Preview-Cache": "HIT"' in server
    assert "preview: true" in studio


def test_active_and_hugging_face_model_cards_link_license_icons():
    studio = (
        _repo_root() / "apps" / "desktop-companion" / "model-manager" / "studio.html"
    ).read_text(encoding="utf-8")
    assert "modelMetadataById" in studio
    assert "rememberModelMetadata(instData)" in studio
    assert "renderModelLicenseIcon(m)" in studio
    assert "renderLicenseIcon(m.license, m.commercial_use, m.upstream_id, m.license_url)" in studio
    assert 'class="model-license-link ${classification}"' in studio
    assert 'target="_blank"' in studio
    assert "licenseUrlFor" in studio
    assert "profile-card-actions" in studio
    assert 'aria-hidden="true" data-tooltip="${tooltip}"' in studio
    assert "target.contains(e.relatedTarget)" in studio
    assert "color: #ef4444" in studio
    assert '<svg class="hw-warn-icon"' in studio
    assert "targetCenterX" in studio
    assert "targetCenterY" in studio
    assert "--tooltip-arrow-x" in studio
    assert "--tooltip-arrow-y" in studio
    assert "const HOVER_DELAY_MS = 500" in studio
    assert "scheduleTooltip(target, text, pos)" in studio
    assert "target.matches(':hover')" in studio
    assert "cursor: default" not in studio
    assert "Live Caption Stream" not in studio
    assert 'class="activity-dock"' not in studio


def test_voice_profiles_retain_and_expose_saved_translation_samples():
    studio = (
        _repo_root() / "apps" / "desktop-companion" / "model-manager" / "studio.html"
    ).read_text(encoding="utf-8")
    server = _server_source()
    assert "translated_sample.wav" in server
    assert 'app.router.add_get("/api/voice/translation/{profile_id}", api_voice_translation)' in server
    assert "playTranslatedProfile" in studio
    assert "<span>Original</span>" in studio
    assert "<span>Translation</span>" in studio
    assert "btn-card-trash" in studio


def test_omnivoice_no_longer_dispatches_other_engines_from_profile_metadata():
    source = _adapter_source("omnivoice_tts_adapter.py")
    stream_body = source[source.index("async def synthesize_stream"):]
    assert "clone_model" not in stream_body.split("async def generate_cloned_audio", 1)[0]
    assert "_external_stream_engine" not in source


def test_playback_resamples_each_chunk_and_owns_consumer_lifecycle():
    source = _playback_source()
    assert "chunk.sample_rate_hz" in source
    assert "resample_poly" in source
    assert "self._consumer_task" in source
    assert "np.interp" not in source
