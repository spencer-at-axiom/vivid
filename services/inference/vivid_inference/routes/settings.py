from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import get_app_state
from ..errors import ApiError
from ..schemas import SettingsUpdateRequest
from ..state import AppState

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("")
async def get_settings(state: AppState = Depends(get_app_state)) -> dict[str, object]:
    """Get all settings."""
    return {"items": state.list_settings()}


@router.get("/{key}")
async def get_setting(key: str, state: AppState = Depends(get_app_state)) -> dict[str, object]:
    """Get a specific setting."""
    value = state.get_setting(key)
    if value is None:
        raise ApiError(
            code="setting_not_found",
            message=f"Setting '{key}' not found.",
            status_code=404,
            detail={"key": key},
        )
    return {"key": key, "value": value}


@router.post("")
async def update_setting(
    request: SettingsUpdateRequest,
    state: AppState = Depends(get_app_state),
) -> dict[str, object]:
    """Update or create a setting."""
    try:
        return state.update_setting(request.key, request.value)
    except ValueError as error:
        normalized_key = str(request.key or "").strip()
        detail: dict[str, object] = {"key": normalized_key, "value": request.value}
        if normalized_key == "hardware_profile":
            detail["allowed"] = ["low_vram", "balanced", "quality"]
        elif normalized_key == "theme":
            detail["allowed"] = ["dark", "light", "auto"]
        elif normalized_key == "auto_save_interval":
            detail["minimum"] = 1
            detail["maximum"] = 300
        raise ApiError(
            code="invalid_setting",
            message=str(error),
            status_code=400,
            detail=detail,
        )
