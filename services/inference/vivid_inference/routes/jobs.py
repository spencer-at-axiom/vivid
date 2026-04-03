from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends

from ..deps import get_app_state
from ..errors import ApiError
from ..schemas import (
    JobCancelRequest,
    JobRequest,
    JobRetryRequest,
    QueueClearRequest,
    QueueReorderRequest,
)
from ..state import AppState

router = APIRouter(prefix="/jobs", tags=["jobs"])


async def _create_validated_job(mode: str, request: JobRequest, state: AppState) -> dict[str, object]:
    _validate_mode_request(mode, request, state)
    try:
        return {"item": await state.create_job(mode, request.model_dump())}
    except ValueError as error:
        detail = str(error)
        normalized = detail.lower()
        if "does not support" in normalized:
            code = "mode_unsupported"
        elif "active model" in normalized:
            code = "no_active_model"
        else:
            code = "job_create_failed"
        raise ApiError(code=code, message="Job could not be created.", status_code=400, detail=detail)


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _existing_image_path(candidate: Any) -> str | None:
    if not _is_non_empty_string(candidate):
        return None
    normalized = str(candidate).strip()
    path = Path(normalized)
    if path.exists() and path.is_file():
        return str(path)
    return None


def _existing_project_asset_path(state: AppState, asset_id: Any, project_id: Any) -> str | None:
    if not _is_non_empty_string(asset_id) or not _is_non_empty_string(project_id):
        return None
    resolved = state._resolve_asset_path(asset_id, project_id)
    if not resolved:
        return None
    resolved_path = Path(resolved)
    if resolved_path.exists() and resolved_path.is_file():
        return str(resolved_path)
    return None


def _validate_source_input(mode: str, payload: dict[str, Any], params: dict[str, Any], state: AppState) -> None:
    project_id = payload.get("project_id")
    path_candidates = {
        "params.init_image_path": params.get("init_image_path"),
        "payload.init_image_path": payload.get("init_image_path"),
    }
    asset_candidates = {
        "params.init_image_asset_id": params.get("init_image_asset_id"),
        "params.source_asset_id": params.get("source_asset_id"),
        "payload.source_asset_id": payload.get("source_asset_id"),
    }

    provided = [
        key
        for key, value in {**path_candidates, **asset_candidates}.items()
        if _is_non_empty_string(value)
    ]
    if not provided:
        raise ApiError(
            code="missing_source_image",
            message=f"{mode} requires an input image.",
            status_code=400,
            detail={
                "required_any_of": [
                    "params.init_image_asset_id",
                    "params.init_image_path",
                    "params.source_asset_id",
                ]
            },
        )

    for candidate in path_candidates.values():
        if _existing_image_path(candidate):
            return
    for candidate in asset_candidates.values():
        if _existing_project_asset_path(state, candidate, project_id):
            return

    raise ApiError(
        code="invalid_source_image",
        message=f"{mode} source image reference did not resolve to an existing file.",
        status_code=400,
        detail={
            "provided": provided,
            "project_id": project_id,
            "hint": "Provide an existing init image path or a valid project asset id.",
        },
    )


def _validate_mask_input(payload: dict[str, Any], params: dict[str, Any], state: AppState) -> None:
    project_id = payload.get("project_id")
    mask_data_candidates = {
        "params.mask_data": params.get("mask_data"),
        "payload.mask_data": payload.get("mask_data"),
    }
    path_candidates = {
        "params.mask_image_path": params.get("mask_image_path"),
        "payload.mask_image_path": payload.get("mask_image_path"),
    }
    asset_candidates = {
        "params.mask_image_asset_id": params.get("mask_image_asset_id"),
        "payload.mask_asset_id": payload.get("mask_asset_id"),
    }
    provided = [
        key
        for key, value in {**mask_data_candidates, **path_candidates, **asset_candidates}.items()
        if _is_non_empty_string(value)
    ]
    if not provided:
        raise ApiError(
            code="missing_mask",
            message="inpaint requires mask data or a mask image reference.",
            status_code=400,
            detail={
                "required_any_of": [
                    "params.mask_data",
                    "params.mask_image_asset_id",
                    "params.mask_image_path",
                ]
            },
        )

    for candidate in mask_data_candidates.values():
        if _is_non_empty_string(candidate) and state._decode_data_url(str(candidate)) is not None:
            return
    for candidate in path_candidates.values():
        if _existing_image_path(candidate):
            return
    for candidate in asset_candidates.values():
        if _existing_project_asset_path(state, candidate, project_id):
            return

    raise ApiError(
        code="invalid_mask",
        message="inpaint mask input did not resolve to valid image data.",
        status_code=400,
        detail={
            "provided": provided,
            "project_id": project_id,
            "hint": "Provide a valid data URL mask, existing mask image path, or valid project mask asset id.",
        },
    )


def _validate_numeric(params: dict[str, Any], key: str, *, minimum: float | None = None) -> None:
    if key not in params:
        return
    raw = params.get(key)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ApiError(
            code="invalid_parameter",
            message=f"Invalid '{key}' value.",
            status_code=400,
            detail={"parameter": key, "value": raw},
        ) from None
    if minimum is not None and value < minimum:
        raise ApiError(
            code="invalid_parameter",
            message=f"'{key}' must be >= {minimum}.",
            status_code=400,
            detail={"parameter": key, "value": raw, "minimum": minimum},
        )


