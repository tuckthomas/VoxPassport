from pathlib import Path

import pytest

from runtime.inference.model_registry.registry import ModelRegistry
from runtime.inference.model_registry.catalog import get_builtin_catalog
from runtime.inference.protocol import CaptionEvent, CaptionEventType, InstallationStatus, LanguageCode
from runtime.inference.server.model_manager_api import ModelManagerController


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


def test_model_manager_global_aliases_fill_real_slots(tmp_path):
    registry = ModelRegistry(tmp_path / "registry.json")
    registry.load()
    for entry in get_builtin_catalog():
        registry.register(entry)
    registry.update_installation_status("omnivoice-stock", InstallationStatus.INSTALLED)
    manager = ModelManagerController(registry, model_store_dir=tmp_path / "models")
    canonical = manager.set_active_model("TTS", "omnivoice")
    assert canonical == "omnivoice-stock"
    slots = manager.get_active_slots()
    assert slots["tts_en"] == "omnivoice-stock"
    assert slots["tts_ro"] == "omnivoice-stock"
    assert slots["TTS"] == "omnivoice"


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


def test_model_activation_does_not_swallow_errors():
    main = source("runtime/inference/server/main.py")
    assert '"success": False, "error": str(exc)' in main
    assert "Registry set_active_model note" not in main


def test_ui_repair_defines_missing_handlers_and_real_caption_stream():
    js = source("apps/desktop-companion/model-manager/runtime-fixes.js")
    assert "w.selectActiveAsrEngine" in js
    assert "w.selectActiveNmtEngine" in js
    assert "w.installHfModel" in js
    assert "ws://127.0.0.1:8765/ws/captions" in js
    assert "w.processLivePhrasePipeline = async () => {}" in js


def test_playback_retains_consumer_task_and_polyphase_resamples():
    text = source("runtime/inference/pipeline/audio_playback.py")
    assert "self._consumer_task" in text
    assert "resample_poly" in text
    assert "np.interp" not in text
