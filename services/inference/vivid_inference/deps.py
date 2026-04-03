from __future__ import annotations

from typing import Any

from fastapi import Request, WebSocket

from .config import Settings, get_settings
from .state import AppState, app_state

_SETTINGS_KEY = "vivid_settings"
_STATE_KEY = "vivid_app_state"


def bind_app_dependencies(app: Any, settings: Settings, state: AppState) -> None:
    setattr(app.state, _SETTINGS_KEY, settings)
    setattr(app.state, _STATE_KEY, state)


def _resolve_settings(app: Any) -> Settings:
    bound = getattr(app.state, _SETTINGS_KEY, None)
    if isinstance(bound, Settings):
        return bound
    return get_settings()


def _resolve_state(app: Any) -> AppState:
    bound = getattr(app.state, _STATE_KEY, None)
    if isinstance(bound, AppState):
        return bound
    return app_state


def get_app_settings(request: Request) -> Settings:
    return _resolve_settings(request.app)


def get_websocket_settings(websocket: WebSocket) -> Settings:
    return _resolve_settings(websocket.app)


def get_app_state(request: Request) -> AppState:
    return _resolve_state(request.app)


def get_websocket_state(websocket: WebSocket) -> AppState:
    return _resolve_state(websocket.app)
