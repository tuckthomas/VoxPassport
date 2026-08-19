"""
Unit tests for PhraseCommitter.

Tests:
  - Punctuation-based commit
  - Stable prefix duration commit
  - Endpoint silence commit
  - Max unsent duration commit
  - Multiple utterances independent
  - Context window accumulation
  - Context reset
  - Committed prefix tracking
"""

from __future__ import annotations

import asyncio
import time
import unittest
from unittest.mock import MagicMock

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from runtime.inference.pipeline.phrase_committer import (
    CommittedPhrase,
    PhraseCommitter,
    PhraseCommitterConfig,
)
from runtime.inference.protocol import (
    LanguageCode,
    TranscriptEvent,
    TranscriptState,
)


def make_event(
    uid: str,
    text: str,
    state: TranscriptState = TranscriptState.PARTIAL,
    revision: int = 0,
) -> TranscriptEvent:
    return TranscriptEvent(
        utterance_id=uid,
        revision=revision,
        source_language=LanguageCode.EN,
        text=text,
        state=state,
    )


class TestPhraseCommitter(unittest.TestCase):

    def setUp(self):
        self.commits: list[CommittedPhrase] = []
        self.config = PhraseCommitterConfig(
            commit_at_punctuation=True,
            stable_prefix_duration_ms=200.0,
            commit_after_endpoint_silence=True,
            stable_revision_word_count=3,
            stable_revision_count=3,
            max_unsent_phrase_ms=500.0,
            max_context_segments=3,
        )
        self.committer = PhraseCommitter(
            config=self.config,
            on_commit=self.commits.append,
            source_language=LanguageCode.EN,
        )

    def test_punctuation_commit(self):
        """Should commit when a sentence-ending punctuation mark appears."""
        self.committer.on_transcript_event(make_event("u1", "Hello world.", revision=0))
        self.assertEqual(len(self.commits), 1)
        self.assertEqual(self.commits[0].text, "Hello world.")
        self.assertEqual(self.commits[0].committed_reason, "punctuation")

    def test_no_commit_without_punctuation(self):
        """Should not commit when text has no punctuation."""
        self.committer.on_transcript_event(make_event("u1", "Hello world", revision=0))
        self.assertEqual(len(self.commits), 0)

    def test_final_event_forces_commit(self):
        """FINAL ASR event should force commit of any uncommitted text."""
        self.committer.on_transcript_event(make_event("u1", "Hello world", revision=0))
        self.assertEqual(len(self.commits), 0)
        self.committer.on_transcript_event(make_event("u1", "Hello world", state=TranscriptState.FINAL, revision=1))
        self.assertEqual(len(self.commits), 1)
        self.assertEqual(self.commits[0].text, "Hello world")
        self.assertEqual(self.commits[0].committed_reason, "endpoint")

    def test_endpoint_commit(self):
        """on_endpoint_detected should force commit."""
        self.committer.on_transcript_event(make_event("u1", "How are you", revision=0))
        self.assertEqual(len(self.commits), 0)
        self.committer.on_endpoint_detected("u1", time.monotonic_ns())
        self.assertEqual(len(self.commits), 1)
        self.assertEqual(self.commits[0].text, "How are you")
        self.assertEqual(self.commits[0].committed_reason, "endpoint")

    def test_no_double_commit_on_empty(self):
        """Should not commit if there's no uncommitted text."""
        self.committer.on_endpoint_detected("u99", time.monotonic_ns())
        self.assertEqual(len(self.commits), 0)

    def test_flush_all(self):
        """flush_all() should commit all open utterances."""
        self.committer.on_transcript_event(make_event("u1", "First sentence", revision=0))
        self.committer.on_transcript_event(make_event("u2", "Second sentence", revision=0))
        self.assertEqual(len(self.commits), 0)
        self.committer.flush_all()
        self.assertEqual(len(self.commits), 2)
        texts = {c.text for c in self.commits}
        self.assertIn("First sentence", texts)
        self.assertIn("Second sentence", texts)

    def test_multiple_utterances_independent(self):
        """Multiple utterances should not interfere with each other."""
        self.committer.on_transcript_event(make_event("u1", "Hello.", revision=0))
        self.committer.on_transcript_event(make_event("u2", "World.", revision=0))
        self.assertEqual(len(self.commits), 2)
        committed_texts = {c.text for c in self.commits}
        self.assertIn("Hello.", committed_texts)
        self.assertIn("World.", committed_texts)

    def test_context_window_accumulation(self):
        """Context from previous commits should accumulate up to max_context_segments."""
        self.committer.add_translation_to_context("Hello.", "Bună.")
        self.committer.add_translation_to_context("How are you?", "Ce mai faci?")
        self.committer.on_transcript_event(make_event("u1", "I'm fine.", revision=0))
        # Force commit
        self.committer.flush_all()
        self.assertEqual(len(self.commits), 1)
        ctx = self.commits[0].context
        self.assertEqual(ctx.recent_source_segments, ["Hello.", "How are you?"])
        self.assertEqual(ctx.recent_translated_segments, ["Bună.", "Ce mai faci?"])

    def test_context_reset(self):
        """reset_context() should clear the context window."""
        self.committer.add_translation_to_context("Hello.", "Bună.")
        self.committer.reset_context()
        self.committer.on_transcript_event(make_event("u1", "Next topic.", revision=0))
        self.committer.flush_all()
        ctx = self.commits[0].context
        self.assertEqual(ctx.recent_source_segments, [])

    def test_question_mark_commits(self):
        """Question mark should also trigger a commit."""
        self.committer.on_transcript_event(make_event("u1", "Are you ready?", revision=0))
        self.assertEqual(len(self.commits), 1)

    def test_exclamation_mark_commits(self):
        """Exclamation mark should trigger a commit."""
        self.committer.on_transcript_event(make_event("u1", "Stop!", revision=0))
        self.assertEqual(len(self.commits), 1)

    def test_utterance_cleaned_up_after_final(self):
        """Utterance state should be removed after FINAL event."""
        self.committer.on_transcript_event(make_event("u1", "Done.", state=TranscriptState.FINAL))
        self.assertNotIn("u1", self.committer._utterances)

    def test_utterance_cleaned_up_after_endpoint(self):
        """Utterance state should be removed after on_endpoint_detected."""
        self.committer.on_transcript_event(make_event("u1", "Some text"))
        self.committer.on_endpoint_detected("u1", time.monotonic_ns())
        self.assertNotIn("u1", self.committer._utterances)


