from __future__ import annotations

import json
import sqlite3
import threading
import time

import pytest

from vivid_inference.config import get_settings
from vivid_inference.db import (
    DEFAULT_BUSY_TIMEOUT_MS,
    WAL_AUTOCHECKPOINT_PAGES,
    execute_with_retry,
    init_db,
    is_sqlite_busy_error,
    wal_checkpoint,
    open_db,
)


def test_db_pragmas_include_wal_sync_busy_timeout_and_autocheckpoint() -> None:
    with open_db() as connection:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()
        synchronous = connection.execute("PRAGMA synchronous").fetchone()
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()
        wal_autocheckpoint = connection.execute("PRAGMA wal_autocheckpoint").fetchone()

    assert journal_mode is not None
    assert str(journal_mode[0]).lower() == "wal"
    assert synchronous is not None
    # SQLite represents NORMAL as integer 1.
    assert int(synchronous[0]) == 1
    assert busy_timeout is not None
    assert int(busy_timeout[0]) == DEFAULT_BUSY_TIMEOUT_MS
    assert wal_autocheckpoint is not None
    assert int(wal_autocheckpoint[0]) == WAL_AUTOCHECKPOINT_PAGES


def test_is_sqlite_busy_error_detects_busy_messages() -> None:
    assert is_sqlite_busy_error(sqlite3.OperationalError("database is locked"))
    assert is_sqlite_busy_error(sqlite3.OperationalError("database table is locked"))
    assert not is_sqlite_busy_error(sqlite3.OperationalError("syntax error"))


def test_execute_with_retry_tolerates_temporary_sqlite_busy() -> None:
    settings = get_settings()
    lock_connection = sqlite3.connect(settings.db_path, timeout=5.0, check_same_thread=False)
    releaser = None
    try:
        lock_connection.execute("PRAGMA journal_mode=WAL")
        lock_connection.execute("BEGIN IMMEDIATE")

        def release_lock() -> None:
            time.sleep(0.12)
            lock_connection.commit()

        releaser = threading.Thread(target=release_lock, daemon=True)
        releaser.start()

        with open_db(settings) as writer:
            # Keep per-attempt lock waits short; retry loop handles the backoff.
            writer.execute("PRAGMA busy_timeout=5")
            execute_with_retry(
                writer,
                """
                INSERT INTO settings (key, value_json)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json
                """,
                ("busy_retry_test", json.dumps({"ok": True})),
                retries=24,
                initial_backoff_ms=5,
                max_backoff_ms=25,
            )
    finally:
        if releaser is not None:
            releaser.join(timeout=1.0)
        try:
            lock_connection.rollback()
        except Exception:
            pass
        lock_connection.close()

    with open_db(settings) as connection:
        row = connection.execute("SELECT value_json FROM settings WHERE key = ?", ("busy_retry_test",)).fetchone()
    assert row is not None


def test_wal_checkpoint_returns_integrity_tuple() -> None:
    with open_db() as connection:
        connection.execute(
            """
            INSERT INTO settings (key, value_json)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json
            """,
            ("checkpoint_test", json.dumps({"ts": "now"})),
        )

    busy, log_frames, checkpointed_frames = wal_checkpoint(mode="PASSIVE")
    assert isinstance(busy, int)
    assert isinstance(log_frames, int)
    assert isinstance(checkpointed_frames, int)


def test_wal_checkpoint_rejects_invalid_mode() -> None:
    with pytest.raises(ValueError, match="Unsupported WAL checkpoint mode"):
        wal_checkpoint(mode="INVALID")


def test_model_registry_migration_adds_metadata_columns() -> None:
    settings = get_settings()
    if settings.db_path.exists():
        settings.db_path.unlink()

    legacy = sqlite3.connect(settings.db_path)
    try:
        legacy.execute(
            """
            CREATE TABLE models (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                local_path TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                last_used_at TEXT,
                profile_json TEXT NOT NULL
            )
            """
        )
        legacy.execute(
            """
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                progress REAL NOT NULL,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        legacy.commit()
    finally:
        legacy.close()

    init_db()

    with open_db() as connection:
        columns = {
            row[1]: row[2]
            for row in connection.execute("PRAGMA table_info(models)").fetchall()
        }
    for required in (
        "family",
        "precision",
        "revision",
        "required_files_json",
        "last_validated_at",
        "is_valid",
        "invalid_reason",
        "favorite",
    ):
        assert required in columns


def test_project_migration_adds_state_json_column() -> None:
    settings = get_settings()
    if settings.db_path.exists():
        settings.db_path.unlink()

    legacy = sqlite3.connect(settings.db_path)
    try:
        legacy.execute(
            """
            CREATE TABLE projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                cover_asset_id TEXT
            )
            """
        )
        legacy.commit()
    finally:
        legacy.close()

    init_db()

    with open_db() as connection:
        columns = {row[1]: row[2] for row in connection.execute("PRAGMA table_info(projects)").fetchall()}
    assert "state_json" in columns
