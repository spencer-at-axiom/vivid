from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ModelInstallRequest(BaseModel):
    model_id: str | None = None
    direct_url: str | None = None
    display_name: str | None = None
    model_type: str = "sdxl"
    revision: str | None = None


class ModelActivateRequest(BaseModel):
    model_id: str


class ModelFavoriteRequest(BaseModel):
    model_id: str
    favorite: bool = True


class JobRequest(BaseModel):
    project_id: str | None = None
    prompt: str = ""
    negative_prompt: str = ""
    parent_generation_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class JobCancelRequest(BaseModel):
    job_id: str


class JobRetryRequest(BaseModel):
    job_id: str


class QueueClearRequest(BaseModel):
    include_terminal: bool = False


class QueueReorderRequest(BaseModel):
    job_ids: list[str]


class ProjectCreateRequest(BaseModel):
    name: str = "Untitled Project"


class ProjectExportRequest(BaseModel):
    format: str = "png"
    include_metadata: bool = True
    flattened: bool = True


class ProjectStateUpdateRequest(BaseModel):
    state: dict[str, Any] = Field(default_factory=dict)


class SettingsUpdateRequest(BaseModel):
    key: str
    value: Any


class PromptEnhanceRequest(BaseModel):
    prompt: str = ""
    style_id: str | None = None
    intent_id: str | None = None
