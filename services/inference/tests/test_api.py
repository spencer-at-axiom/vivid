from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from vivid_inference.config import get_settings
from vivid_inference.main import create_app
from vivid_inference.model_manager import get_model_manifest
from vivid_inference.state import app_state


def _register_local_model(model_id: str, model_type: str = "sd15", favorite: bool = False) -> None:
    settings = get_settings()
    local_path = settings.models_dir / model_id.replace("/", "_")
    manifest = get_model_manifest(model_type)
    local_path.mkdir(parents=True, exist_ok=True)
    for file_path in manifest["required_files"]:
        target = local_path / file_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}", encoding="utf-8")
    for group in manifest["required_any_of"]:
        target = local_path / group[0]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}", encoding="utf-8")

    model = app_state._normalize_model_record(
        {
            "id": model_id,
            "source": "test",
            "name": model_id.split("/")[-1],
            "type": model_type,
            "family": model_type,
            "precision": manifest["default_precision"],
            "revision": "test-revision",
            "local_path": str(local_path),
            "size_bytes": sum(path.stat().st_size for path in local_path.rglob("*") if path.is_file()),
            "last_used_at": None,
            "required_files": list(manifest["required_files"]),
            "last_validated_at": "2026-04-01T00:00:00+00:00",
            "is_valid": True,
            "invalid_reason": None,
            "favorite": favorite,
            "profile_json": {},
        }
    )
    app_state.models[model_id] = model
    app_state._upsert_model(model)


def _activate_local_model(model_id: str) -> None:
    app_state.active_model_id = model_id
    with TestClient(create_app()) as client:
        response = client.post("/models/activate", json={"model_id": model_id})
        assert response.status_code == 200


def _await_terminal_job(client: TestClient, job_id: str, timeout_seconds: float = 8.0) -> dict:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        response = client.get(f"/jobs/{job_id}")
        assert response.status_code == 200
        job = response.json()["item"]
        if job["status"] in {"completed", "failed", "cancelled"}:
            return job
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} did not reach a terminal state")


def _receive_until_event(websocket: object, event_name: str, max_reads: int = 8) -> dict:
    for _ in range(max_reads):
        message = websocket.receive_json()  # type: ignore[attr-defined]
        if message.get("event") == event_name:
            return message
    raise AssertionError(f"did not receive event '{event_name}' within {max_reads} messages")


def test_health() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"


def test_http_origin_allowlist_rejects_disallowed_origins() -> None:
    with TestClient(create_app()) as client:
        blocked = client.get("/health", headers={"origin": "https://evil.example"})
        assert blocked.status_code == 403
        blocked_payload = blocked.json()["error"]
        assert blocked_payload["code"] == "origin_not_allowed"

        allowed = client.get("/health", headers={"origin": "http://localhost:1420"})
        assert allowed.status_code == 200


def test_settings_include_hardware_profile_default() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/settings")
        assert response.status_code == 200
        settings = response.json()["items"]
        assert settings["hardware_profile"] in {"low_vram", "balanced", "quality"}
        assert settings["runtime_policy"]["name"] == settings["hardware_profile"]
        assert "offload" in settings["runtime_policy"]
        assert settings["auto_save_interval"] == 1
        assert settings["export_metadata"] is True
        assert settings["theme"] in {"dark", "light", "auto"}
        assert settings["diagnostic_mode"] is False
        assert settings["scrub_prompt_text"] is True
        assert settings["network_access_mode"] == "explicit_model_ops"


def test_prompting_config_and_enhancer_contract() -> None:
    with TestClient(create_app()) as client:
        config_response = client.get("/prompting/config")
        assert config_response.status_code == 200
        config = config_response.json()["item"]
        assert config["version"] == 1
        assert config["latency_target_ms"] == 250
        assert any(item["id"] == "photo" for item in config["starter_intents"])
        assert any(item["id"] == "cinematic" for item in config["styles"])
        assert any(item["id"] == "text-watermark" for item in config["negative_prompt_chips"])

        enhance_response = client.post(
            "/prompting/enhance",
            json={
                "prompt": "futuristic city skyline",
                "intent_id": "illustration",
                "style_id": "illustration",
            },
        )
        assert enhance_response.status_code == 200
        item = enhance_response.json()["item"]
        assert item["original_prompt"] == "futuristic city skyline"
        assert "futuristic city skyline" in item["suggested_prompt"]
        assert item["intent_id"] == "illustration"
        assert item["style_id"] == "illustration"
        assert item["latency_ms"] >= 0
        assert item["latency_target_ms"] == 250
        assert item["reasons"]


