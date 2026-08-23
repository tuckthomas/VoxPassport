from __future__ import annotations

from pathlib import Path

from runtime.workers.tts_host.drivers.xtts_common import (
    conditioning_cache_key,
    dynamic_max_new_tokens,
    normalize_language,
    normalize_romanian_text,
    split_live_clauses,
    target_conditioning_reference,
)


def test_romanian_cedillas_are_normalized_to_comma_below() -> None:
    assert normalize_romanian_text("Ştefan şi Ţara ţării") == "Ștefan și Țara țării"


def test_language_aliases_cover_live_english_romanian_names() -> None:
    assert normalize_language("English") == "en"
    assert normalize_language("ro-RO") == "ro"


def test_dynamic_generation_limit_matches_romanian_recipe() -> None:
    assert dynamic_max_new_tokens("salut") == 150
    assert dynamic_max_new_tokens(" ".join(["cuvânt"] * 5)) == 250
    assert dynamic_max_new_tokens(" ".join(["cuvânt"] * 20)) == 500


def test_live_clause_splitting_is_bounded() -> None:
    text = " ".join(f"cuvânt{i}" for i in range(40))
    clauses = split_live_clauses(text)
    assert len(clauses) >= 3
    assert all(len(clause.split()) <= 15 for clause in clauses)
    assert all(len(clause) <= 180 for clause in clauses)


def test_target_language_conditioning_does_not_replace_canonical_reference(tmp_path: Path) -> None:
    canonical = tmp_path / "reference.wav"
    canonical.write_bytes(b"real-speaker")
    conditioning = tmp_path / "conditioning"
    conditioning.mkdir()
    derived = conditioning / "ro.wav"
    derived.write_bytes(b"teacher-generated-romanian")

    assert canonical.read_bytes() == b"real-speaker"
    assert target_conditioning_reference(tmp_path, "Romanian") == derived


def test_conditioning_cache_key_changes_when_target_reference_changes(tmp_path: Path) -> None:
    canonical = tmp_path / "reference.wav"
    canonical.write_bytes(b"real-speaker")
    conditioning = tmp_path / "conditioning"
    conditioning.mkdir()
    derived = conditioning / "ro.wav"
    derived.write_bytes(b"teacher-v1")
    first = conditioning_cache_key(canonical, derived, "ro")

    derived.write_bytes(b"teacher-v2-with-a-different-size")
    second = conditioning_cache_key(canonical, derived, "ro")
    assert first != second


def test_no_target_reference_falls_back_cleanly(tmp_path: Path) -> None:
    (tmp_path / "reference.wav").write_bytes(b"real-speaker")
    assert target_conditioning_reference(tmp_path, "ro") is None
