from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from typing import Callable, Iterator

from .config import Settings, get_settings

SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS models (
        id TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        family TEXT,
        precision TEXT,
        revision TEXT,
        local_path TEXT NOT NULL,
        size_bytes INTEGER NOT NULL,
        last_used_at TEXT,
        required_files_json TEXT NOT NULL DEFAULT '[]',
        last_validated_at TEXT,
        is_valid INTEGER NOT NULL DEFAULT 0,
        invalid_reason TEXT,
        favorite INTEGER NOT NULL DEFAULT 0,
        profile_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        cover_asset_id TEXT,
        state_json TEXT NOT NULL DEFAULT '{}'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS assets (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        path TEXT NOT NULL,
        kind TEXT NOT NULL,
        width INTEGER NOT NULL,
        height INTEGER NOT NULL,
        meta_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS generations (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        parent_generation_id TEXT,
        model_id TEXT NOT NULL,
        mode TEXT NOT NULL,
        prompt TEXT NOT NULL,
        params_json TEXT NOT NULL,
        output_asset_id TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        status TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        progress REAL NOT NULL,
        error TEXT,
        queue_position INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value_json TEXT NOT NULL
    )
    """,
)

WAL_AUTOCHECKPOINT_PAGES = 1000
DEFAULT_BUSY_TIMEOUT_MS = 5000
SQLITE_BUSY_TOKENS = ("database is locked", "database table is locked", "sqlite_busy")


def _configure_connection(connection: sqlite3.Connection) -> None:
    # Durability and concurrency defaults for queue-heavy local workloads.
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute(f"PRAGMA busy_timeout={DEFAULT_BUSY_TIMEOUT_MS}")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute(f"PRAGMA wal_autocheckpoint={WAL_AUTOCHECKPOINT_PAGES}")


def is_sqlite_busy_error(error: sqlite3.OperationalError) -> bool:
    message = str(error).lower()
    return any(token in message for token in SQLITE_BUSY_TOKENS)


def execute_with_retry(
    connection: sqlite3.Connection,
    statement: str,
    params: tuple[object, ...] | list[object] = (),
    *,
    retries: int = 8,
    initial_backoff_ms: int = 15,
    max_backoff_ms: int = 250,
    on_retry: Callable[[int, sqlite3.OperationalError], None] | None = None,
) -> sqlite3.Cursor:
    attempt = 0
    while True:
        try:
            return connection.execute(statement, params)
        except sqlite3.OperationalError as error:
            if not is_sqlite_busy_error(error) or attempt >= retries:
                raise
            if on_retry:
                on_retry(attempt + 1, error)
            backoff_ms = min(max_backoff_ms, initial_backoff_ms * (2**attempt))
            time.sleep(backoff_ms / 1000.0)
            attempt += 1


def wal_checkpoint(settings: Settings | None = None, *, mode: str = "PASSIVE") -> tuple[int, int, int]:
    normalized_mode = mode.strip().upper()
    if normalized_mode not in {"PASSIVE", "FULL", "RESTART", "TRUNCATE"}:
        raise ValueError(f"Unsupported WAL checkpoint mode '{mode}'.")
    with open_db(settings) as connection:
        row = execute_with_retry(connection, f"PRAGMA wal_checkpoint({normalized_mode})").fetchone()
    if not row:
        return (0, 0, 0)
    return (int(row[0]), int(row[1]), int(row[2]))


def _column_exists(connection: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    cursor = connection.execute(f"PRAGMA table_info({table_name})")
    return any(row[1] == column_name for row in cursor.fetchall())


def _ensure_column(connection: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
    if _column_exists(connection, table_name, column_name):
        return
    connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def _run_migrations(connection: sqlite3.Connection) -> None:
    _ensure_column(connection, "jobs", "queue_position", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "projects", "state_json", "TEXT NOT NULL DEFAULT '{}'")
    _ensure_column(connection, "models", "family", "TEXT")
    _ensure_column(connection, "models", "precision", "TEXT")
    _ensure_column(connection, "models", "revision", "TEXT")
    _ensure_column(connection, "models", "required_files_json", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(connection, "models", "last_validated_at", "TEXT")
    _ensure_column(connection, "models", "is_valid", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "models", "invalid_reason", "TEXT")
    _ensure_column(connection, "models", "favorite", "INTEGER NOT NULL DEFAULT 0")


@contextmanager
def open_db(settings: Settings | None = None) -> Iterator[sqlite3.Connection]:
    current_settings = settings or get_settings()
    connection = sqlite3.connect(current_settings.db_path, timeout=5.0)
    _configure_connection(connection)
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db(settings: Settings | None = None) -> None:
    with open_db(settings) as connection:
        cursor = connection.cursor()
        for statement in SCHEMA:
            cursor.execute(statement)
        _run_migrations(connection)
