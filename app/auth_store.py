from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError


AUTH_ROLES = ("admin", "operator", "viewer")
PASSWORD_HASHER = PasswordHasher()
SESSION_TTL_SECONDS_DEFAULT = 8 * 60 * 60


class _ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            return bool(super().__exit__(exc_type, exc_value, traceback))
        finally:
            self.close()


@dataclass(frozen=True)
class AuthPrincipal:
    user_id: int
    username: str
    display_name: str
    role: str
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def hash_password(password: str) -> str:
    value = str(password or "")
    if len(value) < 8:
        raise ValueError("Password must contain at least 8 characters.")
    return PASSWORD_HASHER.hash(value)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return bool(PASSWORD_HASHER.verify(str(password_hash or ""), str(password or "")))
    except (InvalidHashError, VerifyMismatchError, TypeError, ValueError):
        return False


def _session_hash(session_id: str) -> str:
    return hashlib.sha256(str(session_id or "").encode("utf-8")).hexdigest()


def _clean_username(raw: str) -> str:
    username = str(raw or "").strip()
    if not username or len(username) > 128:
        raise ValueError("Username must contain 1 to 128 characters.")
    if any(char.isspace() for char in username):
        raise ValueError("Username cannot contain whitespace.")
    if not re.fullmatch(r"[A-Za-z0-9_.@-]+", username):
        raise ValueError("Username may contain only letters, numbers, '.', '_', '@', and '-'.")
    return username


def _clean_role(raw: str) -> str:
    role = str(raw or "viewer").strip().lower()
    if role not in AUTH_ROLES:
        raise ValueError(f"Role must be one of: {', '.join(AUTH_ROLES)}.")
    return role


