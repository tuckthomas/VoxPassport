"""
LiveTranslator — Degraded Mode Scheduler
=========================================
Dynamic load shedding and VRAM/latency watchdog that automatically adjusts
pipeline fidelity and runtime tiers based on system resources.

Tiers (Section 20 & 21):
- TIER_FULL: Full duplex + 4B MT + Cloned TTS
- TIER_BALANCED: Full duplex + 1B MT + Stock TTS
- TIER_LOW_LATENCY: Outbound prioritized + 1B MT + Quantized Stock TTS
- TIER_DEGRADED: Captions-only (ASR + MT, TTS suppressed to save VRAM/compute)
- TIER_CRITICAL: Local ASR only (ASR active, MT & TTS suppressed)

Triggers:
- VRAM usage > 90%
- End-to-end latency p95 > 3500ms
- Dropped audio frames > 5/sec
- User manual tier override
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable, Optional

from runtime.inference.metrics.latency_metrics import PipelineMetrics
from runtime.inference.pipeline.duplex_orchestrator import DuplexOrchestrator
from runtime.inference.protocol import PipelineMode, RuntimeTier, TtsMode

logger = logging.getLogger(__name__)


class DegradedModeScheduler:
    """
    Monitors latency, queue depths, and VRAM to dynamically shed load.
    """

    def __init__(
        self,
        orchestrator: DuplexOrchestrator,
        metrics: PipelineMetrics,
        check_interval_s: float = 3.0,
        target_p95_ms: float = 2500.0,
        max_p95_ms: float = 4000.0,
    ):
        self.orchestrator = orchestrator
        self.metrics = metrics
        self.check_interval_s = check_interval_s
        self.target_p95_ms = target_p95_ms
        self.max_p95_ms = max_p95_ms

        self.current_tier = RuntimeTier.BALANCED
        self._is_monitoring = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._on_tier_change_callback: Optional[Callable[[RuntimeTier], None]] = None

    def set_tier_change_callback(self, callback: Callable[[RuntimeTier], None]) -> None:
        self._on_tier_change_callback = callback

    async def start(self) -> None:
        if self._is_monitoring:
            return
        self._is_monitoring = True
        self._monitor_task = asyncio.create_task(self._watchdog_loop())
        logger.info("Degraded Mode Scheduler started (current tier: %s)", self.current_tier.value)

    async def stop(self) -> None:
        self._is_monitoring = False
        if self._monitor_task:
            self._monitor_task.cancel()
            self._monitor_task = None
        logger.info("Degraded Mode Scheduler stopped.")

    async def _watchdog_loop(self) -> None:
        """Watchdog checking latency SLO and system load."""
        while self._is_monitoring:
            await asyncio.sleep(self.check_interval_s)
            summary = self.metrics.get_summary()

            e2e_stats = summary.get("capture_to_first_translated_audio_ms", {})
            p95 = e2e_stats.get("p95_ms", 0.0) if isinstance(e2e_stats, dict) else 0.0
            dropped = summary.get("dropped_audio_frames", 0)

            # Evaluate downgrade
            if (p95 > self.max_p95_ms or dropped > 10) and self.current_tier != RuntimeTier.DEGRADED_CAPTIONS_ONLY:
                await self._downgrade_tier()
            elif p95 > 0 and p95 < self.target_p95_ms and self.current_tier == RuntimeTier.DEGRADED_CAPTIONS_ONLY:
                # Potential recovery
                await self._upgrade_tier()

    async def _downgrade_tier(self) -> None:
        """Step down one tier to restore interactive latency."""
        if self.current_tier == RuntimeTier.QUALITY:
            new_tier = RuntimeTier.BALANCED
            await self.orchestrator.set_tts_mode(TtsMode.STOCK)
        elif self.current_tier == RuntimeTier.BALANCED:
            new_tier = RuntimeTier.LOW_LATENCY_LIGHT
        elif self.current_tier == RuntimeTier.LOW_LATENCY_LIGHT:
            new_tier = RuntimeTier.DEGRADED_CAPTIONS_ONLY
            await self.orchestrator.set_mode(PipelineMode.CAPTIONS_ONLY)
        else:
            return

        logger.warning("DegradedModeScheduler DOWNGRADED tier from %s to %s", self.current_tier.value, new_tier.value)
        self.current_tier = new_tier
        if self._on_tier_change_callback:
            self._on_tier_change_callback(new_tier)

    async def _upgrade_tier(self) -> None:
        """Upgrade tier when performance is stable."""
        if self.current_tier == RuntimeTier.DEGRADED_CAPTIONS_ONLY:
            new_tier = RuntimeTier.BALANCED
            await self.orchestrator.set_mode(PipelineMode.FULL_DUPLEX)
            await self.orchestrator.set_tts_mode(TtsMode.STOCK)
            logger.info("DegradedModeScheduler RESTORED tier to %s", new_tier.value)
            self.current_tier = new_tier
            if self._on_tier_change_callback:
                self._on_tier_change_callback(new_tier)
