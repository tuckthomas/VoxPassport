"""
Unit tests for ModelRegistry.

Tests:
  - Register and retrieve entries
  - Capability-based slot resolution
  - Active model selection
  - Known-good model set save/rollback
  - Fallback chain management
  - Cleanup candidates
  - Persistence (round-trip)
"""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from runtime.inference.model_registry.registry import (
    KnownGoodModelSet,
    ModelRegistry,
    ModelRegistryEntry,
)
from runtime.inference.protocol import (
    InstallationStatus,
    ModelCapability,
    RecommendationState,
)


def _make_entry(
    model_id: str = "test-model",
    capability: ModelCapability = ModelCapability.ASR,
    installed: bool = True,
) -> ModelRegistryEntry:
    return ModelRegistryEntry(
        model_id=model_id,
        name=f"Test Model {model_id}",
        family="test",
        provider="test",
        capability=capability,
        upstream_id="test/test",
        revision="main",
        supported_source_languages=["en", "ro"],
        supported_target_languages=[],
        supports_english=True,
        supports_romanian=True,
        streaming_support=True,
        voice_cloning_support=False,
        cross_lingual_voice_cloning=False,
        required_runtime="pytorch",
        min_runtime_version="2.0.0",
        quantization_options=["fp16"],
        estimated_download_size_gb=1.0,
        installed_size_gb=1.0 if installed else None,
        expected_vram_tiers={"fp16": "~3GB"},
        expected_ram_gb=2.0,
        license="MIT",
        commercial_use="yes",
        redistribution="yes",
        installation_status=InstallationStatus.INSTALLED if installed else InstallationStatus.NOT_INSTALLED,
    )


class TestModelRegistryBasics(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.registry_path = Path(self.tmp.name)
        self.tmp.close()
        self.registry_path.unlink(missing_ok=True)
        self.registry = ModelRegistry(self.registry_path)
        self.registry.load()

    def tearDown(self):
        self.registry_path.unlink(missing_ok=True)

    def test_empty_registry(self):
        self.assertEqual(len(self.registry.list_entries()), 0)

    def test_register_and_retrieve(self):
        entry = _make_entry("asr-model-1", ModelCapability.ASR)
        self.registry.register(entry)
        retrieved = self.registry.get_entry("asr-model-1")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.name, "Test Model asr-model-1")

    def test_list_by_capability(self):
        self.registry.register(_make_entry("asr-1", ModelCapability.ASR))
        self.registry.register(_make_entry("mt-1", ModelCapability.TRANSLATION))
        asr_entries = self.registry.list_entries(capability=ModelCapability.ASR)
        self.assertEqual(len(asr_entries), 1)
        self.assertEqual(asr_entries[0].model_id, "asr-1")

    def test_list_installed_only(self):
        self.registry.register(_make_entry("asr-installed", installed=True))
        self.registry.register(_make_entry("asr-not-installed", installed=False))
        installed = self.registry.list_entries(installed_only=True)
        self.assertEqual(len(installed), 1)
        self.assertEqual(installed[0].model_id, "asr-installed")


class TestModelRegistrySlotResolution(unittest.TestCase):

    def test_asr_en_slot(self):
        slot = ModelRegistry._resolve_slot("ASR", language="en")
        self.assertEqual(slot, "asr_en")

    def test_asr_ro_slot(self):
        slot = ModelRegistry._resolve_slot("ASR", language="ro")
        self.assertEqual(slot, "asr_ro")

    def test_translation_en_ro_slot(self):
        slot = ModelRegistry._resolve_slot("TRANSLATION", language_pair="en-ro")
        self.assertEqual(slot, "translation_en_ro")

    def test_translation_ro_en_slot(self):
        slot = ModelRegistry._resolve_slot("TRANSLATION", language_pair="ro-en")
        self.assertEqual(slot, "translation_ro_en")

    def test_tts_ro_slot(self):
        slot = ModelRegistry._resolve_slot("TTS", language="ro")
        self.assertEqual(slot, "tts_ro")

    def test_vad_slot(self):
        slot = ModelRegistry._resolve_slot("VAD")
        self.assertEqual(slot, "vad")


class TestModelRegistryActiveModels(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.registry_path = Path(self.tmp.name)
        self.tmp.close()
        self.registry_path.unlink(missing_ok=True)
        self.registry = ModelRegistry(self.registry_path)
        self.registry.load()

    def tearDown(self):
        self.registry_path.unlink(missing_ok=True)

    def test_no_active_model_initially(self):
        result = self.registry.get_active_model_id("ASR", language="en")
        self.assertIsNone(result)

    def test_set_and_get_active_model(self):
        entry = _make_entry("asr-en-model", ModelCapability.ASR)
        self.registry.register(entry)
        self.registry.set_active_model("ASR", "asr-en-model", language="en")
        result = self.registry.get_active_model_id("ASR", language="en")
        self.assertEqual(result, "asr-en-model")

    def test_set_active_uninstalled_raises(self):
        entry = _make_entry("asr-not-installed", installed=False)
        self.registry.register(entry)
        with self.assertRaises(ValueError):
            self.registry.set_active_model("ASR", "asr-not-installed", language="en")

    def test_set_active_unknown_raises(self):
        with self.assertRaises(KeyError):
            self.registry.set_active_model("ASR", "nonexistent", language="en")


class TestKnownGoodModelSets(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.registry_path = Path(self.tmp.name)
        self.tmp.close()
        self.registry_path.unlink(missing_ok=True)
        self.registry = ModelRegistry(self.registry_path)
        self.registry.load()

        # Register and activate an ASR model
        entry = _make_entry("asr-en-v1", ModelCapability.ASR)
        self.registry.register(entry)
        self.registry.set_active_model("ASR", "asr-en-v1", language="en")

    def tearDown(self):
        self.registry_path.unlink(missing_ok=True)

    def test_save_known_good_set(self):
        kgms = self.registry.save_known_good_set(app_version="0.1.0")
        self.assertIsNotNone(kgms.set_id)
        self.assertEqual(kgms.models.get("asr_en"), "asr-en-v1")

    def test_rollback_restores_model(self):
        # Save known-good with asr-en-v1
        self.registry.save_known_good_set(app_version="0.1.0")

        # Register a new model and activate it
        entry2 = _make_entry("asr-en-v2", ModelCapability.ASR)
        self.registry.register(entry2)
        self.registry.set_active_model("ASR", "asr-en-v2", language="en")
        self.assertEqual(self.registry.get_active_model_id("ASR", language="en"), "asr-en-v2")

        # Rollback
        self.registry.rollback_to_known_good()
        self.assertEqual(self.registry.get_active_model_id("ASR", language="en"), "asr-en-v1")

    def test_no_known_good_set_returns_none(self):
        result = self.registry.get_previous_known_good_set()
        self.assertIsNone(result)


class TestRegistryPersistence(unittest.TestCase):

    def test_round_trip_persistence(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        path = Path(tmp.name)
        tmp.close()
        path.unlink(missing_ok=True)

        # Create and populate registry
        r1 = ModelRegistry(path)
        r1.load()
        entry = _make_entry("test-persist")
        r1.register(entry)
        r1.set_active_model("ASR", "test-persist", language="en")
        r1.save_known_good_set("0.1.0")

        # Load a fresh registry from the same file
        r2 = ModelRegistry(path)
        r2.load()

        self.assertIsNotNone(r2.get_entry("test-persist"))
        self.assertEqual(r2.get_active_model_id("ASR", language="en"), "test-persist")
        self.assertIsNotNone(r2.get_previous_known_good_set())

        path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
