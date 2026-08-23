"""VoxPassport TTS adapters.

ManifestTtsAdapter is the normal integration point for worker-backed TTS
models. Concrete XTTS/MOSS/VoxCPM names remain as compatibility shims only.
"""

from runtime.inference.adapters.tts.manifest_tts_adapter import ManifestTtsAdapter
from runtime.inference.adapters.tts.omnivoice_tts_adapter import OmniVoiceTtsAdapter
from runtime.inference.adapters.tts.higgs_tts_adapter import HiggsTtsAdapter
from runtime.inference.adapters.tts.higgs_native_tts_adapter import HiggsNativeTtsAdapter
from runtime.inference.adapters.tts.voxcpm_tts_adapter import VoxCpmTtsAdapter
from runtime.inference.adapters.tts.moss_tts_adapter import MossTtsAdapter
from runtime.inference.adapters.tts.xtts_romanian_tts_adapter import XttsRomanianTtsAdapter

__all__ = [
    "ManifestTtsAdapter",
    "OmniVoiceTtsAdapter",
    "HiggsTtsAdapter",
    "HiggsNativeTtsAdapter",
    "VoxCpmTtsAdapter",
    "MossTtsAdapter",
    "XttsRomanianTtsAdapter",
]