class AuthStore:
    """SQLite-backed users and server-side sessions.

    Connections are deliberately short lived, so the store is safe to use from
    FastAPI worker threads. WAL and busy_timeout keep small concurrent auth and
    audit writes predictable.
    """

    def __init__(self, database_path: Path, *, session_ttl_seconds: int = SESSION_TTL_SECONDS_DEFAULT) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.session_ttl_seconds = max(300, int(session_ttl_seconds))

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self.database_path,
            timeout=10.0,
            factory=_ClosingConnection,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_versions (
                    version INTEGER PRIMARY KEY,
                    applied_at INTEGER NOT NULL
                );
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
            connection.execute(
                "INSERT OR IGNORE INTO schema_versions(version, applied_at) VALUES(1, ?)",
                (int(time.time()),),
            )

    def count_users(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS value FROM users").fetchone()
        return int(row["value"] if row else 0)

    def count_enabled_admins(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS value FROM users WHERE role='admin' AND enabled=1"
            ).fetchone()
        return int(row["value"] if row else 0)

    def create_user(
        self,
        *,
        username: str,
        password: str | None = None,
        password_hash: str | None = None,
        display_name: str = "",
        role: str = "viewer",
        enabled: bool = True,
        replace: bool = False,
    ) -> AuthPrincipal:
        clean_username = _clean_username(username)
        clean_role = _clean_role(role)
        encoded_password = str(password_hash or "").strip()
        if not encoded_password:
            encoded_password = hash_password(str(password or ""))
        elif not encoded_password.startswith("$argon2"):
            raise ValueError("Imported password_hash must use Argon2.")
        now = int(time.time())
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT id FROM users WHERE username=? COLLATE NOCASE", (clean_username,)
            ).fetchone()
            if existing and not replace:
                raise ValueError(f"User '{clean_username}' already exists.")
            if existing:
                connection.execute(
                    """UPDATE users SET display_name=?, password_hash=?, role=?, enabled=?, updated_at=?
                       WHERE id=?""",
                    (str(display_name).strip(), encoded_password, clean_role, int(enabled), now, existing["id"]),
                )
                user_id = int(existing["id"])
            else:
                cursor = connection.execute(
                    """INSERT INTO users(username, display_name, password_hash, role, enabled, created_at, updated_at)
                       VALUES(?, ?, ?, ?, ?, ?, ?)""",
                    (clean_username, str(display_name).strip(), encoded_password, clean_role, int(enabled), now, now),
                )
                user_id = int(cursor.lastrowid)
            self._audit_with_connection(
                connection,
                user_id=user_id,
                username=clean_username,
                action="user.upsert",
                resource=clean_username,
                result="ok",
            )
        return AuthPrincipal(user_id, clean_username, str(display_name).strip(), clean_role, bool(enabled))

    def bootstrap(self, legacy_users: dict[str, str] | None = None) -> int:
        if self.count_users():
            return 0
        candidates: list[tuple[str, str, bool]] = []
        bootstrap_username = str(os.getenv("EVSUI_BOOTSTRAP_ADMIN", "")).strip()
        bootstrap_password = str(os.getenv("EVSUI_BOOTSTRAP_PASSWORD", ""))
        if bool(bootstrap_username) != bool(bootstrap_password):
            raise RuntimeError("EVSUI_BOOTSTRAP_ADMIN and EVSUI_BOOTSTRAP_PASSWORD must be set together.")
        if bootstrap_username:
            if len(bootstrap_password) < 8:
                raise RuntimeError("EVSUI_BOOTSTRAP_PASSWORD must contain at least 8 characters.")
            candidates.append((bootstrap_username, bootstrap_password, True))
        candidates.extend(
            (str(username), str(password), False)
            for username, password in dict(legacy_users or {}).items()
            if str(username).strip() and str(password)
            and str(username).strip().lower() != bootstrap_username.lower()
        )
        created = 0
        for username, password, enforce_length in candidates:
            self.create_user(
                username=username,
                password=password if enforce_length else None,
                password_hash=None if enforce_length else PASSWORD_HASHER.hash(password),
                role="admin" if created == 0 else "operator",
            )
            created += 1
        return created

    def authenticate(self, username: str, password: str) -> AuthPrincipal | None:
        clean_username = str(username or "").strip()
        now = int(time.time())
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE username=? COLLATE NOCASE", (clean_username,)
            ).fetchone()
            if row is None or not bool(row["enabled"]):
                self._audit_with_connection(
                    connection,
                    username=clean_username,
                    action="login",
                    result="denied",
                    detail="unknown or disabled user",
                )
                return None
            locked_until = int(row["locked_until"] or 0)
            if locked_until > now:
                self._audit_with_connection(
                    connection,
                    user_id=int(row["id"]),
                    username=str(row["username"]),
                    action="login",
                    result="locked",
                )
                return None
            if not verify_password(str(row["password_hash"]), password):
                failures = int(row["failed_login_count"] or 0) + 1
                lock_until = now + 300 if failures >= 5 else None
                connection.execute(
                    "UPDATE users SET failed_login_count=?, locked_until=?, updated_at=? WHERE id=?",
                    (0 if lock_until else failures, lock_until, now, row["id"]),
                )
                self._audit_with_connection(
                    connection,
                    user_id=int(row["id"]),
                    username=str(row["username"]),
                    action="login",
                    result="denied",
                    detail="invalid password",
                )
                return None
            connection.execute(
                """UPDATE users SET failed_login_count=0, locked_until=NULL,
                   last_login_at=?, updated_at=? WHERE id=?""",
                (now, now, row["id"]),
            )
            self._audit_with_connection(
                connection,
                user_id=int(row["id"]),
                username=str(row["username"]),
                action="login",
                result="ok",
            )
            return self._principal_from_row(row)

    def create_session(self, principal: AuthPrincipal) -> str:
        session_id = secrets.token_urlsafe(32)
        now = int(time.time())
        with self._connect() as connection:
            connection.execute("DELETE FROM sessions WHERE expires_at<=? OR revoked_at IS NOT NULL", (now,))
            connection.execute(
                """INSERT INTO sessions(session_id_hash, user_id, created_at, last_seen_at, expires_at)
                   VALUES(?, ?, ?, ?, ?)""",
                (_session_hash(session_id), principal.user_id, now, now, now + self.session_ttl_seconds),
            )
        return session_id

    def get_session(self, session_id: str, *, touch: bool = True) -> AuthPrincipal | None:
        if not str(session_id or "").strip():
            return None
        now = int(time.time())
        with self._connect() as connection:
            row = connection.execute(
                """SELECT u.*, s.last_seen_at, s.expires_at, s.revoked_at
                   FROM sessions s JOIN users u ON u.id=s.user_id
                   WHERE s.session_id_hash=?""",
                (_session_hash(session_id),),
            ).fetchone()
            if row is None or row["revoked_at"] is not None or int(row["expires_at"]) <= now or not bool(row["enabled"]):
                return None
            if touch and now - int(row["last_seen_at"] or 0) >= 60:
                connection.execute(
                    "UPDATE sessions SET last_seen_at=? WHERE session_id_hash=?",
                    (now, _session_hash(session_id)),
                )
            return self._principal_from_row(row)

    def revoke_session(self, session_id: str) -> None:
        if not session_id:
            return
        with self._connect() as connection:
            connection.execute(
                "UPDATE sessions SET revoked_at=? WHERE session_id_hash=?",
                (int(time.time()), _session_hash(session_id)),
            )

    def list_users(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT id, username, display_name, role, enabled, failed_login_count,
                          locked_until, last_login_at, created_at, updated_at
                   FROM users ORDER BY username COLLATE NOCASE"""
            ).fetchall()
        users = []
        for row in rows:
            item = dict(row)
            item["enabled"] = bool(item["enabled"])
            item["last_login_display"] = (
                time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(int(item["last_login_at"])))
                if item.get("last_login_at")
                else ""
            )
            users.append(item)
        return users

    def set_enabled(self, username: str, enabled: bool) -> None:
        clean_username = _clean_username(username)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, role, enabled FROM users WHERE username=? COLLATE NOCASE", (clean_username,)
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown user '{clean_username}'.")
            if row["role"] == "admin" and bool(row["enabled"]) and not enabled and self.count_enabled_admins() <= 1:
                raise ValueError("The last enabled administrator cannot be disabled.")
            connection.execute(
                "UPDATE users SET enabled=?, updated_at=? WHERE id=?",
                (int(enabled), int(time.time()), row["id"]),
            )
            if not enabled:
                connection.execute(
                    "UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
                    (int(time.time()), row["id"]),
                )
            self._audit_with_connection(
                connection,
                user_id=int(row["id"]),
                username=clean_username,
                action="user.enabled",
                resource=clean_username,
                result="ok",
                detail=str(bool(enabled)).lower(),
            )

    def set_role(self, username: str, role: str) -> None:
        clean_username = _clean_username(username)
        clean_role = _clean_role(role)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, role, enabled FROM users WHERE username=? COLLATE NOCASE", (clean_username,)
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown user '{clean_username}'.")
            if (
                row["role"] == "admin"
                and bool(row["enabled"])
                and clean_role != "admin"
                and self.count_enabled_admins() <= 1
            ):
                raise ValueError("The last enabled administrator cannot be demoted.")
            connection.execute(
                "UPDATE users SET role=?, updated_at=? WHERE id=?",
                (clean_role, int(time.time()), row["id"]),
            )
            self._audit_with_connection(
                connection,
                user_id=int(row["id"]),
                username=clean_username,
                action="user.role",
                resource=clean_username,
                result="ok",
                detail=clean_role,
            )

    def reset_password(self, username: str, password: str) -> None:
        clean_username = _clean_username(username)
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE users SET password_hash=?, failed_login_count=0, locked_until=NULL, updated_at=?
                   WHERE username=? COLLATE NOCASE""",
                (hash_password(password), int(time.time()), clean_username),
            )
            if not cursor.rowcount:
                raise ValueError(f"Unknown user '{clean_username}'.")
            connection.execute(
                """UPDATE sessions SET revoked_at=? WHERE user_id=(SELECT id FROM users WHERE username=? COLLATE NOCASE)
                   AND revoked_at IS NULL""",
                (int(time.time()), clean_username),
            )
            row = connection.execute(
                "SELECT id FROM users WHERE username=? COLLATE NOCASE", (clean_username,)
            ).fetchone()
            self._audit_with_connection(
                connection,
                user_id=int(row["id"]) if row is not None else None,
                username=clean_username,
                action="user.password_reset",
                resource=clean_username,
                result="ok",
            )

    def export_users(self) -> dict[str, Any]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT username, display_name, password_hash, role, enabled FROM users ORDER BY username COLLATE NOCASE"
            ).fetchall()
        users = []
        for row in rows:
            item = dict(row)
            item["enabled"] = bool(item["enabled"])
            users.append(item)
        return {"version": 1, "users": users}

    def import_users(self, payload: dict[str, Any], *, replace: bool = True) -> int:
        if int(payload.get("version") or 1) != 1:
            raise ValueError("Unsupported user export version.")
        raw_users = payload.get("users")
        if not isinstance(raw_users, list):
            raise ValueError("User import must contain a users array.")
        normalized: list[dict[str, Any]] = []
        for item in raw_users:
            if not isinstance(item, dict):
                raise ValueError("Every imported user must be an object.")
            username = _clean_username(str(item.get("username") or ""))
            role = _clean_role(str(item.get("role") or "viewer"))
            password_hash = str(item.get("password_hash") or "").strip()
            password = str(item.get("password") or "")
            if password_hash and not password_hash.startswith("$argon2"):
                raise ValueError("Imported password_hash must use Argon2.")
            if not password_hash and len(password) < 8:
                raise ValueError(f"Imported user '{username}' requires a password of at least 8 characters.")
            enabled_value = item.get("enabled", True)
            if not isinstance(enabled_value, bool):
                raise ValueError(f"Imported user '{username}' enabled must be true or false.")
            normalized.append(
                {
                    "username": username,
                    "display_name": str(item.get("display_name") or ""),
                    "password": password or None,
                    "password_hash": password_hash or None,
                    "role": role,
                    "enabled": enabled_value,
                }
            )

        prospective = {
            str(item["username"]).lower(): {"role": item["role"], "enabled": bool(item["enabled"])}
            for item in self.list_users()
        }
        for item in normalized:
            prospective[item["username"].lower()] = {
                "role": item["role"],
                "enabled": item["enabled"],
            }
        if not any(item["role"] == "admin" and item["enabled"] for item in prospective.values()):
            raise ValueError("Import must leave at least one enabled administrator.")

        imported = 0
        for item in normalized:
            self.create_user(
                **item,
                replace=replace,
            )
            imported += 1
        return imported

    def _principal_from_row(self, row: sqlite3.Row) -> AuthPrincipal:
        return AuthPrincipal(
            user_id=int(row["id"]),
            username=str(row["username"]),
            display_name=str(row["display_name"] or ""),
            role=str(row["role"]),
            enabled=bool(row["enabled"]),
        )

    def _audit_with_connection(
        self,
        connection: sqlite3.Connection,
        *,
        username: str,
        action: str,
        result: str,
        user_id: int | None = None,
        resource: str = "",
        detail: str = "",
    ) -> None:
        connection.execute(
            """INSERT INTO audit_logs(user_id, username, action, resource, result, detail, created_at)
               VALUES(?, ?, ?, ?, ?, ?, ?)""",
            (user_id, username, action, resource, result, detail[:2000], int(time.time())),
        )


def auth_database_path(default_path: Path) -> Path:
    return Path(os.getenv("EVSUI_DATABASE_PATH", str(default_path))).expanduser()


def load_user_import(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("User import file must contain a JSON object.")
    return payload
