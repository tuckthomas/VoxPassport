"""
LiveTranslator — Benchmark Corpus Harness
==========================================
Loads and manages the EN↔RO evaluation corpus for model bakeoffs.

Corpus format (JSONL — one utterance per line):
{
  "utterance_id": "en-ro-001",
  "source_language": "en",
  "target_language": "ro",
  "source_text": "Hello, how are you?",
  "reference_translation": "Bună, ce mai faci?",
  "alternative_translations": ["Bună ziua, cum ești?"],
  "audio_file": "fixtures/audio/en-ro-001.wav",  // optional
  "category": "greetings",
  "named_entities": ["..."],
  "numbers": [],
  "must_preserve": [],
  "notes": ""
}

Categories (Section 26.1 of plan):
  greetings, long_sentences, short_acknowledgments, questions,
  interruptions, false_starts, filler_words, fast_speech, slow_speech,
  quiet_speech, background_noise, different_microphones, proper_names,
  romanian_personal_names, romanian_place_names, us_place_names,
  dates, times, currency, percentages, phone_numbers, addresses,
  technical_terminology, business_terminology, code_switching,
  english_romanian_names, romanian_accented_english, english_accented_romanian
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

logger = logging.getLogger(__name__)


@dataclass
class CorpusEntry:
    utterance_id: str
    source_language: str
    target_language: str
    source_text: str
    reference_translation: str
    alternative_translations: list[str] = field(default_factory=list)
    audio_file: Optional[str] = None
    category: str = "general"
    named_entities: list[str] = field(default_factory=list)
    numbers: list[str] = field(default_factory=list)
    must_preserve: list[str] = field(default_factory=list)
    notes: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "CorpusEntry":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})  # type: ignore[attr-defined]


class BenchmarkCorpus:
    """
    Loads and filters the EN↔RO evaluation corpus.

    Usage:
        corpus = BenchmarkCorpus.load(Path("tests/fixtures/corpus/en_ro_corpus.jsonl"))
        for entry in corpus.iter_direction("en", "ro"):
            result = adapter.translate(entry.source_text, "en", "ro")
            # compute metrics against entry.reference_translation
    """

    def __init__(self, entries: list[CorpusEntry]):
        self._entries = entries
        logger.info("Corpus loaded: %d entries", len(entries))

    @classmethod
    def load(cls, path: Path) -> "BenchmarkCorpus":
        """Load corpus from a JSONL file."""
        if not path.exists():
            logger.warning("Corpus file not found: %s. Using empty corpus.", path)
            return cls([])
        entries = []
        with open(path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    d = json.loads(line)
                    entries.append(CorpusEntry.from_dict(d))
                except (json.JSONDecodeError, TypeError) as e:
                    logger.warning("Corpus parse error at line %d: %s", lineno, e)
        return cls(entries)

    def iter_direction(
        self,
        source_language: str,
        target_language: str,
        categories: Optional[list[str]] = None,
    ) -> Iterator[CorpusEntry]:
        for entry in self._entries:
            if entry.source_language != source_language:
                continue
            if entry.target_language != target_language:
                continue
            if categories and entry.category not in categories:
                continue
            yield entry

    def filter_by_category(self, category: str) -> list[CorpusEntry]:
        return [e for e in self._entries if e.category == category]

    def __len__(self) -> int:
        return len(self._entries)

    def summary(self) -> dict:
        from collections import Counter
        cats = Counter(e.category for e in self._entries)
        dirs = Counter(f"{e.source_language}→{e.target_language}" for e in self._entries)
        return {
            "total_entries": len(self._entries),
            "categories": dict(cats),
            "directions": dict(dirs),
        }
