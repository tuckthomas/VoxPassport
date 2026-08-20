"""Process-wide coordination for heavyweight CUDA inference.

Capture and VAD continue while this lock is held.  Only model execution is
serialized so an 8 GB GPU does not run Parakeet ASR and native Higgs TTS kernels
at the same time.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator


_HEAVY_GPU_INFERENCE_LOCK = threading.RLock()


@contextmanager
def heavy_gpu_inference() -> Iterator[None]:
    with _HEAVY_GPU_INFERENCE_LOCK:
        yield
