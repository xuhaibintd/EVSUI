from __future__ import annotations

import json
import time
import uuid
from typing import Any

from app.db.sqlite import SQLiteDatabase


class JobRepository:
    def __init__(self, database: SQLiteDatabase, credential_vault=None) -> None:
        self.database = database
        self.credential_vault = credential_vault

    def create(
        self,
        *,
        kind: str,
        payload: dict[str, Any] | None = None,
        secret_payload: dict[str, Any] | None = None,
        owner_user_id: int | None = None,
        connection_profile_id: int | None = None,
    ) -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        now = int(time.time())
        secret_json = json.dumps(secret_payload or {}, ensure_ascii=False, default=str)
        if secret_payload and self.credential_vault is None:
            raise RuntimeError("A credential vault is required for sensitive job payloads.")
        secret_ciphertext = self.credential_vault.encrypt_text(secret_json) if secret_payload else ""
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO jobs(
                       id, kind, status, owner_user_id, connection_profile_id,
                       payload_json, secret_payload_ciphertext, created_at, updated_at
                   ) VALUES(?, ?, 'queued', ?, ?, ?, ?, ?, ?)""",
                (
                    job_id,
                    str(kind).strip(),
                    owner_user_id,
                    connection_profile_id,
                    json.dumps(payload or {}, ensure_ascii=False, default=str),
                    secret_ciphertext,
                    now,
                    now,
                ),
            )
        return self.get(job_id) or {}

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id=?", (str(job_id),)).fetchone()
        return self._row_to_dict(row) if row is not None else None

    def list_recent(self, *, owner_user_id: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
        sql = "SELECT * FROM jobs"
        values: list[object] = []
        if owner_user_id is not None:
            sql += " WHERE owner_user_id=?"
            values.append(int(owner_user_id))
        sql += " ORDER BY created_at DESC LIMIT ?"
        values.append(max(1, min(int(limit), 500)))
        with self.database.connect() as connection:
            rows = connection.execute(sql, values).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def claim_next(self, *, kinds: set[str] | None = None) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            sql = "SELECT id FROM jobs WHERE status='queued'"
            values: list[object] = []
            if kinds:
                placeholders = ",".join("?" for _ in kinds)
                sql += f" AND kind IN ({placeholders})"
                values.extend(sorted(kinds))
            sql += " ORDER BY created_at, id LIMIT 1"
            row = connection.execute(sql, values).fetchone()
            if row is None:
                return None
            now = int(time.time())
            updated = connection.execute(
                """UPDATE jobs SET status='running', attempt=attempt+1,
                          started_at=COALESCE(started_at, ?), heartbeat_at=?, updated_at=?
                   WHERE id=? AND status='queued'""",
                (now, now, now, str(row["id"])),
            )
            if updated.rowcount != 1:
                return None
            claimed = connection.execute("SELECT * FROM jobs WHERE id=?", (str(row["id"]),)).fetchone()
            return self._row_to_dict(claimed, decrypt_secrets=True)

    def heartbeat(self, job_id: str, *, progress: int) -> None:
        now = int(time.time())
        with self.database.connect() as connection:
            connection.execute(
                """UPDATE jobs SET heartbeat_at=?, updated_at=?, progress=?
                   WHERE id=? AND status='running'""",
                (now, now, max(0, min(int(progress), 99)), str(job_id)),
            )

    def succeed(self, job_id: str, result: dict[str, Any] | None = None) -> None:
        now = int(time.time())
        with self.database.connect() as connection:
            connection.execute(
                """UPDATE jobs SET status='succeeded', result_json=?, error='', progress=100,
                          secret_payload_ciphertext='',
                          heartbeat_at=?, finished_at=?, updated_at=?
                   WHERE id=? AND status='running'""",
                (json.dumps(result or {}, ensure_ascii=False, default=str), now, now, now, str(job_id)),
            )

    def fail(self, job_id: str, error: str) -> None:
        now = int(time.time())
        with self.database.connect() as connection:
            connection.execute(
                """UPDATE jobs SET status='failed', error=?, secret_payload_ciphertext='',
                          heartbeat_at=?, finished_at=?, updated_at=?
                   WHERE id=? AND status='running'""",
                (str(error or "")[:4000], now, now, now, str(job_id)),
            )

    def cancel(self, job_id: str, *, owner_user_id: int | None = None) -> bool:
        """Cancel a queued job without interrupting an operation already running."""
        now = int(time.time())
        sql = """UPDATE jobs SET status='cancelled', error='Cancelled by user.', secret_payload_ciphertext='',
                         finished_at=?, updated_at=?
                  WHERE id=? AND status='queued'"""
        values: list[object] = [now, now, str(job_id)]
        if owner_user_id is not None:
            sql += " AND owner_user_id=?"
            values.append(int(owner_user_id))
        with self.database.connect() as connection:
            cursor = connection.execute(sql, values)
            return cursor.rowcount == 1

    def recover_stale(self, *, stale_before: int) -> int:
        now = int(time.time())
        with self.database.connect() as connection:
            cursor = connection.execute(
                """UPDATE jobs SET status='queued', started_at=NULL, heartbeat_at=NULL,
                          error='Recovered after worker interruption.', updated_at=?
                   WHERE status='running' AND COALESCE(heartbeat_at, started_at, updated_at)<?""",
                (now, int(stale_before)),
            )
            return int(cursor.rowcount)

    def _row_to_dict(self, row, *, decrypt_secrets: bool = False) -> dict[str, Any]:
        item = dict(row)
        item["payload"] = json.loads(str(item.pop("payload_json") or "{}"))
        item["result"] = json.loads(str(item.pop("result_json") or "{}"))
        secret_ciphertext = str(item.pop("secret_payload_ciphertext", "") or "")
        if secret_ciphertext and decrypt_secrets:
            if self.credential_vault is None:
                raise RuntimeError("A credential vault is required to decrypt this job payload.")
            item["secret_payload"] = json.loads(self.credential_vault.decrypt_text(secret_ciphertext))
        else:
            item["secret_payload"] = {}
        return item
