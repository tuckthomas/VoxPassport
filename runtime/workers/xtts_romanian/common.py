"""Pure helpers shared by the XTTS Romanian worker and its adapter.

This module deliberately has no torch/Coqui imports so unit tests can exercise
normalization, profile reference selection, and cache invalidation without
installing the optional XTTS worker environment.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

CEDILLA_TO_COMMA = str.maketrans({
    "ş": "ș",
    "ţ": "ț",
    "Ş": "Ș",
    "Ţ": "Ț",
})

_LANGUAGE_ALIASES = {
    "en": "en",
    "english": "en",
    "en-us": "en",
    "en-gb": "en",
    "ro": "ro",
    "romanian": "ro",
    "ro-ro": "ro",
}


def normalize_language(value: str) -> str:
    """Return the XTTS language code supported by this worker."""
    clean = str(value or "").strip().lower().replace("_", "-")
    language = _LANGUAGE_ALIASES.get(clean, clean.split("-", 1)[0])
    if language not in {"en", "ro"}:
        raise ValueError(f"XTTS Romanian worker only supports English/Romanian, got {value!r}")
    return language


def normalize_romanian_text(text: str) -> str:
    """Normalize legacy Romanian cedillas and collapse transport whitespace."""
    clean = str(text or "").translate(CEDILLA_TO_COMMA)
    return re.sub(r"\s+", " ", clean).strip()


def prepare_text(text: str, language: str) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if normalize_language(language) == "ro":
        clean = normalize_romanian_text(clean)
    if not clean:
        raise ValueError("XTTS synthesis text must not be empty")
    return clean


def dynamic_max_new_tokens(text: str) -> int:
    """Bound Romanian generation as recommended by the fine-tune author."""
    words = len(str(text or "").split())
    return max(min(max(words, 1) * 50, 500), 150)


def split_live_clauses(text: str, *, max_words: int = 15, max_chars: int = 180) -> list[str]:
    """Keep live autoregressive requests short while preserving punctuation."""
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if not clean:
        return []
    clauses: list[str] = []
    for sentence in re.split(r"(?<=[.!?;:])\s+", clean):
        pending = ""
        for piece in re.split(r"(?<=,)\s+", sentence):
            candidate = f"{pending} {piece}".strip()
            if pending and (len(candidate) > max_chars or len(candidate.split()) > max_words):
                clauses.append(pending)
                pending = piece
            else:
                pending = candidate
        if pending:
            words = pending.split()
            while len(words) > max_words or len(" ".join(words)) > max_chars:
                take = min(max_words, len(words))
                while take > 1 and len(" ".join(words[:take])) > max_chars:
                    take -= 1
                clauses.append(" ".join(words[:take]))
                words = words[take:]
            if words:
                clauses.append(" ".join(words))
    return clauses


def target_conditioning_reference(profile_dir: Path | str, language: str) -> Path | None:
    """Return an optional derived target-language reference without replacing identity.

    Canonical identity remains ``reference.wav``.  Offline teacher-generated
    conditioning audio lives under ``conditioning/<lang>.wav``.  A flat legacy
    filename is accepted to make earlier experiments easy to reuse.
    """
    root = Path(profile_dir)
    lang = normalize_language(language)
    candidates = [
        root / "conditioning" / f"{lang}.wav",
        root / f"conditioning_{lang}.wav",
    ]
    return next((path for path in candidates if path.exists()), None)


def file_fingerprint(path: Path | str | None) -> str:
    if path is None:
        return "none"
    candidate = Path(path)
    if not candidate.exists():
        return f"missing:{candidate.resolve()}"
    stat = candidate.stat()
    material = f"{candidate.resolve()}\0{stat.st_size}\0{stat.st_mtime_ns}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:20]


def conditioning_cache_key(
    canonical_reference: Path | str,
    target_reference: Path | str | None,
    language: str,
) -> str:
    material = "\0".join([
        normalize_language(language),
        file_fingerprint(canonical_reference),
        file_fingerprint(target_reference),
    ])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
