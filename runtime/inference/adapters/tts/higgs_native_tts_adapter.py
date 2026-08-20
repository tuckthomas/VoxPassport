"""Native GGUF Higgs TTS adapter backed by audiocpp_engine.dll."""

from __future__ import annotations

import asyncio
import ctypes
import hashlib
import json
import logging
import os
import io
import re
import threading
import uuid
import wave
from ctypes import POINTER, Structure, c_bool, c_char_p, c_float, c_int32, c_int64, c_size_t, c_void_p
from pathlib import Path
from typing import AsyncIterator, Optional

from runtime.inference.adapters.base import TtsAdapter
from runtime.inference.adapters.tts.profile_reference import resolve_profile_reference
from runtime.inference.gpu_inference_coordinator import heavy_gpu_inference
from runtime.inference.protocol import LanguageCode, SampleFormat, TtsAudioChunk, VoiceSpec

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


def _candidate_dlls(project_root: Path) -> list[Path]:
    configured = os.getenv("VOXPASSPORT_HIGGS_NATIVE_DLL", "").strip()
    candidates = [Path(configured)] if configured else []
    candidates.extend([
        project_root / "native" / "audiocpp_engine.dll",
        project_root / "temp_higgs_test" / "audiocpp_engine.dll",
        project_root.parent / "Higgs-Audio-v3-Studio" / "build" / "windows-cuda-release" / "bin" / "audiocpp_engine.dll",
    ])
    return [path for path in candidates if path and path.exists()]


