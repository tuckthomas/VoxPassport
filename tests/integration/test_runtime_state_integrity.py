from pathlib import Path

import pytest

from runtime.inference.model_registry.catalog import get_builtin_catalog
from runtime.inference.model_registry.registry import ModelRegistry
from runtime.inference.protocol import CaptionEvent, CaptionEventType, InstallationStatus, LanguageCode, ModelCapability
from runtime.inference.server.model_manager_api import ModelManagerController
from runtime.inference.tts_plugins import TtsManifestCatalog, manifest_registry_entry


ROOT = Path(__file__).resolve().parents[2]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_caption_protocol_accepts_legacy_pipeline_fields():
    event = CaptionEvent(
        event_type=CaptionEventType.PARTIAL_SOURCE,
        utterance_id="u1",
        language=LanguageCode.EN,
        text="hello",
        is_final=False,
        monotonic_timestamp_ns=123,
    )
    assert event.event_type.value == "source_partial"
    assert event.is_provisional is True
    assert event.monotonic_timestamp_ns == 123
    assert event.created_monotonic_ns == 123


def test_model_manager_uses_manifest_aliases_for_tts_slots(tmp_path):
    registry = ModelRegistry(tmp_path / "registry.json")
    registry.load()
    for entry in get_builtin_catalog():
        registry.register(entry)

    catalog = TtsManifestCatalog().load()
    manifest = catalog.resolve("omnivoice")
    registry.register(manifest_registry_entry(manifest))
    registry.update_installation_status(manifest.model_id, InstallationStatus.INSTALLED)

    manager = ModelManagerController(registry, model_store_dir=tmp_path / "models")
    for alias in (manifest.model_id, *manifest.aliases):
        manager.register_alias(alias, manifest.model_id)

    canonical = manager.set_active_model("TTS", "omnivoice")
    assert canonical == "omnivoice-stock"
    slots = manager.get_active_slots()
    assert slots["tts_en"] == "omnivoice-stock"
    assert slots["tts_ro"] == "omnivoice-stock"
    assert slots["TTS"] == "omnivoice-stock"


def test_empty_active_model_is_rejected(tmp_path):
    registry = ModelRegistry(tmp_path / "registry.json")
    registry.load()
    manager = ModelManagerController(registry, model_store_dir=tmp_path / "models")
    with pytest.raises(ValueError):
        manager.set_active_model("TTS", "")


def test_milmmt_translation_is_local_not_google_translate():
    text = source("runtime/inference/adapters/translation/milmmt46_translation_adapter.py").lower()
    assert "translate.googleapis.com" not in text
    assert "requests.get" not in text
    assert "translate this from" in text
    assert "self._model.generate" in text


def test_parakeet_adapter_performs_real_decode():
    text = source("runtime/inference/adapters/asr/parakeet_tdt_v3_asr_adapter.py")
    assert 'pipeline("automatic-speech-recognition"' in text
    push_body = text[text.index("async def push_audio"):text.index("def _transcribe_blocking")]
    assert "pass" not in push_body
    assert "_decode_state" in push_body
    assert "async def endpoint" in text


def test_voice_profiles_are_engine_agnostic_and_synthesis_uses_active_tts():
    main = source("runtime/inference/server/main.py")
    assert '"last_preview_model": preview_model' in main
    assert 'data.get("clone_model") or self._active_tts_model()' in main
    assert 'profile_meta.get("clone_model"' not in main
    assert "manifest.transcript_required" in main


def test_model_activation_does_not_swallow_errors():
    main = source("runtime/inference/server/main.py")
    assert '"success": False, "error": str(exc)' in main
    assert "Registry set_active_model note" not in main


def test_canonical_expo_client_owns_model_and_caption_controls():
    models = source("apps/client/src/features/models/ModelsScreen.tsx")
    translator = source("apps/client/src/features/translator/TranslatorScreen.tsx")
    assert "api.activateModel" in models
    assert "api.installModel" in models
    assert "api.uninstallModel" in models
    assert "liveTranslation" in translator or "LiveTranslation" in translator
    assert not (ROOT / "apps" / "desktop-companion" / "model-manager" / "runtime-fixes.js").exists()


def test_playback_retains_consumer_task_and_polyphase_resamples():
    text = source("runtime/inference/pipeline/audio_playback.py")
    assert "self._consumer_task" in text
    assert "resample_poly" in text
    assert "np.interp" not in text


