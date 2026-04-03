from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import pytest
from PIL import Image, features

from vivid_inference.config import get_settings
from vivid_inference.db import open_db
from vivid_inference.model_manager import get_model_manifest
from vivid_inference.state import AppState, JobCancellationRequested, allowed_job_transitions


def _register_active_model(state: AppState, model_id: str = "tests/sd15-active", family: str = "sd15") -> None:
    settings = get_settings()
    local_path = settings.models_dir / model_id.replace("/", "_")
    manifest = get_model_manifest(family)
    local_path.mkdir(parents=True, exist_ok=True)
    for file_path in manifest["required_files"]:
        target = local_path / file_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}", encoding="utf-8")
    for group in manifest["required_any_of"]:
        target = local_path / group[0]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}", encoding="utf-8")

    model = state._normalize_model_record(
        {
            "id": model_id,
            "source": "test",
            "name": model_id.split("/")[-1],
            "type": family,
            "family": family,
            "precision": manifest["default_precision"],
            "revision": "test-revision",
            "local_path": str(local_path),
            "size_bytes": sum(path.stat().st_size for path in local_path.rglob("*") if path.is_file()),
            "last_used_at": None,
            "required_files": list(manifest["required_files"]),
            "last_validated_at": "2026-04-01T00:00:00+00:00",
            "is_valid": True,
            "invalid_reason": None,
            "favorite": False,
            "profile_json": {},
        }
    )
    state.models[model_id] = model
    state.active_model_id = model_id
    state._upsert_model(model)


async def _await_terminal_job(state: AppState, job_id: str, attempts: int = 80) -> dict[str, object]:
    for _ in range(attempts):
        current = state.get_job(job_id)
        if current and current["status"] in {"completed", "failed", "cancelled"}:
            return current
        await asyncio.sleep(0.1)
    raise AssertionError(f"job {job_id} did not reach a terminal state")


def test_app_state_initialization() -> None:
    state = AppState()
    assert isinstance(state.jobs, dict)
    assert isinstance(state.models, dict)
    assert isinstance(state.projects, dict)
    assert state.active_model_id is None


def test_runtime_defaults_include_studio_and_privacy_contracts() -> None:
    state = AppState()
    settings = state.list_settings()

    assert settings["auto_save_interval"] == 1
    assert settings["export_metadata"] is True
    assert settings["theme"] in {"dark", "light", "auto"}
    assert settings["diagnostic_mode"] is False
    assert settings["scrub_prompt_text"] is True
    assert settings["network_access_mode"] == "explicit_model_ops"
    assert settings["runtime_policy"]["name"] == settings["hardware_profile"]


def test_first_run_hardware_detection_failure_falls_back_to_balanced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("vivid_inference.state.detect_hardware_profile", lambda: (_ for _ in ()).throw(RuntimeError("gpu probe failed")))
    state = AppState()
    assert state._get_runtime_setting("hardware_profile", None) == "balanced"


def test_user_hardware_profile_override_is_preserved_across_boot(monkeypatch: pytest.MonkeyPatch) -> None:
    with open_db() as connection:
        connection.execute(
            """
            INSERT INTO settings (key, value_json)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json
            """,
            ("hardware_profile", json.dumps("low_vram")),
        )

    monkeypatch.setattr("vivid_inference.state.detect_hardware_profile", lambda: "quality")
    state = AppState()
    assert state._get_runtime_setting("hardware_profile", None) == "low_vram"


@pytest.mark.asyncio
async def test_diagnostics_scrubs_prompt_text_by_default(caplog: pytest.LogCaptureFixture) -> None:
    state = AppState()
    state.start()
    _register_active_model(state)
    state.update_setting("diagnostic_mode", True)
    state.update_setting("scrub_prompt_text", True)

    sensitive_prompt = "sensitive client prompt value"
    caplog.set_level("INFO", logger="vivid_inference.state")

    await state.create_job("generate", {"prompt": sensitive_prompt, "params": {"steps": 8}})

    rendered = "\n".join(record.getMessage() for record in caplog.records)
    assert "diagnostic.job_queued" in rendered
    assert "<redacted:" in rendered
    assert sensitive_prompt not in rendered


@pytest.mark.asyncio
async def test_diagnostics_can_opt_in_to_raw_prompt_logging(caplog: pytest.LogCaptureFixture) -> None:
    state = AppState()
    state.start()
    _register_active_model(state)
    state.update_setting("diagnostic_mode", True)
    state.update_setting("scrub_prompt_text", False)

    prompt = "raw prompt diagnostics opt-in"
    caplog.set_level("INFO", logger="vivid_inference.state")

    await state.create_job("generate", {"prompt": prompt, "params": {"steps": 8}})

    rendered = "\n".join(record.getMessage() for record in caplog.records)
    assert "diagnostic.job_queued" in rendered
    assert prompt in rendered


