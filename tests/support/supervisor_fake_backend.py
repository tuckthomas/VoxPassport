"""Tiny OpenAI-style HTTP backend used by TTS supervisor process tests."""

from __future__ import annotations

import argparse
import json
import struct
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path


class Handler(BaseHTTPRequestHandler):
    server_version = "VoxPassportFakeTtsBackend/1"

    def log_message(self, _format: str, *_args) -> None:
        return

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path in {"/health", "/v1/models"}:
            marker = getattr(self.server, "restart_health_marker", None)
            if marker is not None and marker.exists():
                self._json({"status": "degraded", "error": "forced unhealthy backend"}, 503)
                return
            self._json({"status": "ok", "data": []})
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path != "/v1/audio/speech":
            self._json({"error": "not found"}, 404)
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            payload = {}
        pcm = b"".join(struct.pack("<h", (index % 200) - 100) for index in range(2400))
        if str(payload.get("response_format", "pcm")).lower() == "wav":
            buffer = BytesIO()
            with wave.open(buffer, "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(24000)
                output.writeframes(pcm)
            body = buffer.getvalue()
            content_type = "audio/wav"
        else:
            body = pcm
            content_type = "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--restart-health-marker", default="")
    args = parser.parse_args()
    marker = Path(args.restart_health_marker).resolve() if args.restart_health_marker else None
    # A newly launched replacement becomes healthy again. The already-running
    # process sees a marker created after startup and returns 503 until killed.
    if marker is not None and marker.exists():
        marker.unlink()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.restart_health_marker = marker
    server.serve_forever()


if __name__ == "__main__":
    main()
