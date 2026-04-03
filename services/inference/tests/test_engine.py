from __future__ import annotations

from types import SimpleNamespace

import pytest
from PIL import Image

from vivid_inference.engine import (
    GenerationEngine,
    GenerationResult,
    describe_runtime_policy,
    get_supported_modes,
    model_supports_mode,
)


def test_supported_modes_matrix_is_explicit() -> None:
    assert get_supported_modes("sd15") == ("generate", "img2img", "inpaint", "outpaint", "upscale")
    assert get_supported_modes("sdxl") == ("generate", "img2img", "inpaint", "outpaint")
    assert get_supported_modes("flux") == ("generate",)
    assert model_supports_mode("sd15", "upscale") is True
    assert model_supports_mode("sdxl", "upscale") is False
    assert model_supports_mode("flux", "inpaint") is False


def test_runtime_policy_descriptions_include_offload_memory_and_cache_contract() -> None:
    low_vram = describe_runtime_policy("low_vram", device="cuda")
    balanced = describe_runtime_policy("balanced", device="cuda")
    quality = describe_runtime_policy("quality", device="cuda")

    assert low_vram["offload"] == "sequential_cpu_offload"
    assert low_vram["attention_slicing"] is True
    assert low_vram["vae_tiling"] is True
    assert low_vram["cache_limit"] == 1

    assert balanced["offload"] == "model_cpu_offload"
    assert balanced["attention_slicing"] is True
    assert balanced["cache_limit"] == 2

    assert quality["offload"] == "none"
    assert quality["attention_slicing"] is False
    assert quality["cache_limit"] == 3


@pytest.mark.asyncio
async def test_engine_downgrades_runtime_profile_after_oom(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    engine = GenerationEngine(models_dir=tmp_path, hardware_profile="quality")
    engine.device = "cpu"

    class FailingPipeline:
        def __call__(self, **_: object) -> SimpleNamespace:
            raise RuntimeError("CUDA out of memory while allocating tensor")

    class SuccessPipeline:
        def __call__(self, **_: object) -> SimpleNamespace:
            return SimpleNamespace(images=[Image.new("RGB", (32, 32), color=(32, 64, 96))])

    async def fake_load_pipeline(
        self: GenerationEngine,
        model_id: str,
        model_type: str,
        mode: str,
        profile: str,
    ) -> object:
        assert model_id == "tests/sd15"
        assert model_type == "sd15"
        assert mode == "generate"
        return FailingPipeline() if profile == "quality" else SuccessPipeline()

    monkeypatch.setattr(GenerationEngine, "_load_pipeline", fake_load_pipeline)
    monkeypatch.setattr(GenerationEngine, "_build_generator", lambda self, seed: None)

    result = await engine.generate(
        model_id="tests/sd15",
        model_type="sd15",
        prompt="downgrade test",
        width=32,
        height=32,
        seed=123,
    )

    assert result.requested_profile == "quality"
    assert result.effective_profile == "balanced"
    assert result.runtime_policy["name"] == "balanced"
    assert result.images[0].size == (32, 32)
    assert "downgraded" in result.warnings[0].lower()


def test_switching_active_model_invalidates_other_cached_pipelines(tmp_path) -> None:
    engine = GenerationEngine(models_dir=tmp_path, hardware_profile="balanced")
    engine._pipeline_cache["model-a:generate:balanced"] = object()
    engine._pipeline_cache["model-b:generate:balanced"] = object()

    engine.set_active_model("model-a")
    assert list(engine._pipeline_cache.keys()) == ["model-a:generate:balanced"]

    engine._pipeline_cache["model-a:img2img:balanced"] = object()
    engine._pipeline_cache["model-b:generate:balanced"] = object()
    engine.set_active_model("model-b")
    assert list(engine._pipeline_cache.keys()) == ["model-b:generate:balanced"]


def test_profile_switch_unloads_pipeline_cache(tmp_path) -> None:
    engine = GenerationEngine(models_dir=tmp_path, hardware_profile="balanced")
    engine._pipeline_cache["model-a:generate:balanced"] = object()

    engine.set_hardware_profile("low_vram")

    assert engine.hardware_profile == "low_vram"
    assert engine._pipeline_cache == {}


@pytest.mark.asyncio
async def test_upscale_honors_requested_factor_for_final_dimensions(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    engine = GenerationEngine(models_dir=tmp_path, hardware_profile="balanced")
    engine.device = "cpu"

    async def fake_run_with_runtime_policy(self: GenerationEngine, **_: object) -> GenerationResult:
        return GenerationResult(
            images=[Image.new("RGB", (512, 512), color=(10, 20, 30))],
            requested_profile="balanced",
            effective_profile="balanced",
            runtime_policy={"name": "balanced"},
            warnings=tuple(),
            pipeline_mode="upscale",
        )

    monkeypatch.setattr(GenerationEngine, "_run_with_runtime_policy", fake_run_with_runtime_policy)
    monkeypatch.setattr(GenerationEngine, "_build_generator", lambda self, seed: None)

    source = Image.new("RGB", (200, 120), color=(40, 60, 80))
    result = await engine.upscale(
        model_id="tests/sd15",
        model_type="sd15",
        image=source,
        factor=1.5,
        steps=8,
    )

    assert result.images[0].size == (300, 180)