@pytest.mark.asyncio
async def test_model_network_calls_require_explicit_path(monkeypatch: pytest.MonkeyPatch) -> None:
    state = AppState()
    observed: dict[str, bool] = {}

    class _StubManager:
        async def search_models(  # type: ignore[no-untyped-def]
            self,
            query: str = "",
            model_type: str | None = None,
            sort: str = "downloads",
            limit: int = 20,
            *,
            allow_network: bool = False,
        ):
            observed["search"] = allow_network
            return []

        async def preflight_install(  # type: ignore[no-untyped-def]
            self,
            model_id: str,
            *,
            requested_type: str | None = None,
            requested_revision: str | None = None,
            allow_network: bool = False,
        ):
            observed["preflight"] = allow_network
            return {"model_id": model_id}

    monkeypatch.setattr("vivid_inference.state.get_model_manager", lambda _models_dir: _StubManager())

    await state.search_models_async(query="sdxl", model_type="sdxl", sort="downloads")
    await state.preflight_model_install({"model_id": "tests/sdxl"})

    assert observed["search"] is True
    assert observed["preflight"] is True


@pytest.mark.asyncio
async def test_create_project_and_job() -> None:
    state = AppState()
    state.start()
    _register_active_model(state)

    project = await state.create_project("State Test Project")
    assert project["id"] in state.projects
    assert project["state"]["canvas"]["assets"] == {}

    job = await state.create_job(
        "generate",
        {"project_id": project["id"], "prompt": "test prompt", "params": {"steps": 8}},
    )
    assert job["kind"] == "generate"
    assert job["status"] == "queued"
    assert job["id"] in state.jobs


def test_activate_model_rejects_switch_while_generation_is_running() -> None:
    state = AppState()
    _register_active_model(state, model_id="tests/sd15-current", family="sd15")
    _register_active_model(state, model_id="tests/sd15-next", family="sd15")
    state.active_model_id = "tests/sd15-current"
    state.jobs["running-job"] = {
        "id": "running-job",
        "status": "running",
    }
    state._running_job_id = "running-job"

    with pytest.raises(ValueError, match="while a generation is running"):
        state.activate_model("tests/sd15-next")


@pytest.mark.asyncio
async def test_simulated_generation_creates_assets() -> None:
    state = AppState()
    state.start()
    _register_active_model(state)

    project = await state.create_project("Sim Project")
    job = await state.create_job(
        "generate",
        {
            "project_id": project["id"],
            "prompt": "city skyline at dusk",
            "negative_prompt": "low quality",
            "params": {"width": 512, "height": 512, "steps": 10},
        },
    )

    for _ in range(80):
        current = state.get_job(job["id"])
        if current and current["status"] in {"completed", "failed", "cancelled"}:
            break
        await asyncio.sleep(0.1)

    current = state.get_job(job["id"])
    assert current is not None
    assert current["status"] == "completed"

    project_payload = state.get_project(project["id"])
    assert project_payload is not None
    assert len(project_payload.get("assets", [])) >= 1
    assert len(project_payload.get("generations", [])) >= 1


@pytest.mark.asyncio
async def test_queued_job_stays_pinned_to_creation_model_after_active_model_changes() -> None:
    state = AppState()
    state.start()
    _register_active_model(state, model_id="tests/sd15-upscale", family="sd15")
    _register_active_model(state, model_id="tests/sdxl-new-active", family="sdxl")
    state.update_setting("hardware_profile", "balanced")
    state.active_model_id = "tests/sd15-upscale"

    project = await state.create_project("Pinned Model Project")
    source_path = Path(get_settings().projects_dir) / project["id"] / "source.png"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (128, 96), color=(20, 40, 60)).save(source_path)

    state.pause_queue()
    queued_job = await state.create_job(
        "upscale",
        {
            "project_id": project["id"],
            "prompt": "pin the model at queue time",
            "params": {"init_image_path": str(source_path), "upscale_factor": 2.0, "steps": 8},
        },
    )
    assert queued_job["payload"]["model_id"] == "tests/sd15-upscale"

    state.activate_model("tests/sdxl-new-active")
    assert state.active_model_id == "tests/sdxl-new-active"
    state.resume_queue()

    terminal_job = await _await_terminal_job(state, queued_job["id"])
    assert terminal_job["status"] == "completed"
    assert terminal_job["model_id_queued"] == "tests/sd15-upscale"