def test_prompting_enhancer_rejects_empty_prompt() -> None:
    with TestClient(create_app()) as client:
        response = client.post("/prompting/enhance", json={"prompt": "   ", "intent_id": "photo", "style_id": "cinematic"})
        assert response.status_code == 400
        payload = response.json()["error"]
        assert payload["code"] == "prompt_enhance_failed"


def test_job_lifecycle_and_project_assets() -> None:
    _register_local_model("tests/sd15-active")
    with TestClient(create_app()) as client:
        activate_response = client.post("/models/activate", json={"model_id": "tests/sd15-active"})
        assert activate_response.status_code == 200
        project_response = client.post("/projects", json={"name": "API Test Project"})
        assert project_response.status_code == 200
        project_id = project_response.json()["item"]["id"]

        job_response = client.post(
            "/jobs/generate",
            json={
                "project_id": project_id,
                "prompt": "test scene",
                "negative_prompt": "low quality",
                "params": {"width": 640, "height": 640, "steps": 12},
            },
        )
        assert job_response.status_code == 200
        job_id = job_response.json()["item"]["id"]

        terminal_job = _await_terminal_job(client, job_id)
        assert terminal_job["status"] == "completed"
        assert terminal_job["progress"] == 1.0

        refreshed_project = client.get(f"/projects/{project_id}")
        assert refreshed_project.status_code == 200
        payload = refreshed_project.json()["item"]
        assert len(payload.get("assets", [])) >= 1
        assert len(payload.get("generations", [])) >= 1
        assert "state" in payload


def test_queue_controls() -> None:
    _register_local_model("tests/sd15-active")
    with TestClient(create_app()) as client:
        activate_response = client.post("/models/activate", json={"model_id": "tests/sd15-active"})
        assert activate_response.status_code == 200
        pause_response = client.post("/jobs/queue/pause")
        assert pause_response.status_code == 200
        assert pause_response.json()["item"]["paused"] is True

        client.post("/jobs/generate", json={"prompt": "first", "params": {}})
        client.post("/jobs/generate", json={"prompt": "second", "params": {}})

        queue_state = client.get("/jobs/queue/state")
        assert queue_state.status_code == 200
        queue_payload = queue_state.json()["item"]
        assert queue_payload["queued_count"] >= 1
        assert queue_payload["progress_contract_version"] == "v1"

        clear_response = client.post("/jobs/queue/clear", json={"include_terminal": False})
        assert clear_response.status_code == 200
        maintenance = clear_response.json()["item"]["maintenance"]["wal_checkpoint"]
        assert maintenance["mode"] == "PASSIVE"
        assert isinstance(maintenance["busy"], int)
        assert isinstance(maintenance["log_frames"], int)
        assert isinstance(maintenance["checkpointed_frames"], int)

        resume_response = client.post("/jobs/queue/resume")
        assert resume_response.status_code == 200
        assert resume_response.json()["item"]["paused"] is False


def test_model_favorite_filter_and_remove() -> None:
    _register_local_model("tests/sd15-model", model_type="sd15", favorite=False)
    with TestClient(create_app()) as client:
        favorite_response = client.post(
            "/models/favorite",
            json={"model_id": "tests/sd15-model", "favorite": True},
        )
        assert favorite_response.status_code == 200
        assert favorite_response.json()["item"]["favorite"] is True

        favorites_only = client.get("/models/local?favorites_only=true")
        assert favorites_only.status_code == 200
        favorite_ids = [item["id"] for item in favorites_only.json()["items"]]
        assert "tests/sd15-model" in favorite_ids

        remove_response = client.delete("/models/tests%2Fsd15-model")
        assert remove_response.status_code == 200
        assert remove_response.json()["item"]["removed"] is True

        local_models = client.get("/models/local")
        assert local_models.status_code == 200
        local_ids = [item["id"] for item in local_models.json()["items"]]
        assert "tests/sd15-model" not in local_ids


