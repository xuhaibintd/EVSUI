from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time

from app.db.sqlite import SQLiteDatabase


def session_hash(session_id: str) -> str:
    return hashlib.sha256(str(session_id or "").encode("utf-8")).hexdigest()


class SessionRepository:
    def __init__(self, database: SQLiteDatabase, *, ttl_seconds: int) -> None:
        self.database = database
        self.ttl_seconds = max(300, int(ttl_seconds))

    def create(self, user_id: int) -> str:
        session_id = secrets.token_urlsafe(32)
        now = int(time.time())
        with self.database.connect() as connection:
            connection.execute("DELETE FROM sessions WHERE expires_at<=? OR revoked_at IS NOT NULL", (now,))
            connection.execute(
                """INSERT INTO sessions(session_id_hash, user_id, created_at, last_seen_at, expires_at)
                   VALUES(?, ?, ?, ?, ?)""",
                (session_hash(session_id), int(user_id), now, now, now + self.ttl_seconds),
            )
        return session_id

    def get(self, session_id: str, *, touch: bool = True) -> sqlite3.Row | None:
        if not str(session_id or "").strip():
            return None
        now = int(time.time())
        hashed = session_hash(session_id)
        with self.database.connect() as connection:
            row = connection.execute(
                """SELECT u.*, s.last_seen_at, s.expires_at, s.revoked_at
                   FROM sessions s JOIN users u ON u.id=s.user_id
                   WHERE s.session_id_hash=?""",
                (hashed,),
            ).fetchone()
            if row is None or row["revoked_at"] is not None or int(row["expires_at"]) <= now or not bool(row["enabled"]):
                return None
            if touch and now - int(row["last_seen_at"] or 0) >= 60:
                connection.execute(
                    "UPDATE sessions SET last_seen_at=? WHERE session_id_hash=?",
                    (now, hashed),
                )
            return row

    def revoke(self, session_id: str) -> None:
        if not session_id:
            return
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE sessions SET revoked_at=? WHERE session_id_hash=?",
                (int(time.time()), session_hash(session_id)),
            )
