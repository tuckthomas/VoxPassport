from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from runtime.inference.adapters.tts.manifest_tts_adapter import ManifestTtsAdapter
from runtime.inference.protocol import LanguageCode, VoiceSpec
from runtime.inference.tts_plugins.manifest import TtsManifestCatalog
from runtime.inference.tts_plugins.runtime_profiles import RuntimeProfileCatalog
from runtime.inference.tts_plugins.runtime_supervisor import TtsRuntimeSupervisor

FAKE_DRIVER = "tests.support.supervisor_fake_tts_driver:SupervisorFakeTtsDriver"


def _write_profiles(tmp_path: Path, *, idle_timeout: float = 0.2) -> RuntimeProfileCatalog:
    path = tmp_path / "runtime_profiles.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profiles": {
                    "alpha": {
                        "interpreter": sys.executable,
                        "startup_timeout_seconds": 8,
                        "idle_timeout_seconds": idle_timeout,
                        "environment": {},
                        "provisioning": {},
                    },
                    "beta": {
                        "interpreter": sys.executable,
                        "startup_timeout_seconds": 8,
                        "idle_timeout_seconds": idle_timeout,
                        "environment": {},
                        "provisioning": {},
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return RuntimeProfileCatalog(path).load()


def _manifest_payload(model_id: str, profile: str, options: dict | None = None) -> dict:
    return {
        "schema_version": 2,
        "model_id": model_id,
        "display_name": model_id,
        "aliases": [],
        "runtime_profile": profile,
        "driver": {"entrypoint": FAKE_DRIVER, "options": options or {}},
        "capabilities": {
            "languages": ["en", "ro"],
            "streaming": True,
            "voice_cloning": False,
            "cross_lingual_voice_cloning": False,
        },
        "voice_cloning": {"reference_transcript_required": False},
        "audio": {"sample_rate_hz": 24000, "sample_format": "pcm_s16le"},
        "registry": {"provider": "test"},
    }


def _write_manifests(tmp_path: Path, payloads: list[dict]) -> TtsManifestCatalog:
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    for payload in payloads:
        (manifest_dir / f"{payload['model_id']}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
    return TtsManifestCatalog(manifest_dir).load()


def _supervisor(tmp_path: Path, payloads: list[dict], *, idle_timeout: float = 0.2) -> TtsRuntimeSupervisor:
    return TtsRuntimeSupervisor(
        manifest_catalog=_write_manifests(tmp_path, payloads),
        profile_catalog=_write_profiles(tmp_path, idle_timeout=idle_timeout),
        project_root=Path(__file__).resolve().parents[1],
        log_dir=tmp_path / "logs",
    )


def test_adapter_load_is_logical_and_does_not_spawn_worker(tmp_path: Path):
    supervisor = _supervisor(tmp_path, [_manifest_payload("one", "alpha")])
    manifest = supervisor.manifest_catalog.resolve("one")
    adapter = ManifestTtsAdapter(manifest, profiles_root=tmp_path, supervisor=supervisor)

    async def exercise():
        await adapter.load()
        state = await supervisor.status()
        alpha = next(item for item in state["profiles"] if item["profile_id"] == "alpha")
        assert state["active_model_id"] is None
        assert alpha["running"] is False
        await supervisor.shutdown()

    asyncio.run(exercise())


def test_same_profile_models_reuse_one_worker_and_dynamic_endpoint(tmp_path: Path):
    supervisor = _supervisor(
        tmp_path,
        [_manifest_payload("one", "alpha"), _manifest_payload("two", "alpha")],
    )

    async def exercise():
        endpoint_one, _ = await supervisor.activate("one")
        first = await supervisor.status()
        alpha_first = next(item for item in first["profiles"] if item["profile_id"] == "alpha")
        pid_one = alpha_first["pid"]
        assert endpoint_one.startswith("http://127.0.0.1:")
        assert not endpoint_one.endswith(":8098")
        assert not endpoint_one.endswith(":8099")

        endpoint_two, _ = await supervisor.activate("two")
        second = await supervisor.status()
        alpha_second = next(item for item in second["profiles"] if item["profile_id"] == "alpha")
        assert endpoint_two == endpoint_one
        assert alpha_second["pid"] == pid_one
        assert second["active_model_id"] == "two"
        await supervisor.shutdown()

    asyncio.run(exercise())


def test_cross_profile_switch_terminates_previous_worker(tmp_path: Path):
    supervisor = _supervisor(
        tmp_path,
        [_manifest_payload("one", "alpha"), _manifest_payload("two", "beta")],
    )

    async def exercise():
        await supervisor.activate("one")
        first = await supervisor.status()
        alpha_first = next(item for item in first["profiles"] if item["profile_id"] == "alpha")
        assert alpha_first["running"] is True

        await supervisor.activate("two")
        second = await supervisor.status()
        alpha_second = next(item for item in second["profiles"] if item["profile_id"] == "alpha")
        beta_second = next(item for item in second["profiles"] if item["profile_id"] == "beta")
        assert alpha_second["running"] is False
        assert beta_second["running"] is True
        assert second["active_profile_id"] == "beta"
        assert second["active_model_id"] == "two"
        await supervisor.shutdown()

    asyncio.run(exercise())


def test_release_unloads_then_idle_shutdown_stops_worker(tmp_path: Path):
    supervisor = _supervisor(
        tmp_path,
        [_manifest_payload("one", "alpha")],
        idle_timeout=0.1,
    )

    async def exercise():
        await supervisor.activate("one")
        await supervisor.release("one")
        immediate = await supervisor.status()
        alpha = next(item for item in immediate["profiles"] if item["profile_id"] == "alpha")
        assert alpha["running"] is True
        assert alpha["loaded_model_id"] is None
        await asyncio.sleep(0.25)
        later = await supervisor.status()
        alpha_later = next(item for item in later["profiles"] if item["profile_id"] == "alpha")
        assert alpha_later["running"] is False
        await supervisor.shutdown()

    asyncio.run(exercise())


def test_worker_crash_during_load_rolls_back_previous_model(tmp_path: Path):
    marker = tmp_path / "load-crash.marker"
    supervisor = _supervisor(
        tmp_path,
        [
            _manifest_payload("good", "alpha"),
            _manifest_payload("crashy", "beta", {"crash_load_once_marker": str(marker)}),
        ],
    )

    async def exercise():
        await supervisor.activate("good")
        with pytest.raises(Exception):
            await supervisor.activate("crashy")
        assert marker.exists()
        state = await supervisor.status()
        assert state["active_model_id"] == "good"
        assert state["active_profile_id"] == "alpha"
        alpha = next(item for item in state["profiles"] if item["profile_id"] == "alpha")
        assert alpha["running"] is True
        await supervisor.shutdown()

    asyncio.run(exercise())


def test_adapter_recovers_worker_crash_before_first_audio(tmp_path: Path):
    marker = tmp_path / "synthesis-crash.marker"
    supervisor = _supervisor(
        tmp_path,
        [_manifest_payload("one", "alpha", {"crash_once_marker": str(marker)})],
    )
    manifest = supervisor.manifest_catalog.resolve("one")
    adapter = ManifestTtsAdapter(manifest, profiles_root=tmp_path, supervisor=supervisor)

    async def exercise():
        await adapter.load()
        chunks = []
        async for chunk in adapter.synthesize_stream(
            "hello",
            LanguageCode.EN,
            VoiceSpec(voice_profile_id="default", is_cloned=False),
        ):
            chunks.append(chunk)
        assert marker.exists()
        assert any(chunk.data for chunk in chunks)
        assert chunks[-1].is_final_chunk is True
        state = await supervisor.status()
        assert state["active_model_id"] == "one"
        alpha = next(item for item in state["profiles"] if item["profile_id"] == "alpha")
        assert alpha["running"] is True
        await adapter.unload()
        await supervisor.shutdown()

    asyncio.run(exercise())