@pytest.mark.asyncio
async def test_all_generation_modes_produce_output_assets() -> None:
    state = AppState()
    state.start()
    _register_active_model(state, model_id="tests/sd15-modes", family="sd15")

    project = await state.create_project("Mode Coverage Project")
    source_path = Path(get_settings().projects_dir) / project["id"] / "source.png"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (256, 256), color=(100, 120, 140)).save(source_path)
    mask = Image.new("L", (256, 256), color=0)
    for x in range(96, 160):
        for y in range(96, 160):
            mask.putpixel((x, y), 255)
    mask_path = Path(get_settings().projects_dir) / project["id"] / "mask.png"
    mask.save(mask_path)

    job_specs = [
        ("generate", {"width": 256, "height": 256, "steps": 8, "seed": 7}),
        ("img2img", {"width": 256, "height": 256, "steps": 8, "seed": 7, "init_image_path": str(source_path)}),
        (
            "inpaint",
            {
                "width": 256,
                "height": 256,
                "steps": 8,
                "seed": 7,
                "init_image_path": str(source_path),
                "mask_image_path": str(mask_path),
            },
        ),
        (
            "outpaint",
            {
                "width": 256,
                "height": 256,
                "steps": 8,
                "seed": 7,
                "init_image_path": str(source_path),
                "outpaint_padding": 64,
            },
        ),
        (
            "upscale",
            {
                "width": 256,
                "height": 256,
                "steps": 8,
                "seed": 7,
                "init_image_path": str(source_path),
                "upscale_factor": 2,
            },
        ),
    ]

    results: dict[str, dict[str, object]] = {}
    for kind, params in job_specs:
        job = await state.create_job(
            kind,
            {
                "project_id": project["id"],
                "prompt": f"{kind} test prompt",
                "params": params,
            },
        )
        results[kind] = await _await_terminal_job(state, job["id"])

    project_payload = state.get_project(project["id"])
    assert project_payload is not None
    assets_by_id = {asset["id"]: asset for asset in project_payload.get("assets", [])}

    for kind, terminal_job in results.items():
        assert terminal_job["status"] == "completed"
        output_asset_id = terminal_job.get("output_asset_id")
        assert isinstance(output_asset_id, str)
        asset = assets_by_id[output_asset_id]
        assert Path(asset["path"]).exists()

    generated_image = Image.open(assets_by_id[str(results["generate"]["output_asset_id"])]["path"])
    img2img_image = Image.open(assets_by_id[str(results["img2img"]["output_asset_id"])]["path"])
    inpaint_image = Image.open(assets_by_id[str(results["inpaint"]["output_asset_id"])]["path"])
    outpaint_image = Image.open(assets_by_id[str(results["outpaint"]["output_asset_id"])]["path"])
    upscale_image = Image.open(assets_by_id[str(results["upscale"]["output_asset_id"])]["path"])

    assert generated_image.size == (256, 256)
    assert img2img_image.size == (256, 256)
    assert inpaint_image.size == (256, 256)
    assert outpaint_image.size == (384, 384)
    assert upscale_image.size == (512, 512)
    assert inpaint_image.getpixel((24, 24)) == (100, 120, 140)
    assert outpaint_image.getpixel((128, 128)) == (100, 120, 140)