def test_model_activation_rejects_incompatible_profile() -> None:
    _register_local_model("tests/flux-model", model_type="flux", favorite=False)
    _register_local_model("tests/sd15-fallback", model_type="sd15", favorite=False)

    with TestClient(create_app()) as client:
        update_profile = client.post("/settings", json={"key": "hardware_profile", "value": "low_vram"})
        assert update_profile.status_code == 200

        response = client.post("/models/activate", json={"model_id": "tests/flux-model"})
        assert response.status_code == 400
        detail = response.json()["error"]["detail"]
        assert "require at least the 'quality'" in detail.lower()
        assert "Suggested fallback" in detail


def test_local_model_listing_surfaces_registry_metadata_after_activation() -> None:
    _register_local_model("tests/sd15-metadata", model_type="sd15")
    with TestClient(create_app()) as client:
        activate_response = client.post("/models/activate", json={"model_id": "tests/sd15-metadata"})
        assert activate_response.status_code == 200

        local_response = client.get("/models/local")
        assert local_response.status_code == 200
        items = local_response.json()["items"]
        item = next(model for model in items if model["id"] == "tests/sd15-metadata")
        assert item["family"] == "sd15"
        assert item["precision"] == "fp16"
        assert item["required_files"]
        assert item["is_valid"] is True
        assert item["last_validated_at"] is not None
        assert item["last_used_at"] is not None
        assert item["compatibility"]["supported"] is True


def test_generation_requires_an_active_model() -> None:
    with TestClient(create_app()) as client:
        response = client.post("/jobs/generate", json={"prompt": "no active model", "params": {"steps": 8}})
        assert response.status_code == 400
        payload = response.json()["error"]
        assert payload["code"] == "no_active_model"


def test_mode_unsupported_is_explicit_for_active_model_family() -> None:
    _register_local_model("tests/flux-active", model_type="flux")
    settings = get_settings()
    source_path = settings.projects_dir / "unsupported-source.png"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), color=(25, 50, 75)).save(source_path)
    with TestClient(create_app()) as client:
        profile_response = client.post("/settings", json={"key": "hardware_profile", "value": "quality"})
        assert profile_response.status_code == 200
        activate_response = client.post("/models/activate", json={"model_id": "tests/flux-active"})
        assert activate_response.status_code == 200

        response = client.post(
            "/jobs/upscale",
            json={"prompt": "unsupported", "params": {"steps": 10, "init_image_path": str(source_path), "upscale_factor": 2}},
        )
        assert response.status_code == 400
        payload = response.json()["error"]
        assert payload["code"] == "mode_unsupported"
        assert "supported modes" in payload["detail"].lower()


def test_invalid_seed_is_rejected() -> None:
    with TestClient(create_app()) as client:
        response = client.post("/jobs/generate", json={"prompt": "bad seed", "params": {"seed": "abc"}})
        assert response.status_code == 400
        payload = response.json()["error"]
        assert payload["code"] == "invalid_parameter"


def test_invalid_hardware_profile_setting_is_rejected() -> None:
    with TestClient(create_app()) as client:
        response = client.post("/settings", json={"key": "hardware_profile", "value": "ultra"})
        assert response.status_code == 400
        payload = response.json()["error"]
        assert payload["code"] == "invalid_setting"


def test_invalid_theme_and_autosave_settings_are_rejected() -> None:
    with TestClient(create_app()) as client:
        theme_response = client.post("/settings", json={"key": "theme", "value": "solarized"})
        assert theme_response.status_code == 400
        theme_payload = theme_response.json()["error"]
        assert theme_payload["code"] == "invalid_setting"

        autosave_response = client.post("/settings", json={"key": "auto_save_interval", "value": 0})
        assert autosave_response.status_code == 400
        autosave_payload = autosave_response.json()["error"]
        assert autosave_payload["code"] == "invalid_setting"


