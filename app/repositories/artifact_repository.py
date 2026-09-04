from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from app.db.sqlite import SQLiteDatabase


class ArtifactRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def register(
        self,
        *,
        path: Path,
        kind: str,
        size_bytes: int,
        sha256: str = "",
        metadata: dict[str, Any] | None = None,
        job_id: str | None = None,
        owner_user_id: int | None = None,
        expires_at: int | None = None,
    ) -> dict[str, Any]:
        artifact_id = uuid.uuid4().hex
        now = int(time.time())
        normalized_path = str(Path(path).expanduser().resolve())
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO artifacts(
                       id, job_id, owner_user_id, kind, path, size_bytes, sha256,
                       metadata_json, created_at, expires_at, deleted_at
                   ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                   ON CONFLICT(path) DO UPDATE SET
                       job_id=excluded.job_id, owner_user_id=excluded.owner_user_id,
                       kind=excluded.kind, size_bytes=excluded.size_bytes, sha256=excluded.sha256,
                       metadata_json=excluded.metadata_json, expires_at=excluded.expires_at,
                       deleted_at=NULL""",
                (
                    artifact_id,
                    job_id,
                    owner_user_id,
                    str(kind).strip(),
                    normalized_path,
                    max(0, int(size_bytes)),
                    str(sha256 or ""),
                    json.dumps(metadata or {}, ensure_ascii=False),
                    now,
                    expires_at,
                ),
            )
            row = connection.execute("SELECT * FROM artifacts WHERE path=?", (normalized_path,)).fetchone()
        return self._row_to_dict(row)

    def list_active(self, *, limit: int = 1000) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM artifacts WHERE deleted_at IS NULL
                   ORDER BY created_at DESC LIMIT ?""",
                (max(1, min(int(limit), 10000)),),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def list_expired(self, *, now: int | None = None) -> list[dict[str, Any]]:
        cutoff = int(now or time.time())
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM artifacts
                   WHERE deleted_at IS NULL AND expires_at IS NOT NULL AND expires_at<=?
                   ORDER BY expires_at, id""",
                (cutoff,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def mark_deleted(self, artifact_id: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE artifacts SET deleted_at=? WHERE id=? AND deleted_at IS NULL",
                (int(time.time()), str(artifact_id)),
            )

    @staticmethod
    def _row_to_dict(row) -> dict[str, Any]:
        item = dict(row)
        item["metadata"] = json.loads(str(item.pop("metadata_json") or "{}"))
        return item
