from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from runtime.inference.adapters.tts.manifest_tts_adapter import ManifestTtsAdapter
from runtime.inference.protocol import LanguageCode, VoiceSpec
from runtime.inference.tts_plugins.backend_runtime import BackendRuntimeCatalog
from runtime.inference.tts_plugins.manifest import TtsManifestCatalog
from runtime.inference.tts_plugins.runtime_profiles import RuntimeProfileCatalog
from runtime.inference.tts_plugins.runtime_supervisor import TtsRuntimeSupervisor

FAKE_DRIVER = "tests.support.supervisor_fake_tts_driver:SupervisorFakeTtsDriver"
PROXY_DRIVER = "runtime.workers.tts_host.drivers.openai_proxy:OpenAiSpeechProxyDriver"
FAKE_BACKEND = Path(__file__).resolve().parent / "support" / "supervisor_fake_backend.py"
TEST_REMOTE_URL_ENV = "VOXPASSPORT_TEST_TTS_BACKEND_URL"


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


def _backend_runtime_payload() -> dict:
    return {
        "schema_version": 1,
        "backend_runtime_id": "fake-openai-server",
        "runtime_profile": "alpha",
        "launch": {
            "command": [
                "{python}",
                str(FAKE_BACKEND),
                "--host",
                "{host}",
                "--port",
                "{port}",
                "--checkpoint",
                "{checkpoint}",
                "--restart-health-marker",
                "{restart_health_marker}",
                "--launch-record",
                "{launch_record}",
            ]
        },
        "remote_url_env": TEST_REMOTE_URL_ENV,
        "health_path": "/v1/models",
        "startup_timeout_seconds": 8,
        "endpoint_driver_option": "backend_url",
        "arguments": {
            "checkpoint": {"required": True},
            "restart_health_marker": {"default": ""},
            "launch_record": {"default": ""},
        },
    }


