from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import logging
import secrets
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import WebSocket
from PIL import Image, ImageDraw, PngImagePlugin

from .config import get_settings
from .db import execute_with_retry, open_db, wal_checkpoint
from .engine import (
    DIFFUSERS_AVAILABLE,
    describe_runtime_policy,
    detect_hardware_profile,
    get_engine,
    get_supported_modes,
    model_supports_mode,
    normalize_hardware_profile,
)
from .model_manager import ModelInstallError, get_model_manager

_PENDING_JOB_STATUSES = {"queued", "recovered"}
_TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled"}
_PROFILE_ORDER = {"low_vram": 0, "balanced": 1, "quality": 2}
_MODEL_MINIMUM_PROFILE = {"sd14": "low_vram", "sd15": "low_vram", "sdxl": "balanced", "flux": "quality"}
_RUNNING_JOB_STATUSES = {"running", "cancel_requested"}
_RESTART_RECOVERABLE_JOB_STATUSES = {"queued", "paused", "recovered"}
_KNOWN_JOB_STATUSES = _PENDING_JOB_STATUSES | _RUNNING_JOB_STATUSES | _TERMINAL_JOB_STATUSES | {"paused"}
_ETA_CONFIDENCE_VALUES = {"none", "low", "high"}
_SUPPORTED_EXPORT_FORMATS = {"png": "PNG", "jpeg": "JPEG", "webp": "WEBP"}
_CANVAS_EXPORT_WIDTH = 1024
_CANVAS_EXPORT_HEIGHT = 768
_DEFAULT_AUTO_SAVE_INTERVAL_SECONDS = 1
_MIN_AUTO_SAVE_INTERVAL_SECONDS = 1
_MAX_AUTO_SAVE_INTERVAL_SECONDS = 300
_DEFAULT_THEME = "dark"
_ALLOWED_THEMES = {"dark", "light", "auto"}
_NETWORK_ACCESS_MODE = "explicit_model_ops"
_RUNTIME_SETTING_DEFAULTS: dict[str, Any] = {
    "auto_save_interval": _DEFAULT_AUTO_SAVE_INTERVAL_SECONDS,
    "export_metadata": True,
    "theme": _DEFAULT_THEME,
    "diagnostic_mode": False,
    "scrub_prompt_text": True,
    "network_access_mode": _NETWORK_ACCESS_MODE,
}
_ALLOWED_JOB_TRANSITIONS: dict[str, set[str]] = {
    "queued": {"running", "cancelled"},
    "recovered": {"running", "cancelled"},
    "running": {"completed", "failed", "cancel_requested", "cancelled"},
    "cancel_requested": {"failed", "cancelled"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}
_logger = logging.getLogger("vivid_inference.state")


def allowed_job_transitions() -> dict[str, tuple[str, ...]]:
    return {
        status: tuple(sorted(next_states))
        for status, next_states in _ALLOWED_JOB_TRANSITIONS.items()
    }


class JobCancellationRequested(RuntimeError):
    """Raised when a running job has been asked to cancel."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_load_json(value: str | None, default: Any) -> Any:
    if value is None:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _estimate_eta_confidence(mode: str, progress: float) -> str:
    # Early/late progress ranges are intentionally treated as low confidence.
    normalized_mode = str(mode).lower()
    if normalized_mode in {"outpaint", "upscale"}:
        return "low"
    if progress < 0.2 or progress > 0.9:
        return "low"
    return "high"


def _stable_prompt_seed(prompt: str) -> int:
    digest = hashlib.sha256(prompt.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big")


def _default_project_state() -> dict[str, Any]:
    return {
        "version": 1,
        "timeline": {"selected_generation_id": None},
        "canvas": {
            "version": 1,
            "focused_asset_id": None,
            "assets": {},
            "autosaved_at": None,
        },
    }


class AppState:
    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, Any]] = {}
        self.models: dict[str, dict[str, Any]] = {}
        self.projects: dict[str, dict[str, Any]] = {}
        self.active_model_id: str | None = None

        self._sockets: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._queue_order: list[str] = []
        self._running_job_id: str | None = None
        self._queue_paused = False
        self._queue_wakeup = asyncio.Event()
        self._processor_task: asyncio.Task[None] | None = None
        self._interactive_burst_count = 0
        self._max_interactive_burst = 2
        self._last_queue_position = 0
        self._event_seq = 0
        self._event_version = "v1"

        self._load_projects_from_db()
        self._load_models_from_db()
        self._load_active_model()
        self._ensure_runtime_defaults()
        self._load_jobs_from_db()

    def reload_from_db(self) -> None:
        self.jobs.clear()
        self.models.clear()
        self.projects.clear()
        self.active_model_id = None
        self._queue_order = []
        self._running_job_id = None
        self._last_queue_position = 0
        self._load_projects_from_db()
        self._load_models_from_db()
        self._load_active_model()
        self._ensure_runtime_defaults()
        self._load_jobs_from_db()

    def _diagnostics_enabled(self) -> bool:
        return bool(self._get_runtime_setting("diagnostic_mode", False))

    def _scrub_prompt_logs(self) -> bool:
        return bool(self._get_runtime_setting("scrub_prompt_text", True))

    def _sanitize_prompt_for_logs(self, prompt: str) -> str:
        if not self._scrub_prompt_logs():
            return prompt
        if not prompt:
            return ""
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
        return f"<redacted:{digest}>"

    def _log_diagnostic_event(self, event: str, **payload: Any) -> None:
        if not self._diagnostics_enabled():
            return
        normalized = dict(payload)
        prompt_value = normalized.get("prompt")
        if isinstance(prompt_value, str):
            normalized["prompt"] = self._sanitize_prompt_for_logs(prompt_value)
        _logger.info("diagnostic.%s %s", event, json.dumps(normalized, sort_keys=True, default=str))

    def start(self) -> None:
        self._ensure_runtime_defaults()
        current_loop = asyncio.get_running_loop()
        if self._processor_task is not None:
            try:
                same_loop = self._processor_task.get_loop() is current_loop
            except Exception:
                same_loop = False
            if same_loop and not self._processor_task.done():
                return
            if not self._processor_task.done():
                self._processor_task.cancel()
        self._queue_wakeup = asyncio.Event()
        self._processor_task = asyncio.create_task(self._processor_loop(), name="vivid-queue-processor")
        self._queue_wakeup.set()

    async def stop(self) -> None:
        task = self._processor_task
        self._processor_task = None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._sockets.add(websocket)
        await websocket.send_json(
            self._build_event(
                "hello",
                {
                    "protocol_version": self._event_version,
                    "queue": self.get_queue_state(),
                },
            )
        )
        await websocket.send_json(self._build_event("queue_update", self.get_queue_state()))

    def disconnect(self, websocket: WebSocket) -> None:
        self._sockets.discard(websocket)

    async def drop_websocket_connections(self, code: int = 1012, reason: str = "e2e reconnect test") -> int:
        sockets = list(self._sockets)
        self._sockets.clear()
        closed = 0
        for socket in sockets:
            try:
                await socket.close(code=code, reason=reason)
                closed += 1
            except Exception:
                pass
        return closed

    def websocket_connection_count(self) -> int:
        return len(self._sockets)

    async def broadcast(self, event: str, payload: dict[str, Any]) -> None:
        if not self._sockets:
            return
        message = self._build_event(event, payload)
        disconnected: list[WebSocket] = []
        for socket in self._sockets:
            try:
                await socket.send_json(message)
            except Exception:
                disconnected.append(socket)
        for socket in disconnected:
            self._sockets.discard(socket)

    def _emit_event_soon(self, event: str, payload: dict[str, Any]) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.broadcast(event, payload))

    def _emit_queue_update_soon(self) -> None:
        self._emit_event_soon("queue_update", self.get_queue_state())

    def build_event(self, event: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._build_event(event, payload)

    def _build_event(self, event: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._event_seq += 1
        return {
            "event": event,
            "version": self._event_version,
            "event_id": self._event_seq,
            "sent_at": _utc_now(),
            "payload": payload,
        }

    def _load_projects_from_db(self) -> None:
        try:
            with open_db() as connection:
                cursor = connection.execute("SELECT id, name, created_at, updated_at, cover_asset_id, state_json FROM projects")
                for row in cursor.fetchall():
                    self.projects[row[0]] = {
                        "id": row[0],
                        "name": row[1],
                        "created_at": row[2],
                        "updated_at": row[3],
                        "cover_asset_id": row[4],
                        "state": self._normalize_project_state(_safe_load_json(row[5], _default_project_state())),
                    }
        except Exception:
            pass

    def _load_models_from_db(self) -> None:
        try:
            with open_db() as connection:
                cursor = connection.execute(
                    """
                    SELECT
                        id,
                        source,
                        name,
                        type,
                        family,
                        precision,
                        revision,
                        local_path,
                        size_bytes,
                        last_used_at,
                        required_files_json,
                        last_validated_at,
                        is_valid,
                        invalid_reason,
                        favorite,
                        profile_json
                    FROM models
                    """
                )
                for row in cursor.fetchall():
                    profile_json = _safe_load_json(row[15], {})
                    required_files = _safe_load_json(row[10], [])
                    model = self._normalize_model_record(
                        {
                            "id": row[0],
                            "source": row[1],
                            "name": row[2],
                            "type": row[3],
                            "family": row[4],
                            "precision": row[5],
                            "revision": row[6],
                            "local_path": row[7],
                            "size_bytes": row[8],
                            "last_used_at": row[9],
                            "required_files": required_files,
                            "last_validated_at": row[11],
                            "is_valid": bool(row[12]),
                            "invalid_reason": row[13],
                            "favorite": bool(row[14]),
                            "profile_json": profile_json,
                        }
                    )
                    self.models[model["id"]] = model
        except Exception:
            pass

    def _load_active_model(self) -> None:
        try:
            with open_db() as connection:
                cursor = connection.execute("SELECT value_json FROM settings WHERE key = ?", ("active_model_id",))
                row = cursor.fetchone()
                if row:
                    self.active_model_id = _safe_load_json(row[0], None)
        except Exception:
            pass

    @staticmethod
    def _upsert_setting_value(connection: Any, key: str, value: Any) -> None:
        execute_with_retry(
            connection,
            """
            INSERT INTO settings (key, value_json)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json
            """,
            (key, json.dumps(value)),
        )

    @staticmethod
    def _normalize_bool_setting(value: Any, *, key: str, strict: bool = True) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        if strict:
            raise ValueError(f"'{key}' must be a boolean.")
        default = _RUNTIME_SETTING_DEFAULTS.get(key, False)
        return bool(default)

    @staticmethod
    def _normalize_theme_setting(value: Any, *, strict: bool = True) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in _ALLOWED_THEMES:
            return normalized
        if strict:
            raise ValueError(f"Unsupported theme '{value}'.")
        return _DEFAULT_THEME

    @staticmethod
    def _normalize_auto_save_interval_setting(value: Any, *, strict: bool = True) -> int:
        if isinstance(value, bool):
            if strict:
                raise ValueError("auto_save_interval must be an integer between 1 and 300 seconds.")
            return _DEFAULT_AUTO_SAVE_INTERVAL_SECONDS
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            if strict:
                raise ValueError("auto_save_interval must be an integer between 1 and 300 seconds.") from None
            return _DEFAULT_AUTO_SAVE_INTERVAL_SECONDS
        if _MIN_AUTO_SAVE_INTERVAL_SECONDS <= parsed <= _MAX_AUTO_SAVE_INTERVAL_SECONDS:
            return parsed
        if strict:
            raise ValueError(
                f"auto_save_interval must be between {_MIN_AUTO_SAVE_INTERVAL_SECONDS} and {_MAX_AUTO_SAVE_INTERVAL_SECONDS} seconds."
            )
        return _DEFAULT_AUTO_SAVE_INTERVAL_SECONDS

    @classmethod
    def _normalize_runtime_setting(
        cls,
        key: str,
        value: Any,
        *,
        strict: bool = True,
    ) -> Any:
        normalized_key = str(key or "").strip()
        if normalized_key == "hardware_profile":
            if strict and (not isinstance(value, str) or value.strip().lower() not in {"low_vram", "balanced", "quality"}):
                raise ValueError("Unsupported hardware profile.")
            return normalize_hardware_profile(value)
        if normalized_key == "auto_save_interval":
            return cls._normalize_auto_save_interval_setting(value, strict=strict)
        if normalized_key == "export_metadata":
            return cls._normalize_bool_setting(value, key=normalized_key, strict=strict)
        if normalized_key == "theme":
            return cls._normalize_theme_setting(value, strict=strict)
        if normalized_key == "diagnostic_mode":
            return cls._normalize_bool_setting(value, key=normalized_key, strict=strict)
        if normalized_key == "scrub_prompt_text":
            return cls._normalize_bool_setting(value, key=normalized_key, strict=strict)
        if normalized_key == "network_access_mode":
            return _NETWORK_ACCESS_MODE
        if strict:
            raise ValueError(f"Unsupported setting key '{normalized_key}'.")
        return value

    def _load_settings_table(self) -> dict[str, Any]:
        settings_dict: dict[str, Any] = {}
        with open_db() as connection:
            cursor = connection.execute("SELECT key, value_json FROM settings")
            for row in cursor.fetchall():
                settings_dict[str(row[0])] = _safe_load_json(row[1], None)
        return settings_dict

    def _apply_runtime_profile(self, hardware_profile: str) -> dict[str, Any]:
        normalized = normalize_hardware_profile(hardware_profile)
        settings = get_settings()
        engine = get_engine(settings.models_dir, hardware_profile=normalized)
        if self.active_model_id:
            engine.set_active_model(self.active_model_id)
        return describe_runtime_policy(normalized)

    def _ensure_runtime_defaults(self) -> None:
        try:
            with open_db() as connection:
                cursor = connection.execute("SELECT key, value_json FROM settings")
                current = {str(row[0]): _safe_load_json(row[1], None) for row in cursor.fetchall()}

                stored_profile = current.get("hardware_profile")
                if stored_profile is None:
                    detected_profile = "balanced"
                    try:
                        detected_profile = normalize_hardware_profile(detect_hardware_profile())
                    except Exception as error:
                        _logger.warning("hardware_profile_detection_failed; using balanced fallback: %s", error)
                    self._upsert_setting_value(connection, "hardware_profile", detected_profile)
                else:
                    normalized_profile = normalize_hardware_profile(stored_profile)
                    if normalized_profile != stored_profile:
                        self._upsert_setting_value(connection, "hardware_profile", normalized_profile)

                for key, default_value in _RUNTIME_SETTING_DEFAULTS.items():
                    raw_value = current.get(key)
                    if raw_value is None:
                        self._upsert_setting_value(connection, key, default_value)
                        continue
                    normalized_value = self._normalize_runtime_setting(key, raw_value, strict=False)
                    if normalized_value != raw_value:
                        self._upsert_setting_value(connection, key, normalized_value)
        except Exception:
            # During module import, tables may not be initialized yet.
            return

    def list_settings(self) -> dict[str, Any]:
        self._ensure_runtime_defaults()
        settings_dict = self._load_settings_table()
        normalized: dict[str, Any] = {}
        for key, value in settings_dict.items():
            if key in {
                "hardware_profile",
                "auto_save_interval",
                "export_metadata",
                "theme",
                "diagnostic_mode",
                "scrub_prompt_text",
                "network_access_mode",
            }:
                normalized[key] = self._normalize_runtime_setting(key, value, strict=False)
            else:
                normalized[key] = value

        for key, default_value in _RUNTIME_SETTING_DEFAULTS.items():
            normalized.setdefault(key, default_value)
        normalized["hardware_profile"] = normalize_hardware_profile(normalized.get("hardware_profile"))
        normalized["runtime_policy"] = describe_runtime_policy(normalized["hardware_profile"])
        return normalized

    def get_setting(self, key: str) -> Any:
        settings_dict = self.list_settings()
        return settings_dict.get(key)

    def update_setting(self, key: str, value: Any) -> dict[str, Any]:
        normalized_key = str(key or "").strip()
        normalized_value = self._normalize_runtime_setting(normalized_key, value, strict=True)
        with open_db() as connection:
            self._upsert_setting_value(connection, normalized_key, normalized_value)

        if normalized_key == "hardware_profile":
            runtime_policy = self._apply_runtime_profile(normalized_value)
            return {"key": normalized_key, "value": normalized_value, "runtime_policy": runtime_policy}
        return {"key": normalized_key, "value": normalized_value}

    @staticmethod
    def _normalize_model_record(model: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(model)
        profile_json = normalized.get("profile_json")
        if not isinstance(profile_json, dict):
            profile_json = {}

        family = str(normalized.get("family") or normalized.get("type") or "sdxl").lower()
        required_files = normalized.get("required_files")
        if not isinstance(required_files, list):
            required_files = profile_json.get("required_files", [])
        required_files = [str(path) for path in required_files if isinstance(path, str)]

        favorite = bool(normalized.get("favorite", profile_json.get("favorite", False)))
        last_validated_at = normalized.get("last_validated_at") or profile_json.get("last_validated_at")
        is_valid = bool(normalized.get("is_valid", profile_json.get("is_valid", False)))
        invalid_reason = normalized.get("invalid_reason") or profile_json.get("invalid_reason")
        precision = str(normalized.get("precision") or profile_json.get("precision") or "fp16").lower()
        revision = normalized.get("revision") or profile_json.get("revision")

        normalized["type"] = family
        normalized["family"] = family
        normalized["precision"] = precision
        normalized["revision"] = revision
        normalized["required_files"] = required_files
        normalized["last_validated_at"] = last_validated_at
        normalized["is_valid"] = is_valid
        normalized["invalid_reason"] = invalid_reason
        normalized["favorite"] = favorite
        normalized["profile_json"] = {
            **profile_json,
            "required_files": required_files,
            "last_validated_at": last_validated_at,
            "is_valid": is_valid,
            "invalid_reason": invalid_reason,
            "favorite": favorite,
            "family": family,
            "precision": precision,
            "revision": revision,
        }
        return normalized

    @staticmethod
    def _normalize_project_state(state: Any) -> dict[str, Any]:
        payload = state if isinstance(state, dict) else {}
        timeline = payload.get("timeline") if isinstance(payload.get("timeline"), dict) else {}
        canvas = payload.get("canvas") if isinstance(payload.get("canvas"), dict) else {}
        assets = canvas.get("assets") if isinstance(canvas.get("assets"), dict) else {}
        return {
            "version": int(payload.get("version", 1) or 1),
            "timeline": {
                "selected_generation_id": timeline.get("selected_generation_id"),
            },
            "canvas": {
                "version": int(canvas.get("version", 1) or 1),
                "focused_asset_id": canvas.get("focused_asset_id"),
                "assets": assets,
                "autosaved_at": canvas.get("autosaved_at"),
            },
        }

    def _update_model_validation(
        self,
        model: dict[str, Any],
        *,
        required_files: list[str] | None = None,
        last_validated_at: str | None = None,
        is_valid: bool | None = None,
        invalid_reason: str | None | object = ...,
        family: str | None = None,
        precision: str | None = None,
        revision: str | None = None,
    ) -> dict[str, Any]:
        if required_files is not None:
            model["required_files"] = list(required_files)
        if last_validated_at is not None:
            model["last_validated_at"] = last_validated_at
        if is_valid is not None:
            model["is_valid"] = bool(is_valid)
        if invalid_reason is not ...:
            model["invalid_reason"] = invalid_reason
        if family is not None:
            model["family"] = family
            model["type"] = family
        if precision is not None:
            model["precision"] = precision
        if revision is not None:
            model["revision"] = revision
        normalized = self._normalize_model_record(model)
        model.clear()
        model.update(normalized)
        return model

    def _revalidate_model_install(self, model: dict[str, Any]) -> dict[str, Any]:
        settings = get_settings()
        manager = get_model_manager(settings.models_dir)
        family = str(model.get("family") or model.get("type") or "sdxl")
        validation = manager.inspect_local_model(Path(str(model.get("local_path", ""))), family)
        self._update_model_validation(
            model,
            required_files=list(validation["required_files"]),
            last_validated_at=_utc_now(),
            is_valid=bool(validation["is_valid"]),
            invalid_reason=validation["reason"],
            family=family,
        )
        self._upsert_model(model)
        return validation

    @staticmethod
    def _resolve_seed(seed_value: Any) -> tuple[int, bool, int | None]:
        if isinstance(seed_value, int):
            parsed = seed_value
        elif isinstance(seed_value, str) and seed_value.strip().lstrip("-").isdigit():
            parsed = int(seed_value.strip())
        else:
            parsed = None

        if parsed is not None and parsed >= 0:
            return parsed, True, parsed
        return secrets.randbelow(2**31), False, None

    @staticmethod
    def _supported_modes_for_model(model: dict[str, Any]) -> list[str]:
        family = str(model.get("family") or model.get("type") or "sdxl")
        return list(get_supported_modes(family))

    def _ensure_active_model_supports_mode(self, model: dict[str, Any], mode: str) -> None:
        family = str(model.get("family") or model.get("type") or "sdxl")
        if model_supports_mode(family, mode):
            return
        supported_modes = ", ".join(self._supported_modes_for_model(model))
        raise ValueError(
            f"Active model '{model.get('name', model.get('id', family))}' does not support '{mode}' mode. "
            f"Supported modes: {supported_modes}."
        )

    def _load_jobs_from_db(self) -> None:
        now = _utc_now()
        try:
            with open_db() as connection:
                cursor = connection.execute(
                    """
                    SELECT id, kind, status, payload_json, progress, error, queue_position, created_at, updated_at
                    FROM jobs
                    ORDER BY queue_position ASC, created_at ASC
                    """
                )
                rows = cursor.fetchall()
            for row in rows:
                status = str(row[2]).lower()
                payload = _safe_load_json(row[3], {})
                queue_position = int(row[6] or 0)
                job = {
                    "id": row[0],
                    "kind": row[1],
                    "status": status,
                    "payload": payload,
                    "progress": float(row[4] or 0.0),
                    "error": row[5],
                    "queue_position": queue_position,
                    "created_at": row[7],
                    "updated_at": row[8],
                    "eta_seconds": None,
                    "eta_confidence": "none",
                    "progress_state": "terminal",
                }
                self._last_queue_position = max(self._last_queue_position, queue_position)
                should_queue, changed = self._recover_job_after_restart(job, now=now)
                self._apply_progress_eta_contract(job)
                if should_queue:
                    self._queue_order.append(job["id"])
                if changed:
                    self._upsert_job(job)
                self.jobs[job["id"]] = job
            self._persist_queue_positions()
        except Exception:
            pass

    def _recover_job_after_restart(self, job: dict[str, Any], *, now: str) -> tuple[bool, bool]:
        status = str(job.get("status", "")).lower()

        if status in _RUNNING_JOB_STATUSES:
            job["status"] = "failed"
            job["updated_at"] = now
            job["error"] = "Inference service restarted while this job was running."
            job["eta_seconds"] = None
            return False, True

        if status in _RESTART_RECOVERABLE_JOB_STATUSES:
            changed = status != "recovered" or job.get("error") is not None
            job["status"] = "recovered"
            job["updated_at"] = now if changed else job.get("updated_at", now)
            job["error"] = None
            job["eta_seconds"] = None
            return True, changed

        if status in _TERMINAL_JOB_STATUSES:
            job["eta_seconds"] = None
            return False, False

        if status not in _KNOWN_JOB_STATUSES:
            # Unknown persisted statuses are hardened to terminal failure to protect queue integrity.
            job["status"] = "failed"
            job["updated_at"] = now
            job["eta_seconds"] = None
            job["error"] = f"Recovered from unknown persisted job status '{status or '<empty>'}'."
            return False, True

        # Defensive fallback: any unhandled known state should not re-enter processing automatically.
        job["status"] = "failed"
        job["updated_at"] = now
        job["eta_seconds"] = None
        job["error"] = f"Recovered from unhandled job status '{status}'."
        return False, True

    async def search_models_async(self, query: str, model_type: str | None, sort: str) -> list[dict[str, Any]]:
        settings = get_settings()
        manager = get_model_manager(settings.models_dir)
        self._log_diagnostic_event("model_search", query=query, model_type=model_type, sort=sort)
        return await manager.search_models(query=query, model_type=model_type, sort=sort, allow_network=True)

    async def preflight_model_install(self, request: dict[str, Any]) -> dict[str, Any]:
        model_id = request.get("model_id") or request.get("direct_url")
        if not model_id:
            raise ValueError("model_id is required")

        settings = get_settings()
        manager = get_model_manager(settings.models_dir)
        self._log_diagnostic_event(
            "model_preflight",
            model_id=model_id,
            requested_type=request.get("model_type"),
            requested_revision=request.get("revision"),
        )
        return await manager.preflight_install(
            model_id=model_id,
            requested_type=request.get("model_type"),
            requested_revision=request.get("revision"),
            allow_network=True,
        )

    async def install_model(self, request: dict[str, Any]) -> dict[str, Any]:
        model_id = request.get("model_id") or request.get("direct_url")
        if not model_id:
            raise ValueError("model_id is required")

        settings = get_settings()
        manager = get_model_manager(settings.models_dir)
        self._log_diagnostic_event(
            "model_install",
            model_id=model_id,
            requested_type=request.get("model_type"),
            requested_revision=request.get("revision"),
        )

        async def progress_callback(progress: float, status: str) -> None:
            await self.broadcast(
                "model_install_progress",
                {"model_id": model_id, "progress": progress, "status": status},
            )

        try:
            install_result = await manager.download_model(
                model_id=model_id,
                progress_callback=progress_callback,
                requested_type=request.get("model_type"),
                requested_revision=request.get("revision"),
                allow_network=True,
            )
        except ModelInstallError as error:
            await progress_callback(1.0, "failed")
            raise ValueError(str(error)) from error

        local_path = Path(str(install_result["local_path"]))
        display_name = request.get("display_name") or model_id.split("/")[-1]
        size_bytes = sum(f.stat().st_size for f in local_path.rglob("*") if f.is_file())
        previous = self.models.get(model_id, {})
        record = self._normalize_model_record(
            {
                "id": model_id,
                "source": "huggingface",
                "name": display_name,
                "type": install_result["family"],
                "family": install_result["family"],
                "precision": install_result["precision"],
                "revision": install_result["revision"],
                "local_path": str(local_path),
                "size_bytes": size_bytes,
                "last_used_at": previous.get("last_used_at"),
                "required_files": list(install_result["required_files"]),
                "last_validated_at": _utc_now(),
                "is_valid": bool(install_result["validation"]["is_valid"]),
                "invalid_reason": install_result["validation"]["reason"],
                "favorite": bool(previous.get("favorite", False)),
                "profile_json": previous.get("profile_json", {}),
            }
        )
        self.models[record["id"]] = record
        self._upsert_model(record)
        return self._serialize_model(record, hardware_profile=self._get_runtime_setting("hardware_profile", "balanced"))

    def list_models(self, favorites_only: bool = False) -> list[dict[str, Any]]:
        hardware_profile = self._get_runtime_setting("hardware_profile", "balanced")
        items: list[dict[str, Any]] = []
        for model in self.models.values():
            serialized = self._serialize_model(model, hardware_profile=hardware_profile)
            if favorites_only and not serialized["favorite"]:
                continue
            items.append(serialized)
        return sorted(items, key=lambda model: model["name"].lower())

    def activate_model(self, model_id: str) -> dict[str, Any]:
        if model_id not in self.models:
            raise KeyError(model_id)
        model = self.models[model_id]
        validation = self._revalidate_model_install(model)
        if not validation["is_valid"]:
            raise ValueError(validation["reason"] or "Model install is invalid or incomplete.")
        hardware_profile = self._get_runtime_setting("hardware_profile", "balanced")
        compatibility = self._evaluate_model_compatibility(model=model, hardware_profile=hardware_profile)
        if not compatibility["supported"]:
            reason = compatibility.get("reason") or "Model is not compatible with the current runtime profile."
            fallback = self._select_compatible_model(hardware_profile)
            if fallback:
                reason = f"{reason} Suggested fallback: {fallback['name']}."
            raise ValueError(reason)

        running_job_id = self._running_job_id
        if running_job_id:
            running_job = self.jobs.get(running_job_id)
            if (
                running_job
                and running_job.get("status") in _RUNNING_JOB_STATUSES
                and model_id != self.active_model_id
            ):
                raise ValueError(
                    f"Cannot activate model '{model_id}' while a generation is running (job '{running_job_id}')."
                )

        self.active_model_id = model_id
        model["last_used_at"] = _utc_now()
        self._upsert_model(model)
        with open_db() as connection:
            execute_with_retry(
                connection,
                """
                INSERT INTO settings (key, value_json)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json
                """,
                ("active_model_id", json.dumps(model_id)),
            )
        settings = get_settings()
        engine = get_engine(settings.models_dir, hardware_profile=hardware_profile)
        engine.set_active_model(model_id)
        return self._serialize_model(model, hardware_profile=hardware_profile)

    def set_model_favorite(self, model_id: str, favorite: bool) -> dict[str, Any]:
        model = self.models.get(model_id)
        if not model:
            raise KeyError(model_id)
        self._update_model_validation(model, is_valid=bool(model.get("is_valid", False)))
        model["favorite"] = bool(favorite)
        model["profile_json"]["favorite"] = bool(favorite)
        self._upsert_model(model)
        hardware_profile = self._get_runtime_setting("hardware_profile", "balanced")
        return self._serialize_model(model, hardware_profile=hardware_profile)

    def get_model_remove_preview(self, model_id: str) -> dict[str, Any]:
        model = self.models.get(model_id)
        if not model:
            raise KeyError(model_id)

        settings = get_settings()
        local_path = Path(str(model.get("local_path", ""))).expanduser()
        resolved = local_path.resolve()
        models_root = settings.models_dir.resolve()
        within_models_root = resolved.exists() and (resolved == models_root or models_root in resolved.parents)
        reclaimable_bytes = 0
        if within_models_root:
            reclaimable_bytes = sum(path.stat().st_size for path in resolved.rglob("*") if path.is_file())

        active = self.active_model_id == model_id
        return {
            "id": model_id,
            "name": model.get("name"),
            "active": active,
            "can_remove": not active,
            "blocked_reason": "Activate another model before removing this one." if active else None,
            "local_path": str(resolved),
            "paths": [str(resolved)] if within_models_root else [],
            "reclaimable_bytes": reclaimable_bytes,
        }

    def remove_model(self, model_id: str) -> dict[str, Any]:
        preview = self.get_model_remove_preview(model_id)
        if preview["active"]:
            raise ValueError("Cannot remove the active model. Activate another model first.")
        settings = get_settings()
        local_path = Path(str(preview["local_path"])).expanduser()
        try:
            resolved = local_path.resolve()
            models_root = settings.models_dir.resolve()
            if resolved.exists() and models_root in resolved.parents:
                shutil.rmtree(resolved, ignore_errors=True)
        except Exception:
            pass

        self.models.pop(model_id, None)
        with open_db() as connection:
            execute_with_retry(connection, "DELETE FROM models WHERE id = ?", (model_id,))

        return {
            **preview,
            "removed": True,
            "freed_bytes": preview["reclaimable_bytes"],
            "deleted_paths": preview["paths"],
        }

    @staticmethod
    def _normalized_optional_text(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _load_generation_for_project(
        connection: Any,
        project_id: str,
        generation_id: str,
    ) -> dict[str, str] | None:
        cursor = connection.execute(
            """
            SELECT id, output_asset_id
            FROM generations
            WHERE id = ? AND project_id = ?
            LIMIT 1
            """,
            (generation_id, project_id),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {"id": str(row[0]), "output_asset_id": str(row[1])}

    @staticmethod
    def _load_generation_for_output_asset(
        connection: Any,
        project_id: str,
        output_asset_id: str,
    ) -> dict[str, str] | None:
        cursor = connection.execute(
            """
            SELECT id, output_asset_id
            FROM generations
            WHERE project_id = ? AND output_asset_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (project_id, output_asset_id),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {"id": str(row[0]), "output_asset_id": str(row[1])}

    def _normalize_job_lineage(self, payload: dict[str, Any]) -> None:
        project_id = self._normalized_optional_text(payload.get("project_id"))
        if not project_id:
            return
        payload["project_id"] = project_id

        params = payload.get("params", {})
        if not isinstance(params, dict):
            params = {}
        payload["params"] = params

        parent_generation_id = self._normalized_optional_text(payload.get("parent_generation_id"))
        if parent_generation_id:
            payload["parent_generation_id"] = parent_generation_id
        else:
            payload["parent_generation_id"] = None

        source_asset_id = (
            self._normalized_optional_text(params.get("init_image_asset_id"))
            or self._normalized_optional_text(params.get("source_asset_id"))
            or self._normalized_optional_text(payload.get("source_asset_id"))
        )

        if not parent_generation_id and not source_asset_id:
            return

        with open_db() as connection:
            parent_generation = None
            if parent_generation_id:
                parent_generation = self._load_generation_for_project(connection, project_id, parent_generation_id)
                if not parent_generation:
                    raise ValueError(
                        f"Parent generation '{parent_generation_id}' does not exist in project '{project_id}'."
                    )

            source_generation = None
            if source_asset_id:
                source_generation = self._load_generation_for_output_asset(connection, project_id, source_asset_id)
                if source_generation and not parent_generation:
                    payload["parent_generation_id"] = source_generation["id"]
                    parent_generation = source_generation
                    parent_generation_id = source_generation["id"]

            if source_asset_id and parent_generation:
                expected_asset_id = parent_generation["output_asset_id"]
                if source_asset_id != expected_asset_id:
                    raise ValueError(
                        "The selected source asset does not match the selected parent generation output."
                    )

    async def create_job(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.start()
        async with self._lock:
            if not self.active_model_id:
                raise ValueError("No active model selected. Install and activate a model before generating.")
            active_model = self.models.get(self.active_model_id)
            if not active_model:
                raise ValueError("The active model is missing from the local registry.")
            validation = self._revalidate_model_install(active_model)
            if not validation["is_valid"]:
                raise ValueError(
                    f"Active model '{active_model.get('name', self.active_model_id)}' is incomplete: {validation['reason']}"
                )
            self._ensure_active_model_supports_mode(active_model, kind)
            now = _utc_now()
            job_id = str(uuid.uuid4())
            normalized_payload = payload.copy()
            normalized_payload.setdefault("params", {})
            self._normalize_job_lineage(normalized_payload)
            normalized_payload["model_id"] = active_model["id"]
            job = {
                "id": job_id,
                "kind": kind,
                "status": "queued",
                "payload": normalized_payload,
                "progress": 0.0,
                "eta_seconds": None,
                "eta_confidence": "low",
                "error": None,
                "queue_class": "interactive" if self._job_is_interactive({"kind": kind, "payload": normalized_payload}) else "batch",
                "queue_position": self._next_queue_position(),
                "created_at": now,
                "updated_at": now,
                "progress_state": "queued",
            }
            self._apply_progress_eta_contract(job)
            self.jobs[job_id] = job
            self._queue_order.append(job_id)
            self._persist_queue_positions()
            self._upsert_job(job)
            self._log_diagnostic_event(
                "job_queued",
                job_id=job_id,
                kind=kind,
                project_id=normalized_payload.get("project_id"),
                prompt=str(normalized_payload.get("prompt", "")),
                has_negative_prompt=bool(str(normalized_payload.get("negative_prompt", "")).strip()),
                params=normalized_payload.get("params", {}),
            )
            self._emit_event_soon("job_update", job.copy())
            self._emit_queue_update_soon()
            self._queue_wakeup.set()
            return job

    async def retry_job(self, job_id: str) -> dict[str, Any]:
        source = self.jobs.get(job_id)
        if not source:
            raise KeyError(job_id)
        payload = dict(source["payload"])
        payload["retry_of"] = job_id
        return await self.create_job(source["kind"], payload)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        return self.jobs.get(job_id)

    def _next_queue_position(self) -> int:
        self._last_queue_position += 1
        return self._last_queue_position

    def _persist_queue_positions(self) -> None:
        # Persist runtime queue ordering for recovery after restart.
        ordered_ids = [
            job_id
            for job_id in self._queue_order
            if self.jobs.get(job_id, {}).get("status") in (_PENDING_JOB_STATUSES | _RUNNING_JOB_STATUSES)
        ]
        position = 1
        for job_id in ordered_ids:
            job = self.jobs.get(job_id)
            if not job:
                continue
            job["queue_position"] = position
            self._upsert_job(job)
            position += 1

        # Keep terminal jobs at the tail to avoid disrupting replay ordering.
        for job in sorted(
            (item for item in self.jobs.values() if item.get("status") in _TERMINAL_JOB_STATUSES),
            key=lambda item: item.get("updated_at", ""),
        ):
            job["queue_position"] = position
            self._upsert_job(job)
            position += 1

        self._last_queue_position = max(self._last_queue_position, position)

    def cancel_job(self, job_id: str) -> dict[str, Any] | None:
        job = self.jobs.get(job_id)
        if not job or job["status"] in _TERMINAL_JOB_STATUSES:
            return job
        if job["status"] in _PENDING_JOB_STATUSES:
            self._transition_job_status(job, "cancelled", error=None, eta_seconds=0)
            self._queue_order = [queued_job_id for queued_job_id in self._queue_order if queued_job_id != job_id]
            self._persist_queue_positions()
        elif job["status"] == "running":
            self._transition_job_status(job, "cancel_requested", error="Cancellation requested by user.", eta_seconds=0)
        elif job["status"] == "cancel_requested":
            return job
        else:
            self._transition_job_status(job, "cancelled", error=None, eta_seconds=0)

        self._emit_event_soon("job_update", job.copy())
        self._emit_queue_update_soon()
        self._queue_wakeup.set()
        return job

    def get_queue_state(self) -> dict[str, Any]:
        queued_ids = [
            job_id
            for job_id in self._queue_order
            if self.jobs.get(job_id, {}).get("status") in _PENDING_JOB_STATUSES
        ]
        running_job = self.jobs.get(self._running_job_id or "")
        active_job = None
        if running_job and running_job.get("status") in _RUNNING_JOB_STATUSES:
            active_job = {
                "id": running_job.get("id"),
                "status": running_job.get("status"),
                "kind": running_job.get("kind"),
                "progress": float(running_job.get("progress", 0.0)),
                "progress_state": running_job.get("progress_state"),
                "eta_seconds": running_job.get("eta_seconds"),
                "eta_confidence": running_job.get("eta_confidence"),
            }
        return {
            "paused": self._queue_paused,
            "running_job_id": self._running_job_id,
            "running_status": running_job.get("status") if running_job else None,
            "queued_job_ids": queued_ids,
            "queued_count": len(queued_ids),
            "active_job": active_job,
            "progress_contract_version": "v1",
        }

    def pause_queue(self) -> dict[str, Any]:
        self._queue_paused = True
        self._emit_queue_update_soon()
        return self.get_queue_state()

    def resume_queue(self) -> dict[str, Any]:
        self._queue_paused = False
        self._queue_wakeup.set()
        self._emit_queue_update_soon()
        return self.get_queue_state()

    def clear_queue(self, include_terminal: bool = False) -> dict[str, Any]:
        cleared_pending = 0
        for job_id in list(self._queue_order):
            job = self.jobs.get(job_id)
            if not job:
                continue
            if job["status"] in _PENDING_JOB_STATUSES:
                self._transition_job_status(job, "cancelled", error=None, eta_seconds=0)
                self._emit_event_soon("job_update", job.copy())
                cleared_pending += 1

        if include_terminal:
            terminal_ids = [job_id for job_id, job in self.jobs.items() if job["status"] in _TERMINAL_JOB_STATUSES]
            if terminal_ids:
                self._delete_jobs(terminal_ids)
                for job_id in terminal_ids:
                    self.jobs.pop(job_id, None)

        self._queue_order = [
            job_id
            for job_id in self._queue_order
            if job_id in self.jobs and self.jobs[job_id]["status"] in (_PENDING_JOB_STATUSES | _RUNNING_JOB_STATUSES)
        ]
        self._persist_queue_positions()
        checkpoint = wal_checkpoint(mode="PASSIVE")
        self._emit_queue_update_soon()
        return {
            "cleared_pending": cleared_pending,
            "deleted_terminal": include_terminal,
            "queue": self.get_queue_state(),
            "maintenance": {
                "wal_checkpoint": {
                    "busy": checkpoint[0],
                    "log_frames": checkpoint[1],
                    "checkpointed_frames": checkpoint[2],
                    "mode": "PASSIVE",
                }
            },
        }

    def reorder_queue(self, job_ids: list[str]) -> dict[str, Any]:
        running = [
            job_id for job_id in self._queue_order if self.jobs.get(job_id, {}).get("status") in _RUNNING_JOB_STATUSES
        ]
        pending = [job_id for job_id in self._queue_order if self.jobs.get(job_id, {}).get("status") in _PENDING_JOB_STATUSES]
        provided = [job_id for job_id in job_ids if job_id in pending]
        remaining = [job_id for job_id in pending if job_id not in provided]
        self._queue_order = running + provided + remaining
        self._persist_queue_positions()
        self._emit_queue_update_soon()
        self._queue_wakeup.set()
        return self.get_queue_state()

    async def create_project(self, name: str) -> dict[str, Any]:
        project_id = str(uuid.uuid4())
        now = _utc_now()
        project = {
            "id": project_id,
            "name": name,
            "created_at": now,
            "updated_at": now,
            "cover_asset_id": None,
            "state": _default_project_state(),
        }
        self.projects[project_id] = project
        self._upsert_project(project)
        return project

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        project = self.projects.get(project_id)
        if not project:
            with open_db() as connection:
                cursor = connection.execute(
                    "SELECT id, name, created_at, updated_at, cover_asset_id, state_json FROM projects WHERE id = ?",
                    (project_id,),
                )
                row = cursor.fetchone()
            if not row:
                return None
            project = {
                "id": row[0],
                "name": row[1],
                "created_at": row[2],
                "updated_at": row[3],
                "cover_asset_id": row[4],
                "state": self._normalize_project_state(_safe_load_json(row[5], _default_project_state())),
            }
            self.projects[project_id] = project

        with open_db() as connection:
            cursor = connection.execute(
                "SELECT id, path, kind, width, height, meta_json, created_at FROM assets WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            )
            project["assets"] = [
                {
                    "id": row[0],
                    "path": row[1],
                    "kind": row[2],
                    "width": row[3],
                    "height": row[4],
                    "meta_json": _safe_load_json(row[5], {}),
                    "created_at": row[6],
                }
                for row in cursor.fetchall()
            ]
            cursor = connection.execute(
                "SELECT id, parent_generation_id, model_id, mode, prompt, params_json, output_asset_id, created_at FROM generations WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            )
            project["generations"] = [
                {
                    "id": row[0],
                    "parent_generation_id": row[1],
                    "model_id": row[2],
                    "mode": row[3],
                    "prompt": row[4],
                    "params_json": _safe_load_json(row[5], {}),
                    "output_asset_id": row[6],
                    "created_at": row[7],
                }
                for row in cursor.fetchall()
            ]
        return project

    def update_project_state(self, project_id: str, state: dict[str, Any]) -> dict[str, Any]:
        project = self.projects.get(project_id)
        if not project:
            project = self.get_project(project_id)
        if not project:
            raise KeyError(project_id)
        project["state"] = self._normalize_project_state(state)
        project["updated_at"] = _utc_now()
        self._upsert_project(project)
        return self.get_project(project_id) or project

    @staticmethod
    def _normalize_export_format(raw_value: Any) -> tuple[str, str]:
        normalized = str(raw_value or "png").strip().lower()
        if normalized == "jpg":
            normalized = "jpeg"
        pil_format = _SUPPORTED_EXPORT_FORMATS.get(normalized)
        if pil_format is None:
            supported = ", ".join(sorted(_SUPPORTED_EXPORT_FORMATS.keys()))
            raise ValueError(f"Unsupported export format '{normalized}'. Supported formats: {supported}.")
        return normalized, pil_format

    @staticmethod
    def _resolve_export_source(
        connection: Any,
        project_id: str,
        selected_generation_id: str | None,
    ) -> dict[str, Any]:
        if selected_generation_id:
            cursor = connection.execute(
                """
                SELECT
                    a.id,
                    a.path,
                    a.width,
                    a.height,
                    g.id,
                    g.parent_generation_id,
                    g.model_id,
                    g.mode,
                    g.prompt,
                    g.params_json
                FROM generations g
                JOIN assets a ON a.id = g.output_asset_id
                WHERE g.project_id = ? AND g.id = ?
                LIMIT 1
                """,
                (project_id, selected_generation_id),
            )
            row = cursor.fetchone()
            if row:
                return {
                    "asset_id": row[0],
                    "asset_path": row[1],
                    "asset_width": int(row[2]),
                    "asset_height": int(row[3]),
                    "generation": {
                        "id": row[4],
                        "parent_generation_id": row[5],
                        "model_id": row[6],
                        "mode": row[7],
                        "prompt": row[8],
                        "params_json": _safe_load_json(row[9], {}),
                    },
                }

        cursor = connection.execute(
            """
            SELECT
                a.id,
                a.path,
                a.width,
                a.height,
                g.id,
                g.parent_generation_id,
                g.model_id,
                g.mode,
                g.prompt,
                g.params_json
            FROM assets a
            LEFT JOIN generations g
                ON g.output_asset_id = a.id
               AND g.project_id = a.project_id
            WHERE a.project_id = ?
            ORDER BY a.created_at DESC
            LIMIT 1
            """,
            (project_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise ValueError("No assets to export.")

        generation_payload = None
        if row[4]:
            generation_payload = {
                "id": row[4],
                "parent_generation_id": row[5],
                "model_id": row[6],
                "mode": row[7],
                "prompt": row[8],
                "params_json": _safe_load_json(row[9], {}),
            }

        return {
            "asset_id": row[0],
            "asset_path": row[1],
            "asset_width": int(row[2]),
            "asset_height": int(row[3]),
            "generation": generation_payload,
        }

    @staticmethod
    def _to_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _render_flattened_export_image(
        source_image: Image.Image,
        project_state: dict[str, Any],
        asset_id: str,
    ) -> Image.Image:
        canvas_state = project_state.get("canvas", {}) if isinstance(project_state, dict) else {}
        assets_state = canvas_state.get("assets", {}) if isinstance(canvas_state, dict) else {}
        scene = assets_state.get(asset_id) if isinstance(assets_state, dict) else None
        if not isinstance(scene, dict):
            return source_image.convert("RGB")

        source_bounds = scene.get("source_bounds")
        viewport = scene.get("viewport")
        source_size = scene.get("source_size")
        if not isinstance(source_bounds, dict) or not isinstance(viewport, dict) or not isinstance(source_size, dict):
            return source_image.convert("RGB")

        source_width = max(1.0, AppState._to_float(source_size.get("width"), float(source_image.width)))
        source_height = max(1.0, AppState._to_float(source_size.get("height"), float(source_image.height)))
        bounds_x = AppState._to_float(source_bounds.get("x"), 0.0)
        bounds_y = AppState._to_float(source_bounds.get("y"), 0.0)
        bounds_w = max(1.0, AppState._to_float(source_bounds.get("width"), float(source_image.width)))
        bounds_h = max(1.0, AppState._to_float(source_bounds.get("height"), float(source_image.height)))
        zoom = max(0.05, AppState._to_float(viewport.get("zoom"), 1.0))
        pan_x = AppState._to_float(viewport.get("pan_x"), 0.0)
        pan_y = AppState._to_float(viewport.get("pan_y"), 0.0)

        screen_x = bounds_x * zoom + pan_x
        screen_y = bounds_y * zoom + pan_y
        screen_w = max(1.0, bounds_w * zoom)
        screen_h = max(1.0, bounds_h * zoom)

        canvas = Image.new("RGBA", (_CANVAS_EXPORT_WIDTH, _CANVAS_EXPORT_HEIGHT), color=(0, 0, 0, 255))
        resized = source_image.convert("RGBA").resize(
            (int(round(screen_w)), int(round(screen_h))),
            Image.Resampling.LANCZOS,
        )
        canvas.paste(resized, (int(round(screen_x)), int(round(screen_y))), resized)

        draw = ImageDraw.Draw(canvas, "RGBA")
        strokes = scene.get("mask_strokes", [])
        if isinstance(strokes, list):
            color_by_tool = {
                "mask": (255, 64, 64, 150),
                "brush": (255, 255, 255, 170),
                "erase": (0, 0, 0, 200),
            }
            for stroke in strokes:
                if not isinstance(stroke, dict):
                    continue
                points = stroke.get("points", [])
                if not isinstance(points, list) or not points:
                    continue
                stroke_size = max(1.0, AppState._to_float(stroke.get("size"), 12.0))
                line_width = max(1, int(round((stroke_size / source_width) * bounds_w * zoom)))
                color = color_by_tool.get(str(stroke.get("tool", "mask")), color_by_tool["mask"])

                transformed_points: list[tuple[float, float]] = []
                for point in points:
                    if not isinstance(point, dict):
                        continue
                    point_x = AppState._to_float(point.get("x"), 0.0)
                    point_y = AppState._to_float(point.get("y"), 0.0)
                    world_x = bounds_x + ((point_x / source_width) * bounds_w)
                    world_y = bounds_y + ((point_y / source_height) * bounds_h)
                    transformed_points.append((world_x * zoom + pan_x, world_y * zoom + pan_y))

                if not transformed_points:
                    continue
                if len(transformed_points) == 1:
                    px, py = transformed_points[0]
                    radius = max(1, line_width // 2)
                    draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=color)
                    continue
                draw.line(transformed_points, fill=color, width=line_width)

        return canvas.convert("RGB")

    @staticmethod
    def _build_export_metadata(
        project_id: str,
        export_source: dict[str, Any],
        *,
        include_metadata: bool,
        flattened: bool,
        format_name: str,
    ) -> dict[str, Any] | None:
        if not include_metadata:
            return None
        generation = export_source.get("generation")
        metadata: dict[str, Any] = {
            "project_id": project_id,
            "asset_id": export_source.get("asset_id"),
            "format": format_name,
            "composition_mode": "flattened" if flattened else "selected_layer",
        }
        if isinstance(generation, dict):
            metadata["generation_id"] = generation.get("id")
            metadata["parent_generation_id"] = generation.get("parent_generation_id")
            metadata["mode"] = generation.get("mode")
            metadata["model_id"] = generation.get("model_id")
            metadata["model"] = generation.get("model_id")
            metadata["prompt"] = generation.get("prompt")
            metadata["params"] = generation.get("params_json", {})
        return metadata

    @staticmethod
    def _save_export_image(
        image: Image.Image,
        export_path: Path,
        *,
        pil_format: str,
        metadata: dict[str, Any] | None,
    ) -> None:
        export_path.parent.mkdir(parents=True, exist_ok=True)
        if pil_format == "PNG":
            if metadata:
                pnginfo = PngImagePlugin.PngInfo()
                for key, value in metadata.items():
                    if value is None:
                        continue
                    if isinstance(value, (dict, list)):
                        serialized = json.dumps(value, sort_keys=True)
                    else:
                        serialized = str(value)
                    pnginfo.add_text(str(key), serialized)
                image.save(export_path, format="PNG", pnginfo=pnginfo)
                return
            image.save(export_path, format="PNG")
            return

        save_kwargs: dict[str, Any] = {}
        if pil_format in {"JPEG", "WEBP"}:
            save_kwargs["quality"] = 95

        if metadata:
            exif = Image.Exif()
            exif[0x010E] = json.dumps(metadata, sort_keys=True)
            save_kwargs["exif"] = exif.tobytes()

        image.save(export_path, format=pil_format, **save_kwargs)

    def export_project(self, project_id: str, export_request: dict[str, Any]) -> dict[str, Any]:
        project = self.projects.get(project_id) or self.get_project(project_id)
        if not project:
            raise KeyError(f"Project {project_id} not found")

        settings = get_settings()
        export_format, pil_format = self._normalize_export_format(export_request.get("format", "png"))
        include_metadata = bool(export_request.get("include_metadata", True))
        flattened = bool(export_request.get("flattened", True))
        project_state = self._normalize_project_state(project.get("state", _default_project_state()))
        selected_generation_id = self._normalized_optional_text(project_state["timeline"].get("selected_generation_id"))

        safe_name = "".join(c for c in project["name"] if c.isalnum() or c in (" ", "-", "_")).strip() or "export"
        with open_db() as connection:
            export_source = self._resolve_export_source(connection, project_id, selected_generation_id)
            asset_id = str(export_source["asset_id"])
            asset_path = Path(str(export_source["asset_path"]))
            if not asset_path.exists() or not asset_path.is_file():
                raise ValueError(f"Export source asset file is missing: {asset_path}")

            with Image.open(asset_path) as source_file:
                source_image = source_file.convert("RGB")
            image = (
                self._render_flattened_export_image(source_image, project_state, asset_id)
                if flattened
                else source_image
            )

            metadata = self._build_export_metadata(
                project_id,
                export_source,
                include_metadata=include_metadata,
                flattened=flattened,
                format_name=export_format,
            )
            export_dir = settings.projects_dir / project_id / "exports"
            export_dir.mkdir(parents=True, exist_ok=True)
            export_path = export_dir / f"{safe_name}.{export_format}"
            self._save_export_image(image, export_path, pil_format=pil_format, metadata=metadata)

        return {
            "project_id": project_id,
            "status": "ok",
            "export": {
                "format": export_format,
                "include_metadata": include_metadata,
                "flattened": flattened,
                "selected_generation_id": selected_generation_id,
            },
            "path": str(export_path),
        }

    async def _processor_loop(self) -> None:
        while True:
            await self._queue_wakeup.wait()
            self._queue_wakeup.clear()

            while not self._queue_paused:
                job_id = self._next_pending_job_id()
                if not job_id:
                    break
                await self._run_job(job_id)

    def _next_pending_job_id(self) -> str | None:
        if self._running_job_id:
            return None
        pending_ids = [
            job_id
            for job_id in self._queue_order
            if self.jobs.get(job_id, {}).get("status") in _PENDING_JOB_STATUSES
        ]
        if not pending_ids:
            self._interactive_burst_count = 0
            return None

        head_job = self.jobs.get(pending_ids[0])
        if not head_job:
            return pending_ids[0]

        if self._job_is_long_running(head_job):
            interactive_candidate = next(
                (
                    candidate_id
                    for candidate_id in pending_ids[1:]
                    if self._job_is_interactive(self.jobs.get(candidate_id, {}))
                ),
                None,
            )
            if interactive_candidate and self._interactive_burst_count < self._max_interactive_burst:
                self._interactive_burst_count += 1
                return interactive_candidate
            self._interactive_burst_count = 0
            return pending_ids[0]

        self._interactive_burst_count = 0
        return pending_ids[0]

    async def _run_job(self, job_id: str) -> None:
        job = self.jobs.get(job_id)
        if not job:
            return

        if job["status"] == "cancelled":
            self._queue_order = [queued_job_id for queued_job_id in self._queue_order if queued_job_id != job_id]
            self._persist_queue_positions()
            return

        self._running_job_id = job_id
        self._transition_job_status(
            job,
            "running",
            error=None,
            progress=max(job.get("progress", 0.0), 0.05),
            eta_seconds=10,
        )
        await self.broadcast("job_update", job.copy())
        await self.broadcast("queue_update", self.get_queue_state())

        try:
            await self._execute_generation(job_id)
        except JobCancellationRequested:
            current = self.jobs.get(job_id)
            if current and current["status"] not in _TERMINAL_JOB_STATUSES:
                self._transition_job_status(current, "cancelled", error=None, eta_seconds=0)
                await self.broadcast("job_update", current.copy())
        except Exception as error:
            current = self.jobs.get(job_id)
            if current and current["status"] not in _TERMINAL_JOB_STATUSES:
                self._transition_job_status(current, "failed", error=str(error), eta_seconds=0)
                await self.broadcast("job_update", current.copy())
        finally:
            self._running_job_id = None
            self._queue_order = [
                queued_job_id
                for queued_job_id in self._queue_order
                if queued_job_id in self.jobs
                and self.jobs[queued_job_id]["status"] in (_PENDING_JOB_STATUSES | _RUNNING_JOB_STATUSES)
            ]
            self._persist_queue_positions()
            await self.broadcast("queue_update", self.get_queue_state())
            self._queue_wakeup.set()

    async def _execute_generation(self, job_id: str) -> None:
        job = self.jobs.get(job_id)
        if not job:
            return
        if job["status"] in {"cancelled", "cancel_requested"}:
            raise JobCancellationRequested()
        if job["status"] != "running":
            return

        payload = job["payload"]
        params = payload.get("params", {}) if isinstance(payload.get("params"), dict) else {}
        prompt = payload.get("prompt", "")
        negative_prompt = payload.get("negative_prompt", "")
        project_id = payload.get("project_id")
        mode = job["kind"]

        width = int(params.get("width", 1024))
        height = int(params.get("height", 1024))
        steps = int(params.get("steps", 25))
        guidance_scale = float(params.get("guidance_scale", 7.0))
        resolved_seed, seed_locked, requested_seed = self._resolve_seed(params.get("seed"))
        params["resolved_seed"] = resolved_seed
        params["seed_mode"] = "locked" if seed_locked else "randomized"
        payload["params"] = params

        settings = get_settings()
        requested_profile = normalize_hardware_profile(self._get_runtime_setting("hardware_profile", "balanced"))
        engine = get_engine(settings.models_dir, hardware_profile=requested_profile)
        queued_model_id = self._normalized_optional_text(payload.get("model_id")) or self.active_model_id
        if not queued_model_id:
            raise RuntimeError("Queued job is missing its pinned model.")
        model = self.models.get(queued_model_id)
        if model is None:
            raise RuntimeError(f"Queued model '{queued_model_id}' is not installed.")
        validation = self._revalidate_model_install(model)
        if not validation["is_valid"]:
            raise RuntimeError(
                f"Queued model '{model.get('name', queued_model_id)}' is incomplete: {validation['reason']}"
            )
        self._ensure_active_model_supports_mode(model, mode)
        engine.set_active_model(model.get("id"))
        use_real_generation = (
            DIFFUSERS_AVAILABLE
            and model is not None
            and not settings.e2e_mode
            and str(model.get("source", "")).lower() not in {"test", "mock"}
        )

        loop = asyncio.get_running_loop()

        def progress_callback(raw_progress: float) -> None:
            current = self.jobs.get(job_id)
            if not current:
                return
            if current["status"] in {"cancelled", "cancel_requested"}:
                raise JobCancellationRequested()
            if current["status"] != "running":
                return
            bounded = min(1.0, max(0.0, raw_progress))
            normalized_progress = round(0.1 + (bounded * 0.8), 4)
            predicted_eta = max(1, int((1.0 - bounded) * 10))
            eta_confidence = _estimate_eta_confidence(mode, bounded)
            current["progress"] = normalized_progress
            current["eta_seconds"] = predicted_eta
            current["eta_confidence"] = eta_confidence
            self._apply_progress_eta_contract(
                current,
                raw_eta_seconds=predicted_eta,
                eta_confidence=eta_confidence,
            )
            current["updated_at"] = _utc_now()
            self._upsert_job(current)
            loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self.broadcast("job_update", current.copy()))
            )

        current = self.jobs.get(job_id)
        if current is not None:
            current["resolved_seed"] = resolved_seed
            current["requested_seed"] = requested_seed
            current["seed_locked"] = seed_locked
            current["runtime_profile_requested"] = requested_profile
            current["runtime_profile_effective"] = requested_profile
            current["runtime_policy"] = describe_runtime_policy(requested_profile)
            current["warnings"] = []
            current["model_id_queued"] = queued_model_id
            current["execution_mode"] = "real" if use_real_generation else "simulated"
            self._upsert_job(current)

        images: list[Image.Image]
        generation_warnings: list[str] = []
        effective_profile = requested_profile
        runtime_policy = describe_runtime_policy(requested_profile)
        pipeline_mode = mode
        if use_real_generation and model:
            generation_result = await self._run_real_generation(
                mode=mode,
                engine=engine,
                model=model,
                prompt=prompt,
                negative_prompt=negative_prompt,
                width=width,
                height=height,
                steps=steps,
                guidance_scale=guidance_scale,
                seed=resolved_seed,
                params=params,
                payload=payload,
                progress_callback=progress_callback,
            )
            images = generation_result["images"]
            generation_warnings = list(generation_result["warnings"])
            effective_profile = str(generation_result["effective_profile"])
            runtime_policy = dict(generation_result["runtime_policy"])
            pipeline_mode = str(generation_result["pipeline_mode"])
        else:
            simulated_steps = max(6, min(max(steps, 1), 30))
            for index in range(simulated_steps):
                current = self.jobs.get(job_id)
                if not current or current["status"] in {"cancelled", "cancel_requested"}:
                    raise JobCancellationRequested()
                await asyncio.sleep(0.05)
                progress_callback((index + 1) / simulated_steps)
            images = self._run_simulated_generation(
                mode=mode,
                prompt=prompt,
                width=width,
                height=height,
                seed=resolved_seed,
                params=params,
                payload=payload,
                engine=engine,
            )

        current = self.jobs.get(job_id)
        if not current:
            return
        if current["status"] in {"cancelled", "cancel_requested"}:
            raise JobCancellationRequested()
        if current["status"] != "running":
            return

        current["warnings"] = generation_warnings
        current["runtime_profile_effective"] = effective_profile
        current["runtime_policy"] = runtime_policy
        current["pipeline_mode"] = pipeline_mode
        model_id_used = model["id"] if use_real_generation else "simulation"
        current["model_id_used"] = model_id_used
        self._upsert_job(current)

        self._transition_job_status(current, "running", progress=0.95, eta_seconds=1)
        await self.broadcast("job_update", current.copy())

        output_asset_ids: list[str] = []
        if project_id:
            for index, image in enumerate(images):
                asset = self._create_output_asset(
                    job_id=job_id,
                    project_id=project_id,
                    kind=mode,
                    width=image.width,
                    height=image.height,
                    index=index,
                )
                metadata = {
                    "prompt": prompt,
                    "negative_prompt": negative_prompt,
                    "mode": mode,
                    "pipeline_mode": pipeline_mode,
                    "model_id": model_id_used,
                    "model_id_queued": queued_model_id,
                    "steps": steps,
                    "guidance_scale": guidance_scale,
                    "seed": resolved_seed,
                    "seed_mode": "locked" if seed_locked else "randomized",
                    "runtime_profile_requested": requested_profile,
                    "runtime_profile_effective": effective_profile,
                    "runtime_policy": json.dumps(runtime_policy),
                    "warnings": json.dumps(generation_warnings),
                    "params": json.dumps(params),
                }
                engine.save_image(image, Path(asset["path"]), format="PNG", metadata=metadata)
                output_asset_ids.append(asset["id"])
                self._create_generation_record(current, asset["id"], model_id_used=model_id_used)

            if output_asset_ids:
                self._update_project_cover(project_id, output_asset_ids[0])

        if current["status"] in {"cancelled", "cancel_requested"}:
            raise JobCancellationRequested()

        if output_asset_ids:
            current["output_asset_id"] = output_asset_ids[0]
            current["output_asset_ids"] = output_asset_ids

        self._transition_job_status(current, "completed", progress=1.0, eta_seconds=0, error=None)
        await self.broadcast("job_update", current.copy())

    async def _run_real_generation(
        self,
        mode: str,
        engine: Any,
        model: dict[str, Any],
        prompt: str,
        negative_prompt: str,
        width: int,
        height: int,
        steps: int,
        guidance_scale: float,
        seed: int | None,
        params: dict[str, Any],
        payload: dict[str, Any],
        progress_callback: Any,
    ) -> dict[str, Any]:
        model_id = model["id"]
        model_type = model["type"]
        if mode == "generate":
            num_images = int(params.get("num_images", 1))
            result = await engine.generate(
                model_id=model_id,
                model_type=model_type,
                prompt=prompt,
                negative_prompt=negative_prompt,
                width=width,
                height=height,
                steps=steps,
                guidance_scale=guidance_scale,
                seed=seed,
                num_images=max(1, min(num_images, 4)),
                progress_callback=progress_callback,
            )
            return {
                "images": result.images,
                "effective_profile": result.effective_profile,
                "runtime_policy": result.runtime_policy,
                "warnings": list(result.warnings),
                "pipeline_mode": result.pipeline_mode,
            }

        source = self._resolve_input_image(payload, params, width, height)
        strength = float(params.get("denoise_strength", 0.75))
        if mode == "img2img":
            result = await engine.img2img(
                model_id=model_id,
                model_type=model_type,
                image=source,
                prompt=prompt,
                negative_prompt=negative_prompt,
                strength=strength,
                steps=steps,
                guidance_scale=guidance_scale,
                seed=seed,
                progress_callback=progress_callback,
            )
            return {
                "images": result.images,
                "effective_profile": result.effective_profile,
                "runtime_policy": result.runtime_policy,
                "warnings": list(result.warnings),
                "pipeline_mode": result.pipeline_mode,
            }

        if mode == "inpaint":
            mask = self._resolve_mask_image(payload, params, source.size)
            result = await engine.inpaint(
                model_id=model_id,
                model_type=model_type,
                image=source,
                mask_image=mask,
                prompt=prompt,
                negative_prompt=negative_prompt,
                strength=strength,
                steps=steps,
                guidance_scale=guidance_scale,
                seed=seed,
                progress_callback=progress_callback,
            )
            return {
                "images": result.images,
                "effective_profile": result.effective_profile,
                "runtime_policy": result.runtime_policy,
                "warnings": list(result.warnings),
                "pipeline_mode": result.pipeline_mode,
            }

        if mode == "outpaint":
            result = await engine.outpaint(
                model_id=model_id,
                model_type=model_type,
                image=source,
                prompt=prompt,
                negative_prompt=negative_prompt,
                padding=int(params.get("outpaint_padding", 128)),
                strength=float(params.get("denoise_strength", 0.85)),
                steps=steps,
                guidance_scale=guidance_scale,
                seed=seed,
                progress_callback=progress_callback,
            )
            return {
                "images": result.images,
                "effective_profile": result.effective_profile,
                "runtime_policy": result.runtime_policy,
                "warnings": list(result.warnings),
                "pipeline_mode": result.pipeline_mode,
            }

        if mode == "upscale":
            result = await engine.upscale(
                model_id=model_id,
                model_type=model_type,
                image=source,
                prompt=prompt,
                negative_prompt=negative_prompt,
                steps=steps,
                guidance_scale=guidance_scale,
                factor=float(params.get("upscale_factor", 2.0)),
                seed=seed,
                progress_callback=progress_callback,
            )
            return {
                "images": result.images,
                "effective_profile": result.effective_profile,
                "runtime_policy": result.runtime_policy,
                "warnings": list(result.warnings),
                "pipeline_mode": result.pipeline_mode,
            }

        raise RuntimeError(f"Unsupported job kind '{mode}'")

    def _run_simulated_generation(
        self,
        *,
        mode: str,
        prompt: str,
        width: int,
        height: int,
        seed: int,
        params: dict[str, Any],
        payload: dict[str, Any],
        engine: Any,
    ) -> list[Image.Image]:
        if mode == "generate":
            num_images = max(1, min(int(params.get("num_images", 1)), 4))
            return [
                self._create_simulated_image(prompt=prompt, width=width, height=height, seed=seed + offset)
                for offset in range(num_images)
            ]

        source = self._resolve_input_image(payload, params, width, height)
        target_size = (max(64, width), max(64, height))
        source = source.resize(target_size).convert("RGB")

        if mode == "img2img":
            generated = self._create_simulated_image(prompt=prompt, width=source.width, height=source.height, seed=seed)
            strength = max(0.05, min(float(params.get("denoise_strength", 0.75)), 0.95))
            return [Image.blend(source, generated, alpha=strength)]

        if mode == "inpaint":
            mask = self._resolve_mask_image(payload, params, source.size).convert("L")
            generated = self._create_simulated_image(prompt=prompt, width=source.width, height=source.height, seed=seed)
            return [Image.composite(generated, source, mask)]

        if mode == "outpaint":
            padding = int(params.get("outpaint_padding", 128))
            padded_image, mask = engine._create_outpaint_canvas(source, padding)
            generated = self._create_simulated_image(
                prompt=prompt,
                width=padded_image.width,
                height=padded_image.height,
                seed=seed,
            )
            return [Image.composite(generated, padded_image, mask)]

        if mode == "upscale":
            factor = max(1.01, float(params.get("upscale_factor", 2.0)))
            return [
                source.resize(
                    (
                        max(64, int(source.width * factor)),
                        max(64, int(source.height * factor)),
                    ),
                    Image.Resampling.LANCZOS,
                )
            ]

        raise RuntimeError(f"Unsupported job kind '{mode}'")

    @staticmethod
    def _create_simulated_image(prompt: str, width: int, height: int, seed: int | None) -> Image.Image:
        width = max(256, min(width, 2048))
        height = max(256, min(height, 2048))
        base_seed = seed if seed is not None else _stable_prompt_seed(prompt)
        base = abs(int(base_seed)) % 255
        color_a = ((base * 37) % 255, (base * 67) % 255, (base * 97) % 255)
        color_b = ((base * 13) % 255, (base * 29) % 255, (base * 43) % 255)
        image = Image.new("RGB", (width, height), color=color_a)
        draw = ImageDraw.Draw(image)
        for offset in range(0, width + height, 30):
            draw.line([(offset, 0), (0, offset)], fill=color_b, width=2)
        text = (prompt or "Vivid simulated output")[:120]
        draw.rectangle([(20, height - 120), (width - 20, height - 20)], fill=(0, 0, 0))
        draw.text((30, height - 100), text, fill=(255, 255, 255))
        return image

    def _resolve_input_image(self, payload: dict[str, Any], params: dict[str, Any], width: int, height: int) -> Image.Image:
        candidates = [
            params.get("init_image_path"),
            payload.get("init_image_path"),
            self._resolve_asset_path(params.get("init_image_asset_id"), payload.get("project_id")),
            self._resolve_asset_path(params.get("source_asset_id"), payload.get("project_id")),
            self._resolve_asset_path(payload.get("source_asset_id"), payload.get("project_id")),
        ]
        for candidate in candidates:
            if candidate and Path(candidate).exists():
                return Image.open(candidate).convert("RGB")
        raise FileNotFoundError("Input image reference did not resolve to an existing file.")

    def _resolve_mask_image(self, payload: dict[str, Any], params: dict[str, Any], size: tuple[int, int]) -> Image.Image:
        mask_data = params.get("mask_data") or payload.get("mask_data")
        if isinstance(mask_data, str):
            decoded = self._decode_data_url(mask_data)
            if decoded is not None:
                return decoded.convert("L").resize(size)

        candidates = [
            params.get("mask_image_path"),
            payload.get("mask_image_path"),
            self._resolve_asset_path(params.get("mask_image_asset_id"), payload.get("project_id")),
            self._resolve_asset_path(payload.get("mask_asset_id"), payload.get("project_id")),
        ]
        for candidate in candidates:
            if candidate and Path(candidate).exists():
                return Image.open(candidate).convert("L").resize(size)

        raise FileNotFoundError("Mask input did not resolve to valid image data.")

    @staticmethod
    def _decode_data_url(data_url: str) -> Image.Image | None:
        if not data_url.startswith("data:image/"):
            return None
        _, _, encoded = data_url.partition(",")
        if not encoded:
            return None
        try:
            binary = base64.b64decode(encoded)
            return Image.open(io.BytesIO(binary))
        except Exception:
            return None

    @staticmethod
    def _resolve_asset_path(asset_id: Any, project_id: Any) -> str | None:
        if not asset_id or not project_id:
            return None
        with open_db() as connection:
            cursor = connection.execute(
                "SELECT path FROM assets WHERE id = ? AND project_id = ?",
                (str(asset_id), str(project_id)),
            )
            row = cursor.fetchone()
        if row:
            return row[0]
        return None

    def _update_project_cover(self, project_id: str, cover_asset_id: str) -> None:
        project = self.projects.get(project_id)
        now = _utc_now()
        if project:
            project["cover_asset_id"] = cover_asset_id
            project["updated_at"] = now
            self._upsert_project(project)
            return
        with open_db() as connection:
            execute_with_retry(
                connection,
                "UPDATE projects SET cover_asset_id = ?, updated_at = ? WHERE id = ?",
                (cover_asset_id, now, project_id),
            )

    def _transition_job_status(
        self,
        job: dict[str, Any],
        new_status: str,
        *,
        error: str | None | object = ...,
        progress: float | None = None,
        eta_seconds: int | None = None,
    ) -> None:
        current_status = str(job.get("status", "queued"))
        if current_status != new_status:
            allowed_next = _ALLOWED_JOB_TRANSITIONS.get(current_status, set())
            if new_status not in allowed_next:
                raise RuntimeError(f"Invalid job status transition '{current_status}' -> '{new_status}'")
            job["status"] = new_status

        if progress is not None:
            job["progress"] = float(progress)
        if eta_seconds is not None:
            job["eta_seconds"] = int(eta_seconds) if eta_seconds > 0 else None
        if error is not ...:
            job["error"] = error

        self._apply_progress_eta_contract(job, raw_eta_seconds=job.get("eta_seconds"))
        job["updated_at"] = _utc_now()
        self._upsert_job(job)

    def _apply_progress_eta_contract(
        self,
        job: dict[str, Any],
        *,
        raw_eta_seconds: int | None = None,
        eta_confidence: str | None = None,
    ) -> None:
        status = str(job.get("status", "")).lower()
        progress = float(job.get("progress", 0.0))
        progress = max(0.0, min(1.0, progress))
        job["progress"] = progress

        if status in _PENDING_JOB_STATUSES:
            job["progress_state"] = "queued"
            job["eta_confidence"] = "low"
            job["eta_seconds"] = None
            return

        if status == "cancel_requested":
            job["progress_state"] = "cancelling"
            job["eta_confidence"] = "low"
            job["eta_seconds"] = None
            return

        if status == "running":
            confidence = (eta_confidence or str(job.get("eta_confidence", "low"))).lower()
            if confidence not in _ETA_CONFIDENCE_VALUES:
                confidence = "low"
            job["progress_state"] = "finalizing" if progress >= 0.9 else "running"
            job["eta_confidence"] = confidence
            normalized_eta = raw_eta_seconds
            if normalized_eta is None:
                job_eta = job.get("eta_seconds")
                normalized_eta = int(job_eta) if isinstance(job_eta, (int, float)) and job_eta > 0 else None
            job["eta_seconds"] = int(normalized_eta) if confidence == "high" and normalized_eta and normalized_eta > 0 else None
            return

        # Terminal statuses
        if status == "completed":
            job["progress"] = 1.0
        job["progress_state"] = "terminal"
        job["eta_confidence"] = "none"
        job["eta_seconds"] = None

    @staticmethod
    def _job_is_interactive(job: dict[str, Any]) -> bool:
        kind = str(job.get("kind", "generate"))
        payload = job.get("payload", {})
        params = payload.get("params", {}) if isinstance(payload, dict) else {}
        if not isinstance(params, dict):
            params = {}

        if kind in {"inpaint", "outpaint", "upscale"}:
            return True

        steps = int(params.get("steps", 25))
        num_images = int(params.get("num_images", 1))
        width = int(params.get("width", 1024))
        height = int(params.get("height", 1024))
        pixel_count = max(1, width * height)

        return num_images <= 1 and steps <= 32 and pixel_count <= 1024 * 1024

    @staticmethod
    def _job_is_long_running(job: dict[str, Any]) -> bool:
        kind = str(job.get("kind", "generate"))
        payload = job.get("payload", {})
        params = payload.get("params", {}) if isinstance(payload, dict) else {}
        if not isinstance(params, dict):
            params = {}

        steps = int(params.get("steps", 25))
        num_images = int(params.get("num_images", 1))
        width = int(params.get("width", 1024))
        height = int(params.get("height", 1024))
        pixel_count = max(1, width * height)

        if kind == "upscale":
            return True
        if num_images > 1:
            return True
        if steps > 38:
            return True
        return pixel_count > 1024 * 1024

    def _serialize_model(self, model: dict[str, Any], hardware_profile: str | None = None) -> dict[str, Any]:
        normalized = self._normalize_model_record(model)
        target_profile = normalize_hardware_profile(hardware_profile or self._get_runtime_setting("hardware_profile", "balanced"))
        compatibility = self._evaluate_model_compatibility(normalized, target_profile)

        serialized = normalized.copy()
        serialized["compatibility"] = compatibility
        serialized["supported_modes"] = list(get_supported_modes(normalized.get("family") or normalized.get("type")))
        serialized["runtime_policy"] = describe_runtime_policy(target_profile)
        return serialized

    def _evaluate_model_compatibility(self, model: dict[str, Any], hardware_profile: str | None = None) -> dict[str, Any]:
        normalized_profile = normalize_hardware_profile(hardware_profile or "balanced")

        model_type = str(model.get("family") or model.get("type", "")).lower()
        required_profile = _MODEL_MINIMUM_PROFILE.get(model_type, "balanced")
        supported = _PROFILE_ORDER[normalized_profile] >= _PROFILE_ORDER[required_profile]
        if supported:
            return {
                "supported": True,
                "reason": None,
                "required_profile": required_profile,
            }

        return {
            "supported": False,
            "reason": f"{(model_type or 'unknown').upper()} models require at least the '{required_profile}' hardware profile.",
            "required_profile": required_profile,
        }

    def _select_compatible_model(self, hardware_profile: str) -> dict[str, Any] | None:
        compatible = [
            model for model in self.models.values() if self._evaluate_model_compatibility(model, hardware_profile)["supported"]
        ]
        if not compatible:
            return None
        return sorted(compatible, key=lambda item: item["name"].lower())[0]

    def _get_runtime_setting(self, key: str, default: Any) -> Any:
        with open_db() as connection:
            cursor = connection.execute("SELECT value_json FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
        if not row:
            return default
        return _safe_load_json(row[0], default)

    def _create_output_asset(
        self,
        job_id: str,
        project_id: str,
        kind: str,
        width: int,
        height: int,
        index: int = 0,
    ) -> dict[str, Any]:
        asset_id = str(uuid.uuid4())
        now = _utc_now()
        settings = get_settings()
        output_dir = settings.projects_dir / project_id / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        suffix = f"_{index}" if index > 0 else ""
        asset_path = output_dir / f"{asset_id}{suffix}.png"
        asset = {
            "id": asset_id,
            "project_id": project_id,
            "path": str(asset_path),
            "kind": kind,
            "width": width,
            "height": height,
            "meta_json": {"job_id": job_id, "index": index},
            "created_at": now,
        }
        with open_db() as connection:
            execute_with_retry(
                connection,
                """
                INSERT INTO assets (id, project_id, path, kind, width, height, meta_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset["id"],
                    asset["project_id"],
                    asset["path"],
                    asset["kind"],
                    asset["width"],
                    asset["height"],
                    json.dumps(asset["meta_json"]),
                    asset["created_at"],
                ),
            )
        return asset

    def _create_generation_record(
        self,
        job: dict[str, Any],
        output_asset_id: str,
        *,
        model_id_used: str,
    ) -> None:
        payload = job["payload"]
        generation_id = str(uuid.uuid4())
        with open_db() as connection:
            execute_with_retry(
                connection,
                """
                INSERT INTO generations (id, project_id, parent_generation_id, model_id, mode, prompt, params_json, output_asset_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    generation_id,
                    payload.get("project_id"),
                    payload.get("parent_generation_id"),
                    model_id_used,
                    job["kind"],
                    payload.get("prompt", ""),
                    json.dumps(payload.get("params", {})),
                    output_asset_id,
                    _utc_now(),
                ),
            )

    @staticmethod
    def _upsert_model(model: dict[str, Any]) -> None:
        normalized = AppState._normalize_model_record(model)
        with open_db() as connection:
            execute_with_retry(
                connection,
                """
                INSERT INTO models (
                    id,
                    source,
                    name,
                    type,
                    family,
                    precision,
                    revision,
                    local_path,
                    size_bytes,
                    last_used_at,
                    required_files_json,
                    last_validated_at,
                    is_valid,
                    invalid_reason,
                    favorite,
                    profile_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    source = excluded.source,
                    name = excluded.name,
                    type = excluded.type,
                    family = excluded.family,
                    precision = excluded.precision,
                    revision = excluded.revision,
                    local_path = excluded.local_path,
                    size_bytes = excluded.size_bytes,
                    last_used_at = excluded.last_used_at,
                    required_files_json = excluded.required_files_json,
                    last_validated_at = excluded.last_validated_at,
                    is_valid = excluded.is_valid,
                    invalid_reason = excluded.invalid_reason,
                    favorite = excluded.favorite,
                    profile_json = excluded.profile_json
                """,
                (
                    normalized["id"],
                    normalized["source"],
                    normalized["name"],
                    normalized["type"],
                    normalized["family"],
                    normalized["precision"],
                    normalized["revision"],
                    normalized["local_path"],
                    normalized["size_bytes"],
                    normalized["last_used_at"],
                    json.dumps(normalized["required_files"]),
                    normalized["last_validated_at"],
                    1 if normalized["is_valid"] else 0,
                    normalized["invalid_reason"],
                    1 if normalized["favorite"] else 0,
                    json.dumps(normalized["profile_json"]),
                ),
            )

    @staticmethod
    def _upsert_job(job: dict[str, Any]) -> None:
        with open_db() as connection:
            execute_with_retry(
                connection,
                """
                INSERT INTO jobs (id, kind, status, payload_json, progress, error, queue_position, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    kind = excluded.kind,
                    status = excluded.status,
                    payload_json = excluded.payload_json,
                    progress = excluded.progress,
                    error = excluded.error,
                    queue_position = excluded.queue_position,
                    updated_at = excluded.updated_at
                """,
                (
                    job["id"],
                    job["kind"],
                    job["status"],
                    json.dumps(job["payload"]),
                    float(job["progress"]),
                    job["error"],
                    int(job.get("queue_position", 0)),
                    job["created_at"],
                    job["updated_at"],
                ),
            )

    @staticmethod
    def _delete_jobs(job_ids: list[str]) -> None:
        if not job_ids:
            return
        placeholders = ",".join("?" for _ in job_ids)
        with open_db() as connection:
            execute_with_retry(connection, f"DELETE FROM jobs WHERE id IN ({placeholders})", tuple(job_ids))

    @staticmethod
    def _upsert_project(project: dict[str, Any]) -> None:
        with open_db() as connection:
            execute_with_retry(
                connection,
                """
                INSERT INTO projects (id, name, created_at, updated_at, cover_asset_id, state_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    updated_at = excluded.updated_at,
                    cover_asset_id = excluded.cover_asset_id,
                    state_json = excluded.state_json
                """,
                (
                    project["id"],
                    project["name"],
                    project["created_at"],
                    project["updated_at"],
                    project["cover_asset_id"],
                    json.dumps(AppState._normalize_project_state(project.get("state"))),
                ),
            )


app_state = AppState()
