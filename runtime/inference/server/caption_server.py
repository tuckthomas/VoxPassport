"""Real-time caption and telemetry WebSocket server."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Set

from runtime.inference.protocol import CaptionEvent

logger = logging.getLogger(__name__)


class CaptionServer:
    """Lightweight async broadcaster for captions and pipeline telemetry."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8765):
        self.host = host
        self.port = port
        self._connected_clients: Set[asyncio.Queue] = set()
        self._server = None
        self._is_running = False

    async def start(self) -> None:
        if self._is_running:
            return
        self._is_running = True
        try:
            import websockets
            self._server = await websockets.serve(self._handle_client, self.host, self.port)
            logger.info("Caption WebSocket server listening on ws://%s:%d/ws/captions", self.host, self.port)
        except Exception as exc:
            logger.warning("websockets server start failed (%s). Running in-memory broadcaster.", exc)

    async def _handle_client(self, websocket, *args, **kwargs):
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
        self._connected_clients.add(queue)
        try:
            while self._is_running:
                await websocket.send(await queue.get())
        except Exception:
            pass
        finally:
            self._connected_clients.discard(queue)

    def broadcast_caption(self, event: CaptionEvent) -> None:
        payload = json.dumps({
            "type": "caption",
            "event_type": event.event_type.value,
            "utterance_id": event.utterance_id,
            "language": event.language.value,
            "text": event.text,
            "is_final": event.is_final,
            "timestamp_ns": event.monotonic_timestamp_ns,
            "metadata": event.metadata or {},
        })
        for queue in list(self._connected_clients):
            try:
                queue.put_nowait(payload)
            except Exception:
                pass

    def broadcast_metrics(self, metrics_summary: dict) -> None:
        payload = json.dumps({"type": "metrics", "data": metrics_summary})
        for queue in list(self._connected_clients):
            try:
                queue.put_nowait(payload)
            except Exception:
                pass

    async def stop(self) -> None:
        self._is_running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        logger.info("Caption server stopped")
