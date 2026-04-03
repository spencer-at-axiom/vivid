from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from ..config import Settings
from ..db import open_db
from ..deps import get_app_settings, get_app_state
from ..state import AppState

router = APIRouter(prefix="/e2e", tags=["e2e"])


def _delete_dir_children(path: Path) -> None:
    if not path.exists():
        return
    for child in path.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)


@router.post("/reset")
async def reset_state(
    settings: Settings = Depends(get_app_settings),
    state: AppState = Depends(get_app_state),
) -> dict[str, object]:
    if not settings.e2e_mode:
        raise HTTPException(status_code=404, detail="Not found")

    with open_db() as connection:
        for table in ("jobs", "generations", "assets", "projects", "models"):
            connection.execute(f"DELETE FROM {table}")
        connection.execute("DELETE FROM settings WHERE key = ?", ("active_model_id",))

    _delete_dir_children(settings.projects_dir)
    _delete_dir_children(settings.models_dir)
    _delete_dir_children(settings.thumbs_dir)

    state.jobs.clear()
    state.models.clear()
    state.projects.clear()
    state.active_model_id = None
    state._queue_order.clear()
    state._running_job_id = None
    state._queue_paused = False
    state._interactive_burst_count = 0

    return {"status": "ok"}


@router.post("/drop-websockets")
async def drop_websockets(
    settings: Settings = Depends(get_app_settings),
    state: AppState = Depends(get_app_state),
) -> dict[str, object]:
    if not settings.e2e_mode:
        raise HTTPException(status_code=404, detail="Not found")
    dropped = await state.drop_websocket_connections()
    return {"status": "ok", "dropped": dropped}


@router.get("/websockets")
async def websocket_status(
    settings: Settings = Depends(get_app_settings),
    state: AppState = Depends(get_app_state),
) -> dict[str, object]:
    if not settings.e2e_mode:
        raise HTTPException(status_code=404, detail="Not found")
    return {"status": "ok", "connections": state.websocket_connection_count()}
