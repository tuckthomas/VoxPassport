"""
LiveTranslator — Direct Model Downloader
Downloads model weights directly into M:\LiveTranslator\models\<model_id>.
Uses pure Python standard library (urllib.request with Range support) or huggingface_hub.
Never touches Drive D or external system folders.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# Add project root and packages directory to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGES_DIR = PROJECT_ROOT / "packages"
MODELS_DIR = PROJECT_ROOT / "models"
STAGING_DIR = MODELS_DIR / ".staging"

if str(PACKAGES_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGES_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Set local project cache
os.environ["HF_HOME"] = str(PROJECT_ROOT / ".cache" / "huggingface")
os.environ["TRANSFORMERS_CACHE"] = str(PROJECT_ROOT / ".cache" / "huggingface" / "transformers")
os.environ["TORCH_HOME"] = str(PROJECT_ROOT / ".cache" / "torch")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("download_models")

from runtime.inference.model_registry.installers.huggingface_installer import HuggingFaceInstaller
from runtime.inference.model_registry.catalog import get_builtin_catalog


async def download_model(model_id: str, upstream_id: str, revision: str = "main"):
    logger.info("Target directory: %s", MODELS_DIR / model_id)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    STAGING_DIR.mkdir(parents=True, exist_ok=True)

    installer = HuggingFaceInstaller(
        model_store_dir=MODELS_DIR,
        staging_dir=STAGING_DIR,
    )

    logger.info("Starting download of %s (%s @ %s)...", model_id, upstream_id, revision)
    async for progress in installer.install(
        model_id=model_id,
        upstream_id=upstream_id,
        revision=revision,
    ):
        if progress.phase == "downloading":
            pct = f"{progress.percent:.1f}%" if progress.bytes_total > 0 else "in progress"
            logger.info("Downloading: %s - %s", progress.message, pct)
        elif progress.phase == "validating":
            logger.info("Validating download: %s", progress.message)
        elif progress.phase == "smoke_testing":
            logger.info("Running smoke test: %s", progress.message)
        elif progress.phase == "promoting":
            logger.info("Promoting to models directory: %s", progress.message)
        elif progress.phase == "done":
            logger.info("SUCCESS: Model %s installed at %s", model_id, MODELS_DIR / model_id)
        elif progress.phase == "failed":
            logger.error("FAILED: %s - Error: %s", progress.message, progress.error)


def main():
    parser = argparse.ArgumentParser(description="Download model weights into project models/ directory")
    parser.add_argument("--model", type=str, required=True, help="Catalog model_id or custom ID")
    parser.add_argument("--upstream", type=str, default=None, help="Upstream Hugging Face repo ID")
    parser.add_argument("--revision", type=str, default="main", help="Git revision or branch")
    args = parser.parse_args()

    upstream_id = args.upstream
    if not upstream_id:
        catalog = {e.model_id: e for e in get_builtin_catalog()}
        if args.model in catalog:
            upstream_id = catalog[args.model].upstream_id
        else:
            logger.error("Model ID '%s' not in catalog and no --upstream provided.", args.model)
            sys.exit(1)

    asyncio.run(download_model(args.model, upstream_id, args.revision))


if __name__ == "__main__":
    main()