@pytest.mark.asyncio
async def test_seed_resolution_is_deterministic_when_locked_and_randomized_when_unlocked() -> None:
    state = AppState()
    state.start()
    _register_active_model(state)

    project = await state.create_project("Seed Project")
    locked_one = await state.create_job(
        "generate",
        {"project_id": project["id"], "prompt": "seeded prompt", "params": {"width": 256, "height": 256, "seed": 1234}},
    )
    locked_two = await state.create_job(
        "generate",
        {"project_id": project["id"], "prompt": "seeded prompt", "params": {"width": 256, "height": 256, "seed": 1234}},
    )
    unlocked_one = await state.create_job(
        "generate",
        {"project_id": project["id"], "prompt": "seeded prompt", "params": {"width": 256, "height": 256}},
    )
    unlocked_two = await state.create_job(
        "generate",
        {"project_id": project["id"], "prompt": "seeded prompt", "params": {"width": 256, "height": 256}},
    )

    locked_terminal_one = await _await_terminal_job(state, locked_one["id"])
    locked_terminal_two = await _await_terminal_job(state, locked_two["id"])
    unlocked_terminal_one = await _await_terminal_job(state, unlocked_one["id"])
    unlocked_terminal_two = await _await_terminal_job(state, unlocked_two["id"])

    assert locked_terminal_one["resolved_seed"] == 1234
    assert locked_terminal_two["resolved_seed"] == 1234
    assert locked_terminal_one["seed_locked"] is True
    assert locked_terminal_two["seed_locked"] is True
    assert unlocked_terminal_one["seed_locked"] is False
    assert unlocked_terminal_two["seed_locked"] is False
    assert unlocked_terminal_one["resolved_seed"] != unlocked_terminal_two["resolved_seed"]

    project_payload = state.get_project(project["id"])
    assert project_payload is not None
    assets_by_id = {asset["id"]: asset for asset in project_payload.get("assets", [])}

    locked_image_one = Image.open(assets_by_id[str(locked_terminal_one["output_asset_id"])]["path"]).tobytes()
    locked_image_two = Image.open(assets_by_id[str(locked_terminal_two["output_asset_id"])]["path"]).tobytes()
    unlocked_image_one = Image.open(assets_by_id[str(unlocked_terminal_one["output_asset_id"])]["path"]).tobytes()
    unlocked_image_two = Image.open(assets_by_id[str(unlocked_terminal_two["output_asset_id"])]["path"]).tobytes()

    assert locked_image_one == locked_image_two
    assert unlocked_image_one != unlocked_image_two


def test_active_model_mode_support_is_enforced_explicitly() -> None:
    state = AppState()
    _register_active_model(state, model_id="tests/flux-active", family="flux")

    with pytest.raises(ValueError, match="does not support 'inpaint' mode"):
        state._ensure_active_model_supports_mode(state.models["tests/flux-active"], "inpaint")


@pytest.mark.asyncio
async def test_project_state_persists_across_reload() -> None:
    state = AppState()
    project = await state.create_project("Persistent Canvas Project")
    updated = state.update_project_state(
        project["id"],
        {
            "version": 1,
            "timeline": {"selected_generation_id": "gen-123"},
            "canvas": {
                "version": 1,
                "focused_asset_id": "asset-123",
                "assets": {
                    "asset-123": {
                        "source_bounds": {"x": 10, "y": 20, "width": 300, "height": 200},
                        "viewport": {"zoom": 1.25, "pan_x": 12, "pan_y": -8},
                    }
                },
                "autosaved_at": "2026-04-02T00:00:00+00:00",
            },
        },
    )
    assert updated["state"]["timeline"]["selected_generation_id"] == "gen-123"

    reloaded = AppState().get_project(project["id"])
    assert reloaded is not None
    assert reloaded["state"]["timeline"]["selected_generation_id"] == "gen-123"
    assert reloaded["state"]["canvas"]["focused_asset_id"] == "asset-123"


@pytest.mark.asyncio
async def test_branching_from_non_latest_generation_persists_parent_child_lineage() -> None:
    state = AppState()
    state.start()
    _register_active_model(state)

    project = await state.create_project("Lineage Branch Project")
    root_job = await state.create_job(
        "generate",
        {
            "project_id": project["id"],
            "prompt": "root branch source",
            "params": {"width": 256, "height": 256, "steps": 8, "seed": 101},
        },
    )
    root_terminal = await _await_terminal_job(state, root_job["id"])
    assert root_terminal["status"] == "completed"
    root_asset_id = str(root_terminal["output_asset_id"])

    # Create a newer generation so branching from a prior generation is explicit.
    latest_job = await state.create_job(
        "generate",
        {
            "project_id": project["id"],
            "prompt": "newest generation",
            "params": {"width": 256, "height": 256, "steps": 8, "seed": 202},
        },
    )
    latest_terminal = await _await_terminal_job(state, latest_job["id"])
    assert latest_terminal["status"] == "completed"

    branch_job = await state.create_job(
        "img2img",
        {
            "project_id": project["id"],
            "prompt": "branch from earlier generation",
            "params": {
                "steps": 8,
                "width": 256,
                "height": 256,
                "init_image_asset_id": root_asset_id,
            },
        },
    )
    branch_terminal = await _await_terminal_job(state, branch_job["id"])
    assert branch_terminal["status"] == "completed"

    payload = state.get_project(project["id"])
    assert payload is not None

    generations_by_asset = {generation["output_asset_id"]: generation for generation in payload.get("generations", [])}
    root_generation = generations_by_asset[root_asset_id]
    branch_generation = generations_by_asset[str(branch_terminal["output_asset_id"])]

    assert branch_generation["parent_generation_id"] == root_generation["id"]
    assert branch_generation["params_json"]["init_image_asset_id"] == root_asset_id


