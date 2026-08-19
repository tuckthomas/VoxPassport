"""Phrase stabilization and commit logic for streaming ASR hypotheses."""

from __future__ import annotations

import logging
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Optional

from runtime.inference.protocol import LanguageCode, TranscriptEvent, TranscriptState, TranslationContext

logger = logging.getLogger(__name__)


@dataclass
class PhraseCommitterConfig:
    commit_at_punctuation: bool = True
    stable_prefix_duration_ms: float = 800.0
    commit_after_endpoint_silence: bool = True
    stable_revision_word_count: int = 5
    stable_revision_count: int = 3
    max_unsent_phrase_ms: float = 1800.0
    max_context_segments: int = 5
    strong_punctuation_pattern: str = r"[.!?]"


@dataclass
class CommittedPhrase:
    utterance_id: str
    text: str
    source_language: LanguageCode
    context: TranslationContext
    committed_at_ns: int = field(default_factory=time.monotonic_ns)
    committed_reason: str = ""


class PhraseCommitter:
    _STRONG_PUNCTUATION = re.compile(r"[.!?]\s*$")

    def __init__(
        self,
        config: PhraseCommitterConfig,
        on_commit: Callable[[CommittedPhrase], None],
        source_language: LanguageCode,
    ) -> None:
        self._config = config
        self._on_commit = on_commit
        self._source_language = source_language
        self._utterances: dict[str, _UtteranceState] = {}
        self._context_window: deque[tuple[str, str]] = deque(maxlen=config.max_context_segments)

    def on_transcript_event(self, event: TranscriptEvent) -> None:
        uid = event.utterance_id
        state = self._utterances.get(uid)
        if state is None:
            state = _UtteranceState(uid, self._config)
            self._utterances[uid] = state

        # The previous implementation committed FINAL before applying the final
        # text, dropping words that appeared only in the endpoint hypothesis.
        state.update(event.text, event.revision)
        if event.state == TranscriptState.FINAL:
            self._try_commit(state, reason="endpoint", force=True)
            self._utterances.pop(uid, None)
            return
        self._check_commit_conditions(state)

    def on_endpoint_detected(self, utterance_id: str, timestamp_ns: int) -> None:
        state = self._utterances.get(utterance_id)
        if state is not None and self._config.commit_after_endpoint_silence:
            self._try_commit(state, reason="endpoint", force=True)
            self._utterances.pop(utterance_id, None)

    def flush_all(self) -> None:
        for uid, state in list(self._utterances.items()):
            self._try_commit(state, reason="flush", force=True)
            self._utterances.pop(uid, None)

    def add_translation_to_context(self, source_text: str, translated_text: str) -> None:
        self._context_window.append((source_text, translated_text))

    def reset_context(self) -> None:
        self._context_window.clear()

    def _check_commit_conditions(self, state: "_UtteranceState") -> None:
        text = state.uncommitted_text.strip()
        if not text:
            return
        now_ms = time.monotonic() * 1000.0
        if self._config.commit_at_punctuation and self._STRONG_PUNCTUATION.search(text):
            self._try_commit(state, "punctuation")
            return
        if state.uncommitted_since_ms is not None and now_ms - state.uncommitted_since_ms >= self._config.max_unsent_phrase_ms:
            self._try_commit(state, "max_duration")
            return
        if state.stable_prefix_since_ms is not None and now_ms - state.stable_prefix_since_ms >= self._config.stable_prefix_duration_ms:
            self._try_commit(state, "stable_prefix")
            return
        if state.stable_revision_count >= self._config.stable_revision_count:
            self._try_commit(state, "stable_revision")

    def _try_commit(self, state: "_UtteranceState", reason: str, force: bool = False) -> None:
        text = state.uncommitted_text.strip()
        if not text:
            return
        context = TranslationContext(
            recent_source_segments=[s for s, _ in self._context_window],
            recent_translated_segments=[t for _, t in self._context_window],
        )
        phrase = CommittedPhrase(
            utterance_id=state.utterance_id,
            text=text,
            source_language=self._source_language,
            context=context,
            committed_reason=reason,
        )
        state.mark_committed(text)
        self._on_commit(phrase)


class _UtteranceState:
    def __init__(self, utterance_id: str, config: PhraseCommitterConfig) -> None:
        self.utterance_id = utterance_id
        self._config = config
        self._committed_prefix = ""
        self._current_text = ""
        self._last_word_prefix = ""
        self.stable_prefix_since_ms: Optional[float] = None
        self.stable_revision_count = 0
        self.uncommitted_since_ms: Optional[float] = None

    @property
    def uncommitted_text(self) -> str:
        if not self._committed_prefix:
            return self._current_text
        if self._current_text.startswith(self._committed_prefix):
            return self._current_text[len(self._committed_prefix):]
        # Do not re-speak an already committed prefix merely because ASR changed
        # punctuation/spacing. Find the longest common prefix and conservatively
        # return only text after the committed character span.
        common = 0
        for a, b in zip(self._committed_prefix, self._current_text):
            if a != b:
                break
            common += 1
        if common >= int(len(self._committed_prefix) * 0.8):
            return self._current_text[min(len(self._committed_prefix), len(self._current_text)):]
        logger.warning("ASR substantially revised already-committed text for %s", self.utterance_id[:8])
        return self._current_text

    def update(self, text: str, revision: int) -> None:
        text = str(text or "").strip()
        now_ms = time.monotonic() * 1000.0
        if self.uncommitted_since_ms is None and text:
            self.uncommitted_since_ms = now_ms
        words = text.split()
        n = self._config.stable_revision_word_count
        prefix = " ".join(words[:n]) if len(words) >= n else ""
        if prefix and prefix == self._last_word_prefix:
            self.stable_revision_count += 1
            if self.stable_prefix_since_ms is None:
                self.stable_prefix_since_ms = now_ms
        else:
            self._last_word_prefix = prefix
            self.stable_revision_count = 0
            self.stable_prefix_since_ms = None
        self._current_text = text

    def mark_committed(self, committed_text: str) -> None:
        start = len(self._committed_prefix)
        idx = self._current_text.find(committed_text, start)
        if idx >= 0:
            self._committed_prefix = self._current_text[: idx + len(committed_text)]
        else:
            self._committed_prefix = (self._committed_prefix + " " + committed_text).strip()
        self.uncommitted_since_ms = None
        self.stable_prefix_since_ms = None
        self.stable_revision_count = 0
