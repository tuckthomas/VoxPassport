from __future__ import annotations

import wave
from pathlib import Path

from runtime.inference.adapters.tts.higgs_native_tts_adapter import HiggsNativeTtsAdapter


def _write_silence(path: Path, seconds: int = 6) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\0\0" * 16000 * seconds)


def test_native_reference_preparation_is_persistent_and_stable(tmp_path: Path) -> None:
    reference = tmp_path / "reference.wav"
    transcript = "one two three four five six seven eight nine ten eleven twelve"
    _write_silence(reference)

    first_audio, first_text, first_cache = HiggsNativeTtsAdapter._prepare_reference_clip(
        str(reference), transcript
    )
    second_audio, second_text, second_cache = HiggsNativeTtsAdapter._prepare_reference_clip(
        str(reference), transcript
    )

    assert first_audio == second_audio
    assert first_text == second_text
    assert first_cache == second_cache
    assert Path(first_audio).exists()
    assert first_cache.suffix == ".hspkcache"
    assert len(first_text.split()) == 10


def test_native_clause_splitter_bounds_long_synthesis_requests() -> None:
    text = (
        "Aceasta este prima propoziție și trebuie păstrată întreagă. "
        "Această a doua propoziție este intenționat foarte lungă pentru a verifica faptul că "
        "generatorul o împarte în fragmente mai mici fără să piardă vreun cuvânt important."
    )
    clauses = HiggsNativeTtsAdapter._split_clauses(text, max_words=12, max_chars=100)

    assert len(clauses) >= 3
    assert all(len(clause.split()) <= 12 for clause in clauses)
    assert " ".join(clauses).replace("  ", " ") == text


def test_native_adapter_uses_dll_streaming_and_common_voice_profile() -> None:
    source = Path(
        "runtime/inference/adapters/tts/higgs_native_tts_adapter.py"
    ).read_text(encoding="utf-8")

    assert "audiocpp_generate_voice_clone_stream" in source
    assert '"reference_cache_path"' in source
    assert "resolve_profile_reference(" in source
    assert "heavy_gpu_inference()" in source