@pytest.mark.asyncio
async def test_create_job_rejects_parent_generation_source_asset_mismatch() -> None:
    state = AppState()
    state.start()
    _register_active_model(state)

    project = await state.create_project("Lineage Guardrails Project")
    first = await state.create_job(
        "generate",
        {
            "project_id": project["id"],
            "prompt": "first source",
            "params": {"width": 256, "height": 256, "steps": 8, "seed": 303},
        },
    )
    second = await state.create_job(
        "generate",
        {
            "project_id": project["id"],
            "prompt": "second source",
            "params": {"width": 256, "height": 256, "steps": 8, "seed": 404},
        },
    )
    first_terminal = await _await_terminal_job(state, first["id"])
    second_terminal = await _await_terminal_job(state, second["id"])
    assert first_terminal["status"] == "completed"
    assert second_terminal["status"] == "completed"

    payload = state.get_project(project["id"])
    assert payload is not None
    generations_by_asset = {generation["output_asset_id"]: generation for generation in payload.get("generations", [])}
    first_generation = generations_by_asset[str(first_terminal["output_asset_id"])]

    with pytest.raises(ValueError, match="does not match"):
        await state.create_job(
            "img2img",
            {
                "project_id": project["id"],
                "prompt": "mismatched lineage",
                "parent_generation_id": first_generation["id"],
                "params": {
                    "steps": 8,
                    "width": 256,
                    "height": 256,
                    "init_image_asset_id": str(second_terminal["output_asset_id"]),
                },
            },
        )


@pytest.mark.asyncio
async def test_export_respects_format_metadata_toggle_and_composition_mode() -> None:
    state = AppState()
    state.start()
    _register_active_model(state)

    project = await state.create_project("Export Fidelity Project")
    source_job = await state.create_job(
        "generate",
        {
            "project_id": project["id"],
            "prompt": "selected generation source",
            "params": {"width": 256, "height": 256, "steps": 8, "seed": 505},
        },
    )
    newer_job = await state.create_job(
        "generate",
        {
            "project_id": project["id"],
            "prompt": "newer generation should not be selected",
            "params": {"width": 256, "height": 256, "steps": 8, "seed": 606},
        },
    )
    source_terminal = await _await_terminal_job(state, source_job["id"])
    newer_terminal = await _await_terminal_job(state, newer_job["id"])
    assert source_terminal["status"] == "completed"
    assert newer_terminal["status"] == "completed"

    payload = state.get_project(project["id"])
    assert payload is not None
    assets_by_id = {asset["id"]: asset for asset in payload.get("assets", [])}
    generations_by_asset = {generation["output_asset_id"]: generation for generation in payload.get("generations", [])}
    selected_asset_id = str(source_terminal["output_asset_id"])
    selected_asset = assets_by_id[selected_asset_id]
    selected_generation = generations_by_asset[selected_asset_id]
    assert selected_generation["model_id"] == "simulation"
    latest_asset_id = str(newer_terminal["output_asset_id"])
    latest_asset = assets_by_id[latest_asset_id]

    state.update_project_state(
        project["id"],
        {
            "version": 1,
            "timeline": {"selected_generation_id": selected_generation["id"]},
            "canvas": {
                "version": 1,
                "focused_asset_id": selected_asset_id,
                "assets": {
                    selected_asset_id: {
                        "source_size": {"width": selected_asset["width"], "height": selected_asset["height"]},
                        "source_bounds": {"x": 120, "y": 160, "width": 220, "height": 220},
                        "viewport": {"zoom": 1.1, "pan_x": -20, "pan_y": 14},
                        "mask_strokes": [
                            {
                                "id": "stroke-1",
                                "tool": "mask",
                                "size": 26,
                                "points": [{"x": 20, "y": 20}, {"x": 230, "y": 220}],
                            }
                        ],
                        "history_past": [],
                        "history_future": [],
                        "updated_at": "2026-04-02T00:00:00+00:00",
                    }
                },
                "autosaved_at": "2026-04-02T00:00:00+00:00",
            },
        },
    )

    png_with_metadata = state.export_project(
        project["id"],
        {"format": "png", "include_metadata": True, "flattened": False},
    )
    png_path = Path(png_with_metadata["path"])
    assert png_path.exists()
    with Image.open(png_path) as exported_png:
        assert exported_png.format == "PNG"
        assert exported_png.size == (selected_asset["width"], selected_asset["height"])
        assert exported_png.info.get("model_id") == "simulation"
        assert exported_png.info.get("model") == "simulation"
        assert exported_png.info.get("prompt") == selected_generation["prompt"]
        exported_png_pixels = exported_png.tobytes()

    with Image.open(Path(selected_asset["path"])) as selected_source_image:
        assert exported_png_pixels == selected_source_image.convert("RGB").tobytes()
    with Image.open(Path(latest_asset["path"])) as latest_source_image:
        assert exported_png_pixels != latest_source_image.convert("RGB").tobytes()

    png_without_metadata = state.export_project(
        project["id"],
        {"format": "png", "include_metadata": False, "flattened": False},
    )
    with Image.open(Path(png_without_metadata["path"])) as stripped_png:
        assert stripped_png.info.get("prompt") is None
        assert stripped_png.info.get("generation_id") is None

    flattened_png = state.export_project(
        project["id"],
        {"format": "png", "include_metadata": False, "flattened": True},
    )
    with Image.open(Path(flattened_png["path"])) as flattened_image:
        assert flattened_image.format == "PNG"
        assert flattened_image.size == (1024, 768)
        assert flattened_image.getpixel((10, 10)) == (0, 0, 0)

    jpeg_export = state.export_project(
        project["id"],
        {"format": "jpeg", "include_metadata": True, "flattened": False},
    )
    with Image.open(Path(jpeg_export["path"])) as jpeg_image:
        assert jpeg_image.format == "JPEG"
        assert jpeg_image.size == (selected_asset["width"], selected_asset["height"])

    if not features.check("webp"):
        pytest.skip("Pillow is built without WebP support.")

    webp_export = state.export_project(
        project["id"],
        {"format": "webp", "include_metadata": True, "flattened": False},
    )
    with Image.open(Path(webp_export["path"])) as webp_image:
        assert webp_image.format == "WEBP"
        assert webp_image.size == (selected_asset["width"], selected_asset["height"])


