"""Generic manifest-driven VoxPassport TTS worker host.

The host exposes one stable local protocol (`voxpassport.tts.v1`) and lazily
loads a driver selected by model manifest.  Only drivers know model-library or
backend-specific semantics.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import threading
from pathlib import Path
from typing import Iterator

from aiohttp import web

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.inference.tts_plugins.manifest import TtsManifest, TtsManifestCatalog
from runtime.workers.tts_host.driver_loader import create_driver
from runtime.workers.tts_host.protocol import TtsDriver, TtsDriverRequest

logger = logging.getLogger("VoxPassport.TtsHost")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

PROTOCOL_VERSION = "voxpassport.tts.v1"


class TtsDriverController:
    def __init__(self, catalog: TtsManifestCatalog) -> None:
        self.catalog = catalog
        self._manifest: TtsManifest | None = None
        self._driver: TtsDriver | None = None
        self._runtime_lock = threading.RLock()
        self._switch_lock = asyncio.Lock()

    @property
    def loaded_model_id(self) -> str | None:
        return self._manifest.model_id if self._manifest is not None else None

    def _load_blocking(self, model_id: str) -> dict:
        manifest = self.catalog.resolve(model_id)
        with self._runtime_lock:
            if self._manifest is not None and self._manifest.model_id == manifest.model_id and self._driver is not None:
                if self._driver.health_check():
                    return self._driver.capabilities()
            if self._driver is not None:
                try:
                    self._driver.unload()
                finally:
                    self._driver = None
                    self._manifest = None
            driver = create_driver(manifest)
            driver.load()
            if not driver.health_check():
                try:
                    driver.unload()
                finally:
                    raise RuntimeError(f"{manifest.display_name} driver failed its health check after load")
            self._manifest = manifest
            self._driver = driver
            logger.info("Loaded TTS plugin %s via %s", manifest.model_id, manifest.driver_entrypoint)
            return driver.capabilities()

    async def load(self, model_id: str) -> dict:
        async with self._switch_lock:
            return await asyncio.to_thread(self._load_blocking, model_id)

    def _unload_blocking(self, requested_model_id: str | None = None) -> None:
        with self._runtime_lock:
            if self._driver is None:
                return
            if requested_model_id and self._manifest is not None:
                requested = self.catalog.resolve(requested_model_id).model_id
                if requested != self._manifest.model_id:
                    return
            try:
                self._driver.unload()
            finally:
                logger.info("Unloaded TTS plugin %s", self.loaded_model_id)
                self._driver = None
                self._manifest = None

    async def unload(self, model_id: str | None = None) -> None:
        async with self._switch_lock:
            await asyncio.to_thread(self._unload_blocking, model_id)

    def _require_loaded(self, model_id: str) -> tuple[TtsManifest, TtsDriver]:
        manifest = self.catalog.resolve(model_id)
        if self._manifest is None or self._driver is None or self._manifest.model_id != manifest.model_id:
            raise RuntimeError(f"TTS plugin {manifest.model_id!r} is not loaded")
        return self._manifest, self._driver

    def pcm_iterator(self, model_id: str, request: TtsDriverRequest) -> Iterator[bytes]:
        # Keep a selected driver resident and immutable for the entire utterance;
        # hot-swap waits until the committed utterance leaves this critical section.
        with self._runtime_lock:
            _manifest, driver = self._require_loaded(model_id)
            yield from driver.synthesize_pcm(request)

    def wav_bytes(self, model_id: str, request: TtsDriverRequest) -> bytes:
        with self._runtime_lock:
            _manifest, driver = self._require_loaded(model_id)
            return driver.synthesize_wav(request)

    def capabilities(self, model_id: str | None = None) -> dict:
        if model_id:
            manifest = self.catalog.resolve(model_id)
            if self._manifest is not None and self._driver is not None and self._manifest.model_id == manifest.model_id:
                return self._driver.capabilities()
            return {
                "protocol": PROTOCOL_VERSION,
                "model_id": manifest.model_id,
                "display_name": manifest.display_name,
                "languages": list(manifest.languages),
                "streaming": bool(manifest.capabilities.get("streaming", True)),
                "voice_cloning": manifest.supports_voice_cloning,
                "cross_lingual_voice_cloning": manifest.cross_lingual_voice_cloning,
                "reference_transcript_required": manifest.transcript_required,
                "sample_rate_hz": manifest.native_sample_rate_hz,
                "sample_format": manifest.sample_format,
                "loaded": False,
            }
        if self._driver is not None:
            result = dict(self._driver.capabilities())
            result["loaded"] = True
            return result
        return {"protocol": PROTOCOL_VERSION, "loaded": False}

    def metrics(self) -> dict:
        if self._driver is None:
            return {"loaded": False, "model_id": None}
        result = dict(self._driver.metrics())
        result.setdefault("loaded", True)
        result["model_id"] = self.loaded_model_id
        return result

    def health(self) -> dict:
        healthy = self._driver.health_check() if self._driver is not None else True
        return {
            "status": "ok" if healthy else "degraded",
            "protocol": PROTOCOL_VERSION,
            "loaded_model_id": self.loaded_model_id,
            "driver_healthy": bool(healthy),
        }


def _request_object(data: dict) -> TtsDriverRequest:
    text = str(data.get("input", "")).strip()
    language = str(data.get("language", "")).strip().lower()
    if not text:
        raise ValueError("input must not be empty")
    if not language:
        raise ValueError("language must not be empty")
    ref_audio = str(data.get("ref_audio_path", "")).strip()
    target_audio = str(data.get("target_conditioning_path", "")).strip()
    return TtsDriverRequest(
        text=text,
        language=language,
        reference_audio=Path(ref_audio) if ref_audio else None,
        reference_text=str(data.get("ref_text", "")).strip(),
        target_conditioning_audio=Path(target_audio) if target_audio else None,
    )


def create_app(controller: TtsDriverController) -> web.Application:
    app = web.Application(client_max_size=4 * 1024 * 1024)

    async def health(_request):
        return web.json_response(controller.health())

    async def capabilities(request):
        model_id = request.query.get("model_id")
        try:
            return web.json_response(controller.capabilities(model_id))
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=404)

    async def load(request):
        data = await request.json()
        model_id = str(data.get("model_id", "")).strip()
        if not model_id:
            return web.json_response({"success": False, "error": "model_id is required"}, status=400)
        try:
            caps = await controller.load(model_id)
            return web.json_response({"success": True, "capabilities": caps, "metrics": controller.metrics()})
        except Exception as exc:
            logger.exception("Could not load TTS plugin %s", model_id)
            return web.json_response({"success": False, "error": str(exc)}, status=500)

    async def unload(request):
        try:
            data = await request.json() if request.can_read_body else {}
        except Exception:
            data = {}
        model_id = str(data.get("model_id", "")).strip() or None
        await controller.unload(model_id)
        return web.json_response({"success": True, "loaded_model_id": controller.loaded_model_id})

    async def speech(request):
        data = await request.json()
        model_id = str(data.get("model", "")).strip()
        if not model_id:
            return web.json_response({"error": "model is required"}, status=400)
        try:
            manifest = controller.catalog.resolve(model_id)
            await controller.load(manifest.model_id)
            driver_request = _request_object(data)
            if driver_request.language not in manifest.languages and "*" not in manifest.languages:
                raise ValueError(
                    f"{manifest.display_name} does not advertise language {driver_request.language!r}"
                )
            if driver_request.reference_audio is not None and not manifest.supports_voice_cloning:
                raise ValueError(f"{manifest.display_name} does not advertise voice cloning")
            if manifest.transcript_required and driver_request.reference_audio is not None and not driver_request.reference_text:
                raise ValueError(f"{manifest.display_name} requires a transcript for cloned voice references")
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=400)

        response_format = str(data.get("response_format", "pcm")).strip().lower()
        if response_format == "wav":
            try:
                body = await asyncio.to_thread(controller.wav_bytes, manifest.model_id, driver_request)
                return web.Response(
                    body=body,
                    content_type="audio/wav",
                    headers={
                        "X-VoxPassport-TTS-Protocol": PROTOCOL_VERSION,
                        "X-VoxPassport-TTS-Model": manifest.model_id,
                        "X-Sample-Rate": str(manifest.native_sample_rate_hz),
                    },
                )
            except Exception as exc:
                logger.exception("TTS WAV synthesis failed for %s", manifest.model_id)
                return web.json_response({"error": str(exc)}, status=500)

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue(maxsize=12)

        def produce() -> None:
            try:
                for pcm in controller.pcm_iterator(manifest.model_id, driver_request):
                    if pcm:
                        asyncio.run_coroutine_threadsafe(queue.put(("pcm", pcm)), loop).result()
                asyncio.run_coroutine_threadsafe(queue.put(("done", None)), loop).result()
            except BaseException as exc:
                asyncio.run_coroutine_threadsafe(queue.put(("error", exc)), loop).result()

        producer = asyncio.create_task(asyncio.to_thread(produce))
        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "application/octet-stream",
                "X-VoxPassport-TTS-Protocol": PROTOCOL_VERSION,
                "X-VoxPassport-TTS-Model": manifest.model_id,
                "X-Sample-Rate": str(manifest.native_sample_rate_hz),
                "X-Channels": "1",
                "X-Bit-Depth": "16",
            },
        )
        await response.prepare(request)
        try:
            emitted = False
            while True:
                kind, payload = await queue.get()
                if kind == "pcm":
                    emitted = True
                    await response.write(payload)
                elif kind == "done":
                    break
                elif kind == "error":
                    raise payload
            await producer
            if not emitted:
                raise RuntimeError(f"{manifest.display_name} returned no PCM audio")
            await response.write_eof()
            return response
        except Exception:
            producer.cancel()
            logger.exception("TTS streaming synthesis failed for %s", manifest.model_id)
            raise

    async def metrics(_request):
        return web.json_response(controller.metrics())

    app.router.add_get("/health", health)
    app.router.add_get("/v1/capabilities", capabilities)
    app.router.add_post("/load", load)
    app.router.add_post("/unload", unload)
    app.router.add_post("/v1/audio/speech", speech)
    app.router.add_get("/metrics", metrics)
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="VoxPassport generic TTS plugin host")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8098)
    parser.add_argument("--manifest-dir", default=str(PROJECT_ROOT / "runtime" / "tts_manifests"))
    args = parser.parse_args()
    catalog = TtsManifestCatalog(Path(args.manifest_dir)).load()
    controller = TtsDriverController(catalog)
    web.run_app(create_app(controller), host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