def test_silero_is_pinned_to_621_and_enforces_endpoint_durations():
    text = source("runtime/inference/adapters/vad/silero_vad_adapter.py")
    assert 'MODEL_VERSION = "v6.2.1"' in text
    assert 'snakers4/silero-vad:{MODEL_VERSION}' in text
    assert "_speech_candidate_ms" in text
    assert "_silence_candidate_ms" in text
    assert "self._min_speech_duration_ms" in text
    assert "self._min_silence_duration_ms" in text
    assert "MOCK_SILERO_VAD" not in text


def test_catalog_exposes_new_benchmark_and_diarization_models():
    entries = {entry.model_id: entry for entry in get_builtin_catalog()}
    assert entries["silero-vad-v6.2.1"].revision == "v6.2.1"
    assert entries["nvidia-parakeet-tdt-0.6b-v3"].recommendation_state.value == "RECOMMENDED_FOR_LOCAL_BENCHMARK"
    assert entries["nvidia-canary-1b-v2"].capability == ModelCapability.DIRECT_SPEECH_TRANSLATION
    assert entries["meta-omniasr-ctc-300m"].upstream_id == "facebook/omniASR-CTC-300M"
    assert entries["meta-omniasr-ctc-1b"].upstream_id == "facebook/omniASR-CTC-1B"
    assert entries["meta-omniasr-ctc-1b-v2"].upstream_id == ""
    assert entries["meta-omnilingual-mt"].upstream_id == ""
    assert all(entry.capability != ModelCapability.TTS for entry in entries.values())
    diar = entries["nvidia-diar-streaming-sortformer-4spk-v2.1"]
    assert diar.capability == ModelCapability.DIARIZATION
    assert diar.upstream_id == "nvidia/diar_streaming_sortformer_4spk-v2.1"


def test_parakeet_language_detection_metadata_is_honest():
    text = source("runtime/inference/adapters/asr/parakeet_tdt_v3_asr_adapter.py")
    assert '"language_detection": detection_mode' in text
    assert 'detection_mode = "implicit_not_exposed"' in text
    assert 'result.get("language") or result.get("lang")' in text


def test_sortformer_is_parallel_inbound_sidecar_not_serial_asr_gate():
    adapter = source("runtime/inference/adapters/diarization/sortformer_streaming_diarization_adapter.py")
    inbound = source("runtime/inference/pipeline/inbound_pipeline.py")
    orchestrator = source("runtime/inference/pipeline/duplex_orchestrator.py")
    assert "CHUNK_LEN = 6" in adapter
    assert "CHUNK_RIGHT_CONTEXT = 7" in adapter
    assert "FIFO_LEN = 188" in adapter
    assert "SPKCACHE_UPDATE_PERIOD = 144" in adapter
    assert "asyncio.create_task(self._infer_snapshot(snapshot))" in adapter
    assert "diarization_adapter=self.diarization_adapter" in orchestrator
    assert 'os.getenv("VOXPASSPORT_DIARIZATION", "auto")' in orchestrator
    assert "await self.diarization_adapter.push_audio(frame)" in inbound
    assert "await self.asr_adapter.push_audio(self._current_asr_stream, frame)" in inbound


def test_caption_websocket_preserves_speaker_metadata():
    server = source("runtime/inference/server/caption_server.py")
    inbound = source("runtime/inference/pipeline/inbound_pipeline.py")
    assert '"metadata": event.metadata or {}' in server
    assert '"speaker_label"' in source(
        "runtime/inference/adapters/diarization/sortformer_streaming_diarization_adapter.py"
    )
    assert "metadata.update(self._speaker_by_utterance.get" in inbound


def test_watchlist_models_expose_backend_owned_non_installable_state(tmp_path):
    registry = ModelRegistry(tmp_path / "registry.json")
    registry.load()
    for entry in get_builtin_catalog():
        registry.register(entry)
    manager = ModelManagerController(registry, model_store_dir=tmp_path / "models")
    catalog = {item["model_id"]: item for item in manager.list_available()}

    for model_id in ("meta-omniasr-ctc-1b-v2", "meta-omnilingual-mt"):
        assert catalog[model_id]["installable"] is False
        assert "No verified official downloadable repository" in catalog[model_id]["installation_reason"]

    models_screen = source("apps/client/src/features/models/ModelsScreen.tsx")
    assert "model.installable === true" in models_screen
    assert "model.installation_reason" in models_screen
    assert not (ROOT / "apps" / "desktop-companion" / "model-manager" / "stack-upgrade-fixes.js").exists()


def test_download_manager_promotes_completed_downloads_to_installed_state():
    manager = source("runtime/inference/server/model_manager_api.py")
    assert "def _handle_download_progress" in manager
    assert 'if task.phase == "done"' in manager
    assert "InstallationStatus.INSTALLED" in manager
    assert "ModelCapability.DIARIZATION" in manager
    assert "ensure_native_higgs_registered" not in manager
