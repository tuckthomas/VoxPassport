"""
LiveTranslator — PhraseCommitter
==================================
Determines when ASR partial transcripts are stable enough to commit
for translation and TTS synthesis.

Critical design constraint (Section 10 of plan):
  Do NOT translate and speak every raw ASR partial.
  Partial hypotheses are revisionable. Speaking incorrect words causes
  audio that cannot be "unsaid."

Commit rules (all configurable):
  1. Commit at strong punctuation when available.
  2. Commit after a stable-prefix duration (same prefix surviving multiple revisions).
  3. Commit after endpoint silence (VAD end event).
  4. Commit when the same word prefix survives N ASR revisions.
  5. Enforce a maximum unsent phrase duration to cap latency.
  6. Prefer phrase/clause boundaries over arbitrary token counts.

Context rules:
  - Send recent committed source context with current segment.
  - Do not resend already-spoken text as new TTS.
  - Preserve conversation context separately from the exact phrase being synthesized.
  - Reset context when language direction or speaker changes materially.
"""

from __future__ import annotations

import re
import time
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Optional

from runtime.inference.protocol import (
    LanguageCode,
    TranscriptEvent,
    TranscriptState,
    TranslationContext,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class PhraseCommitterConfig:
    """Tuning parameters for commit decisions."""

    # Commit at punctuation (period, question mark, exclamation)
    commit_at_punctuation: bool = True

    # Commit after this many milliseconds with a stable prefix (no revision)
    stable_prefix_duration_ms: float = 800.0

    # Commit after endpoint silence detected (VAD SPEECH_END)
    commit_after_endpoint_silence: bool = True

    # Commit if the same N-word prefix has survived M ASR revisions
    stable_revision_word_count: int = 5
    stable_revision_count: int = 3

    # Hard cap: commit regardless of other rules after this duration
    max_unsent_phrase_ms: float = 1800.0

    # Maximum recent context segments to send with each translation
    max_context_segments: int = 5

    # Strong punctuation patterns that signal a commit boundary
    strong_punctuation_pattern: str = r"[.!?]"


# ---------------------------------------------------------------------------
# Committed phrase
# ---------------------------------------------------------------------------

@dataclass
class CommittedPhrase:
    """A phrase approved for translation and TTS synthesis."""
    utterance_id: str
    text: str
    source_language: LanguageCode
    context: TranslationContext
    committed_at_ns: int = field(default_factory=time.monotonic_ns)
    committed_reason: str = ""  # "punctuation" | "stable_prefix" | "endpoint" | "max_duration"


# ---------------------------------------------------------------------------
# PhraseCommitter
# ---------------------------------------------------------------------------

class PhraseCommitter:
    """
    Manages a rolling buffer of ASR partial transcripts per utterance
    and decides when to commit a phrase for translation.

    One PhraseCommitter instance is created per pipeline direction
    (outbound English, inbound Romanian).

    Usage:
        committer = PhraseCommitter(config=config, on_commit=handle_commit)

        # Feed ASR events as they arrive:
        committer.on_transcript_event(event)

        # Feed VAD end events to trigger endpoint commits:
        committer.on_endpoint_detected(utterance_id, timestamp_ns)
    """

    _STRONG_PUNCTUATION = re.compile(r"[.!?]\s*$")

    def __init__(
        self,
        config: PhraseCommitterConfig,
        on_commit: Callable[[CommittedPhrase], None],
        source_language: LanguageCode,
    ):
        self._config = config
        self._on_commit = on_commit
        self._source_language = source_language

        # Per-utterance state: utterance_id → _UtteranceState
        self._utterances: dict[str, "_UtteranceState"] = {}

        # Rolling conversation context
        self._context_window: deque[tuple[str, str]] = deque(
            maxlen=config.max_context_segments
        )  # [(source_text, translated_text), ...]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def on_transcript_event(self, event: TranscriptEvent) -> None:
        """
        Feed an ASR transcript event (partial, stable, or final) into the committer.
        """
        uid = event.utterance_id

        if uid not in self._utterances:
            self._utterances[uid] = _UtteranceState(
                utterance_id=uid,
                config=self._config,
            )

        state = self._utterances[uid]

        if event.state == TranscriptState.FINAL:
            # Final event: commit everything remaining
            self._try_commit(state, reason="endpoint", force=True)
            self._utterances.pop(uid, None)
            return

        state.update(event.text, event.revision)
        self._check_commit_conditions(state)

    def on_endpoint_detected(self, utterance_id: str, timestamp_ns: int) -> None:
        """
        Called when VAD signals end of speech for an utterance.
        Forces a commit of any uncommitted text.
        """
        state = self._utterances.get(utterance_id)
        if state is None:
            return
        if self._config.commit_after_endpoint_silence:
            self._try_commit(state, reason="endpoint", force=True)
            self._utterances.pop(utterance_id, None)

    def flush_all(self) -> None:
        """Force-commit all open utterances. Call when stopping the pipeline."""
        for uid in list(self._utterances.keys()):
            state = self._utterances[uid]
            self._try_commit(state, reason="flush", force=True)
        self._utterances.clear()

    def add_translation_to_context(self, source_text: str, translated_text: str) -> None:
        """
        Update the rolling conversation context after a translation is committed.
        Called by the translation layer once translation is complete.
        """
        self._context_window.append((source_text, translated_text))

    def reset_context(self) -> None:
        """Reset conversation context (e.g., on language/speaker change)."""
        self._context_window.clear()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _check_commit_conditions(self, state: "_UtteranceState") -> None:
        uncommitted = state.uncommitted_text.strip()
        if not uncommitted:
            return

        now_ms = time.monotonic() * 1000.0

        # Rule 1: Strong punctuation
        if self._config.commit_at_punctuation:
            if self._STRONG_PUNCTUATION.search(uncommitted):
                self._try_commit(state, reason="punctuation")
                return

        # Rule 2: Max unsent phrase duration
        if state.uncommitted_since_ms is not None:
            age_ms = now_ms - state.uncommitted_since_ms
            if age_ms >= self._config.max_unsent_phrase_ms:
                self._try_commit(state, reason="max_duration")
                return

        # Rule 3: Stable prefix duration
        if state.stable_prefix_since_ms is not None:
            stable_age_ms = now_ms - state.stable_prefix_since_ms
            if stable_age_ms >= self._config.stable_prefix_duration_ms:
                self._try_commit(state, reason="stable_prefix")
                return

        # Rule 4: Stable revisions (same word prefix survived N revisions)
        if state.stable_revision_count >= self._config.stable_revision_count:
            self._try_commit(state, reason="stable_revision")

    def _try_commit(
        self,
        state: "_UtteranceState",
        reason: str,
        force: bool = False,
    ) -> None:
        text_to_commit = state.uncommitted_text.strip()
        if not text_to_commit and not force:
            return
        if not text_to_commit:
            return

        context = TranslationContext(
            recent_source_segments=[s for s, _ in self._context_window],
            recent_translated_segments=[t for _, t in self._context_window],
        )

        phrase = CommittedPhrase(
            utterance_id=state.utterance_id,
            text=text_to_commit,
            source_language=self._source_language,
            context=context,
            committed_reason=reason,
        )

        logger.debug(
            "Committing phrase [%s] reason=%r text=%r",
            state.utterance_id[:8],
            reason,
            text_to_commit[:60],
        )

        state.mark_committed(text_to_commit)
        self._on_commit(phrase)


# ---------------------------------------------------------------------------
# Internal utterance state
# ---------------------------------------------------------------------------

class _UtteranceState:
    """Tracks the rolling state for one open utterance."""

    def __init__(self, utterance_id: str, config: PhraseCommitterConfig):
        self.utterance_id = utterance_id
        self._config = config

        # Full current text (including already-committed portions as prefix)
        self._committed_prefix: str = ""
        self._current_text: str = ""
        self._last_revision: int = -1

        # Stability tracking
        self._last_word_prefix: str = ""
        self._last_word_prefix_since_ms: Optional[float] = None
        self.stable_prefix_since_ms: Optional[float] = None
        self.stable_revision_count: int = 0

        # Timing
        self.uncommitted_since_ms: Optional[float] = None

    @property
    def uncommitted_text(self) -> str:
        """The portion of current text not yet committed."""
        if self._current_text.startswith(self._committed_prefix):
            return self._current_text[len(self._committed_prefix):]
        # ASR revised past the committed prefix — this should not happen.
        # Return the full current text and log a warning.
        logger.warning(
            "ASR revised past committed prefix for utterance %s. "
            "committed_prefix=%r current_text=%r",
            self.utterance_id[:8],
            self._committed_prefix,
            self._current_text[:60],
        )
        return self._current_text

    def update(self, text: str, revision: int) -> None:
        """Apply a new ASR hypothesis."""
        now_ms = time.monotonic() * 1000.0

        if self.uncommitted_since_ms is None and text.strip():
            self.uncommitted_since_ms = now_ms

        # Stable prefix tracking: how many N-word prefixes have been identical
        current_words = text.split()
        n = self._config.stable_revision_word_count
        word_prefix = " ".join(current_words[:n]) if len(current_words) >= n else ""

        if word_prefix and word_prefix == self._last_word_prefix:
            self.stable_revision_count += 1
            if self.stable_prefix_since_ms is None:
                self.stable_prefix_since_ms = now_ms
        else:
            self.stable_revision_count = 0
            self.stable_prefix_since_ms = None
            self._last_word_prefix = word_prefix

        self._current_text = text
        self._last_revision = revision

    def mark_committed(self, committed_text: str) -> None:
        """Record that committed_text has been sent to translation/TTS."""
        self._committed_prefix += committed_text
        self.uncommitted_since_ms = None
        self.stable_prefix_since_ms = None
        self.stable_revision_count = 0
