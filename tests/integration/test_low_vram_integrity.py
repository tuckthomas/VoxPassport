from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_parakeet_uses_one_physical_model_for_both_directions():
    text = source("runtime/inference/adapters/asr/parakeet_tdt_v3_asr_adapter.py")
    assert "_shared_pipe" in text
    assert "_shared_refcount" in text
    assert "_shared_inference_lock" in text
    assert "Reusing shared Parakeet TDT model" in text
    assert '"shared_model_instance": True' in text


def test_milmmt_auto_policy_reserves_low_vram_gpu_for_speech_models():
    text = source("runtime/inference/adapters/translation/milmmt46_translation_adapter.py")
    assert "LOW_VRAM_CUTOFF_GB = 10.0" in text
    assert 'device: str = "auto"' in text
    assert "if total_gb <= self.LOW_VRAM_CUTOFF_GB" in text
    assert "keeping translation on CPU" in text
    assert "torch_dtype=torch.float16" in text
    assert "torch.bfloat16" not in text


def test_omnivoice_driver_is_lazy_and_bounds_speaker_cache():
    text = source("runtime/workers/tts_host/drivers/omnivoice.py")
    assert "Keep activation cheap" in text
    assert "self._speaker_cache.clear()" in text
    assert "with torch.inference_mode():" in text
    assert "_release_cuda_cache" in text
    assert "if self._model is not None" in text


def test_sortformer_uses_cpu_on_low_vram_systems():
    text = source("runtime/inference/adapters/diarization/sortformer_streaming_diarization_adapter.py")
    assert "LOW_VRAM_CUTOFF_GB = 12.0" in text
    assert 'device: str = "auto"' in text
    assert "diarization will run on CPU" in text
    assert "self.resolved_device" in text


def test_low_vram_policy_applies_to_preconference_and_live_paths_without_tts_ui_forks():
    parakeet = source("runtime/inference/adapters/asr/parakeet_tdt_v3_asr_adapter.py")
    milmmt = source("runtime/inference/adapters/translation/milmmt46_translation_adapter.py")
    omnivoice = source("runtime/workers/tts_host/drivers/omnivoice.py")
    generic_tts = source("runtime/inference/adapters/tts/manifest_tts_adapter.py")
    assert "one physical Parakeet model" in parakeet
    assert "Voice Studio, Live Studio, and Debug verification" in milmmt
    assert "Keep activation cheap" in omnivoice
    assert "heavy_gpu_inference" in generic_tts
