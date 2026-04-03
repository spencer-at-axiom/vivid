from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import get_app_state
from ..errors import ApiError
from ..schemas import ProjectCreateRequest, ProjectExportRequest, ProjectStateUpdateRequest
from ..state import AppState

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("")
async def create_project(
    request: ProjectCreateRequest,
    state: AppState = Depends(get_app_state),
) -> dict[str, object]:
    return {"item": await state.create_project(request.name)}


@router.get("/{project_id}")
async def get_project(
    project_id: str,
    state: AppState = Depends(get_app_state),
) -> dict[str, object]:
    project = state.get_project(project_id)
    if not project:
        raise ApiError(code="project_not_found", message="Project not found.", status_code=404, detail={"project_id": project_id})
    return {"item": project}


@router.put("/{project_id}/state")
async def update_project_state(
    project_id: str,
    request: ProjectStateUpdateRequest,
    state: AppState = Depends(get_app_state),
) -> dict[str, object]:
    try:
        return {"item": state.update_project_state(project_id, request.state)}
    except KeyError:
        raise ApiError(code="project_not_found", message="Project not found.", status_code=404, detail={"project_id": project_id})


@router.post("/{project_id}/export")
async def export_project(
    project_id: str,
    request: ProjectExportRequest,
    state: AppState = Depends(get_app_state),
) -> dict[str, object]:
    try:
        result = state.export_project(project_id=project_id, export_request=request.model_dump())
        return {"item": result}
    except KeyError as e:
        raise ApiError(code="project_not_found", message="Project not found.", status_code=404, detail=str(e))
    except ValueError as e:
        raise ApiError(code="export_failed", message="Export failed.", status_code=400, detail=str(e))


@router.get("")
async def list_projects(limit: int = 50) -> dict[str, object]:
    """List all projects."""
    from ..db import open_db
    
    with open_db() as connection:
        cursor = connection.execute(
            "SELECT id, name, created_at, updated_at, cover_asset_id FROM projects ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
        projects = [
            {
                "id": row[0],
                "name": row[1],
                "created_at": row[2],
                "updated_at": row[3],
                "cover_asset_id": row[4],
            }
            for row in cursor.fetchall()
        ]
    
    return {"items": projects, "total": len(projects)}
