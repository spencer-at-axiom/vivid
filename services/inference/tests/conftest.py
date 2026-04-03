from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_TEST_DATA_ROOT = Path(tempfile.mkdtemp(prefix="vivid-inference-tests-"))
os.environ["VIVID_DATA_ROOT"] = str(_TEST_DATA_ROOT)


@pytest.fixture(autouse=True)
def reset_state() -> None:
    from vivid_inference.config import get_settings
    from vivid_inference.db import init_db, open_db
    from vivid_inference.state import app_state

    get_settings.cache_clear()
    init_db()
    with open_db() as connection:
        for table in ("jobs", "generations", "assets", "projects", "models", "settings"):
            connection.execute(f"DELETE FROM {table}")

    app_state.jobs.clear()
    app_state.models.clear()
    app_state.projects.clear()
    app_state.active_model_id = None
    app_state._queue_order.clear()
    app_state._running_job_id = None
    app_state._queue_paused = False
    app_state._interactive_burst_count = 0
    if app_state._processor_task is not None and not app_state._processor_task.done():
        app_state._processor_task.cancel()
    app_state._processor_task = None
