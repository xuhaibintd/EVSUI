from __future__ import annotations

import time
from typing import Any

from cryptography.fernet import InvalidToken

from app.db.sqlite import SQLiteDatabase
from app.services.credential_vault import CredentialVault


class ExternalServiceRepository:
    """Persist shared external-service endpoints and encrypted API keys."""

    def __init__(self, database: SQLiteDatabase, credential_vault: CredentialVault) -> None:
        self.database = database
        self.credential_vault = credential_vault

    def get(self, service_name: str) -> dict[str, Any] | None:
        name = self._normalize_name(service_name)
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM external_service_configs WHERE service_name=? COLLATE NOCASE",
                (name,),
            ).fetchone()
        if row is None:
            return None
        try:
            api_key = self.credential_vault.decrypt_text(str(row["api_key_ciphertext"] or ""))
        except InvalidToken as ex:
            raise RuntimeError(
                f"Stored {name} credentials cannot be decrypted with the configured key."
            ) from ex
        return {
            "service_name": str(row["service_name"]),
            "api_url": str(row["api_url"] or ""),
            "api_key": api_key,
            "api_key_configured": bool(row["api_key_ciphertext"]),
            "updated_at": int(row["updated_at"]),
        }

    def save(
        self,
        service_name: str,
        *,
        api_url: str,
        api_key: str,
        updated_by: int | None,
    ) -> dict[str, Any]:
        name = self._normalize_name(service_name)
        url = str(api_url or "").strip()
        if len(url) > 2048:
            raise ValueError("External service API URL exceeds 2048 characters.")
        key = str(api_key or "").strip()
        if len(key) > 8192:
            raise ValueError("External service API key exceeds 8192 characters.")
        encrypted_key = self.credential_vault.encrypt_text(key)
        now = int(time.time())
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO external_service_configs(
                       service_name, api_url, api_key_ciphertext, updated_by, created_at, updated_at
                   ) VALUES(?, ?, ?, ?, ?, ?)
                   ON CONFLICT(service_name) DO UPDATE SET
                       api_url=excluded.api_url,
                       api_key_ciphertext=excluded.api_key_ciphertext,
                       updated_by=excluded.updated_by,
                       updated_at=excluded.updated_at""",
                (name, url, encrypted_key, updated_by, now, now),
            )
        return self.get(name) or {}

    def bootstrap(self, service_name: str, *, api_url: str, api_key: str) -> bool:
        name = self._normalize_name(service_name)
        with self.database.connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM external_service_configs WHERE service_name=? COLLATE NOCASE",
                (name,),
            ).fetchone()
        if exists is not None:
            return False
        self.save(name, api_url=api_url, api_key=api_key, updated_by=None)
        return True

    @staticmethod
    def _normalize_name(service_name: str) -> str:
        name = str(service_name or "").strip().lower()
        if not name or len(name) > 64 or not name.replace("-", "").replace("_", "").isalnum():
            raise ValueError("External service name must be an alphanumeric identifier.")
        return name
