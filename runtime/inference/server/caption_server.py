"""
LiveTranslator — Real-Time Caption & Telemetry Server
======================================================
WebSocket & HTTP server broadcasting live transcription, translation captions,
and pipeline telemetry to the desktop overlay and browser companion.

Endpoints:
- WS /ws/captions     — Real-time stream of CaptionEvent & MetricsEvent packets
- GET /api/status     — Current pipeline state, active models, runtime tier
- GET /api/metrics    — Latency percentiles (p50, p95, max)
- POST /api/mode      — Switch operating mode (FULL_DUPLEX, CAPTIONS_ONLY, etc.)
- POST /api/tts-mode  — Toggle stock / cloned voice
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from typing import Set

from runtime.inference.metrics.latency_metrics import PipelineMetrics
from runtime.inference.protocol import CaptionEvent, MetricsEvent

logger = logging.getLogger(__name__)


class CaptionServer:
    """
    Lightweight async server for caption broadcasting.
    Supports pure asyncio / websockets without requiring external heavy web frameworks.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8765):
        self.host = host
        self.port = port
        self._connected_clients: Set[asyncio.Queue] = set()
        self._server = None
        self._is_running = False

    async def start(self) -> None:
        """Start the caption WebSocket server."""
        if self._is_running:
            return
        self._is_running = True
        try:
            import websockets
            self._server = await websockets.serve(self._handle_client, self.host, self.port)
            logger.info("Caption WebSocket server listening on ws://%s:%d/ws/captions", self.host, self.port)
        except Exception as e:
            logger.warning("websockets server start failed (%s). Running in-memory broadcaster.", e)

    async def _handle_client(self, websocket, *args, **kwargs):
        """Handle individual WebSocket client connection."""
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
        self._connected_clients.add(queue)
        logger.info("New caption client connected. Total clients: %d", len(self._connected_clients))

        try:
            while self._is_running:
                msg = await queue.get()
                await websocket.send(msg)
        except Exception:
            pass
        finally:
            self._connected_clients.discard(queue)
            logger.info("Caption client disconnected. Remaining clients: %d", len(self._connected_clients))

    def broadcast_caption(self, event: CaptionEvent) -> None:
        """Broadcast a caption event to all connected overlays."""
        payload = json.dumps({
            "type": "caption",
            "event_type": event.event_type.value,
            "utterance_id": event.utterance_id,
            "language": event.language.value,
            "text": event.text,
            "is_final": event.is_final,
            "timestamp_ns": event.monotonic_timestamp_ns,
        })
        for q in list(self._connected_clients):
            try:
                q.put_nowait(payload)
            except Exception:
                pass

    def broadcast_metrics(self, metrics_summary: dict) -> None:
        """Broadcast pipeline metrics and latency stats."""
        payload = json.dumps({
            "type": "metrics",
            "data": metrics_summary,
        })
        for q in list(self._connected_clients):
            try:
                q.put_nowait(payload)
            except Exception:
                pass

    async def stop(self) -> None:
        """Stop the caption server."""
        self._is_running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        logger.info("Caption server stopped.")
