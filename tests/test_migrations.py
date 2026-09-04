from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.db.migrations import LATEST_SCHEMA_VERSION, migrate_database, migration_status


class MigrationTests(unittest.TestCase):
    def test_fresh_database_applies_all_numbered_migrations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "evsui.db"

            applied = migrate_database(database_path)
            status = migration_status(database_path)

            self.assertEqual(applied, list(range(1, LATEST_SCHEMA_VERSION + 1)))
            self.assertEqual(status["pending_versions"], [])
            connection = sqlite3.connect(database_path)
            try:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
            finally:
                connection.close()
            self.assertTrue(
                {"users", "sessions", "audit_logs", "system_connection_profiles"}.issubset(tables)
            )

    def test_migration_runner_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "evsui.db"

            migrate_database(database_path)

            self.assertEqual(migrate_database(database_path), [])

    def test_existing_pre_pem_schema_is_upgraded_without_data_loss(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "evsui.db"
            connection = sqlite3.connect(database_path)
            try:
                connection.executescript(
                    """
                    CREATE TABLE schema_versions(version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL);
                    INSERT INTO schema_versions VALUES(1, 1);
                    INSERT INTO schema_versions VALUES(2, 1);
                    INSERT INTO schema_versions VALUES(3, 1);
                    CREATE TABLE system_connection_config (
                        config_id INTEGER PRIMARY KEY,
                        host TEXT NOT NULL DEFAULT '', username TEXT NOT NULL DEFAULT '',
                        password_ciphertext TEXT NOT NULL DEFAULT '', ues_url TEXT NOT NULL DEFAULT '',
                        pat_token_ciphertext TEXT NOT NULL DEFAULT '', pem_file TEXT NOT NULL DEFAULT '',
                        updated_by INTEGER, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
                    );
                    INSERT INTO system_connection_config VALUES(
                        1, 'kept-host', 'kept-user', '', '', '', '', NULL, 1, 1
                    );
                    """
                )
                connection.commit()
            finally:
                connection.close()

            self.assertEqual(migrate_database(database_path), [4, 5])

            connection = sqlite3.connect(database_path)
            try:
                columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(system_connection_config)").fetchall()
                }
                host = connection.execute(
                    "SELECT host FROM system_connection_config WHERE config_id=1"
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertIn("pem_ciphertext", columns)
            self.assertEqual(host, "kept-host")


if __name__ == "__main__":
    unittest.main()
