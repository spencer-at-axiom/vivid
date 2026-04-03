"""Generation engine with explicit mode support, runtime policy, and cache rules."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import torch
from PIL import Image

try:
    from diffusers import (
        AutoPipelineForImage2Image,
        AutoPipelineForInpainting,
        AutoPipelineForText2Image,
        DiffusionPipeline,
        StableDiffusionImg2ImgPipeline,
        StableDiffusionInpaintPipeline,
        StableDiffusionPipeline,
        StableDiffusionUpscalePipeline,
        StableDiffusionXLImg2ImgPipeline,
        StableDiffusionXLInpaintPipeline,
        StableDiffusionXLPipeline,
    )

    DIFFUSERS_AVAILABLE = True
except ImportError:
    DIFFUSERS_AVAILABLE = False
    AutoPipelineForImage2Image = None
    AutoPipelineForInpainting = None
    AutoPipelineForText2Image = None
    DiffusionPipeline = None
    StableDiffusionImg2ImgPipeline = None
    StableDiffusionInpaintPipeline = None
    StableDiffusionPipeline = None
    StableDiffusionUpscalePipeline = None
    StableDiffusionXLImg2ImgPipeline = None
    StableDiffusionXLInpaintPipeline = None
    StableDiffusionXLPipeline = None

ProgressCallback = Callable[[float], None]

_PROFILE_ORDER = ("low_vram", "balanced", "quality")
_SUPPORTED_MODEL_FAMILY_MODES: dict[str, tuple[str, ...]] = {
    "sd14": ("generate", "img2img", "inpaint", "outpaint", "upscale"),
    "sd15": ("generate", "img2img", "inpaint", "outpaint", "upscale"),
    "sdxl": ("generate", "img2img", "inpaint", "outpaint"),
    "flux": ("generate",),
}
_PROFILE_POLICIES: dict[str, dict[str, Any]] = {
    "low_vram": {
        "label": "Low VRAM",
        "gpu_dtype": "float16",
        "cpu_dtype": "float32",
        "offload": "sequential_cpu_offload",
        "attention_slicing": True,
        "vae_slicing": True,
        "vae_tiling": True,
        "attention_backend": "sdpa",
        "cache_limit": 1,
        "retain_warm_model": True,
    },
    "balanced": {
        "label": "Balanced",
        "gpu_dtype": "float16",
        "cpu_dtype": "float32",
        "offload": "model_cpu_offload",
        "attention_slicing": True,
        "vae_slicing": False,
        "vae_tiling": True,
        "attention_backend": "sdpa",
        "cache_limit": 2,
        "retain_warm_model": True,
    },
    "quality": {
        "label": "Quality",
        "gpu_dtype": "float16",
        "cpu_dtype": "float32",
        "offload": "none",
        "attention_slicing": False,
        "vae_slicing": False,
        "vae_tiling": False,
        "attention_backend": "sdpa",
        "cache_limit": 3,
        "retain_warm_model": True,
    },
}


@dataclass(frozen=True)
class GenerationResult:
    images: list[Image.Image]
    requested_profile: str
    effective_profile: str
    runtime_policy: dict[str, Any]
    warnings: tuple[str, ...]
    pipeline_mode: str


class UnsupportedGenerationMode(RuntimeError):
    """Raised when a model family does not support the requested generation mode."""


def normalize_hardware_profile(profile: str | None) -> str:
    normalized = str(profile or "balanced").strip().lower()
    if normalized not in _PROFILE_POLICIES:
        return "balanced"
    return normalized


def get_supported_modes(model_type: str | None) -> tuple[str, ...]:
    normalized = str(model_type or "sdxl").strip().lower()
    return _SUPPORTED_MODEL_FAMILY_MODES.get(normalized, _SUPPORTED_MODEL_FAMILY_MODES["sdxl"])


def model_supports_mode(model_type: str | None, mode: str) -> bool:
    return str(mode).strip().lower() in get_supported_modes(model_type)


def describe_runtime_policy(profile: str | None, *, device: str | None = None) -> dict[str, Any]:
    normalized = normalize_hardware_profile(profile)
    policy = dict(_PROFILE_POLICIES[normalized])
    resolved_device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    dtype_label = policy["gpu_dtype"] if resolved_device == "cuda" else policy["cpu_dtype"]
    return {
        "name": normalized,
        "label": policy["label"],
        "device": resolved_device,
        "dtype": dtype_label,
        "offload": policy["offload"] if resolved_device == "cuda" else "none",
        "attention_slicing": bool(policy["attention_slicing"]),
        "vae_slicing": bool(policy["vae_slicing"]),
        "vae_tiling": bool(policy["vae_tiling"]),
        "attention_backend": str(policy["attention_backend"]),
        "cache_limit": int(policy["cache_limit"]),
        "retain_warm_model": bool(policy["retain_warm_model"]),
    }


class GenerationEngine:
    """Loads and executes generation pipelines with explicit runtime policy and warm-cache rules."""

    def __init__(self, models_dir: Path, hardware_profile: str = "balanced"):
        self.models_dir = models_dir
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.hardware_profile = normalize_hardware_profile(hardware_profile)
        self._pipeline_cache: OrderedDict[str, Any] = OrderedDict()
        self._warm_model_id: str | None = None
        self._sync_cache_limit()

    def set_hardware_profile(self, hardware_profile: str) -> None:
        normalized = normalize_hardware_profile(hardware_profile)
        if normalized == self.hardware_profile:
            self._sync_cache_limit()
            return
        self.hardware_profile = normalized
        self.unload()
        self._sync_cache_limit()

    def set_active_model(self, model_id: str | None) -> None:
        normalized = str(model_id or "").strip() or None
        if normalized == self._warm_model_id:
            return
        self._warm_model_id = normalized
        if normalized is None:
            self.unload()
            return

        for cache_key in list(self._pipeline_cache.keys()):
            cached_model_id, _, _ = cache_key.partition(":")
            if cached_model_id != normalized:
                self._discard_pipeline(cache_key)
        self._sync_cache_limit()

    def get_runtime_policy(self, profile: str | None = None) -> dict[str, Any]:
        return describe_runtime_policy(profile or self.hardware_profile, device=self.device)

    def _sync_cache_limit(self) -> None:
        self._max_cached_pipelines = int(self.get_runtime_policy()["cache_limit"])
        self._trim_pipeline_cache()

    def get_torch_dtype(self, profile: str | None = None) -> torch.dtype:
        policy = self.get_runtime_policy(profile)
        dtype_label = str(policy["dtype"]).lower()
        if dtype_label == "bfloat16":
            return torch.bfloat16
        if dtype_label == "float16":
            return torch.float16
        return torch.float32

    def get_pipeline_kwargs(self, profile: str | None = None) -> dict[str, Any]:
        normalized = normalize_hardware_profile(profile or self.hardware_profile)
        kwargs: dict[str, Any] = {"torch_dtype": self.get_torch_dtype(normalized)}
        if normalized == "low_vram":
            kwargs["low_cpu_mem_usage"] = True
            kwargs["use_safetensors"] = True
        return kwargs

    def _resolve_pipeline_class(self, mode: str, model_type: str) -> Any:
        normalized_mode = str(mode).strip().lower()
        normalized_type = str(model_type or "sdxl").strip().lower()
        if not model_supports_mode(normalized_type, normalized_mode):
            supported = ", ".join(get_supported_modes(normalized_type))
            raise UnsupportedGenerationMode(
                f"Model family '{normalized_type}' does not support '{normalized_mode}'. Supported modes: {supported}."
            )

        if normalized_mode == "generate":
            if normalized_type == "sdxl" and StableDiffusionXLPipeline is not None:
                return StableDiffusionXLPipeline
            if normalized_type in {"sd15", "sd14"} and StableDiffusionPipeline is not None:
                return StableDiffusionPipeline
            return AutoPipelineForText2Image or DiffusionPipeline

        if normalized_mode == "img2img":
            if normalized_type == "sdxl" and StableDiffusionXLImg2ImgPipeline is not None:
                return StableDiffusionXLImg2ImgPipeline
            if normalized_type in {"sd15", "sd14"} and StableDiffusionImg2ImgPipeline is not None:
                return StableDiffusionImg2ImgPipeline
            return AutoPipelineForImage2Image

        if normalized_mode in {"inpaint", "outpaint"}:
            if normalized_type == "sdxl" and StableDiffusionXLInpaintPipeline is not None:
                return StableDiffusionXLInpaintPipeline
            if normalized_type in {"sd15", "sd14"} and StableDiffusionInpaintPipeline is not None:
                return StableDiffusionInpaintPipeline
            return AutoPipelineForInpainting

        if normalized_mode == "upscale":
            if normalized_type in {"sd15", "sd14"} and StableDiffusionUpscalePipeline is not None:
                return StableDiffusionUpscalePipeline
            raise UnsupportedGenerationMode(
                f"Model family '{normalized_type}' does not support a dedicated '{normalized_mode}' pipeline."
            )

        raise UnsupportedGenerationMode(f"Unsupported generation mode '{normalized_mode}'.")

    def _pipeline_cache_key(self, model_id: str, mode: str, profile: str) -> str:
        return f"{model_id}:{mode}:{normalize_hardware_profile(profile)}"

    def _apply_runtime_policy(self, pipeline: Any, profile: str) -> Any:
        policy = self.get_runtime_policy(profile)
        if hasattr(pipeline, "set_progress_bar_config"):
            pipeline.set_progress_bar_config(disable=True)

        if self.device == "cuda":
            offload = str(policy["offload"])
            if offload == "sequential_cpu_offload" and hasattr(pipeline, "enable_sequential_cpu_offload"):
                pipeline.enable_sequential_cpu_offload()
            elif offload == "model_cpu_offload" and hasattr(pipeline, "enable_model_cpu_offload"):
                pipeline.enable_model_cpu_offload()
            elif hasattr(pipeline, "to"):
                pipeline = pipeline.to(self.device)
        elif hasattr(pipeline, "to"):
            pipeline = pipeline.to(self.device)

        if bool(policy["attention_slicing"]) and hasattr(pipeline, "enable_attention_slicing"):
            pipeline.enable_attention_slicing()
        if bool(policy["vae_slicing"]) and hasattr(pipeline, "enable_vae_slicing"):
            pipeline.enable_vae_slicing()
        if bool(policy["vae_tiling"]) and hasattr(pipeline, "enable_vae_tiling"):
            pipeline.enable_vae_tiling()
        return pipeline

    async def _load_pipeline(self, model_id: str, model_type: str, mode: str, profile: str) -> Any:
        if not DIFFUSERS_AVAILABLE:
            raise RuntimeError("Diffusers not installed. Install `diffusers`, `torch`, and `transformers`.")

        normalized_profile = normalize_hardware_profile(profile)
        cache_key = self._pipeline_cache_key(model_id, mode, normalized_profile)
        cached = self._pipeline_cache.get(cache_key)
        if cached is not None:
            self._pipeline_cache.move_to_end(cache_key)
            return cached

        pipeline_class = self._resolve_pipeline_class(mode, model_type)
        if pipeline_class is None:
            raise UnsupportedGenerationMode(
                f"Model family '{model_type}' does not expose a usable '{mode}' pipeline in this runtime."
            )

        source = self.models_dir / model_id.replace("/", "_")
        model_source = str(source) if source.exists() else model_id
        kwargs = self.get_pipeline_kwargs(normalized_profile)

        await asyncio.sleep(0)
        pipeline = await asyncio.to_thread(pipeline_class.from_pretrained, model_source, **kwargs)
        pipeline = self._apply_runtime_policy(pipeline, normalized_profile)

        self._pipeline_cache[cache_key] = pipeline
        self._pipeline_cache.move_to_end(cache_key)
        self._trim_pipeline_cache()
        return pipeline

    def _trim_pipeline_cache(self) -> None:
        warm_prefix = f"{self._warm_model_id}:" if self._warm_model_id else None
        while len(self._pipeline_cache) > self._max_cached_pipelines:
            removable_key = None
            for candidate in self._pipeline_cache.keys():
                if warm_prefix and candidate.startswith(warm_prefix):
                    continue
                removable_key = candidate
                break
            if removable_key is None:
                removable_key = next(iter(self._pipeline_cache))
            self._discard_pipeline(removable_key)

    def _discard_pipeline(self, cache_key: str) -> None:
        pipeline = self._pipeline_cache.pop(cache_key, None)
        if pipeline is not None:
            del pipeline
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def _build_generator(self, seed: int | None) -> torch.Generator | None:
        if seed is None or seed < 0:
            return None
        return torch.Generator(device=self.device).manual_seed(seed)

    @staticmethod
    def _build_progress_callback(steps: int, progress_callback: ProgressCallback | None) -> tuple[Any, int] | None:
        if progress_callback is None:
            return None

        def callback_wrapper(step: int, timestep: int, latents: torch.Tensor) -> None:
            progress_callback(min(1.0, max(0.0, step / max(steps, 1))))

        return callback_wrapper, 1

    @staticmethod
    def _is_oom_error(error: Exception) -> bool:
        if isinstance(error, torch.cuda.OutOfMemoryError):
            return True
        return "out of memory" in str(error).lower()

    @staticmethod
    def _downgrade_profile(profile: str) -> str | None:
        normalized = normalize_hardware_profile(profile)
        try:
            current_index = _PROFILE_ORDER.index(normalized)
        except ValueError:
            return "balanced"
        if current_index == 0:
            return None
        return _PROFILE_ORDER[current_index - 1]

    async def _run_with_runtime_policy(
        self,
        *,
        mode: str,
        model_id: str,
        model_type: str,
        runner: Callable[[Any], Any],
    ) -> GenerationResult:
        requested_profile = normalize_hardware_profile(self.hardware_profile)
        active_profile = requested_profile
        warnings: list[str] = []

        while True:
            self.set_hardware_profile(active_profile)
            pipeline = await self._load_pipeline(model_id, model_type, mode, active_profile)
            try:
                images = await asyncio.to_thread(runner, pipeline)
                return GenerationResult(
                    images=images,
                    requested_profile=requested_profile,
                    effective_profile=active_profile,
                    runtime_policy=self.get_runtime_policy(active_profile),
                    warnings=tuple(warnings),
                    pipeline_mode=mode,
                )
            except Exception as error:
                if not self._is_oom_error(error):
                    raise
                downgraded = self._downgrade_profile(active_profile)
                if downgraded is None:
                    raise RuntimeError(
                        f"Generation exhausted memory under the '{requested_profile}' runtime profile and could not downgrade further."
                    ) from error
                warnings.append(
                    f"Runtime downgraded from '{active_profile}' to '{downgraded}' after an out-of-memory failure."
                )
                self.unload()
                active_profile = downgraded

    async def generate(
        self,
        model_id: str,
        model_type: str,
        prompt: str,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 1024,
        steps: int = 25,
        guidance_scale: float = 7.0,
        seed: int | None = None,
        num_images: int = 1,
        progress_callback: ProgressCallback | None = None,
    ) -> GenerationResult:
        call_kwargs: dict[str, Any] = {
            "prompt": prompt,
            "negative_prompt": negative_prompt or None,
            "width": width,
            "height": height,
            "num_inference_steps": steps,
            "guidance_scale": guidance_scale,
            "num_images_per_prompt": num_images,
            "generator": self._build_generator(seed),
        }
        progress_args = self._build_progress_callback(steps, progress_callback)
        if progress_args:
            callback, callback_steps = progress_args
            call_kwargs["callback"] = callback
            call_kwargs["callback_steps"] = callback_steps

        return await self._run_with_runtime_policy(
            mode="generate",
            model_id=model_id,
            model_type=model_type,
            runner=lambda pipeline: pipeline(**call_kwargs).images,
        )

    async def img2img(
        self,
        model_id: str,
        model_type: str,
        image: Image.Image,
        prompt: str,
        negative_prompt: str = "",
        strength: float = 0.75,
        steps: int = 25,
        guidance_scale: float = 7.0,
        seed: int | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> GenerationResult:
        call_kwargs: dict[str, Any] = {
            "prompt": prompt,
            "negative_prompt": negative_prompt or None,
            "image": image.convert("RGB"),
            "strength": strength,
            "num_inference_steps": steps,
            "guidance_scale": guidance_scale,
            "generator": self._build_generator(seed),
        }
        progress_args = self._build_progress_callback(steps, progress_callback)
        if progress_args:
            callback, callback_steps = progress_args
            call_kwargs["callback"] = callback
            call_kwargs["callback_steps"] = callback_steps

        return await self._run_with_runtime_policy(
            mode="img2img",
            model_id=model_id,
            model_type=model_type,
            runner=lambda pipeline: pipeline(**call_kwargs).images,
        )

    async def inpaint(
        self,
        model_id: str,
        model_type: str,
        image: Image.Image,
        mask_image: Image.Image,
        prompt: str,
        negative_prompt: str = "",
        strength: float = 0.75,
        steps: int = 25,
        guidance_scale: float = 7.0,
        seed: int | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> GenerationResult:
        call_kwargs: dict[str, Any] = {
            "prompt": prompt,
            "negative_prompt": negative_prompt or None,
            "image": image.convert("RGB"),
            "mask_image": mask_image.convert("L"),
            "strength": strength,
            "num_inference_steps": steps,
            "guidance_scale": guidance_scale,
            "generator": self._build_generator(seed),
        }
        progress_args = self._build_progress_callback(steps, progress_callback)
        if progress_args:
            callback, callback_steps = progress_args
            call_kwargs["callback"] = callback
            call_kwargs["callback_steps"] = callback_steps

        return await self._run_with_runtime_policy(
            mode="inpaint",
            model_id=model_id,
            model_type=model_type,
            runner=lambda pipeline: pipeline(**call_kwargs).images,
        )

    async def outpaint(
        self,
        model_id: str,
        model_type: str,
        image: Image.Image,
        prompt: str,
        negative_prompt: str = "",
        padding: int = 128,
        strength: float = 0.85,
        steps: int = 25,
        guidance_scale: float = 7.0,
        seed: int | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> GenerationResult:
        padded_image, mask_image = self._create_outpaint_canvas(image.convert("RGB"), padding)
        result = await self.inpaint(
            model_id=model_id,
            model_type=model_type,
            image=padded_image,
            mask_image=mask_image,
            prompt=prompt,
            negative_prompt=negative_prompt,
            strength=strength,
            steps=steps,
            guidance_scale=guidance_scale,
            seed=seed,
            progress_callback=progress_callback,
        )
        return GenerationResult(
            images=result.images,
            requested_profile=result.requested_profile,
            effective_profile=result.effective_profile,
            runtime_policy=result.runtime_policy,
            warnings=result.warnings,
            pipeline_mode="outpaint",
        )

    @staticmethod
    def _create_outpaint_canvas(image: Image.Image, padding: int) -> tuple[Image.Image, Image.Image]:
        padding = max(32, int(padding))
        width, height = image.size
        out_width = width + (padding * 2)
        out_height = height + (padding * 2)
        canvas = Image.new("RGB", (out_width, out_height), color=(0, 0, 0))
        canvas.paste(image, (padding, padding))

        mask = Image.new("L", (out_width, out_height), color=255)
        keep_region = Image.new("L", (width, height), color=0)
        mask.paste(keep_region, (padding, padding))
        return canvas, mask

    async def upscale(
        self,
        model_id: str,
        model_type: str,
        image: Image.Image,
        prompt: str = "",
        negative_prompt: str = "",
        steps: int = 20,
        guidance_scale: float = 7.0,
        factor: float = 2.0,
        seed: int | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> GenerationResult:
        if not model_supports_mode(model_type, "upscale"):
            supported = ", ".join(get_supported_modes(model_type))
            raise UnsupportedGenerationMode(
                f"Model family '{model_type}' does not support 'upscale'. Supported modes: {supported}."
            )

        call_kwargs: dict[str, Any] = {
            "prompt": prompt or "high quality detailed image",
            "negative_prompt": negative_prompt or None,
            "image": image.convert("RGB"),
            "num_inference_steps": steps,
            "guidance_scale": guidance_scale,
            "generator": self._build_generator(seed),
        }
        progress_args = self._build_progress_callback(steps, progress_callback)
        if progress_args:
            callback, callback_steps = progress_args
            call_kwargs["callback"] = callback
            call_kwargs["callback_steps"] = callback_steps

        result = await self._run_with_runtime_policy(
            mode="upscale",
            model_id=model_id,
            model_type=model_type,
            runner=lambda pipeline: pipeline(**call_kwargs).images,
        )
        target_factor = max(1.01, float(factor))
        target_size = (
            max(64, int(round(image.width * target_factor))),
            max(64, int(round(image.height * target_factor))),
        )
        resized_images = [
            generated.resize(target_size, Image.Resampling.LANCZOS)
            if generated.size != target_size
            else generated
            for generated in result.images
        ]
        return GenerationResult(
            images=resized_images,
            requested_profile=result.requested_profile,
            effective_profile=result.effective_profile,
            runtime_policy=result.runtime_policy,
            warnings=result.warnings,
            pipeline_mode=result.pipeline_mode,
        )

    def save_image(
        self,
        image: Image.Image,
        path: Path,
        format: str = "PNG",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if format.upper() == "PNG" and metadata:
            from PIL import PngImagePlugin

            pnginfo = PngImagePlugin.PngInfo()
            for key, value in metadata.items():
                pnginfo.add_text(key, str(value))
            image.save(path, format="PNG", pnginfo=pnginfo)
            return
        image.save(path, format=format.upper())

    def unload(self) -> None:
        for pipeline in self._pipeline_cache.values():
            del pipeline
        self._pipeline_cache.clear()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


_engine: GenerationEngine | None = None


def detect_hardware_profile() -> str:
    """Infer a default runtime profile from available VRAM."""
    if not torch.cuda.is_available():
        return "low_vram"

    try:
        props = torch.cuda.get_device_properties(0)
        vram_gb = props.total_memory / (1024**3)
    except Exception:
        return "balanced"

    if vram_gb < 6:
        return "low_vram"
    if vram_gb < 12:
        return "balanced"
    return "quality"


def get_engine(models_dir: Path, hardware_profile: str = "balanced") -> GenerationEngine:
    global _engine
    if _engine is None:
        _engine = GenerationEngine(models_dir=models_dir, hardware_profile=hardware_profile)
        return _engine

    _engine.set_hardware_profile(hardware_profile)
    return _engine
