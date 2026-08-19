"""
LiveTranslator — Latency Metrics Tracker
==========================================
Content-free pipeline latency instrumentation.

All measurements are numeric-only — no speech content, no transcripts,
no translations, no audio are stored in metric records.

Tracks (Section 27.4 of plan):
  - Capture → source caption latency
  - Capture → translated caption latency
  - Capture → first translated audio latency
  - p50 / p95 / max per metric
  - Dropped audio frames
  - Queue depths
  - GPU memory peak
  - CPU memory peak
  - Audio feedback events
"""

from __future__ import annotations

import statistics
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Per-utterance latency record
# ---------------------------------------------------------------------------

@dataclass
class UtteranceMetrics:
    """Content-free latency measurements for one utterance."""
    utterance_id: str
    direction: str  # "outbound" (EN→RO) or "inbound" (RO→EN)
    capture_timestamp_ns: int = 0

    # Stage completions
    vad_speech_start_ns: Optional[int] = None
    vad_speech_end_ns: Optional[int] = None
    asr_first_partial_ns: Optional[int] = None
    asr_final_ns: Optional[int] = None
    mt_complete_ns: Optional[int] = None
    tts_first_chunk_ns: Optional[int] = None
    tts_complete_ns: Optional[int] = None

    # Derived
    @property
    def capture_to_asr_partial_ms(self) -> Optional[float]:
        if self.asr_first_partial_ns and self.capture_timestamp_ns:
            return (self.asr_first_partial_ns - self.capture_timestamp_ns) / 1e6
        return None

    @property
    def endpoint_to_asr_final_ms(self) -> Optional[float]:
        if self.vad_speech_end_ns and self.asr_final_ns:
            return (self.asr_final_ns - self.vad_speech_end_ns) / 1e6
        return None

    @property
    def translation_ms(self) -> Optional[float]:
        if self.asr_final_ns and self.mt_complete_ns:
            return (self.mt_complete_ns - self.asr_final_ns) / 1e6
        return None

    @property
    def tts_time_to_first_audio_ms(self) -> Optional[float]:
        if self.mt_complete_ns and self.tts_first_chunk_ns:
            return (self.tts_first_chunk_ns - self.mt_complete_ns) / 1e6
        return None

    @property
    def capture_to_first_translated_audio_ms(self) -> Optional[float]:
        if self.capture_timestamp_ns and self.tts_first_chunk_ns:
            return (self.tts_first_chunk_ns - self.capture_timestamp_ns) / 1e6
        return None


# ---------------------------------------------------------------------------
# Pipeline metrics aggregator
# ---------------------------------------------------------------------------

class PipelineMetrics:
    """
    Aggregates content-free latency metrics across utterances.
    Computes p50, p95, and max for all measured latency types.
    """

    # Rolling window size for percentile calculations
    WINDOW_SIZE = 100

    def __init__(self):
        # Rolling deques of latency values (ms)
        self._windows: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=self.WINDOW_SIZE)
        )
        # Counters
        self.dropped_audio_frames: int = 0
        self.audio_feedback_events: int = 0
        self.duplicate_translation_events: int = 0
        # Resource snapshots (updated externally)
        self.gpu_vram_used_mb: float = 0.0
        self.gpu_vram_total_mb: float = 0.0
        self.cpu_percent: float = 0.0
        self.gpu_utilization_percent: float = 0.0
        # Queue depths
        self.asr_queue_depth: int = 0
        self.mt_queue_depth: int = 0
        self.tts_queue_depth: int = 0

    def record_utterance(self, metrics: UtteranceMetrics) -> None:
        """Record all available latency values from a completed utterance."""
        def _add(name: str, value: Optional[float]) -> None:
            if value is not None and value >= 0:
                self._windows[name].append(value)

        _add("capture_to_asr_partial_ms", metrics.capture_to_asr_partial_ms)
        _add("endpoint_to_asr_final_ms", metrics.endpoint_to_asr_final_ms)
        _add("translation_ms", metrics.translation_ms)
        _add("tts_time_to_first_audio_ms", metrics.tts_time_to_first_audio_ms)
        _add("capture_to_first_translated_audio_ms", metrics.capture_to_first_translated_audio_ms)

    def get_summary(self) -> dict:
        """Return a content-free summary of all measured latencies."""
        result: dict = {
            "dropped_audio_frames": self.dropped_audio_frames,
            "audio_feedback_events": self.audio_feedback_events,
            "duplicate_translation_events": self.duplicate_translation_events,
            "gpu_vram_used_mb": self.gpu_vram_used_mb,
            "gpu_vram_total_mb": self.gpu_vram_total_mb,
            "cpu_percent": self.cpu_percent,
            "gpu_utilization_percent": self.gpu_utilization_percent,
            "asr_queue_depth": self.asr_queue_depth,
            "mt_queue_depth": self.mt_queue_depth,
            "tts_queue_depth": self.tts_queue_depth,
        }
        for name, window in self._windows.items():
            if not window:
                continue
            vals = sorted(window)
            n = len(vals)
            result[name] = {
                "count": n,
                "p50_ms": vals[n // 2],
                "p95_ms": vals[int(n * 0.95)],
                "max_ms": vals[-1],
                "mean_ms": statistics.mean(vals),
            }
        return result

    def check_latency_slo(self) -> list[str]:
        """
        Check whether current p50/p95 latency meets the SLOs defined in Section 19.
        Returns a list of violation messages (empty if all SLOs are met).
        """
        violations = []
        summary = self.get_summary()
        e2e = summary.get("capture_to_first_translated_audio_ms", {})
        if isinstance(e2e, dict):
            p50 = e2e.get("p50_ms", 0.0)
            p95 = e2e.get("p95_ms", 0.0)
            if p50 > 1500:
                violations.append(f"p50 end-to-end latency {p50:.0f}ms exceeds 1500ms target")
            if p95 > 2500:
                violations.append(f"p95 end-to-end latency {p95:.0f}ms exceeds 2500ms target")
            if e2e.get("max_ms", 0.0) > 5000:
                violations.append(f"Max end-to-end latency {e2e['max_ms']:.0f}ms exceeds 5000ms threshold")
        return violations
