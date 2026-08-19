"""
LiveTranslator - Hot-Swap State Machine
========================================
Safe model swapping without interrupting active utterances.

State transitions (Section 16A.3):
  REQUESTED -> PRELOADING -> READY -> DRAINING_OLD_MODEL -> ACTIVE
                                                          -> FAILED -> ROLLED_BACK

Rules:
  - Never switch mid-utterance. Wait for current committed phrase to finish.
  - Preload new model before unloading old when VRAM permits.
  - Run health check on new adapter before activating.
  - Auto-rollback to prior known-good on any failure.
  - Only content-free failure info is logged (no transcripts/audio).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from runtime.inference.protocol import HotSwapState, ModelCapability

logger = logging.getLogger(__name__)


@dataclass
class HotSwapRequest:
    """Describes a requested model swap for one capability slot."""
    slot: str                   # e.g. "asr_en", "translation_en_ro"
    model_id: str               # target model to activate
    capability: ModelCapability
    requested_at: float = field(default_factory=time.time)
    state: HotSwapState = HotSwapState.REQUESTED
    error: Optional[str] = None
    rolled_back_to: Optional[str] = None


class HotSwapController:
    """
    Orchestrates safe hot-swapping of model adapters.

    Usage:
        controller = HotSwapController(registry, orchestrator)
        async for event in controller.swap(slot="asr_en", new_model_id="..."):
            send_to_ui(event)
    """

    def __init__(
        self,
        registry,                           # ModelRegistry
        get_adapter: Callable[[str], object],  # slot -> current loaded adapter
        load_adapter: Callable[[str, str], Awaitable[object]],   # (slot, model_id) -> adapter
        unload_adapter: Callable[[str, object], Awaitable[None]],  # (slot, adapter) -> None
        health_check: Callable[[object], Awaitable[bool]],         # adapter -> bool
        drain_slot: Callable[[str], Awaitable[None]],              # slot -> drain in-flight work
        vram_headroom_gb: float = 1.0,
    ):
        self.registry = registry
        self._get_adapter = get_adapter
        self._load_adapter = load_adapter
        self._unload_adapter = unload_adapter
        self._health_check = health_check
        self._drain_slot = drain_slot
        self.vram_headroom_gb = vram_headroom_gb

        self._active_swaps: dict[str, HotSwapRequest] = {}

    async def swap(
        self,
        slot: str,
        new_model_id: str,
        capability: ModelCapability = ModelCapability.ASR,
    ):
        """
        Async generator yielding HotSwapRequest state updates.

        Caller must consume all events to drive the swap to completion.
        """
        req = HotSwapRequest(slot=slot, model_id=new_model_id, capability=capability)
        self._active_swaps[slot] = req

        prior_model_id = self.registry.get_active_model_id(
            capability.value, language=slot.split("_")[-1]
        )

        try:
            # REQUESTED -> PRELOADING
            req.state = HotSwapState.PRELOADING
            yield req
            logger.info("[HotSwap] Preloading %s for slot %s", new_model_id, slot)

            new_adapter = await self._load_adapter(slot, new_model_id)
            if new_adapter is None:
                raise RuntimeError(f"Adapter load returned None for {new_model_id!r}")

            # PRELOADING -> READY
            req.state = HotSwapState.READY
            yield req

            # Health check on new adapter
            healthy = await self._health_check(new_adapter)
            if not healthy:
                raise RuntimeError(f"Health check failed for new adapter {new_model_id!r}")

            # READY -> DRAINING_OLD_MODEL
            req.state = HotSwapState.DRAINING_OLD_MODEL
            yield req
            logger.info("[HotSwap] Draining slot %s before swap", slot)

            # Wait for current utterance to complete (max 5 seconds)
            try:
                await asyncio.wait_for(self._drain_slot(slot), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("[HotSwap] Drain timeout for slot %s — proceeding with swap.", slot)

            # Unload old adapter
            old_adapter = self._get_adapter(slot)
            if old_adapter is not None:
                await self._unload_adapter(slot, old_adapter)

            # Activate new model in registry
            self.registry.set_active_model(capability.value, new_model_id)

            # DRAINING_OLD_MODEL -> ACTIVE
            req.state = HotSwapState.ACTIVE
            yield req
            logger.info("[HotSwap] Slot %s now using %s", slot, new_model_id)

        except Exception as exc:
            # FAILED -> ROLLED_BACK
            error_msg = type(exc).__name__  # content-free — no transcript/audio info
            logger.error("[HotSwap] Slot %s swap to %s FAILED: %s", slot, new_model_id, error_msg)
            req.state = HotSwapState.FAILED
            req.error = error_msg
            yield req

            # Attempt rollback
            if prior_model_id:
                logger.info("[HotSwap] Rolling back slot %s to %s", slot, prior_model_id)
                try:
                    await self._load_adapter(slot, prior_model_id)
                    self.registry.set_active_model(capability.value, prior_model_id)
                    req.state = HotSwapState.ROLLED_BACK
                    req.rolled_back_to = prior_model_id
                    yield req
                    logger.info("[HotSwap] Rollback successful: slot %s restored to %s", slot, prior_model_id)
                except Exception as rollback_exc:
                    logger.error(
                        "[HotSwap] Rollback also failed for slot %s: %s",
                        slot, type(rollback_exc).__name__,
                    )

        finally:
            self._active_swaps.pop(slot, None)

    def is_swap_in_progress(self, slot: str) -> bool:
        return slot in self._active_swaps

    def get_active_swap(self, slot: str) -> Optional[HotSwapRequest]:
        return self._active_swaps.get(slot)