@pytest.mark.asyncio
async def test_export_fails_when_selected_source_asset_file_is_missing() -> None:
    state = AppState()
    state.start()
    _register_active_model(state)

    project = await state.create_project("Missing Export Asset")
    job = await state.create_job(
        "generate",
        {
            "project_id": project["id"],
            "prompt": "export missing file guardrail",
            "params": {"width": 256, "height": 256, "steps": 8, "seed": 707},
        },
    )
    terminal = await _await_terminal_job(state, job["id"])
    assert terminal["status"] == "completed"

    payload = state.get_project(project["id"])
    assert payload is not None
    generations_by_asset = {generation["output_asset_id"]: generation for generation in payload.get("generations", [])}
    selected_asset_id = str(terminal["output_asset_id"])
    selected_generation = generations_by_asset[selected_asset_id]
    selected_asset = next(asset for asset in payload["assets"] if asset["id"] == selected_asset_id)
    Path(selected_asset["path"]).unlink(missing_ok=True)

    state.update_project_state(
        project["id"],
        {
            "version": 1,
            "timeline": {"selected_generation_id": selected_generation["id"]},
            "canvas": {"version": 1, "focused_asset_id": selected_asset_id, "assets": {}, "autosaved_at": None},
        },
    )

    with pytest.raises(ValueError, match="missing"):
        state.export_project(
            project["id"],
            {"format": "png", "include_metadata": True, "flattened": False},
        )


