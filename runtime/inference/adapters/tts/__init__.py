"""
LiveTranslator — TTS Adapters Package
"""

from runtime.inference.adapters.tts.omnivoice_tts_adapter import OmniVoiceTtsAdapter
from runtime.inference.adapters.tts.higgs_tts_adapter import HiggsTtsAdapter
from runtime.inference.adapters.tts.higgs_native_tts_adapter import HiggsNativeTtsAdapter
from runtime.inference.adapters.tts.voxcpm_tts_adapter import VoxCpmTtsAdapter
from runtime.inference.adapters.tts.moss_tts_adapter import MossTtsAdapter

__all__ = [
    "OmniVoiceTtsAdapter",
    "HiggsTtsAdapter",
    "HiggsNativeTtsAdapter",
    "VoxCpmTtsAdapter",
    "MossTtsAdapter",
]