def test_hardware_profile_setting_drives_runtime_policy_for_generation() -> None:
    _register_local_model("tests/sd15-runtime")
    with TestClient(create_app()) as client:
        activate_response = client.post("/models/activate", json={"model_id": "tests/sd15-runtime"})
        assert activate_response.status_code == 200

        project_response = client.post("/projects", json={"name": "Runtime Policy Contract"})
        assert project_response.status_code == 200
        project_id = project_response.json()["item"]["id"]

        set_profile_response = client.post("/settings", json={"key": "hardware_profile", "value": "low_vram"})
        assert set_profile_response.status_code == 200
        assert set_profile_response.json()["runtime_policy"]["name"] == "low_vram"

        job_response = client.post(
            "/jobs/generate",
            json={"project_id": project_id, "prompt": "runtime policy low_vram", "params": {"steps": 8}},
        )
        assert job_response.status_code == 200
        job_id = job_response.json()["item"]["id"]

        terminal = _await_terminal_job(client, job_id)
        assert terminal["status"] == "completed"
        assert terminal["runtime_profile_requested"] == "low_vram"
        assert terminal["runtime_policy"]["name"] == "low_vram"


def test_project_state_update_persists_canvas_and_timeline_state() -> None:
    with TestClient(create_app()) as client:
        project_response = client.post("/projects", json={"name": "Canvas Persistence"})
        assert project_response.status_code == 200
        project_id = project_response.json()["item"]["id"]

        state_payload = {
            "version": 1,
            "timeline": {"selected_generation_id": "gen-42"},
            "canvas": {
                "version": 1,
                "focused_asset_id": "asset-42",
                "assets": {
                    "asset-42": {
                        "source_bounds": {"x": 12, "y": 18, "width": 640, "height": 512},
                        "viewport": {"zoom": 1.1, "pan_x": -6, "pan_y": 9},
                        "mask_strokes": [],
                        "history_past": [],
                        "history_future": [],
                    }
                },
                "autosaved_at": "2026-04-02T00:00:00+00:00",
            },
        }

        update_response = client.put(f"/projects/{project_id}/state", json={"state": state_payload})
        assert update_response.status_code == 200
        assert update_response.json()["item"]["state"]["timeline"]["selected_generation_id"] == "gen-42"

        refreshed_response = client.get(f"/projects/{project_id}")
        assert refreshed_response.status_code == 200
        assert refreshed_response.json()["item"]["state"]["canvas"]["focused_asset_id"] == "asset-42"


def test_model_activation_rejects_invalid_local_install() -> None:
    _register_local_model("tests/broken-sd15", model_type="sd15")
    settings = get_settings()
    local_path = settings.models_dir / "tests_broken-sd15"
    (local_path / "unet" / "config.json").unlink(missing_ok=True)

    with TestClient(create_app()) as client:
        response = client.post("/models/activate", json={"model_id": "tests/broken-sd15"})
        assert response.status_code == 400
        payload = response.json()["error"]
        assert payload["code"] == "model_invalid"
        assert "missing files" in str(payload["detail"]).lower()


def test_model_activation_rejects_switch_during_running_generation() -> None:
    _register_local_model("tests/sd15-active", model_type="sd15")
    _register_local_model("tests/sd15-next", model_type="sd15")

    app = create_app()
    with TestClient(app) as client:
        activate_response = client.post("/models/activate", json={"model_id": "tests/sd15-active"})
        assert activate_response.status_code == 200

        app_state.jobs["running-job"] = {
            "id": "running-job",
            "kind": "generate",
            "status": "running",
            "payload": {"prompt": "running"},
            "progress": 0.5,
            "error": None,
            "queue_position": 1,
            "created_at": "2026-04-02T00:00:00+00:00",
            "updated_at": "2026-04-02T00:00:00+00:00",
        }
        app_state._running_job_id = "running-job"

        response = client.post("/models/activate", json={"model_id": "tests/sd15-next"})
        assert response.status_code == 400
        payload = response.json()["error"]
        assert payload["code"] == "generation_in_progress"
        assert "while a generation is running" in str(payload["detail"]).lower()


def test_model_remove_preview_and_remove_returns_disk_reclaim() -> None:
    _register_local_model("tests/remove-preview", model_type="sd15")
    with TestClient(create_app()) as client:
        preview_response = client.get("/models/tests%2Fremove-preview/remove-preview")
        assert preview_response.status_code == 200
        preview = preview_response.json()["item"]
        assert preview["can_remove"] is True
        assert preview["reclaimable_bytes"] > 0

        remove_response = client.delete("/models/tests%2Fremove-preview")
        assert remove_response.status_code == 200
        removed = remove_response.json()["item"]
        assert removed["removed"] is True
        assert removed["freed_bytes"] == preview["reclaimable_bytes"]
        assert removed["deleted_paths"] == preview["paths"]