def test_runtime_recovery_marks_running_jobs_failed_and_pending_recovered() -> None:
    running_id = str(uuid.uuid4())
    queued_id = str(uuid.uuid4())
    with open_db() as connection:
        connection.execute(
            """
            INSERT INTO jobs (id, kind, status, payload_json, progress, error, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                running_id,
                "generate",
                "running",
                json.dumps({"prompt": "recover me", "params": {}}),
                0.42,
                None,
                "2026-04-01T00:00:00+00:00",
                "2026-04-01T00:00:00+00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO jobs (id, kind, status, payload_json, progress, error, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                queued_id,
                "generate",
                "queued",
                json.dumps({"prompt": "queue me", "params": {}}),
                0.0,
                None,
                "2026-04-01T00:00:00+00:00",
                "2026-04-01T00:00:00+00:00",
            ),
        )

    state = AppState()
    recovered = state.get_job(queued_id)
    assert recovered is not None
    assert recovered["status"] == "recovered"
    assert queued_id in state.get_queue_state()["queued_job_ids"]

    failed_running = state.get_job(running_id)
    assert failed_running is not None
    assert failed_running["status"] == "failed"
    assert "restarted" in str(failed_running["error"]).lower()


def test_open_db_enables_wal_and_busy_timeout() -> None:
    with open_db() as connection:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()
    assert journal_mode is not None
    assert str(journal_mode[0]).lower() == "wal"
    assert busy_timeout is not None
    assert int(busy_timeout[0]) >= 5000


def test_transition_violation_raises_runtime_error() -> None:
    state = AppState()
    transitions = allowed_job_transitions()
    assert "completed" not in transitions["queued"]

    with pytest.raises(RuntimeError, match="Invalid job status transition"):
        state._transition_job_status({"status": "queued"}, "completed")


def test_queue_fairness_allows_interactive_bypass_then_runs_long_job() -> None:
    state = AppState()
    long_job_id = str(uuid.uuid4())
    interactive_job_id = str(uuid.uuid4())

    state.jobs[long_job_id] = {
        "id": long_job_id,
        "kind": "generate",
        "status": "queued",
        "payload": {"params": {"steps": 60, "num_images": 3, "width": 1536, "height": 1024}},
        "progress": 0.0,
        "eta_seconds": 0,
        "error": None,
        "created_at": "2026-04-01T00:00:00+00:00",
        "updated_at": "2026-04-01T00:00:00+00:00",
    }
    state.jobs[interactive_job_id] = {
        "id": interactive_job_id,
        "kind": "inpaint",
        "status": "queued",
        "payload": {"params": {"steps": 20, "width": 768, "height": 768}},
        "progress": 0.0,
        "eta_seconds": 0,
        "error": None,
        "created_at": "2026-04-01T00:00:01+00:00",
        "updated_at": "2026-04-01T00:00:01+00:00",
    }
    state._queue_order = [long_job_id, interactive_job_id]

    assert state._next_pending_job_id() == interactive_job_id
    assert state._next_pending_job_id() == interactive_job_id
    assert state._next_pending_job_id() == long_job_id


def test_runtime_recovery_marks_cancel_requested_jobs_failed() -> None:
    cancel_requested_id = str(uuid.uuid4())
    with open_db() as connection:
        connection.execute(
            """
            INSERT INTO jobs (id, kind, status, payload_json, progress, error, queue_position, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cancel_requested_id,
                "generate",
                "cancel_requested",
                json.dumps({"prompt": "cancel-in-flight", "params": {}}),
                0.75,
                "Cancellation requested by user.",
                2,
                "2026-04-01T00:00:00+00:00",
                "2026-04-01T00:00:00+00:00",
            ),
        )

    state = AppState()
    recovered = state.get_job(cancel_requested_id)
    assert recovered is not None
    assert recovered["status"] == "failed"
    assert "restarted" in str(recovered["error"]).lower()


def test_runtime_recovery_hardens_unknown_persisted_status_to_failed() -> None:
    unknown_status_id = str(uuid.uuid4())
    with open_db() as connection:
        connection.execute(
            """
            INSERT INTO jobs (id, kind, status, payload_json, progress, error, queue_position, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                unknown_status_id,
                "generate",
                "zombie",
                json.dumps({"prompt": "broken-status", "params": {}}),
                0.0,
                None,
                4,
                "2026-04-01T00:00:00+00:00",
                "2026-04-01T00:00:00+00:00",
            ),
        )

    state = AppState()
    recovered = state.get_job(unknown_status_id)
    assert recovered is not None
    assert recovered["status"] == "failed"
    assert "unknown persisted job status" in str(recovered["error"]).lower()


def test_restart_recovery_rehydrates_queue_in_persisted_order() -> None:
    first_id = str(uuid.uuid4())
    second_id = str(uuid.uuid4())
    with open_db() as connection:
        connection.execute(
            """
            INSERT INTO jobs (id, kind, status, payload_json, progress, error, queue_position, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                first_id,
                "generate",
                "queued",
                json.dumps({"prompt": "first", "params": {"steps": 10}}),
                0.0,
                None,
                2,
                "2026-04-01T00:00:01+00:00",
                "2026-04-01T00:00:01+00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO jobs (id, kind, status, payload_json, progress, error, queue_position, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                second_id,
                "generate",
                "queued",
                json.dumps({"prompt": "second", "params": {"steps": 10}}),
                0.0,
                None,
                1,
                "2026-04-01T00:00:02+00:00",
                "2026-04-01T00:00:02+00:00",
            ),
        )

    state = AppState()
    queue = state.get_queue_state()
    assert queue["queued_job_ids"][:2] == [second_id, first_id]
    assert state.get_job(first_id)["status"] == "recovered"
    assert state.get_job(second_id)["status"] == "recovered"