def _write_backend_runtimes(tmp_path: Path, payloads: list[dict] | None = None) -> BackendRuntimeCatalog:
    runtime_dir = tmp_path / "backend-runtimes"
    runtime_dir.mkdir()
    for payload in payloads or [_backend_runtime_payload()]:
        (runtime_dir / f"{payload['backend_runtime_id']}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
    return BackendRuntimeCatalog(runtime_dir).load()


def _manifest_payload(model_id: str, profile: str, options: dict | None = None) -> dict:
    return {
        "schema_version": 3,
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


def _proxy_manifest_payload(
    model_id: str,
    profile: str = "alpha",
    *,
    checkpoint: str | None = None,
    restart_health_marker: Path | None = None,
    launch_record: Path | None = None,
) -> dict:
    options: dict[str, object] = {
        "health_path": "/v1/models",
        "speech_path": "/v1/audio/speech",
        "text_field": "input",
        "response_format_field": "response_format",
        "stream_field": "stream",
        "language_field": "language",
        "reference_audio_field": "ref_audio",
        "reference_text_field": "ref_text",
    }
    payload = _manifest_payload(model_id, profile)
    payload["backend_runtime"] = "fake-openai-server"
    payload["backend_args"] = {
        "checkpoint": checkpoint or f"checkpoint/{model_id}",
        "restart_health_marker": str(restart_health_marker) if restart_health_marker else "",
        "launch_record": str(launch_record) if launch_record else "",
    }
    payload["driver"] = {"entrypoint": PROXY_DRIVER, "options": options}
    return payload


def _write_manifests(
    tmp_path: Path,
    payloads: list[dict],
    backend_catalog: BackendRuntimeCatalog,
) -> TtsManifestCatalog:
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    for payload in payloads:
        (manifest_dir / f"{payload['model_id']}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
    return TtsManifestCatalog(
        manifest_dir,
        backend_runtime_catalog=backend_catalog,
    ).load()


def _supervisor(
    tmp_path: Path,
    payloads: list[dict],
    *,
    idle_timeout: float = 0.2,
    backend_payloads: list[dict] | None = None,
) -> TtsRuntimeSupervisor:
    backend_catalog = _write_backend_runtimes(tmp_path, backend_payloads)
    return TtsRuntimeSupervisor(
        manifest_catalog=_write_manifests(tmp_path, payloads, backend_catalog),
        profile_catalog=_write_profiles(tmp_path, idle_timeout=idle_timeout),
        backend_runtime_catalog=backend_catalog,
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
        assert state["backends"] == []
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
    supervisor = _supervisor(tmp_path, [_manifest_payload("one", "alpha")], idle_timeout=0.1)

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


def test_managed_proxy_backend_uses_dynamic_endpoint_and_is_killed_on_switch(tmp_path: Path):
    supervisor = _supervisor(
        tmp_path,
        [_proxy_manifest_payload("proxy"), _manifest_payload("direct", "alpha")],
    )

    async def exercise():
        await supervisor.activate("proxy")
        first = await supervisor.status()
        assert first["active_model_id"] == "proxy"
        assert len(first["backends"]) == 1
        backend = first["backends"][0]
        assert backend["model_id"] == "proxy"
        assert backend["backend_runtime_id"] == "fake-openai-server"
        assert backend["managed"] is True
        assert backend["running"] is True
        assert backend["endpoint"].startswith("http://127.0.0.1:")
        assert not backend["endpoint"].endswith(":8095")
        assert not backend["endpoint"].endswith(":8096")
        assert not backend["endpoint"].endswith(":8097")

        await supervisor.activate("direct")
        second = await supervisor.status()
        assert second["active_model_id"] == "direct"
        assert second["backends"] == []
        await supervisor.shutdown()

    asyncio.run(exercise())


def test_two_models_hot_swap_through_one_backend_runtime_definition(tmp_path: Path):
    first_record = tmp_path / "first-checkpoint.txt"
    second_record = tmp_path / "second-checkpoint.txt"
    supervisor = _supervisor(
        tmp_path,
        [
            _proxy_manifest_payload(
                "proxy-one",
                checkpoint="vendor/model-one",
                launch_record=first_record,
            ),
            _proxy_manifest_payload(
                "proxy-two",
                checkpoint="vendor/model-two",
                launch_record=second_record,
            ),
        ],
    )

    async def exercise():
        await supervisor.activate("proxy-one")
        assert first_record.read_text(encoding="utf-8") == "vendor/model-one"
        first = await supervisor.status()
        first_backend_pid = first["backends"][0]["pid"]

        await supervisor.activate("proxy-two")
        assert second_record.read_text(encoding="utf-8") == "vendor/model-two"
        second = await supervisor.status()
        assert second["active_model_id"] == "proxy-two"
        assert second["backends"][0]["backend_runtime_id"] == "fake-openai-server"
        assert second["backends"][0]["pid"] != first_backend_pid
        await supervisor.shutdown()

    asyncio.run(exercise())


def test_managed_proxy_backend_is_killed_on_release(tmp_path: Path):
    supervisor = _supervisor(tmp_path, [_proxy_manifest_payload("proxy")])

    async def exercise():
        await supervisor.activate("proxy")
        assert (await supervisor.status())["backends"]
        await supervisor.release("proxy")
        state = await supervisor.status()
        assert state["active_model_id"] is None
        assert state["backends"] == []
        await supervisor.shutdown()

    asyncio.run(exercise())


def test_managed_proxy_backend_is_recycled_when_process_is_alive_but_unhealthy(tmp_path: Path):
    marker = tmp_path / "backend-unhealthy.marker"
    supervisor = _supervisor(
        tmp_path,
        [_proxy_manifest_payload("proxy", restart_health_marker=marker)],
    )

    async def exercise():
        await supervisor.activate("proxy")
        first = await supervisor.status()
        first_backend = first["backends"][0]
        first_pid = first_backend["pid"]
        first_endpoint = first_backend["endpoint"]
        marker.write_text("force unhealthy", encoding="utf-8")

        await supervisor.ensure_active("proxy")
        second = await supervisor.status()
        second_backend = second["backends"][0]
        assert second_backend["running"] is True
        assert second_backend["pid"] != first_pid
        assert second_backend["endpoint"] != first_endpoint
        assert not marker.exists()
        assert second["active_model_id"] == "proxy"
        await supervisor.shutdown()

    asyncio.run(exercise())


def test_unmanaged_loopback_backend_runtime_override_is_rejected(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(TEST_REMOTE_URL_ENV, "http://127.0.0.1:65530")
    supervisor = _supervisor(tmp_path, [_proxy_manifest_payload("proxy")])

    async def exercise():
        with pytest.raises(RuntimeError, match="unmanaged local"):
            await supervisor.activate("proxy")
        state = await supervisor.status()
        assert state["active_model_id"] is None
        assert state["backends"] == []
        assert all(not profile["running"] for profile in state["profiles"])
        await supervisor.shutdown()

    asyncio.run(exercise())


def test_unknown_backend_runtime_fails_catalog_validation(tmp_path: Path):
    backend_catalog = _write_backend_runtimes(tmp_path)
    payload = _proxy_manifest_payload("proxy")
    payload["backend_runtime"] = "does-not-exist"
    with pytest.raises(Exception, match="unknown backend_runtime"):
        _write_manifests(tmp_path, [payload], backend_catalog)


def test_missing_required_backend_arg_fails_catalog_validation(tmp_path: Path):
    backend_catalog = _write_backend_runtimes(tmp_path)
    payload = _proxy_manifest_payload("proxy")
    payload["backend_args"] = {}
    with pytest.raises(Exception, match="requires backend_args.checkpoint"):
        _write_manifests(tmp_path, [payload], backend_catalog)