def test_mode_validation_rejects_missing_source_inputs(tmp_path: Path) -> None:
    source_path = tmp_path / "source.png"
    Image.new("RGB", (64, 64), color=(128, 64, 32)).save(source_path)

    with TestClient(create_app()) as client:
        project_response = client.post("/projects", json={"name": "Validation Project"})
        assert project_response.status_code == 200
        project_id = project_response.json()["item"]["id"]

        img2img_response = client.post(
            "/jobs/img2img",
            json={
                "project_id": project_id,
                "prompt": "no source image",
                "params": {"steps": 10},
            },
        )
        assert img2img_response.status_code == 400
        img2img_payload = img2img_response.json()["error"]
        assert img2img_payload["code"] == "missing_source_image"

        invalid_source_response = client.post(
            "/jobs/img2img",
            json={
                "project_id": project_id,
                "prompt": "invalid source image path",
                "params": {"steps": 10, "init_image_path": "C:/does/not/exist.png"},
            },
        )
        assert invalid_source_response.status_code == 400
        invalid_source_payload = invalid_source_response.json()["error"]
        assert invalid_source_payload["code"] == "invalid_source_image"

        inpaint_response = client.post(
            "/jobs/inpaint",
            json={
                "project_id": project_id,
                "prompt": "source but no mask",
                "params": {"steps": 10, "init_image_path": str(source_path)},
            },
        )
        assert inpaint_response.status_code == 400
        inpaint_payload = inpaint_response.json()["error"]
        assert inpaint_payload["code"] == "missing_mask"

        invalid_mask_response = client.post(
            "/jobs/inpaint",
            json={
                "project_id": project_id,
                "prompt": "invalid mask payload",
                "params": {"steps": 10, "init_image_path": str(source_path), "mask_data": "not-a-data-url"},
            },
        )
        assert invalid_mask_response.status_code == 400
        invalid_mask_payload = invalid_mask_response.json()["error"]
        assert invalid_mask_payload["code"] == "invalid_mask"

        upscale_response = client.post(
            "/jobs/upscale",
            json={
                "project_id": project_id,
                "prompt": "invalid upscale factor",
                "params": {
                    "init_image_path": str(source_path),
                    "upscale_factor": 1.0,
                },
            },
        )
        assert upscale_response.status_code == 400
        upscale_payload = upscale_response.json()["error"]
        assert upscale_payload["code"] == "invalid_parameter"


def test_websocket_event_contract_and_ping() -> None:
    with TestClient(create_app()) as client:
        with client.websocket_connect("/events") as websocket:
            hello = _receive_until_event(websocket, "hello")
            assert hello["version"] == "v1"
            assert isinstance(hello["event_id"], int)
            assert "sent_at" in hello
            assert "queue" in hello["payload"]
            assert hello["payload"]["queue"]["progress_contract_version"] == "v1"

            websocket.send_text("ping")
            pong_text = _receive_until_event(websocket, "pong")
            assert pong_text["version"] == "v1"

            websocket.send_text('{"type":"ping","id":"abc123"}')
            pong_json = _receive_until_event(websocket, "pong")
            assert pong_json["payload"]["echo"] == "abc123"


def test_websocket_job_update_respects_progress_contract() -> None:
    _register_local_model("tests/sd15-active")
    with TestClient(create_app()) as client:
        activate_response = client.post("/models/activate", json={"model_id": "tests/sd15-active"})
        assert activate_response.status_code == 200
        pause_response = client.post("/jobs/queue/pause")
        assert pause_response.status_code == 200

        with client.websocket_connect("/events") as websocket:
            _receive_until_event(websocket, "hello")

            create_response = client.post("/jobs/generate", json={"prompt": "ws contract", "params": {"steps": 8}})
            assert create_response.status_code == 200

            job_update = _receive_until_event(websocket, "job_update", max_reads=16)
            payload = job_update["payload"]
            assert payload["status"] == "queued"
            assert payload["progress_state"] == "queued"
            assert payload["eta_confidence"] == "low"
            assert payload["eta_seconds"] is None

            queue_update = _receive_until_event(websocket, "queue_update", max_reads=16)
            assert queue_update["payload"]["progress_contract_version"] == "v1"
