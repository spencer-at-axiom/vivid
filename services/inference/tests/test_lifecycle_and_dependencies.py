from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vivid_inference.config import Settings
from vivid_inference.deps import get_app_settings, get_app_state
from vivid_inference.main import create_app
from vivid_inference.state import AppState


def _receive_event(websocket: object, event_name: str, max_reads: int = 8) -> dict:
    for _ in range(max_reads):
        message = websocket.receive_json()  # type: ignore[attr-defined]
        if message.get("event") == event_name:
            return message
    raise AssertionError(f"Event '{event_name}' not received")


class TrackingState(AppState):
    def __init__(self) -> None:
        super().__init__()
        self.start_calls = 0
        self.stop_calls = 0

    def start(self) -> None:
        self.start_calls += 1
        super().start()

    async def stop(self) -> None:
        self.stop_calls += 1
        await super().stop()


@pytest.fixture
def isolated_app() -> tuple[object, AppState]:
    state = AppState()
    app = create_app(state=state)
    return app, state


def test_lifespan_starts_and_stops_processor() -> None:
    state = TrackingState()
    app = create_app(state=state)

    assert state._processor_task is None
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert state.start_calls == 1
        assert state._processor_task is not None
        assert not state._processor_task.done()

    assert state.stop_calls == 1
    assert state._processor_task is None


def test_websocket_disconnect_and_reconnect_updates_connection_registry(isolated_app: tuple[object, AppState]) -> None:
    app, state = isolated_app
    with TestClient(app) as client:
        assert state.websocket_connection_count() == 0
        with client.websocket_connect("/events") as websocket:
            hello = _receive_event(websocket, "hello")
            assert hello["version"] == "v1"
            assert state.websocket_connection_count() == 1
            websocket.send_text("ping")
            _receive_event(websocket, "pong")

        deadline = time.time() + 1.0
        while time.time() < deadline and state.websocket_connection_count() != 0:
            time.sleep(0.02)
        assert state.websocket_connection_count() == 0

        with client.websocket_connect("/events") as websocket:
            hello = _receive_event(websocket, "hello")
            assert hello["event"] == "hello"
            assert state.websocket_connection_count() == 1


def test_dependency_override_for_state_and_settings(isolated_app: tuple[object, AppState], tmp_path: Path) -> None:
    app, _ = isolated_app

    class StubState:
        def get_queue_state(self) -> dict[str, object]:
            return {
                "paused": True,
                "running_job_id": "override-job",
                "running_status": "running",
                "queued_job_ids": ["q-1", "q-2"],
                "queued_count": 2,
            }

    custom_settings = Settings(data_root=tmp_path, api_host="0.0.0.0", api_port=9876, e2e_mode=False)
    app.dependency_overrides[get_app_state] = lambda: StubState()
    app.dependency_overrides[get_app_settings] = lambda: custom_settings

    try:
        with TestClient(app) as client:
            queue_response = client.get("/jobs/queue/state")
            assert queue_response.status_code == 200
            queue = queue_response.json()["item"]
            assert queue["paused"] is True
            assert queue["running_job_id"] == "override-job"
            assert queue["queued_job_ids"] == ["q-1", "q-2"]

            health_response = client.get("/health")
            assert health_response.status_code == 200
            health = health_response.json()
            assert health["api_host"] == "0.0.0.0"
            assert health["api_port"] == 9876
            assert Path(health["data_root"]) == tmp_path
    finally:
        app.dependency_overrides.clear()
