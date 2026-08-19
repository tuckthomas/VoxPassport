"""Safe runtime model hot-swap state machine."""

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
    slot: str
    model_id: str
    capability: ModelCapability
    requested_at: float = field(default_factory=time.time)
    state: HotSwapState = HotSwapState.REQUESTED
    error: Optional[str] = None
    rolled_back_to: Optional[str] = None


class HotSwapController:
    """Preload, drain, bind, persist, and rollback one runtime slot."""

    def __init__(
        self,
        registry,
        get_adapter: Callable[[str], object],
        set_adapter: Callable[[str, object], None],
        load_adapter: Callable[[str, str], Awaitable[object]],
        unload_adapter: Callable[[str, object], Awaitable[None]],
        health_check: Callable[[object], Awaitable[bool]],
        drain_slot: Callable[[str], Awaitable[None]],
        vram_headroom_gb: float = 1.0,
    ) -> None:
        self.registry = registry
        self._get_adapter = get_adapter
        self._set_adapter = set_adapter
        self._load_adapter = load_adapter
        self._unload_adapter = unload_adapter
        self._health_check = health_check
        self._drain_slot = drain_slot
        self.vram_headroom_gb = vram_headroom_gb
        self._active_swaps: dict[str, HotSwapRequest] = {}

    def _persist_slot(self, slot: str, model_id: str) -> None:
        if slot == "asr_en":
            self.registry.set_active_model("ASR", model_id, language="en")
        elif slot == "asr_ro":
            self.registry.set_active_model("ASR", model_id, language="ro")
        elif slot == "translation_en_ro":
            self.registry.set_active_model("TRANSLATION", model_id, language_pair="en-ro")
        elif slot == "translation_ro_en":
            self.registry.set_active_model("TRANSLATION", model_id, language_pair="ro-en")
        elif slot == "tts_en":
            self.registry.set_active_model("TTS", model_id, language="en")
        elif slot == "tts_ro":
            self.registry.set_active_model("TTS", model_id, language="ro")
        elif slot == "vad":
            self.registry.set_active_model("VAD", model_id)
        else:
            raise ValueError(f"Unknown runtime slot: {slot}")

    async def swap(
        self,
        slot: str,
        new_model_id: str,
        capability: ModelCapability = ModelCapability.ASR,
    ):
        req = HotSwapRequest(slot=slot, model_id=new_model_id, capability=capability)
        self._active_swaps[slot] = req
        prior_model_id = getattr(self.registry._active, slot, None)
        old_adapter = self._get_adapter(slot)
        new_adapter = None

        try:
            req.state = HotSwapState.PRELOADING
            yield req
            new_adapter = await self._load_adapter(slot, new_model_id)
            if new_adapter is None:
                raise RuntimeError("adapter_load_returned_none")

            req.state = HotSwapState.READY
            yield req
            if not await self._health_check(new_adapter):
                raise RuntimeError("adapter_health_check_failed")

            req.state = HotSwapState.DRAINING_OLD_MODEL
            yield req
            try:
                await asyncio.wait_for(self._drain_slot(slot), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("Hot-swap drain timed out for %s; switching after timeout", slot)

            # The missing step in the old implementation: actually bind the new
            # adapter into the orchestrator/pipeline before claiming ACTIVE.
            self._set_adapter(slot, new_adapter)
            self._persist_slot(slot, new_model_id)

            if old_adapter is not None and old_adapter is not new_adapter:
                await self._unload_adapter(slot, old_adapter)

            req.state = HotSwapState.ACTIVE
            yield req
        except Exception as exc:
            req.state = HotSwapState.FAILED
            req.error = f"{type(exc).__name__}: {exc}"
            yield req

            if prior_model_id:
                try:
                    rollback_adapter = await self._load_adapter(slot, prior_model_id)
                    self._set_adapter(slot, rollback_adapter)
                    self._persist_slot(slot, prior_model_id)
                    if new_adapter is not None and new_adapter is not rollback_adapter:
                        await self._unload_adapter(slot, new_adapter)
                    req.state = HotSwapState.ROLLED_BACK
                    req.rolled_back_to = prior_model_id
                    yield req
                except Exception:
                    logger.exception("Hot-swap rollback failed for %s", slot)
        finally:
            self._active_swaps.pop(slot, None)

    def is_swap_in_progress(self, slot: str) -> bool:
        return slot in self._active_swaps

    def get_active_swap(self, slot: str) -> Optional[HotSwapRequest]:
        return self._active_swaps.get(slot)