def _validate_seed(params: dict[str, Any]) -> None:
    if "seed" not in params:
        return
    raw = params.get("seed")
    if raw is None:
        return
    if isinstance(raw, int):
        return
    if isinstance(raw, str) and raw.strip().lstrip("-").isdigit():
        return
    raise ApiError(
        code="invalid_parameter",
        message="Invalid 'seed' value.",
        status_code=400,
        detail={"parameter": "seed", "value": raw, "hint": "Use an integer seed or omit it for randomized generation."},
    )


def _validate_mode_request(mode: str, request: JobRequest, state: AppState) -> None:
    payload = request.model_dump()
    params = payload.get("params", {})
    if not isinstance(params, dict):
        raise ApiError(
            code="validation_error",
            message="'params' must be an object.",
            status_code=422,
            detail={"parameter": "params"},
        )

    _validate_numeric(params, "width", minimum=64)
    _validate_numeric(params, "height", minimum=64)
    _validate_numeric(params, "steps", minimum=1)
    _validate_numeric(params, "guidance_scale", minimum=0)
    _validate_numeric(params, "denoise_strength", minimum=0)
    _validate_seed(params)

    if mode in {"img2img", "inpaint", "outpaint", "upscale"}:
        _validate_source_input(mode, payload, params, state)

    if mode == "inpaint":
        _validate_mask_input(payload, params, state)

    if mode == "outpaint":
        _validate_numeric(params, "outpaint_padding", minimum=1)

    if mode == "upscale":
        _validate_numeric(params, "upscale_factor", minimum=1.01)


@router.post("/generate")
async def generate_job(
    request: JobRequest,
    state: AppState = Depends(get_app_state),
) -> dict[str, object]:
    return await _create_validated_job("generate", request, state)


@router.post("/img2img")
async def img2img_job(
    request: JobRequest,
    state: AppState = Depends(get_app_state),
) -> dict[str, object]:
    return await _create_validated_job("img2img", request, state)


@router.post("/inpaint")
async def inpaint_job(
    request: JobRequest,
    state: AppState = Depends(get_app_state),
) -> dict[str, object]:
    return await _create_validated_job("inpaint", request, state)


@router.post("/outpaint")
async def outpaint_job(
    request: JobRequest,
    state: AppState = Depends(get_app_state),
) -> dict[str, object]:
    return await _create_validated_job("outpaint", request, state)


@router.post("/upscale")
async def upscale_job(
    request: JobRequest,
    state: AppState = Depends(get_app_state),
) -> dict[str, object]:
    return await _create_validated_job("upscale", request, state)


@router.post("/cancel")
async def cancel_job(
    request: JobCancelRequest,
    state: AppState = Depends(get_app_state),
) -> dict[str, object]:
    job = state.cancel_job(request.job_id)
    if not job:
        raise ApiError(code="job_not_found", message="Job not found.", status_code=404, detail={"job_id": request.job_id})
    return {"item": job}


@router.get("/{job_id}")
async def get_job(
    job_id: str,
    state: AppState = Depends(get_app_state),
) -> dict[str, object]:
    job = state.get_job(job_id)
    if not job:
        raise ApiError(code="job_not_found", message="Job not found.", status_code=404, detail={"job_id": job_id})
    return {"item": job}


@router.get("")
async def list_jobs(
    status: str | None = None,
    limit: int = 50,
    state: AppState = Depends(get_app_state),
) -> dict[str, object]:
    """List jobs with optional status filter."""
    jobs = list(state.jobs.values())
    
    if status:
        jobs = [j for j in jobs if j["status"] == status]
    
    # Sort by created_at descending
    jobs.sort(key=lambda j: j["created_at"], reverse=True)
    
    return {"items": jobs[:limit], "total": len(jobs)}


@router.post("/queue/pause")
async def pause_queue(state: AppState = Depends(get_app_state)) -> dict[str, object]:
    return {"item": state.pause_queue()}


@router.post("/queue/resume")
async def resume_queue(state: AppState = Depends(get_app_state)) -> dict[str, object]:
    return {"item": state.resume_queue()}


@router.post("/queue/clear")
async def clear_queue(
    request: QueueClearRequest,
    state: AppState = Depends(get_app_state),
) -> dict[str, object]:
    return {"item": state.clear_queue(include_terminal=request.include_terminal)}


@router.post("/queue/retry")
async def retry_job(
    request: JobRetryRequest,
    state: AppState = Depends(get_app_state),
) -> dict[str, object]:
    try:
        return {"item": await state.retry_job(request.job_id)}
    except KeyError:
        raise ApiError(code="job_not_found", message="Job not found.", status_code=404, detail={"job_id": request.job_id})


@router.post("/queue/reorder")
async def reorder_queue(
    request: QueueReorderRequest,
    state: AppState = Depends(get_app_state),
) -> dict[str, object]:
    return {"item": state.reorder_queue(request.job_ids)}


@router.get("/queue/state")
async def queue_state(state: AppState = Depends(get_app_state)) -> dict[str, object]:
    return {"item": state.get_queue_state()}
