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
        if kinds is not None and not kinds:
            return None
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
            try:
                return self._row_to_dict(claimed, decrypt_secrets=True)
            except Exception:
                # One unreadable payload must not roll back its claim and block every later job.
                safe_json = {}
                for field in ("payload_json", "result_json"):
                    try:
                        value = json.loads(str(claimed[field] or "{}"))
                        safe_json[field] = json.dumps(value if isinstance(value, dict) else {})
                    except (TypeError, ValueError):
                        safe_json[field] = "{}"
                connection.execute(
                    """UPDATE jobs SET status='failed', secret_payload_ciphertext='',
                              error='Stored job credentials or payload could not be read. Resubmit this operation.',
                              payload_json=?, result_json=?, finished_at=?, updated_at=? WHERE id=?""",
                    (safe_json["payload_json"], safe_json["result_json"], now, now, str(row["id"])),
                )
                failed = dict(claimed)
                failed.update(
                    status="failed", secret_payload_ciphertext="", **safe_json,
                    error="Stored job credentials or payload could not be read. Resubmit this operation.",
                    finished_at=now, updated_at=now,
                )
                return self._row_to_dict(failed)

    def heartbeat(self, job_id: str, *, progress: int, expected_attempt: int | None = None) -> bool:
        now = int(time.time())
        with self.database.connect() as connection:
            cursor = connection.execute(
                """UPDATE jobs SET heartbeat_at=?, updated_at=?, progress=?
                   WHERE id=? AND status='running' AND (? IS NULL OR attempt=?)""",
                (now, now, max(0, min(int(progress), 99)), str(job_id), expected_attempt, expected_attempt),
            )
            return cursor.rowcount == 1

    def succeed(self, job_id: str, result: dict[str, Any] | None = None, *, expected_attempt: int | None = None) -> bool:
        now = int(time.time())
        with self.database.connect() as connection:
            cursor = connection.execute(
                """UPDATE jobs SET status='succeeded', result_json=?, error='', progress=100,
                          secret_payload_ciphertext='',
                          heartbeat_at=?, finished_at=?, updated_at=?
                   WHERE id=? AND status='running' AND (? IS NULL OR attempt=?)""",
                (json.dumps(result or {}, ensure_ascii=False, default=str), now, now, now, str(job_id), expected_attempt, expected_attempt),
            )
            return cursor.rowcount == 1

    def fail(
        self, job_id: str, error: str, *, result: dict[str, Any] | None = None,
        expected_attempt: int | None = None,
    ) -> bool:
        now = int(time.time())
        with self.database.connect() as connection:
            cursor = connection.execute(
                """UPDATE jobs SET status='failed', error=?, result_json=?, secret_payload_ciphertext='',
                          heartbeat_at=?, finished_at=?, updated_at=?
                   WHERE id=? AND status='running' AND (? IS NULL OR attempt=?)""",
                (str(error or "")[:4000], json.dumps(result or {}, ensure_ascii=False, default=str), now, now, now, str(job_id), expected_attempt, expected_attempt),
            )
            return cursor.rowcount == 1

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
                """UPDATE jobs SET status='queued', started_at=NULL, heartbeat_at=NULL, progress=0,
                          error='Recovered after application interruption.', updated_at=?
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
