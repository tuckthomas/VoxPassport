import json
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _adapter_source(filename: str) -> str:
    return (_repo_root() / "runtime" / "inference" / "adapters" / "tts" / filename).read_text(encoding="utf-8")


def _server_source() -> str:
    return (_repo_root() / "runtime" / "inference" / "server" / "main.py").read_text(encoding="utf-8")


def _client_source(path: str) -> str:
    return (_repo_root() / "apps" / "client" / "src" / path).read_text(encoding="utf-8")


def _playback_source() -> str:
    return (_repo_root() / "runtime" / "inference" / "pipeline" / "audio_playback.py").read_text(encoding="utf-8")


def _tts_manifest(model_id: str) -> dict:
    return json.loads(
        (_repo_root() / "runtime" / "tts_manifests" / f"{model_id}.json").read_text(encoding="utf-8")
    )


def test_local_tts_transport_is_only_manifest_adapter():
    tts_dir = _repo_root() / "runtime" / "inference" / "adapters" / "tts"
    adapter_files = {path.name for path in tts_dir.glob("*_tts_adapter.py")}
    assert adapter_files == {"manifest_tts_adapter.py"}
    source = _adapter_source("manifest_tts_adapter.py")
    assert "ManifestTtsAdapter" in source
    assert "TtsManifestCatalog" in source


def test_voxcpm2_rejects_romanian_through_manifest_capabilities():
    manifest = _tts_manifest("voxcpm-2")
    assert "en" in manifest["capabilities"]["languages"]
    assert "ro" not in manifest["capabilities"]["languages"]


def test_voice_profiles_are_not_bound_to_a_tts_engine():
    server = _server_source()
    assert '"last_preview_model": preview_model' in server
    assert 'profile_meta.get("clone_model"' not in server
    assert 'data.get("clone_model") or self._active_tts_model()' in server


def test_synthesize_uses_active_or_explicit_manifest_backend():
    server = _server_source()
    assert "self._active_tts_model()" in server
    assert "self._tts_engine_for_model(selected_model)" in server
    assert "engine.generate_cloned_audio(" in server
    assert "manifest.transcript_required" in server
    assert 'selected_model != "omnivoice"' not in server


def test_main_daemon_has_no_model_specific_local_tts_branches():
    source = _server_source()
    lowered = source.lower()
    assert "ttsmanifestcatalog" in lowered
    assert "manifestttsadapter" in lowered
    for concrete in (
        "omnivoicettsadapter", "higgsttsadapter", "higgsnativettsadapter",
        "mossttsadapter", "voxcpmttsadapter", "xttsromanianttsadapter",
    ):
        assert concrete not in lowered
    assert "if any(k in model" not in lowered


def test_server_never_reintroduces_two_step_or_silent_edge_fallback():
    source = _server_source().lower()
    assert "num_step=2" not in source
    assert "edge_tts" not in source
    assert '"x-voxpassport-tts-engine"' in source


def test_manifest_tts_uses_real_pcm_streaming():
    generic = _adapter_source("manifest_tts_adapter.py")
    stream_body = generic[generic.index("async def synthesize_stream"):]
    assert '"response_format": response_format' in generic
    assert "response.content.iter_chunked" in stream_body
    assert "SampleFormat.PCM_S16LE" in stream_body
    assert "NotImplementedError" not in stream_body


def test_manifest_tts_resolves_common_active_profile_once():
    helper = _adapter_source("profile_reference.py")
    generic = _adapter_source("manifest_tts_adapter.py")
    assert '"active_selection.json"' in helper
    assert "resolve_profile_reference(" in generic


def test_every_local_tts_manifest_uses_v3_supervised_topology():
    manifest_dir = _repo_root() / "runtime" / "tts_manifests"
    manifests = [json.loads(path.read_text(encoding="utf-8")) for path in manifest_dir.glob("*.json")]
    assert manifests
    assert all(manifest["schema_version"] == 3 for manifest in manifests)
    assert all("worker" not in manifest for manifest in manifests)
    assert all("runtime_profile" in manifest for manifest in manifests)
    assert all("driver" in manifest and "entrypoint" in manifest["driver"] for manifest in manifests)
    for manifest in manifests:
        options = manifest["driver"].get("options", {})
        assert "backend_process" not in options
        assert "backend_url" not in options
        assert "backend_url_env" not in options


def test_voice_preview_requests_are_cached_by_server_and_owned_by_expo_flow():
    server = _server_source()
    screen = _client_source("features/voice-profiles/VoiceProfilesScreen.tsx")
    assert '"X-VoxPassport-Preview-Cache": "HIT"' in server
    assert "api.stageVoiceProfile" in screen
    assert "api.synthesizeVoicePreview" in screen
    assert "Stage & preview" in screen


def test_model_workflows_use_backend_owned_installability_metadata():
    screen = _client_source("features/models/ModelsScreen.tsx")
    contracts = _client_source("api/contracts.ts")
    assert "model.installable === true" in screen
    assert "model.installation_reason" in screen
    assert "api.installModel" in screen
    assert "api.activateModel" in screen
    assert "api.uninstallModel" in screen
    assert "installable?: boolean" in contracts
    assert "installation_reason?: string | null" in contracts


def test_voice_profiles_retain_and_expose_saved_translation_samples():
    screen = _client_source("features/voice-profiles/VoiceProfilesScreen.tsx")
    server = _server_source()
    assert "translated_sample.wav" in server
    assert 'app.router.add_get("/api/voice/translation/{profile_id}", api_voice_translation)' in server
    assert "profile.has_translation_audio" in screen
    assert "/api/voice/translation/" in screen
    assert "Play reference" in screen
    assert "Play preview" in screen
    assert "Delete" in screen


def test_voice_enrollment_is_expo_native_and_typed():
    screen = _client_source("features/voice-profiles/VoiceProfilesScreen.tsx")
    assert "requestRecordingPermissionsAsync" in screen
    assert "useAudioRecorder" in screen
    assert "api.stageVoiceProfile" in screen
    assert "api.commitVoiceStage" in screen
    assert "Save & activate" in screen
    assert "Discard" in screen


def test_runtime_residency_state_has_backend_and_expo_diagnostics():
    server = _server_source()
    screen = _client_source("features/runtime/RuntimeScreen.tsx")
    assert "_runtime_residency" in server
    assert "_ensure_runtime_ready" in server
    assert "_release_runtime_when_idle" in server
    assert '"/api/runtime/residency"' in server
    assert "runtime?.model_residency" in screen
    assert "runtime.models_loaded" in screen
    assert "Active model slots" in screen


def test_playback_resamples_each_chunk_and_owns_consumer_lifecycle():
    source = _playback_source()
    assert "chunk.sample_rate_hz" in source
    assert "resample_poly" in source
    assert "self._consumer_task" in source
    assert "np.interp" not in source
