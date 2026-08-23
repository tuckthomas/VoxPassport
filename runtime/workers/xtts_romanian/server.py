"""Local XTTS-v2 Romanian streaming worker.

The worker is intentionally isolated from the primary VoxPassport interpreter.
XTTS/Coqui has a substantially different dependency lifecycle from the current
Parakeet/Transformers stack, so keeping it in a separate Python environment
prevents a TTS package upgrade from changing the ASR runtime.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import io
import logging
import os
import re
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Iterator

import numpy as np
from aiohttp import web

if __package__ in {None, ""}:
    import sys

    PROJECT_ROOT = Path(__file__).resolve().parents[3]
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from runtime.workers.xtts_romanian.common import (
        conditioning_cache_key,
        dynamic_max_new_tokens,
        normalize_language,
        prepare_text,
        split_live_clauses,
    )
else:
    PROJECT_ROOT = Path(__file__).resolve().parents[3]
    from .common import (
        conditioning_cache_key,
        dynamic_max_new_tokens,
        normalize_language,
        prepare_text,
        split_live_clauses,
    )

logger = logging.getLogger("VoxPassport.XttsRomanianWorker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

MODEL_ID = "eduardem/xtts-v2-romanian-v2"
SAMPLE_RATE = 24000


def _patch_romanian_tokenizer() -> None:
    """Teach Coqui's XTTS tokenizer how to pass Romanian text to the v2 vocab.

    The Romanian checkpoint adds the [ro] token and Romanian glyphs, while
    upstream Coqui still rejects ``ro`` in ``VoiceBpeTokenizer.preprocess_text``.
    We preserve upstream preprocessing for every existing language and use a
    deliberately conservative Romanian cleaner: Unicode normalization happens
    in VoxPassport before this method and we only lowercase/collapse whitespace.
    """
    from TTS.tts.layers.xtts import tokenizer as tokenizer_module

    cls = tokenizer_module.VoiceBpeTokenizer
    if getattr(cls, "_voxpassport_romanian_patch", False):
        return
    original = cls.preprocess_text

    def preprocess_text(self, txt, lang):
        base = str(lang).split("-", 1)[0].lower()
        if base == "ro":
            clean = str(txt).translate(str.maketrans({"ş": "ș", "ţ": "ț", "Ş": "Ș", "Ţ": "Ț"}))
            clean = clean.replace('"', "").lower()
            return re.sub(r"\s+", " ", clean).strip()
        return original(self, txt, lang)

    cls.preprocess_text = preprocess_text
    cls._voxpassport_romanian_patch = True


class XttsRomanianRuntime:
    def __init__(self, model_dir: Path, *, device: str = "cuda", cache_size: int = 4) -> None:
        self.model_dir = Path(model_dir)
        self.device = device
        self.cache_size = max(1, int(cache_size))
        self.model = None
        self._lock = threading.RLock()
        self._conditioning_cache: OrderedDict[str, tuple[object, object, str]] = OrderedDict()

    @property
    def loaded(self) -> bool:
        return self.model is not None

    def _ensure_model_files(self) -> None:
        required = ("config.json", "model.pth", "dvae.pth", "mel_stats.pth", "vocab.json")
        if all((self.model_dir / name).exists() for name in required):
            return
        logger.info("XTTS Romanian checkpoint not present; downloading %s to %s", MODEL_ID, self.model_dir)
        from huggingface_hub import snapshot_download

        self.model_dir.mkdir(parents=True, exist_ok=True)
        snapshot_download(repo_id=MODEL_ID, local_dir=str(self.model_dir))
        missing = [name for name in required if not (self.model_dir / name).exists()]
        if missing:
            raise FileNotFoundError(f"XTTS Romanian download is incomplete; missing: {', '.join(missing)}")

    def load(self) -> None:
        with self._lock:
            if self.model is not None:
                return
            self._ensure_model_files()
            _patch_romanian_tokenizer()
            import torch
            from TTS.tts.configs.xtts_config import XttsConfig
            from TTS.tts.models.xtts import Xtts

            config = XttsConfig()
            config.load_json(str(self.model_dir / "config.json"))
            model = Xtts.init_from_config(config)
            model.load_checkpoint(config, checkpoint_dir=str(self.model_dir), use_deepspeed=False)
            use_cuda = self.device.startswith("cuda") and torch.cuda.is_available()
            model = model.cuda() if use_cuda else model.cpu()
            model.eval()
            model.tokenizer.char_limits["ro"] = 250
            self.device = "cuda" if use_cuda else "cpu"
            self.model = model
            logger.info("Loaded XTTS Romanian v2 on %s from %s", self.device, self.model_dir)

    def unload(self) -> None:
        with self._lock:
            self._conditioning_cache.clear()
            old_model = self.model
            self.model = None
            if old_model is not None:
                del old_model
            gc.collect()
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass

    def _default_reference(self) -> Path:
        candidates = sorted((self.model_dir / "reference_voices").glob("*.wav"))
        if not candidates:
            raise FileNotFoundError("XTTS stock synthesis requires a bundled reference voice, but none was found")
        return candidates[0]

    def _conditioning(
        self,
        canonical_reference: Path,
        target_reference: Path | None,
        language: str,
    ):
        if self.model is None:
            raise RuntimeError("XTTS Romanian model is not loaded")
        canonical_reference = Path(canonical_reference)
        if not canonical_reference.exists():
            raise FileNotFoundError(f"Canonical voice reference does not exist: {canonical_reference}")
        if target_reference is not None:
            target_reference = Path(target_reference)
            if not target_reference.exists():
                target_reference = None

        key = conditioning_cache_key(canonical_reference, target_reference, language)
        cached = self._conditioning_cache.pop(key, None)
        if cached is not None:
            self._conditioning_cache[key] = cached
            gpt_cpu, speaker_cpu, mode = cached
            return gpt_cpu, speaker_cpu, mode

        canonical_gpt, speaker_embedding = self.model.get_conditioning_latents(
            audio_path=[str(canonical_reference)], gpt_cond_len=6, gpt_cond_chunk_len=6
        )
        conditioning_mode = "canonical-reference"
        gpt_cond_latent = canonical_gpt
        if target_reference is not None and target_reference.resolve() != canonical_reference.resolve():
            target_gpt, _ = self.model.get_conditioning_latents(
                audio_path=[str(target_reference)], gpt_cond_len=6, gpt_cond_chunk_len=6
            )
            gpt_cond_latent = target_gpt
            conditioning_mode = "real-speaker+target-language-gpt"

        # Conditioning is small, but keep the cache on CPU so multiple saved
        # profiles do not quietly consume the RTX 2070's limited VRAM.
        gpt_cpu = gpt_cond_latent.detach().cpu()
        speaker_cpu = speaker_embedding.detach().cpu()
        self._conditioning_cache[key] = (gpt_cpu, speaker_cpu, conditioning_mode)
        while len(self._conditioning_cache) > self.cache_size:
            self._conditioning_cache.popitem(last=False)
        return gpt_cpu, speaker_cpu, conditioning_mode

    def stream(
        self,
        *,
        text: str,
        language: str,
        canonical_reference: Path | None,
        target_reference: Path | None = None,
    ) -> Iterator[tuple[bytes, str]]:
        import torch

        language = normalize_language(language)
        clean_text = prepare_text(text, language)
        canonical_reference = Path(canonical_reference) if canonical_reference else self._default_reference()
        with self._lock, torch.inference_mode():
            if self.model is None:
                self.load()
            gpt_cond, speaker_embedding, mode = self._conditioning(
                canonical_reference, target_reference, language
            )
            for clause in split_live_clauses(clean_text):
                max_tokens = dynamic_max_new_tokens(clause) if language == "ro" else 400
                generator = self.model.inference_stream(
                    clause,
                    language,
                    gpt_cond,
                    speaker_embedding,
                    stream_chunk_size=20,
                    overlap_wav_len=1024,
                    temperature=0.3,
                    top_p=0.7,
                    top_k=30,
                    length_penalty=0.8,
                    repetition_penalty=10.0,
                    enable_text_splitting=False,
                    max_new_tokens=max_tokens,
                )
                for tensor in generator:
                    values = tensor.detach().float().cpu().numpy().reshape(-1)
                    if not values.size:
                        continue
                    pcm = (np.clip(values, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
                    if pcm:
                        yield pcm, mode

    def memory_snapshot(self) -> dict:
        try:
            import torch

            if not torch.cuda.is_available():
                return {"cuda": False}
            free, total = torch.cuda.mem_get_info()
            return {
                "cuda": True,
                "allocated_mb": round(torch.cuda.memory_allocated() / 1024**2, 1),
                "reserved_mb": round(torch.cuda.memory_reserved() / 1024**2, 1),
                "free_mb": round(free / 1024**2, 1),
                "total_mb": round(total / 1024**2, 1),
                "conditioning_cache_entries": len(self._conditioning_cache),
            }
        except Exception as exc:
            return {"cuda": None, "error": str(exc)}


def _request_paths(data: dict) -> tuple[Path | None, Path | None]:
    canonical = str(data.get("ref_audio_path", "")).strip()
    target = str(data.get("target_conditioning_path", "")).strip()
    return (Path(canonical) if canonical else None, Path(target) if target else None)


def create_app(runtime: XttsRomanianRuntime) -> web.Application:
    app = web.Application(client_max_size=2 * 1024 * 1024)

    async def health(_request):
        return web.json_response({
            "status": "ok",
            "model_id": MODEL_ID,
            "loaded": runtime.loaded,
            "model_dir": str(runtime.model_dir),
            "memory": runtime.memory_snapshot(),
        })

    async def load(_request):
        try:
            await asyncio.to_thread(runtime.load)
            return web.json_response({"success": True, "loaded": True, "memory": runtime.memory_snapshot()})
        except Exception as exc:
            logger.exception("XTTS load failed")
            return web.json_response({"success": False, "error": str(exc)}, status=500)

    async def unload(_request):
        await asyncio.to_thread(runtime.unload)
        return web.json_response({"success": True, "loaded": False, "memory": runtime.memory_snapshot()})

    async def speech(request):
        data = await request.json()
        text = str(data.get("input", ""))
        language = str(data.get("language", "ro"))
        response_format = str(data.get("response_format", "pcm")).lower()
        canonical, target = _request_paths(data)
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue(maxsize=12)

        def produce() -> None:
            try:
                mode = "canonical-reference"
                collected: list[np.ndarray] = []
                for pcm, mode in runtime.stream(
                    text=text,
                    language=language,
                    canonical_reference=canonical,
                    target_reference=target,
                ):
                    if response_format == "wav":
                        collected.append(np.frombuffer(pcm, dtype="<i2").copy())
                    else:
                        asyncio.run_coroutine_threadsafe(queue.put(("pcm", pcm)), loop).result()
                if response_format == "wav":
                    import soundfile as sf

                    audio = np.concatenate(collected) if collected else np.zeros(0, dtype=np.int16)
                    if not audio.size:
                        raise RuntimeError("XTTS returned no audio")
                    buffer = io.BytesIO()
                    sf.write(buffer, audio.astype(np.float32) / 32767.0, SAMPLE_RATE, format="WAV", subtype="PCM_16")
                    asyncio.run_coroutine_threadsafe(queue.put(("wav", buffer.getvalue())), loop).result()
                asyncio.run_coroutine_threadsafe(queue.put(("done", mode)), loop).result()
            except BaseException as exc:
                asyncio.run_coroutine_threadsafe(queue.put(("error", exc)), loop).result()

        producer = asyncio.create_task(asyncio.to_thread(produce))
        if response_format == "wav":
            kind, payload = await queue.get()
            if kind == "error":
                await producer
                return web.json_response({"error": str(payload)}, status=500)
            if kind != "wav":
                await producer
                return web.json_response({"error": "XTTS worker returned an invalid WAV result"}, status=500)
            done_kind, mode = await queue.get()
            await producer
            if done_kind == "error":
                return web.json_response({"error": str(mode)}, status=500)
            return web.Response(
                body=payload,
                content_type="audio/wav",
                headers={"X-Sample-Rate": str(SAMPLE_RATE), "X-XTTS-Conditioning": str(mode)},
            )

        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "application/octet-stream",
                "X-Sample-Rate": str(SAMPLE_RATE),
                "X-Channels": "1",
                "X-Bit-Depth": "16",
            },
        )
        await response.prepare(request)
        conditioning_mode = "canonical-reference"
        try:
            while True:
                kind, payload = await queue.get()
                if kind == "pcm":
                    await response.write(payload)
                elif kind == "done":
                    conditioning_mode = str(payload)
                    break
                elif kind == "error":
                    raise payload
            await producer
            logger.info("XTTS streamed %s synthesis using %s", normalize_language(language), conditioning_mode)
            await response.write_eof()
            return response
        except Exception:
            producer.cancel()
            logger.exception("XTTS streaming synthesis failed")
            raise

    async def metrics(_request):
        return web.json_response(runtime.memory_snapshot())

    app.router.add_get("/health", health)
    app.router.add_post("/load", load)
    app.router.add_post("/unload", unload)
    app.router.add_post("/v1/audio/speech", speech)
    app.router.add_get("/metrics", metrics)
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="VoxPassport XTTS Romanian worker")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8098)
    parser.add_argument("--model-dir", default=os.getenv(
        "VOXPASSPORT_XTTS_MODEL_DIR", str(PROJECT_ROOT / "models" / "xtts-v2-romanian-v2")
    ))
    parser.add_argument("--device", default=os.getenv("VOXPASSPORT_XTTS_DEVICE", "cuda"))
    args = parser.parse_args()
    runtime = XttsRomanianRuntime(Path(args.model_dir), device=args.device)
    web.run_app(create_app(runtime), host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
