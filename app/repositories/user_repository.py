from __future__ import annotations

import sqlite3

from app.db.sqlite import SQLiteDatabase


class UserRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def count(self) -> int:
        with self.database.connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS value FROM users").fetchone()
        return int(row["value"] if row else 0)

    def count_enabled_admins(self) -> int:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS value FROM users WHERE role='admin' AND enabled=1"
            ).fetchone()
        return int(row["value"] if row else 0)

    def list_admin_rows(self) -> list[sqlite3.Row]:
        with self.database.connect() as connection:
            return connection.execute(
                """SELECT id, username, display_name, role, enabled, failed_login_count,
                          locked_until, last_login_at, created_at, updated_at
                   FROM users ORDER BY username COLLATE NOCASE"""
            ).fetchall()

    def export_rows(self) -> list[sqlite3.Row]:
        with self.database.connect() as connection:
            return connection.execute(
                """SELECT username, display_name, password_hash, role, enabled
                   FROM users ORDER BY username COLLATE NOCASE"""
            ).fetchall()
