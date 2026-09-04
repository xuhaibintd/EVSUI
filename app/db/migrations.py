from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


MigrationFunction = Callable[[sqlite3.Connection], None]


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: MigrationFunction


def _migration_001_identity(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL COLLATE NOCASE UNIQUE,
            display_name TEXT NOT NULL DEFAULT '',
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('admin', 'operator', 'viewer')),
            enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
            failed_login_count INTEGER NOT NULL DEFAULT 0,
            locked_until INTEGER,
            last_login_at INTEGER,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            session_id_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at INTEGER NOT NULL,
            last_seen_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            revoked_at INTEGER
        );
        CREATE INDEX IF NOT EXISTS ix_sessions_user ON sessions(user_id);
        CREATE INDEX IF NOT EXISTS ix_sessions_expiry ON sessions(expires_at);
        CREATE TABLE IF NOT EXISTS permissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            resource_type TEXT NOT NULL,
            resource_name TEXT NOT NULL,
            permission TEXT NOT NULL CHECK (permission IN ('read', 'write', 'admin')),
            created_at INTEGER NOT NULL,
            UNIQUE(user_id, resource_type, resource_name)
        );
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            username TEXT NOT NULL DEFAULT '',
            action TEXT NOT NULL,
            resource TEXT NOT NULL DEFAULT '',
            result TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL
        );
        """
    )


def _migration_002_legacy_user_connections(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS connection_configs (
               user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
               host TEXT NOT NULL DEFAULT '',
               username TEXT NOT NULL DEFAULT '',
               password_ciphertext TEXT NOT NULL DEFAULT '',
               ues_url TEXT NOT NULL DEFAULT '',
               pat_token_ciphertext TEXT NOT NULL DEFAULT '',
               pem_file TEXT NOT NULL DEFAULT '',
               created_at INTEGER NOT NULL,
               updated_at INTEGER NOT NULL
           )"""
    )


def _migration_003_system_connection(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS system_connection_config (
               config_id INTEGER PRIMARY KEY CHECK (config_id = 1),
               host TEXT NOT NULL DEFAULT '',
               username TEXT NOT NULL DEFAULT '',
               password_ciphertext TEXT NOT NULL DEFAULT '',
               ues_url TEXT NOT NULL DEFAULT '',
               pat_token_ciphertext TEXT NOT NULL DEFAULT '',
               pem_file TEXT NOT NULL DEFAULT '',
               updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
               created_at INTEGER NOT NULL,
               updated_at INTEGER NOT NULL
           )"""
    )


def _migration_004_encrypted_pem(connection: sqlite3.Connection) -> None:
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(system_connection_config)").fetchall()
    }
    if "pem_filename" not in columns:
        connection.execute(
            "ALTER TABLE system_connection_config ADD COLUMN pem_filename TEXT NOT NULL DEFAULT ''"
        )
    if "pem_ciphertext" not in columns:
        connection.execute(
            "ALTER TABLE system_connection_config ADD COLUMN pem_ciphertext TEXT NOT NULL DEFAULT ''"
        )


def _migration_005_connection_profiles(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS system_connection_profiles (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               name TEXT NOT NULL COLLATE NOCASE UNIQUE,
               host TEXT NOT NULL DEFAULT '',
               username TEXT NOT NULL DEFAULT '',
               password_ciphertext TEXT NOT NULL DEFAULT '',
               ues_url TEXT NOT NULL DEFAULT '',
               pat_token_ciphertext TEXT NOT NULL DEFAULT '',
               pem_filename TEXT NOT NULL DEFAULT '',
               pem_ciphertext TEXT NOT NULL DEFAULT '',
               is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1)),
               updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
               created_at INTEGER NOT NULL,
               updated_at INTEGER NOT NULL
           )"""
    )


def _migration_006_persistent_jobs(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
            owner_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            connection_profile_id INTEGER REFERENCES system_connection_profiles(id) ON DELETE SET NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            result_json TEXT NOT NULL DEFAULT '{}',
            error TEXT NOT NULL DEFAULT '',
            progress INTEGER NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
            attempt INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL,
            started_at INTEGER,
            heartbeat_at INTEGER,
            finished_at INTEGER,
            updated_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_jobs_status_created ON jobs(status, created_at);
        CREATE INDEX IF NOT EXISTS ix_jobs_owner_created ON jobs(owner_user_id, created_at DESC);
        """
    )


def _migration_007_artifacts(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS artifacts (
            id TEXT PRIMARY KEY,
            job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL,
            owner_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            kind TEXT NOT NULL,
            path TEXT NOT NULL UNIQUE,
            size_bytes INTEGER NOT NULL DEFAULT 0,
            sha256 TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at INTEGER NOT NULL,
            expires_at INTEGER,
            deleted_at INTEGER
        );
        CREATE INDEX IF NOT EXISTS ix_artifacts_expiry ON artifacts(expires_at, deleted_at);
        CREATE INDEX IF NOT EXISTS ix_artifacts_job ON artifacts(job_id);
        """
    )


def _migration_008_external_service_configs(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS external_service_configs (
               service_name TEXT PRIMARY KEY COLLATE NOCASE,
               api_url TEXT NOT NULL DEFAULT '',
               api_key_ciphertext TEXT NOT NULL DEFAULT '',
               updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
               created_at INTEGER NOT NULL,
               updated_at INTEGER NOT NULL
           )"""
    )


MIGRATIONS = (
    Migration(1, "identity_and_audit", _migration_001_identity),
    Migration(2, "legacy_user_connections", _migration_002_legacy_user_connections),
    Migration(3, "system_connection", _migration_003_system_connection),
    Migration(4, "encrypted_pem", _migration_004_encrypted_pem),
    Migration(5, "connection_profiles", _migration_005_connection_profiles),
    Migration(6, "persistent_jobs", _migration_006_persistent_jobs),
    Migration(7, "artifacts", _migration_007_artifacts),
    Migration(8, "external_service_configs", _migration_008_external_service_configs),
)
LATEST_SCHEMA_VERSION = MIGRATIONS[-1].version


def run_migrations(connection: sqlite3.Connection) -> list[int]:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS schema_versions (
               version INTEGER PRIMARY KEY,
               applied_at INTEGER NOT NULL
           )"""
    )
    applied = {
        int(row[0])
        for row in connection.execute("SELECT version FROM schema_versions").fetchall()
    }
    completed: list[int] = []
    for migration in MIGRATIONS:
        if migration.version in applied:
            continue
        migration.apply(connection)
        connection.execute(
            "INSERT INTO schema_versions(version, applied_at) VALUES(?, ?)",
            (migration.version, int(time.time())),
        )
        completed.append(migration.version)
    return completed


def migration_status(database_path: Path) -> dict[str, object]:
    path = Path(database_path).expanduser().resolve()
    applied: set[int] = set()
    if path.is_file():
        connection = sqlite3.connect(path)
        try:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_versions'"
            ).fetchone()
            if table:
                applied = {
                    int(row[0])
                    for row in connection.execute("SELECT version FROM schema_versions").fetchall()
                }
        finally:
            connection.close()
    return {
        "database_path": str(path),
        "latest_version": LATEST_SCHEMA_VERSION,
        "applied_versions": sorted(applied),
        "pending_versions": [migration.version for migration in MIGRATIONS if migration.version not in applied],
    }


def migrate_database(database_path: Path) -> list[int]:
    path = Path(database_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        applied = run_migrations(connection)
        connection.commit()
        return applied
    finally:
        connection.close()
