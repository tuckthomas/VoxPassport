"""Native GGUF Higgs TTS driver backed by audiocpp_engine.dll."""

from __future__ import annotations

import ctypes
import hashlib
import io
import json
import logging
import os
import queue
import re
import threading
import wave
from ctypes import POINTER, Structure, c_bool, c_char_p, c_float, c_int32, c_int64, c_size_t, c_void_p
from pathlib import Path
from typing import Iterator

from runtime.workers.tts_host.protocol import TtsDriver, TtsDriverRequest

logger = logging.getLogger(__name__)


class _AudioResult(Structure):
    _fields_ = [
        ("sample_rate", c_int32),
        ("channels", c_int32),
        ("sample_count", c_size_t),
        ("samples", POINTER(c_float)),
        ("error", c_char_p),
    ]


_PROGRESS_FN = ctypes.CFUNCTYPE(None, c_int32, c_int32, c_char_p, c_void_p)
_AUDIO_CHUNK_FN = ctypes.CFUNCTYPE(
    None, c_int32, c_int32, c_int64, POINTER(c_float), c_size_t, c_bool, c_void_p
)


class HiggsNativeDriver(TtsDriver):
    """Q4 GGUF Higgs inference through the generic TTS worker protocol."""

    _MAX_REFERENCE_SECONDS = 5.0

    def __init__(self, manifest) -> None:
        super().__init__(manifest)
        project_root = Path(__file__).resolve().parents[4]
        configured_model = str(manifest.driver_options.get("model_dir", "models/higgs-tts-3-q4_k_m"))
        model_path = Path(configured_model)
        self._model_dir = model_path if model_path.is_absolute() else project_root / model_path
        configured_dll = os.getenv("VOXPASSPORT_HIGGS_NATIVE_DLL", "").strip()
        if configured_dll:
            self._dll_path = Path(configured_dll)
        else:
            candidates = [
                project_root / "native" / "audiocpp_engine.dll",
                project_root.parent / "Higgs-Audio-v3-Studio" / "build" / "windows-cuda-release" / "bin" / "audiocpp_engine.dll",
            ]
            self._dll_path = next((path for path in candidates if path.exists()), candidates[0])
        self._device = int(manifest.driver_options.get("device", 0))
        self._threads = int(manifest.driver_options.get("threads", 4))
        self._lib = None
        self._engine = None
        self._progress_callback = _PROGRESS_FN(lambda *_args: None)
        self._generation_lock = threading.Lock()

    def load(self) -> None:
        if self._engine is not None:
            return
        if not self._dll_path.exists() or not self._model_dir.exists():
            raise RuntimeError(
                "Native Higgs runtime unavailable: install the Q4_K_M model and audiocpp_engine.dll "
                "or set VOXPASSPORT_HIGGS_NATIVE_DLL."
            )

        dll_dir = self._dll_path.parent
        cuda_root = os.getenv("CUDA_PATH", "").strip()
        cuda_bin = str(Path(cuda_root) / "bin") if cuda_root and (Path(cuda_root) / "bin").exists() else ""
        if hasattr(os, "add_dll_directory"):
            if cuda_bin:
                os.add_dll_directory(cuda_bin)
            os.add_dll_directory(str(dll_dir))
        os.environ["PATH"] = ";".join(
            part for part in (cuda_bin, str(dll_dir), os.environ.get("PATH", "")) if part
        )

        lib = ctypes.CDLL(str(self._dll_path))
        lib.audiocpp_create.restype = c_void_p
        lib.audiocpp_create.argtypes = []
        lib.audiocpp_destroy.restype = None
        lib.audiocpp_destroy.argtypes = [c_void_p]
        lib.audiocpp_load_model.restype = c_int32
        lib.audiocpp_load_model.argtypes = [c_void_p, c_char_p, c_int32, c_int32, c_int32, c_char_p, c_char_p]
        lib.audiocpp_unload_model.restype = None
        lib.audiocpp_unload_model.argtypes = [c_void_p]
        lib.audiocpp_last_error.restype = c_char_p
        lib.audiocpp_last_error.argtypes = [c_void_p]
        lib.audiocpp_generate_tts.restype = c_int32
        lib.audiocpp_generate_tts.argtypes = [c_void_p, c_char_p, c_char_p, _PROGRESS_FN, c_void_p, POINTER(_AudioResult)]
        lib.audiocpp_generate_voice_clone_stream.restype = c_int32
        lib.audiocpp_generate_voice_clone_stream.argtypes = [
            c_void_p, c_char_p, c_char_p, c_char_p, c_char_p,
            _PROGRESS_FN, _AUDIO_CHUNK_FN, c_void_p, POINTER(_AudioResult),
        ]
        lib.audiocpp_free_result.restype = None
        lib.audiocpp_free_result.argtypes = [POINTER(_AudioResult)]

        engine = lib.audiocpp_create()
        if not engine:
            raise RuntimeError("audiocpp_create failed")
        status = lib.audiocpp_load_model(
            engine,
            str(self._model_dir).encode("utf-8"),
            2,
            self._device,
            self._threads,
            None,
            b"{}",
        )
        if status != 0:
            error = lib.audiocpp_last_error(engine)
            lib.audiocpp_destroy(engine)
            detail = error.decode("utf-8", errors="replace") if error else "unknown error"
            raise RuntimeError(f"Native Higgs model load failed ({status}): {detail}")
        self._lib = lib
        self._engine = engine

    def unload(self) -> None:
        lib, engine = self._lib, self._engine
        self._lib = None
        self._engine = None
        if not lib or not engine:
            return
        with self._generation_lock:
            lib.audiocpp_unload_model(engine)
            lib.audiocpp_destroy(engine)

    @staticmethod
    def _release_unused_torch_cuda_cache() -> None:
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    @staticmethod
    def _float_samples_to_pcm(samples: POINTER(c_float), count: int, *, validate: bool = True) -> bytes:
        import numpy as np

        values = np.ctypeslib.as_array(samples, shape=(count,)).copy()
        rms = float(np.sqrt(np.mean(values * values))) if values.size else 0.0
        if validate and rms < 0.0001:
            raise RuntimeError(f"Native Higgs generated effectively silent audio (RMS {rms:.6f})")
        return (np.clip(values, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()

    @staticmethod
    def _reference_digest(source: Path, ref_text: str) -> str:
        digest = hashlib.sha256()
        with source.open("rb") as audio_file:
            for block in iter(lambda: audio_file.read(1024 * 1024), b""):
                digest.update(block)
        digest.update(b"\0")
        digest.update(ref_text.encode("utf-8"))
        return digest.hexdigest()[:20]

    @classmethod
    def _prepare_reference_clip(cls, source: Path, ref_text: str) -> tuple[Path, str, Path]:
        cache_key = cls._reference_digest(source, ref_text)
        cache_dir = source.parent / ".higgs_native_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        speaker_cache = cache_dir / f"speaker_{cache_key}.hspkcache"
        with wave.open(str(source), "rb") as reader:
            frame_rate = reader.getframerate()
            frame_count = reader.getnframes()
            duration = frame_count / frame_rate if frame_rate else 0.0
            if duration <= cls._MAX_REFERENCE_SECONDS:
                return source, ref_text, speaker_cache
            clip_frames = int(frame_rate * cls._MAX_REFERENCE_SECONDS)
            params = reader.getparams()
            frames = reader.readframes(clip_frames)

        words = ref_text.split()
        keep_words = max(1, round(len(words) * cls._MAX_REFERENCE_SECONDS / duration)) if words else 0
        clipped_text = " ".join(words[:keep_words]) if keep_words else ref_text
        clip_path = cache_dir / f"reference_{cache_key}_{cls._MAX_REFERENCE_SECONDS:g}s.wav"
        if not clip_path.exists():
            with wave.open(str(clip_path), "wb") as writer:
                writer.setparams(params)
                writer.writeframes(frames)
        return clip_path, clipped_text, speaker_cache

    @staticmethod
    def _split_clauses(text: str, *, max_words: int = 18, max_chars: int = 140) -> list[str]:
        clean = re.sub(r"\s+", " ", str(text or "")).strip()
        if not clean:
            return []
        clauses: list[str] = []
        for sentence in re.split(r"(?<=[.!?;:])\s+", clean):
            pieces = re.split(r"(?<=,)\s+", sentence)
            pending = ""
            for piece in pieces:
                candidate = f"{pending} {piece}".strip()
                if pending and (len(candidate) > max_chars or len(candidate.split()) > max_words):
                    clauses.append(pending)
                    pending = piece
                else:
                    pending = candidate
            if pending:
                words = pending.split()
                while len(words) > max_words or len(" ".join(words)) > max_chars:
                    take = min(max_words, len(words))
                    while take > 1 and len(" ".join(words[:take])) > max_chars:
                        take -= 1
                    clauses.append(" ".join(words[:take]))
                    words = words[take:]
                if words:
                    clauses.append(" ".join(words))
        return clauses

    @staticmethod
    def _stable_seed(text: str, cache_path: Path) -> int:
        material = f"{cache_path.name}\0{text}".encode("utf-8")
        return int.from_bytes(hashlib.sha256(material).digest()[:4], "little")

    def _voice_clone_options(self, text: str, cache_path: Path) -> bytes:
        return json.dumps({
            "max_tokens": 128,
            "seed": self._stable_seed(text, cache_path),
            "temperature": 0.8,
            "top_k": 30,
            "top_p": 0.8,
            "first_stream_frames": 12,
            "stream_frames": 8,
            "emit_stream_audio_chunks": True,
            "keep_runtime_cache": False,
            "reference_cache_path": str(cache_path),
        }, ensure_ascii=False).encode("utf-8")

    def _stock_pcm(self, text: str) -> bytes:
        with self._generation_lock:
            lib, engine = self._lib, self._engine
            if not lib or not engine:
                raise RuntimeError("Native Higgs driver is not loaded")
            result = _AudioResult()
            status = lib.audiocpp_generate_tts(
                engine,
                text.encode("utf-8"),
                b'{"max_tokens":128}',
                self._progress_callback,
                None,
                ctypes.byref(result),
            )
            try:
                if status != 0:
                    error = result.error.decode("utf-8", errors="replace") if result.error else "unknown error"
                    raise RuntimeError(f"Native Higgs synthesis failed ({status}): {error}")
                if not result.samples or result.sample_count <= 0:
                    raise RuntimeError("Native Higgs synthesis returned no audio")
                return self._float_samples_to_pcm(result.samples, int(result.sample_count))
            finally:
                lib.audiocpp_free_result(ctypes.byref(result))

    def _clone_into_queue(self, request: TtsDriverRequest, output: queue.Queue) -> None:
        try:
            self._release_unused_torch_cuda_cache()
            reference = Path(request.reference_audio) if request.reference_audio is not None else None
            if reference is None or not reference.exists():
                raise FileNotFoundError("Native Higgs voice cloning requires reference audio")
            if not request.reference_text.strip():
                raise ValueError("Native Higgs voice cloning requires the exact reference transcript")
            prepared_path, prepared_text, cache_path = self._prepare_reference_clip(reference, request.reference_text.strip())

            with self._generation_lock:
                lib, engine = self._lib, self._engine
                if not lib or not engine:
                    raise RuntimeError("Native Higgs driver is not loaded")
                total_samples = 0
                square_sum = 0.0
                callback_error: list[BaseException] = []

                def audio_callback(rate, channels, _start, samples, count, _is_final, _user_data) -> None:
                    nonlocal total_samples, square_sum
                    try:
                        if channels != 1:
                            raise RuntimeError(f"Native Higgs returned unsupported {channels}-channel audio")
                        import numpy as np
                        values = np.ctypeslib.as_array(samples, shape=(int(count),)).copy()
                        if values.size:
                            square_sum += float(np.sum(values * values))
                            total_samples += int(values.size)
                            pcm = (np.clip(values, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
                            output.put(("pcm", pcm))
                    except BaseException as exc:
                        callback_error.append(exc)

                native_callback = _AUDIO_CHUNK_FN(audio_callback)
                for clause in self._split_clauses(request.text):
                    result = _AudioResult()
                    before = total_samples
                    try:
                        status = lib.audiocpp_generate_voice_clone_stream(
                            engine,
                            clause.encode("utf-8"),
                            str(prepared_path).encode("utf-8"),
                            prepared_text.encode("utf-8"),
                            self._voice_clone_options(clause, cache_path),
                            self._progress_callback,
                            native_callback,
                            None,
                            ctypes.byref(result),
                        )
                        if callback_error:
                            raise callback_error[0]
                        if status != 0:
                            error = result.error.decode("utf-8", errors="replace") if result.error else "unknown error"
                            raise RuntimeError(f"Native Higgs voice cloning failed ({status}): {error}")
                        if total_samples == before:
                            if not result.samples or result.sample_count <= 0:
                                raise RuntimeError("Native Higgs voice cloning returned no audio")
                            pcm = self._float_samples_to_pcm(result.samples, int(result.sample_count), validate=False)
                            output.put(("pcm", pcm))
                            total_samples += int(result.sample_count)
                    finally:
                        lib.audiocpp_free_result(ctypes.byref(result))

                rms = (square_sum / total_samples) ** 0.5 if total_samples else 0.0
                if not total_samples or (square_sum and rms < 0.0001):
                    raise RuntimeError(f"Native Higgs generated effectively silent audio (RMS {rms:.6f})")
            output.put(("done", None))
        except BaseException as exc:
            output.put(("error", exc))

    def synthesize_pcm(self, request: TtsDriverRequest) -> Iterator[bytes]:
        clean = str(request.text).strip()
        if not clean:
            raise ValueError("Target TTS text must not be empty")
        if request.reference_audio is None:
            pcm = self._stock_pcm(clean)
            for offset in range(0, len(pcm), 16384):
                yield pcm[offset : offset + 16384]
            return

        output: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=12)
        worker = threading.Thread(target=self._clone_into_queue, args=(request, output), daemon=True)
        worker.start()
        while True:
            kind, payload = output.get()
            if kind == "pcm":
                yield payload
            elif kind == "done":
                break
            elif kind == "error":
                raise payload
        worker.join()

    def synthesize_wav(self, request: TtsDriverRequest) -> bytes:
        pcm = b"".join(self.synthesize_pcm(request))
        if not pcm:
            raise RuntimeError("Native Higgs generated no audio")
        output = io.BytesIO()
        with wave.open(output, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.manifest.native_sample_rate_hz)
            wav_file.writeframes(pcm)
        return output.getvalue()

    def health_check(self) -> bool:
        return bool(self._engine and self._lib)
