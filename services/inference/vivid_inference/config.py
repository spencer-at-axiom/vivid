from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

APP_NAME = "Vivid"
_DEFAULT_ALLOWED_ORIGINS = (
    "http://127.0.0.1:4173",
    "http://127.0.0.1:1420",
    "http://localhost:4173",
    "http://localhost:1420",
    "http://tauri.localhost",
    "https://tauri.localhost",
    "tauri://localhost",
)


@dataclass(frozen=True)
class Settings:
    data_root: Path
    api_host: str = "127.0.0.1"
    api_port: int = 8765
    e2e_mode: bool = False
    allowed_origins: tuple[str, ...] = _DEFAULT_ALLOWED_ORIGINS

    @property
    def models_dir(self) -> Path:
        return self.data_root / "models"

    @property
    def projects_dir(self) -> Path:
        return self.data_root / "projects"

    @property
    def thumbs_dir(self) -> Path:
        return self.data_root / "thumbs"

    @property
    def db_dir(self) -> Path:
        return self.data_root / "db"

    @property
    def logs_dir(self) -> Path:
        return self.data_root / "logs"

    @property
    def db_path(self) -> Path:
        return self.db_dir / "vivid.sqlite"


def _default_data_root() -> Path:
    system = platform.system().lower()
    if "windows" in system:
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / APP_NAME
    if "darwin" in system:
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME.lower()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    override = os.environ.get("VIVID_DATA_ROOT")
    data_root = Path(override).expanduser().resolve() if override else _default_data_root()
    e2e_mode = os.environ.get("VIVID_E2E_MODE", "").strip().lower() in {"1", "true", "yes"}
    raw_allowed_origins = os.environ.get("VIVID_ALLOWED_ORIGINS", "")
    if raw_allowed_origins.strip():
        allowed_origins = tuple(origin.strip() for origin in raw_allowed_origins.split(",") if origin.strip())
    else:
        allowed_origins = _DEFAULT_ALLOWED_ORIGINS

    settings = Settings(
        data_root=data_root,
        e2e_mode=e2e_mode,
        allowed_origins=allowed_origins or _DEFAULT_ALLOWED_ORIGINS,
    )

    for path in (
        settings.models_dir,
        settings.projects_dir,
        settings.thumbs_dir,
        settings.db_dir,
        settings.logs_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)

    return settings
