from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import get_app_state
from ..errors import ApiError
from ..schemas import ModelActivateRequest, ModelFavoriteRequest, ModelInstallRequest
from ..state import AppState

router = APIRouter(prefix="/models", tags=["models"])


@router.get("/search")
async def search_models(
    q: str = "",
    type: str | None = None,
    sort: str = "relevance",
    state: AppState = Depends(get_app_state),
) -> dict[str, object]:
    items = await state.search_models_async(query=q, model_type=type, sort=sort)
    return {"items": items}


@router.post("/install/preflight")
async def preflight_install_model(
    request: ModelInstallRequest,
    state: AppState = Depends(get_app_state),
) -> dict[str, object]:
    try:
        item = await state.preflight_model_install(request.model_dump())
        return {"item": item}
    except ValueError as error:
        raise ApiError(code="model_preflight_failed", message="Model preflight failed.", status_code=400, detail=str(error))


@router.post("/install")
async def install_model(
    request: ModelInstallRequest,
    state: AppState = Depends(get_app_state),
) -> dict[str, object]:
    try:
        model = await state.install_model(request.model_dump())
    except ValueError as error:
        raise ApiError(code="model_install_failed", message="Model install failed.", status_code=400, detail=str(error))
    return {"item": model}


@router.post("/activate")
async def activate_model(
    request: ModelActivateRequest,
    state: AppState = Depends(get_app_state),
) -> dict[str, object]:
    try:
        item = state.activate_model(request.model_id)
        return {"item": item, "active_model_id": state.active_model_id}
    except KeyError:
        raise ApiError(
            code="model_not_found",
            message="Model not found or not installed.",
            status_code=404,
            detail={"model_id": request.model_id},
        )
    except ValueError as error:
        detail = str(error)
        normalized = detail.lower()
        code = (
            "generation_in_progress"
            if "generation is running" in normalized
            else "model_invalid"
            if "invalid" in normalized
            or "incomplete" in normalized
            or "missing files" in normalized
            or "missing component weights" in normalized
            else "model_incompatible"
        )
        raise ApiError(code=code, message="Model cannot be activated.", status_code=400, detail=detail)


@router.get("/local")
async def local_models(
    favorites_only: bool = False,
    state: AppState = Depends(get_app_state),
) -> dict[str, object]:
    return {
        "items": state.list_models(favorites_only=favorites_only),
        "active_model_id": state.active_model_id,
    }


@router.post("/favorite")
async def favorite_model(
    request: ModelFavoriteRequest,
    state: AppState = Depends(get_app_state),
) -> dict[str, object]:
    try:
        item = state.set_model_favorite(request.model_id, request.favorite)
        return {"item": item}
    except KeyError:
        raise ApiError(code="model_not_found", message="Model not found.", status_code=404, detail={"model_id": request.model_id})


@router.delete("/{model_id:path}")
async def remove_model(
    model_id: str,
    state: AppState = Depends(get_app_state),
) -> dict[str, object]:
    try:
        item = state.remove_model(model_id)
        return {"item": item}
    except KeyError:
        raise ApiError(code="model_not_found", message="Model not found.", status_code=404, detail={"model_id": model_id})
    except ValueError as error:
        raise ApiError(code="model_remove_failed", message="Model could not be removed.", status_code=400, detail=str(error))


@router.get("/{model_id:path}/remove-preview")
async def remove_model_preview(
    model_id: str,
    state: AppState = Depends(get_app_state),
) -> dict[str, object]:
    try:
        return {"item": state.get_model_remove_preview(model_id)}
    except KeyError:
        raise ApiError(code="model_not_found", message="Model not found.", status_code=404, detail={"model_id": model_id})
