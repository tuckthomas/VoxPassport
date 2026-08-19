import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGES_DIR = PROJECT_ROOT / "packages"
MODELS_DIR = PROJECT_ROOT / "models"

if str(PACKAGES_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGES_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.inference.adapters.translation.milmmt46_translation_adapter import MiLMMT46TranslationAdapter
from runtime.inference.protocol import LanguageCode
import asyncio

async def main():
    print("Testing live translation inference using downloaded model in M:\\LiveTranslator\\models\\xiaomi-milmmt-46-1b-v1.0...")
    adapter = MiLMMT46TranslationAdapter(model_size="1b", device="cuda")
    # Point model_id to the exact local path
    adapter._model_id = str(MODELS_DIR / "xiaomi-milmmt-46-1b-v1.0")
    await adapter.load()
    
    test_text = "Hello, how are you today?"
    print(f"Translating: {test_text}")
    res = await adapter.translate(test_text, LanguageCode.EN, LanguageCode.RO)
    print(f"Result: {res.translated_text} (Latency: {res.latency_ms:.1f}ms)")

if __name__ == "__main__":
    asyncio.run(main())
