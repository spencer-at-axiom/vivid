from __future__ import annotations

from pathlib import Path

import pytest

from vivid_inference.model_manager import ModelInstallError, ModelManager


class _StubSibling:
    def __init__(self, rfilename: str) -> None:
        self.rfilename = rfilename


class _StubModelInfo:
    def __init__(self, sha: str, tags: list[str], files: list[str]) -> None:
        self.sha = sha
        self.tags = tags
        self.siblings = [_StubSibling(path) for path in files]


class _StubDryRunFile:
    def __init__(self, size_on_disk: int) -> None:
        self.size_on_disk = size_on_disk


class _StubApi:
    def __init__(self, info: _StubModelInfo) -> None:
        self._info = info

    def model_info(self, model_id: str, *, revision: str | None = None, files_metadata: bool = False):  # type: ignore[override]
        assert model_id
        assert files_metadata is True
        return self._info


@pytest.mark.asyncio
async def test_preflight_uses_pinned_revision_and_explicit_patterns(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    info = _StubModelInfo(
        sha="abc123revision",
        tags=["diffusers", "sd15", "fp16"],
        files=[
            "model_index.json",
            "scheduler/scheduler_config.json",
            "tokenizer/tokenizer_config.json",
            "text_encoder/config.json",
            "text_encoder/pytorch_model.bin",
            "unet/config.json",
            "unet/diffusion_pytorch_model.safetensors",
            "vae/config.json",
            "vae/diffusion_pytorch_model.bin",
        ],
    )
    captured: dict[str, object] = {}

    def fake_snapshot_download(*args, **kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return [_StubDryRunFile(1024), _StubDryRunFile(2048)]

    monkeypatch.setattr("vivid_inference.model_manager.snapshot_download", fake_snapshot_download)

    manager = ModelManager(tmp_path / "models")
    manager.api = _StubApi(info)

    preflight = await manager.preflight_install("tests/sd15-model", allow_network=True)
    assert preflight["revision"] == "abc123revision"
    assert preflight["family"] == "sd15"
    assert preflight["estimated_bytes"] == 3072
    assert captured["revision"] == "abc123revision"
    assert captured["dry_run"] is True
    assert isinstance(captured["allow_patterns"], list)
    assert isinstance(captured["ignore_patterns"], list)
    assert "unet/*" in captured["allow_patterns"]
    assert "onnx/*" in captured["ignore_patterns"]


@pytest.mark.asyncio
async def test_download_model_removes_partial_install_on_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    info = _StubModelInfo(
        sha="deadbeef",
        tags=["diffusers", "sd15", "fp16"],
        files=[
            "model_index.json",
            "scheduler/scheduler_config.json",
            "tokenizer/tokenizer_config.json",
            "text_encoder/config.json",
            "text_encoder/pytorch_model.bin",
            "unet/config.json",
            "unet/diffusion_pytorch_model.safetensors",
            "vae/config.json",
            "vae/diffusion_pytorch_model.bin",
        ],
    )

    def fake_snapshot_download(*args, **kwargs):  # type: ignore[no-untyped-def]
        if kwargs.get("dry_run"):
            return [_StubDryRunFile(1024)]
        local_dir = Path(str(kwargs["local_dir"]))
        local_dir.mkdir(parents=True, exist_ok=True)
        (local_dir / "partial.bin").write_text("broken", encoding="utf-8")
        raise RuntimeError("network failure")

    monkeypatch.setattr("vivid_inference.model_manager.snapshot_download", fake_snapshot_download)

    manager = ModelManager(tmp_path / "models")
    manager.api = _StubApi(info)

    with pytest.raises(ModelInstallError, match="Download failed"):
        await manager.download_model("tests/sd15-model", allow_network=True)

    assert not manager.get_local_path("tests/sd15-model").exists()


def test_inspect_local_model_reports_manifest_gaps(tmp_path: Path) -> None:
    manager = ModelManager(tmp_path / "models")
    local_path = manager.get_local_path("tests/sd15-model")
    local_path.mkdir(parents=True, exist_ok=True)
    (local_path / "model_index.json").write_text("{}", encoding="utf-8")

    inspection = manager.inspect_local_model(local_path, "sd15")
    assert inspection["is_valid"] is False
    assert inspection["missing_files"]
    assert inspection["missing_groups"]
    assert "missing files" in str(inspection["reason"]).lower()


@pytest.mark.asyncio
async def test_preflight_requires_explicit_network_opt_in(tmp_path: Path) -> None:
    manager = ModelManager(tmp_path / "models")

    with pytest.raises(ModelInstallError, match="explicit model browsing/install action"):
        await manager.preflight_install("tests/sd15-model")


@pytest.mark.asyncio
async def test_search_without_network_opt_in_returns_local_mock_catalog(tmp_path: Path) -> None:
    manager = ModelManager(tmp_path / "models")

    class _FailingApi:
        def list_models(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("list_models should not be called without allow_network=True")

    manager.api = _FailingApi()  # type: ignore[assignment]
    results = await manager.search_models(query="sd", allow_network=False)
    assert results
