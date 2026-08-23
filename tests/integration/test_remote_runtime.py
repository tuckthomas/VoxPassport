from pathlib import Path

import pytest

from runtime.inference.remote_runtime import RemoteEndpointStore, remote_model_id


def test_remote_endpoint_store_persists_capabilities_without_token(tmp_path: Path):
    path = tmp_path / "remote_endpoints.json"
    endpoint = RemoteEndpointStore(path).upsert(
        name="Private GPU", base_url="https://gpu.example.test/",
        capabilities=["ASR", "TRANSLATION"], auth_token_env="VOXPASSPORT_GPU_TOKEN",
    )

    raw = path.read_text(encoding="utf-8")
    reloaded = RemoteEndpointStore(path).get(endpoint.endpoint_id)

    assert remote_model_id(endpoint.endpoint_id, "ASR") == f"remote::{endpoint.endpoint_id}::ASR"
    assert reloaded is not None
    assert reloaded.base_url == "https://gpu.example.test"
    assert reloaded.capabilities == ["ASR", "TRANSLATION"]
    assert "VOXPASSPORT_GPU_TOKEN" in raw
    assert "Bearer " not in raw


def test_remote_endpoint_store_rejects_plaintext_nonlocal_url(tmp_path: Path):
    with pytest.raises(ValueError, match="HTTPS"):
        RemoteEndpointStore(tmp_path / "endpoints.json").upsert(
            name="Unsafe", base_url="http://gpu.example.test", capabilities=["TTS"],
        )