@pytest.mark.asyncio
async def test_running_cancel_transitions_to_cancel_requested_then_cancelled() -> None:
    state = AppState()
    state.start()
    _register_active_model(state)

    async def controlled_execute(job_id: str) -> None:
        for _ in range(30):
            current = state.get_job(job_id)
            if current and current["status"] == "cancel_requested":
                raise JobCancellationRequested()
            await asyncio.sleep(0.02)
        raise RuntimeError("cancel was not requested in time")

    state._execute_generation = controlled_execute  # type: ignore[assignment]

    job = await state.create_job("generate", {"prompt": "cancel me", "params": {"steps": 50}})
    await asyncio.sleep(0.05)
    requested = state.cancel_job(job["id"])
    assert requested is not None
    assert requested["status"] == "cancel_requested"

    for _ in range(80):
        current = state.get_job(job["id"])
        if current and current["status"] in {"completed", "failed", "cancelled"}:
            break
        await asyncio.sleep(0.05)

    final_job = state.get_job(job["id"])
    assert final_job is not None
    assert final_job["status"] == "cancelled"


@pytest.mark.asyncio
async def test_queue_reorder_persists_across_restart() -> None:
    state = AppState()
    _register_active_model(state)
    state.pause_queue()
    first = await state.create_job("generate", {"prompt": "first", "params": {"steps": 15}})
    second = await state.create_job("generate", {"prompt": "second", "params": {"steps": 15}})
    third = await state.create_job("generate", {"prompt": "third", "params": {"steps": 15}})

    reordered = state.reorder_queue([third["id"], first["id"], second["id"]])
    assert reordered["queued_job_ids"][:3] == [third["id"], first["id"], second["id"]]

    reloaded = AppState()
    queue = reloaded.get_queue_state()
    assert queue["queued_job_ids"][:3] == [third["id"], first["id"], second["id"]]


def test_queue_progress_contract_exposes_eta_only_for_high_confidence() -> None:
    state = AppState()
    job_id = str(uuid.uuid4())
    job = {
        "id": job_id,
        "kind": "generate",
        "status": "running",
        "payload": {"prompt": "progress-contract", "params": {"steps": 25}},
        "progress": 0.5,
        "eta_seconds": 12,
        "eta_confidence": "low",
        "error": None,
        "queue_position": 1,
        "created_at": "2026-04-01T00:00:00+00:00",
        "updated_at": "2026-04-01T00:00:00+00:00",
    }
    state.jobs[job_id] = job
    state._running_job_id = job_id
    state._queue_order = [job_id]

    state._apply_progress_eta_contract(job, raw_eta_seconds=12, eta_confidence="low")
    queue = state.get_queue_state()
    assert queue["progress_contract_version"] == "v1"
    assert queue["active_job"]["progress_state"] == "running"
    assert queue["active_job"]["eta_confidence"] == "low"
    assert queue["active_job"]["eta_seconds"] is None

    state._apply_progress_eta_contract(job, raw_eta_seconds=12, eta_confidence="high")
    queue = state.get_queue_state()
    assert queue["active_job"]["eta_confidence"] == "high"
    assert queue["active_job"]["eta_seconds"] == 12

    job["status"] = "cancel_requested"
    state._apply_progress_eta_contract(job, raw_eta_seconds=6, eta_confidence="high")
    queue = state.get_queue_state()
    assert queue["running_status"] == "cancel_requested"
    assert queue["active_job"]["progress_state"] == "cancelling"
    assert queue["active_job"]["eta_seconds"] is None


@pytest.mark.asyncio
async def test_clear_queue_reports_checkpoint_maintenance_and_deletes_terminal_jobs() -> None:
    state = AppState()
    _register_active_model(state)
    state.pause_queue()
    queued = await state.create_job("generate", {"prompt": "queued", "params": {"steps": 20}})
    terminal = await state.create_job("generate", {"prompt": "terminal", "params": {"steps": 20}})

    terminal_job = state.get_job(terminal["id"])
    assert terminal_job is not None
    terminal_job["status"] = "failed"
    terminal_job["error"] = "forced failure for maintenance test"
    state._apply_progress_eta_contract(terminal_job)
    state._upsert_job(terminal_job)

    result = state.clear_queue(include_terminal=True)
    maintenance = result["maintenance"]["wal_checkpoint"]
    assert maintenance["mode"] == "PASSIVE"
    assert isinstance(maintenance["busy"], int)
    assert isinstance(maintenance["log_frames"], int)
    assert isinstance(maintenance["checkpointed_frames"], int)

    assert state.get_job(queued["id"]) is None
    assert state.get_job(terminal["id"]) is None
    assert state.get_queue_state()["queued_count"] == 0
