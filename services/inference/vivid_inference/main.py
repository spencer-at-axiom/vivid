from __future__ import annotations

import json
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings, get_settings
from .db import init_db
from .deps import bind_app_dependencies, get_app_settings, get_websocket_state
from .errors import ApiError, http_status_default_code
from .routes import e2e_router, jobs_router, models_router, prompting_router, projects_router, settings_router
from .state import AppState, app_state


def create_app(
    *,
    settings: Settings | None = None,
    state: AppState | None = None,
) -> FastAPI:
    current_settings = settings or get_settings()
    current_state = state or app_state
    allowed_origins = tuple(current_settings.allowed_origins)
    allowed_origin_set = set(allowed_origins)
    init_db(current_settings)
    current_state.reload_from_db()

    @asynccontextmanager
    async def _lifespan(_: FastAPI):
        current_state.start()
        try:
            yield
        finally:
            await current_state.stop()

    app = FastAPI(
        title="Vivid Inference API",
        version="0.1.0",
        description="Local sidecar API for Vivid V1",
        lifespan=_lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["content-type", "x-requested-with"],
    )
    bind_app_dependencies(app, current_settings, current_state)

    app.include_router(models_router)
    app.include_router(jobs_router)
    app.include_router(projects_router)
    app.include_router(settings_router)
    app.include_router(prompting_router)
    if current_settings.e2e_mode:
        app.include_router(e2e_router)

    @app.middleware("http")
    async def enforce_origin_allowlist(request: Request, call_next):
        request_origin = request.headers.get("origin")
        if request_origin and request_origin not in allowed_origin_set:
            return JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "code": "origin_not_allowed",
                        "message": "Request origin is not allowed.",
                        "detail": {
                            "origin": request_origin,
                        },
                    }
                },
            )
        return await call_next(request)

    @app.exception_handler(ApiError)
    async def api_error_handler(_: Request, error: ApiError) -> JSONResponse:
        return JSONResponse(status_code=error.status_code, content=error.to_payload())

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, error: RequestValidationError) -> JSONResponse:
        payload = {
            "error": {
                "code": "validation_error",
                "message": "Request validation failed.",
                "detail": error.errors(),
            }
        }
        return JSONResponse(status_code=422, content=payload)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_: Request, error: HTTPException) -> JSONResponse:
        detail = error.detail
        payload = {
            "error": {
                "code": http_status_default_code(error.status_code),
                "message": str(detail) if isinstance(detail, str) else "Request failed.",
                "detail": detail,
            }
        }
        return JSONResponse(status_code=error.status_code, content=payload)

    @app.exception_handler(Exception)
    async def unhandled_error_handler(_: Request, error: Exception) -> JSONResponse:
        payload = {
            "error": {
                "code": "internal_error",
                "message": "Unexpected server error.",
                "detail": str(error),
            }
        }
        return JSONResponse(status_code=500, content=payload)

    @app.get("/health")
    async def health(
        active_settings: Settings = Depends(get_app_settings),
    ) -> dict[str, object]:
        return {
            "status": "ok",
            "service": "vivid-inference",
            "api_host": active_settings.api_host,
            "api_port": active_settings.api_port,
            "data_root": str(active_settings.data_root),
        }

    @app.websocket("/events")
    async def events(
        websocket: WebSocket,
        state_for_ws: AppState = Depends(get_websocket_state),
    ) -> None:
        request_origin = websocket.headers.get("origin")
        if request_origin and request_origin not in allowed_origin_set:
            await websocket.close(code=1008, reason="Origin not allowed")
            return
        try:
            await state_for_ws.connect(websocket)
            while True:
                message = await websocket.receive_text()
                normalized = message.strip().lower()
                if normalized == "ping":
                    await websocket.send_json(state_for_ws.build_event("pong", {}))
                    continue
                try:
                    payload = json.loads(message)
                except Exception:
                    continue
                if isinstance(payload, dict) and str(payload.get("type", "")).lower() == "ping":
                    await websocket.send_json(state_for_ws.build_event("pong", {"echo": payload.get("id")}))
        except WebSocketDisconnect:
            state_for_ws.disconnect(websocket)
        except Exception:
            state_for_ws.disconnect(websocket)

    return app


app = create_app()