class HiggsNativeTtsAdapter(TtsAdapter):
    """Local Q4 GGUF Higgs backend with native reference-audio voice cloning."""

    ADAPTER_NAME = "HiggsNativeTtsAdapter"
    _SAMPLE_RATE_HZ = 24000
    _MAX_REFERENCE_SECONDS = 5.0

    def __init__(
        self,
        model_dir: Optional[str | Path] = None,
        dll_path: Optional[str | Path] = None,
        device: int = 0,
        threads: int = 4,
        profiles_root: Optional[str | Path] = None,
    ) -> None:
        project_root = Path(__file__).resolve().parents[4]
        self._model_dir = Path(model_dir or project_root / "models" / "higgs-tts-3-q4_k_m")
        self._dll_path = Path(dll_path) if dll_path else (_candidate_dlls(project_root)[0] if _candidate_dlls(project_root) else None)
        self._device = int(device)
        self._threads = int(threads)
        self._profiles_root = Path(profiles_root or project_root / "data" / "voice_profiles")
        self._lib = None
        self._engine = None
        self._loaded = False
        self._progress_callback = _PROGRESS_FN(lambda *_args: None)
        self._generation_lock = threading.Lock()

    @property
    def available(self) -> bool:
        return bool(self._dll_path and self._dll_path.exists() and self._model_dir.exists())

    async def load(self) -> None:
        if self._loaded:
            return
        if not self.available:
            raise RuntimeError(
                "Native Higgs runtime unavailable: install the Q4_K_M model and audiocpp_engine.dll "
                "or set VOXPASSPORT_HIGGS_NATIVE_DLL."
            )
        await asyncio.get_running_loop().run_in_executor(None, self._load_blocking)

    def _load_blocking(self) -> None:
        dll_dir = self._dll_path.parent
        cuda_root = os.getenv("CUDA_PATH", "").strip()
        cuda_candidates = [Path(cuda_root)] if cuda_root else []
        project_root = Path(__file__).resolve().parents[4]
        cuda_candidates.extend([
            project_root.parent / "CUDA" / "v13.3",
        ])
        cuda_root_path = next((path for path in cuda_candidates if path and (path / "bin").exists()), None)
        cuda_bin = str(cuda_root_path / "bin") if cuda_root_path else ""
        if hasattr(os, "add_dll_directory"):
            if cuda_bin and Path(cuda_bin).exists():
                os.add_dll_directory(cuda_bin)
            os.add_dll_directory(str(dll_dir))
        os.environ["PATH"] = ";".join(part for part in (cuda_bin, str(dll_dir), os.environ.get("PATH", "")) if part)

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
        lib.audiocpp_generate_voice_clone.restype = c_int32
        lib.audiocpp_generate_voice_clone.argtypes = [
            c_void_p,
            c_char_p,
            c_char_p,
            c_char_p,
            c_char_p,
            _PROGRESS_FN,
            c_void_p,
            POINTER(_AudioResult),
        ]
        lib.audiocpp_generate_voice_clone_stream.restype = c_int32
        lib.audiocpp_generate_voice_clone_stream.argtypes = [
            c_void_p,
            c_char_p,
            c_char_p,
            c_char_p,
            c_char_p,
            _PROGRESS_FN,
            _AUDIO_CHUNK_FN,
            c_void_p,
            POINTER(_AudioResult),
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
        self._loaded = True

    async def unload(self) -> None:
        if not self._loaded or not self._lib or not self._engine:
            self._loaded = False
            return
        lib, engine = self._lib, self._engine
        self._lib = None
        self._engine = None
        self._loaded = False
        def release() -> None:
            with self._generation_lock:
                lib.audiocpp_unload_model(engine)
                lib.audiocpp_destroy(engine)

        await asyncio.get_running_loop().run_in_executor(None, release)

    @staticmethod
    def _float_audio_to_pcm(samples: POINTER(c_float), count: int, *, validate: bool = True) -> bytes:
        import numpy as np

        values = np.ctypeslib.as_array(samples, shape=(count,)).copy()
        rms = float(np.sqrt(np.mean(values * values))) if values.size else 0.0
        if validate and rms < 0.0001:
            raise RuntimeError(f"Native Higgs generated effectively silent audio (RMS {rms:.6f})")
        return (np.clip(values, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()

    def _generate_blocking(self, text: str) -> tuple[bytes, int]:
        with heavy_gpu_inference(), self._generation_lock:
            lib, engine = self._lib, self._engine
            if not lib or not engine:
                raise RuntimeError("Native Higgs adapter was unloaded before synthesis")
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
                return self._float_audio_to_pcm(result.samples, int(result.sample_count)), int(result.sample_rate or self._SAMPLE_RATE_HZ)
            finally:
                lib.audiocpp_free_result(ctypes.byref(result))

    @staticmethod
    def _release_unused_torch_cuda_cache() -> None:
        """Return unused PyTorch reservations without unloading live ASR tensors."""
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

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
    def _prepare_reference_clip(cls, ref_audio_path: str, ref_text: str) -> tuple[str, str, Path]:
        """Create a stable bounded reference and DLL speaker-conditioning cache."""
        source = Path(ref_audio_path)
        cache_key = cls._reference_digest(source, ref_text)
        cache_dir = source.parent / ".higgs_native_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        speaker_cache = cache_dir / f"speaker_{cache_key}.hspkcache"
        with wave.open(str(source), "rb") as reader:
            frame_rate = reader.getframerate()
            frame_count = reader.getnframes()
            duration = frame_count / frame_rate if frame_rate else 0.0
            if duration <= cls._MAX_REFERENCE_SECONDS:
                return str(source), ref_text, speaker_cache

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
            logger.info(
                "Cached %.1fs native Higgs reference clip from %.1fs profile audio",
                cls._MAX_REFERENCE_SECONDS,
                duration,
            )
        return str(clip_path), clipped_text, speaker_cache

    @staticmethod
    def _split_clauses(text: str, *, max_words: int = 18, max_chars: int = 140) -> list[str]:
        """Split translated text at natural boundaries before hard word limits."""
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

    def _generate_voice_clone_stream_blocking(
        self,
        text: str,
        ref_audio_path: str,
        ref_text: str,
        on_pcm,
    ) -> tuple[int, int]:
        self._release_unused_torch_cuda_cache()
        with heavy_gpu_inference(), self._generation_lock:
            lib, engine = self._lib, self._engine
            if not lib or not engine:
                raise RuntimeError("Native Higgs adapter was unloaded before voice cloning")
            prepared_path, prepared_text, cache_path = self._prepare_reference_clip(ref_audio_path, ref_text)
            total_samples = 0
            sample_rate = self._SAMPLE_RATE_HZ
            square_sum = 0.0
            callback_error: list[BaseException] = []

            def audio_callback(rate, channels, _start, samples, count, _is_final, _user_data) -> None:
                nonlocal total_samples, sample_rate, square_sum
                try:
                    if channels != 1:
                        raise RuntimeError(f"Native Higgs returned unsupported {channels}-channel audio")
                    import numpy as np

                    values = np.ctypeslib.as_array(samples, shape=(int(count),)).copy()
                    if values.size:
                        square_sum += float(np.sum(values * values))
                        total_samples += int(values.size)
                        sample_rate = int(rate or self._SAMPLE_RATE_HZ)
                        on_pcm((np.clip(values, -1.0, 1.0) * 32767.0).astype("<i2").tobytes(), sample_rate)
                except BaseException as exc:
                    callback_error.append(exc)

            native_callback = _AUDIO_CHUNK_FN(audio_callback)
            for clause in self._split_clauses(text):
                result = _AudioResult()
                before = total_samples
                try:
                    status = lib.audiocpp_generate_voice_clone_stream(
                        engine,
                        clause.encode("utf-8"),
                        prepared_path.encode("utf-8"),
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
                        import numpy as np

                        values = np.ctypeslib.as_array(
                            result.samples, shape=(int(result.sample_count),)
                        ).copy()
                        square_sum += float(np.sum(values * values))
                        pcm = (np.clip(values, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
                        on_pcm(pcm, int(result.sample_rate or self._SAMPLE_RATE_HZ))
                        total_samples += int(result.sample_count)
                finally:
                    lib.audiocpp_free_result(ctypes.byref(result))

            rms = (square_sum / total_samples) ** 0.5 if total_samples else 0.0
            if not total_samples or rms < 0.0001:
                raise RuntimeError(f"Native Higgs generated effectively silent audio (RMS {rms:.6f})")
            return sample_rate, total_samples

    async def synthesize_stream(
        self,
        text: str,
        language: LanguageCode,
        voice: VoiceSpec,
    ) -> AsyncIterator[TtsAudioChunk]:
        if not self._loaded:
            raise RuntimeError("Native Higgs adapter is not loaded")
        clean = str(text).strip()
        if not clean:
            raise ValueError("Target TTS text must not be empty")
        if voice.is_cloned:
            _, ref_audio, ref_text = resolve_profile_reference(
                self._profiles_root, voice.voice_profile_id, require_transcript=True
            )
            loop = asyncio.get_running_loop()
            queue: asyncio.Queue[tuple[Optional[bytes], int, Optional[BaseException]]] = asyncio.Queue()

            def emit(pcm: bytes, sample_rate: int) -> None:
                loop.call_soon_threadsafe(queue.put_nowait, (pcm, sample_rate, None))

            async def produce() -> None:
                try:
                    await loop.run_in_executor(
                        None,
                        self._generate_voice_clone_stream_blocking,
                        clean,
                        str(ref_audio),
                        ref_text,
                        emit,
                    )
                    await queue.put((None, self._SAMPLE_RATE_HZ, None))
                except BaseException as exc:
                    await queue.put((None, self._SAMPLE_RATE_HZ, exc))

            producer = asyncio.create_task(produce())
            utterance_id = str(uuid.uuid4())
            segment_id = str(uuid.uuid4())
            sequence = 0
            final_rate = self._SAMPLE_RATE_HZ
            try:
                while True:
                    pcm, sample_rate, error = await queue.get()
                    if error:
                        raise error
                    if pcm is None:
                        break
                    final_rate = sample_rate
                    yield TtsAudioChunk(
                        utterance_id=utterance_id,
                        segment_id=segment_id,
                        sequence=sequence,
                        sample_rate_hz=sample_rate,
                        sample_format=SampleFormat.PCM_S16LE,
                        data=pcm,
                        is_final_chunk=False,
                    )
                    sequence += 1
                await producer
            finally:
                if not producer.done():
                    producer.cancel()
            yield TtsAudioChunk(
                utterance_id=utterance_id,
                segment_id=segment_id,
                sequence=sequence,
                sample_rate_hz=final_rate,
                sample_format=SampleFormat.PCM_S16LE,
                data=b"",
                is_final_chunk=True,
            )
            return

        pcm, sample_rate = await asyncio.get_running_loop().run_in_executor(None, self._generate_blocking, clean)
        utterance_id = str(uuid.uuid4())
        segment_id = str(uuid.uuid4())
        chunk_size = 16384
        for sequence, start in enumerate(range(0, len(pcm), chunk_size)):
            yield TtsAudioChunk(
                utterance_id=utterance_id,
                segment_id=segment_id,
                sequence=sequence,
                sample_rate_hz=sample_rate,
                sample_format=SampleFormat.PCM_S16LE,
                data=pcm[start:start + chunk_size],
                is_final_chunk=False,
            )
        yield TtsAudioChunk(
            utterance_id=utterance_id,
            segment_id=segment_id,
            sequence=(len(pcm) + chunk_size - 1) // chunk_size,
            sample_rate_hz=sample_rate,
            sample_format=SampleFormat.PCM_S16LE,
            data=b"",
            is_final_chunk=True,
        )

    async def supports_voice_cloning(self) -> bool:
        return True

    async def generate_cloned_audio(
        self,
        text: str,
        ref_audio_path: str,
        ref_text: str = "",
        num_step: int = 32,
        language: str = "English",
    ) -> bytes:
        """Generate speech conditioned on the saved reference recording and transcript."""
        if not self._loaded:
            raise RuntimeError("Native Higgs adapter is not loaded")
        clean = str(text).strip()
        reference = Path(ref_audio_path)
        if not clean:
            raise ValueError("Target TTS text must not be empty")
        if not reference.exists():
            raise FileNotFoundError(f"Reference audio not found: {reference}")
        if not str(ref_text).strip():
            raise ValueError("Native Higgs voice cloning requires the reference transcript")
        chunks: list[bytes] = []
        sample_rate, _ = await asyncio.get_running_loop().run_in_executor(
            None,
            self._generate_voice_clone_stream_blocking,
            clean,
            str(reference),
            str(ref_text).strip(),
            lambda pcm, _rate: chunks.append(pcm),
        )
        pcm = b"".join(chunks)
        output = io.BytesIO()
        with wave.open(output, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm)
        return output.getvalue()

    async def supports_language(self, language: LanguageCode) -> bool:
        return language in {
            LanguageCode.EN,
            LanguageCode.RO,
            LanguageCode.ES,
            LanguageCode.FR,
            LanguageCode.DE,
            LanguageCode.IT,
        }

    @property
    def native_sample_rate_hz(self) -> int:
        return self._SAMPLE_RATE_HZ

    async def health_check(self) -> bool:
        return bool(self._loaded and self._engine and self._lib)
