"""Model search, install preflight, and validated local registry helpers."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

try:
    from huggingface_hub import HfApi, snapshot_download

    HF_AVAILABLE = True
except ImportError:
    HF_AVAILABLE = False
    HfApi = None
    snapshot_download = None

ProgressCallback = Callable[[float, str], Any]
_MANIFESTS_PATH = Path(__file__).with_name("data") / "model_manifests.json"


class ModelInstallError(RuntimeError):
    """Raised when a model cannot be preflighted, downloaded, or validated."""


@lru_cache(maxsize=1)
def load_model_manifests() -> dict[str, dict[str, Any]]:
    payload = json.loads(_MANIFESTS_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Model manifest data is invalid.")
    return payload


def get_model_manifest(family: str) -> dict[str, Any]:
    manifests = load_model_manifests()
    normalized = str(family).strip().lower()
    manifest = manifests.get(normalized)
    if manifest is None:
        raise ModelInstallError(f"Unsupported model family '{family}'.")
    return manifest


class ModelManager:
    """Manages Hugging Face discovery, preflight, and validated local installs."""

    def __init__(self, models_dir: Path):
        self.models_dir = models_dir
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.api = HfApi() if HF_AVAILABLE else None

    async def search_models(
        self,
        query: str = "",
        model_type: str | None = None,
        sort: str = "downloads",
        limit: int = 20,
        *,
        allow_network: bool = False,
    ) -> list[dict[str, Any]]:
        if os.environ.get("VIVID_E2E_MODE", "").strip().lower() in {"1", "true", "yes"}:
            return self._get_mock_models(query, model_type)

        if not allow_network:
            # Privacy default: network discovery is opt-in per explicit model browsing flows.
            return self._get_mock_models(query, model_type)

        if not HF_AVAILABLE or self.api is None:
            return self._get_mock_models(query, model_type)

        hf_sort = sort if sort in {"downloads", "likes", "lastModified"} else "downloads"
        try:
            models = await asyncio.to_thread(
                self.api.list_models,
                search=query or None,
                sort=hf_sort,
                limit=limit,
                filter={"library": "diffusers"},
            )
        except Exception:
            models = await asyncio.to_thread(
                self.api.list_models,
                search=query or None,
                sort=hf_sort,
                limit=limit,
            )

        results: list[dict[str, Any]] = []
        for model in models:
            tags = [str(tag).lower() for tag in (getattr(model, "tags", None) or [])]
            family = self._infer_model_family(str(getattr(model, "id", "")), tags, [])
            if model_type and family != model_type:
                continue
            precision = self._infer_precision(str(getattr(model, "id", "")), tags, [])
            safetensors_info = getattr(model, "safetensors", {}) or {}
            size_bytes = safetensors_info.get("total") or 7_000_000_000
            results.append(
                {
                    "id": model.id,
                    "name": model.id.split("/")[-1],
                    "type": family,
                    "family": family,
                    "precision": precision,
                    "revision": getattr(model, "sha", None),
                    "size_bytes": int(size_bytes),
                    "updated_at": model.lastModified.isoformat() if getattr(model, "lastModified", None) else None,
                    "downloads": int(getattr(model, "downloads", 0) or 0),
                    "likes": int(getattr(model, "likes", 0) or 0),
                    "tags": tags,
                }
            )
        return results

    async def preflight_install(
        self,
        model_id: str,
        *,
        requested_type: str | None = None,
        requested_revision: str | None = None,
        allow_network: bool = False,
    ) -> dict[str, Any]:
        if os.environ.get("VIVID_E2E_MODE", "").strip().lower() in {"1", "true", "yes"}:
            family = requested_type or self._infer_model_family(model_id.lower(), [], [])
            manifest = get_model_manifest(family)
            local_path = self.get_local_path(model_id)
            validation = self.inspect_local_model(local_path, family)
            return {
                "model_id": model_id,
                "family": family,
                "precision": manifest.get("default_precision", "fp16"),
                "revision": requested_revision or f"e2e-{family}-revision",
                "required_files": list(manifest.get("required_files", [])),
                "allow_patterns": list(manifest.get("allow_patterns", [])),
                "ignore_patterns": list(manifest.get("ignore_patterns", [])),
                "estimated_bytes": max(1, sum(len(path) for path in manifest.get("required_files", [])) * 1024),
                "local_path": str(local_path),
                "already_installed": validation["is_valid"],
                "validation": validation,
            }

        if not allow_network:
            raise ModelInstallError("Network model preflight requires an explicit model browsing/install action.")

        if not HF_AVAILABLE or self.api is None or snapshot_download is None:
            raise ModelInstallError(
                "Hugging Face dependencies are not installed. Install `huggingface-hub` for model downloads."
            )

        try:
            info = await asyncio.to_thread(
                self.api.model_info,
                model_id,
                revision=requested_revision,
                files_metadata=True,
            )
        except Exception as error:
            raise ModelInstallError(f"Could not fetch model metadata for '{model_id}': {error}") from error

        repo_files = [str(getattr(item, "rfilename", "") or "") for item in (getattr(info, "siblings", None) or [])]
        tags = [str(tag).lower() for tag in (getattr(info, "tags", None) or [])]
        family = requested_type or self._infer_model_family(model_id.lower(), tags, repo_files)
        manifest = get_model_manifest(family)
        revision = requested_revision or getattr(info, "sha", None)
        if not revision:
            raise ModelInstallError(f"Model '{model_id}' did not expose an immutable revision for download pinning.")

        missing_required = [path for path in manifest.get("required_files", []) if path not in repo_files]
        missing_groups = [
            list(group)
            for group in manifest.get("required_any_of", [])
            if not any(candidate in repo_files for candidate in group)
        ]
        if missing_required or missing_groups:
            details: list[str] = []
            if missing_required:
                details.append(f"missing files: {', '.join(missing_required)}")
            if missing_groups:
                rendered = [" | ".join(group) for group in missing_groups]
                details.append(f"missing required component weights: {', '.join(rendered)}")
            raise ModelInstallError(
                f"Model '{model_id}' does not satisfy the '{family}' manifest ({'; '.join(details)})."
            )

        allow_patterns = list(manifest.get("allow_patterns", []))
        ignore_patterns = list(manifest.get("ignore_patterns", []))
        try:
            dry_run = await asyncio.to_thread(
                snapshot_download,
                repo_id=model_id,
                repo_type="model",
                revision=revision,
                allow_patterns=allow_patterns,
                ignore_patterns=ignore_patterns,
                dry_run=True,
            )
        except Exception as error:
            raise ModelInstallError(f"Install preflight failed for '{model_id}': {error}") from error

        local_path = self.get_local_path(model_id)
        validation = self.inspect_local_model(local_path, family)
        return {
            "model_id": model_id,
            "family": family,
            "precision": self._infer_precision(model_id.lower(), tags, repo_files),
            "revision": revision,
            "required_files": list(manifest.get("required_files", [])),
            "allow_patterns": allow_patterns,
            "ignore_patterns": ignore_patterns,
            "estimated_bytes": self._estimate_dry_run_bytes(dry_run),
            "local_path": str(local_path),
            "already_installed": validation["is_valid"],
            "validation": validation,
        }

    async def download_model(
        self,
        model_id: str,
        progress_callback: ProgressCallback | None = None,
        requested_type: str | None = None,
        requested_revision: str | None = None,
        *,
        allow_network: bool = False,
    ) -> dict[str, Any]:
        await self._emit_progress(progress_callback, 0.05, "preflight")
        preflight = await self.preflight_install(
            model_id,
            requested_type=requested_type,
            requested_revision=requested_revision,
            allow_network=allow_network,
        )

        family = str(preflight["family"])
        local_path = Path(str(preflight["local_path"]))
        if preflight["validation"]["is_valid"]:
            await self._emit_progress(progress_callback, 1.0, "ready")
            return {
                "local_path": local_path,
                "family": family,
                "precision": preflight["precision"],
                "revision": preflight["revision"],
                "required_files": tuple(preflight["required_files"]),
                "validation": preflight["validation"],
            }

        if local_path.exists():
            shutil.rmtree(local_path, ignore_errors=True)
        local_path.mkdir(parents=True, exist_ok=True)

        await self._emit_progress(progress_callback, 0.2, "downloading")
        try:
            if os.environ.get("VIVID_E2E_MODE", "").strip().lower() in {"1", "true", "yes"}:
                self._populate_mock_install(local_path, family)
            else:
                await asyncio.to_thread(
                    snapshot_download,
                    repo_id=model_id,
                    repo_type="model",
                    revision=str(preflight["revision"]),
                    local_dir=str(local_path),
                    allow_patterns=list(preflight["allow_patterns"]),
                    ignore_patterns=list(preflight["ignore_patterns"]),
                    local_dir_use_symlinks=False,
                )
        except Exception as error:
            shutil.rmtree(local_path, ignore_errors=True)
            raise ModelInstallError(f"Download failed for '{model_id}': {error}") from error

        await self._emit_progress(progress_callback, 0.9, "validating")
        validation = self.inspect_local_model(local_path, family)
        if not validation["is_valid"]:
            shutil.rmtree(local_path, ignore_errors=True)
            raise ModelInstallError(
                f"Downloaded files for '{model_id}' failed validation: {validation['reason']}"
            )

        await self._emit_progress(progress_callback, 1.0, "ready")
        return {
            "local_path": local_path,
            "family": family,
            "precision": preflight["precision"],
            "revision": preflight["revision"],
            "required_files": tuple(preflight["required_files"]),
            "validation": validation,
        }

    def inspect_local_model(self, local_path: Path, family: str) -> dict[str, Any]:
        manifest = get_model_manifest(family)
        if not local_path.exists():
            return {
                "is_valid": False,
                "family": family,
                "required_files": list(manifest.get("required_files", [])),
                "missing_files": list(manifest.get("required_files", [])),
                "missing_groups": [list(group) for group in manifest.get("required_any_of", [])],
                "reason": "Model files are not installed.",
            }

        missing_files = [path for path in manifest.get("required_files", []) if not (local_path / path).exists()]
        missing_groups = [
            list(group)
            for group in manifest.get("required_any_of", [])
            if not any((local_path / candidate).exists() for candidate in group)
        ]
        is_valid = not missing_files and not missing_groups
        reason = None
        if missing_files or missing_groups:
            details: list[str] = []
            if missing_files:
                details.append(f"missing files: {', '.join(missing_files)}")
            if missing_groups:
                details.append(
                    "missing component weights: "
                    + ", ".join(" | ".join(group) for group in missing_groups)
                )
            reason = "; ".join(details)

        return {
            "is_valid": is_valid,
            "family": family,
            "required_files": list(manifest.get("required_files", [])),
            "missing_files": missing_files,
            "missing_groups": missing_groups,
            "reason": reason,
        }

    def get_local_path(self, model_id: str) -> Path:
        return self.models_dir / model_id.replace("/", "_")

    def is_downloaded(self, model_id: str, model_type: str = "sdxl") -> bool:
        return self.inspect_local_model(self.get_local_path(model_id), model_type)["is_valid"]

    @staticmethod
    async def _emit_progress(
        progress_callback: ProgressCallback | None, progress: float, status: str
    ) -> None:
        if progress_callback is None:
            return
        result = progress_callback(progress, status)
        if asyncio.iscoroutine(result):
            await result

    @staticmethod
    def _infer_model_family(model_id: str, tags: list[str], repo_files: list[str]) -> str:
        lowered_files = [path.lower() for path in repo_files]
        haystack = " ".join([model_id.lower(), *tags, *lowered_files])
        if "flux" in haystack or any("transformer/" in path for path in lowered_files):
            return "flux"
        if "sdxl" in haystack or "stable-diffusion-xl" in haystack or any("text_encoder_2/" in path for path in lowered_files):
            return "sdxl"
        if "sd-1" in haystack or "sd1" in haystack or "v1-5" in haystack or "stable-diffusion-v1" in haystack:
            return "sd15"
        return "sdxl"

    @staticmethod
    def _infer_precision(model_id: str, tags: list[str], repo_files: list[str]) -> str:
        haystack = " ".join([model_id.lower(), *tags, *(path.lower() for path in repo_files)])
        if "bf16" in haystack:
            return "bf16"
        if "fp32" in haystack or "float32" in haystack:
            return "fp32"
        if "int8" in haystack:
            return "int8"
        return "fp16"

    @staticmethod
    def _estimate_dry_run_bytes(dry_run: Any) -> int:
        if isinstance(dry_run, str):
            return 0
        total = 0
        for item in dry_run or []:
            size = getattr(item, "size_on_disk", None)
            if size is None:
                size = getattr(item, "size", 0)
            total += int(size or 0)
        return total

    def _populate_mock_install(self, local_path: Path, family: str) -> None:
        manifest = get_model_manifest(family)
        for file_path in manifest.get("required_files", []):
            target = local_path / file_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{}", encoding="utf-8")
        for group in manifest.get("required_any_of", []):
            if not group:
                continue
            target = local_path / group[0]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{}", encoding="utf-8")

    @staticmethod
    def _get_mock_models(query: str = "", model_type: str | None = None) -> list[dict[str, Any]]:
        models = [
            {
                "id": "black-forest-labs/FLUX.1-dev",
                "name": "FLUX.1 dev",
                "type": "flux",
                "family": "flux",
                "precision": "bf16",
                "revision": "e2e-flux-revision",
                "size_bytes": 12_000_000_000,
                "updated_at": "2026-01-15T00:00:00Z",
                "downloads": 1_500_000,
                "likes": 25_000,
                "tags": ["diffusers", "flux", "bf16"],
            },
            {
                "id": "stabilityai/stable-diffusion-xl-base-1.0",
                "name": "SDXL Base 1.0",
                "type": "sdxl",
                "family": "sdxl",
                "precision": "fp16",
                "revision": "e2e-sdxl-revision",
                "size_bytes": 7_000_000_000,
                "updated_at": "2025-09-01T00:00:00Z",
                "downloads": 5_000_000,
                "likes": 50_000,
                "tags": ["diffusers", "sdxl", "fp16"],
            },
            {
                "id": "runwayml/stable-diffusion-v1-5",
                "name": "Stable Diffusion 1.5",
                "type": "sd15",
                "family": "sd15",
                "precision": "fp16",
                "revision": "e2e-sd15-revision",
                "size_bytes": 4_000_000_000,
                "updated_at": "2025-07-20T00:00:00Z",
                "downloads": 10_000_000,
                "likes": 75_000,
                "tags": ["diffusers", "sd15", "fp16"],
            },
        ]
        if query:
            lowered = query.lower()
            models = [model for model in models if lowered in model["name"].lower() or lowered in model["id"].lower()]
        if model_type:
            models = [model for model in models if model["type"] == model_type]
        return models


_manager: ModelManager | None = None


def get_model_manager(models_dir: Path) -> ModelManager:
    global _manager
    if _manager is None:
        _manager = ModelManager(models_dir)
    return _manager