class TestPhraseCommitterMaxDuration(unittest.TestCase):
    """Tests that require time manipulation for max_unsent_phrase_ms."""

    def test_max_duration_commit_logic(self):
        """
        The max_unsent_phrase_ms logic uses monotonic time internally.
        We test it by using a very small timeout and sleeping briefly.
        """
        commits = []
        config = PhraseCommitterConfig(
            commit_at_punctuation=False,
            stable_prefix_duration_ms=99999.0,   # effectively disabled
            commit_after_endpoint_silence=False,
            stable_revision_count=9999,
            max_unsent_phrase_ms=50.0,  # 50ms timeout
        )
        committer = PhraseCommitter(
            config=config,
            on_commit=commits.append,
            source_language=LanguageCode.EN,
        )

        committer.on_transcript_event(
            TranscriptEvent(
                utterance_id="u1",
                revision=0,
                source_language=LanguageCode.EN,
                text="Time sensitive phrase",
                state=TranscriptState.PARTIAL,
            )
        )
        self.assertEqual(len(commits), 0, "Should not commit before timeout")

        time.sleep(0.08)  # 80ms — exceeds 50ms timeout

        # Trigger check by sending another event
        committer.on_transcript_event(
            TranscriptEvent(
                utterance_id="u1",
                revision=1,
                source_language=LanguageCode.EN,
                text="Time sensitive phrase more",
                state=TranscriptState.PARTIAL,
            )
        )
        self.assertEqual(len(commits), 1, "Should commit after max_unsent_phrase_ms")
        self.assertEqual(commits[0].committed_reason, "max_duration")


if __name__ == "__main__":
    unittest.main()
