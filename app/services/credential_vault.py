from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet


class CredentialVault:
    """Encrypt secrets at rest and materialize SDK-only PEM files."""

    def __init__(
        self,
        *,
        database_path: Path,
        runtime_dir: Path,
        credential_key: str = "",
        credential_key_file: Path | None = None,
        allow_generated_key: bool = True,
    ) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.runtime_dir = Path(runtime_dir).expanduser().resolve()
        self.credential_key = str(credential_key or "").strip()
        self.credential_key_file = (
            Path(credential_key_file).expanduser().resolve()
            if credential_key_file is not None
            else None
        )
        self.allow_generated_key = bool(allow_generated_key)

    def key_path(self) -> Path:
        if self.credential_key_file is not None:
            return self.credential_key_file
        configured = str(os.getenv("EVSUI_CREDENTIAL_KEY_FILE", "")).strip()
        return (
            Path(configured).expanduser().resolve()
            if configured
            else self.database_path.with_suffix(".credentials.key")
        )

    def cipher(self) -> Fernet:
        configured = self.credential_key or str(os.getenv("EVSUI_CREDENTIAL_KEY", "")).strip()
        if configured:
            return Fernet(configured.encode("ascii"))

        key_path = self.key_path()
        key_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            key = key_path.read_bytes().strip()
        except FileNotFoundError:
            if not self.allow_generated_key:
                raise RuntimeError(
                    f"Credential key file does not exist: {key_path}. "
                    "Create it before starting EVSUI in production."
                )
            generated = Fernet.generate_key()
            try:
                with key_path.open("xb") as handle:
                    handle.write(generated)
                try:
                    key_path.chmod(0o600)
                except OSError:
                    pass
                key = generated
            except FileExistsError:
                key = key_path.read_bytes().strip()
        return Fernet(key)

    def encrypt_text(self, value: str) -> str:
        if not value:
            return ""
        return self.cipher().encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt_text(self, value: str) -> str:
        if not value:
            return ""
        return self.cipher().decrypt(value.encode("ascii")).decode("utf-8")

    def encrypt_bytes(self, value: bytes) -> str:
        if not value:
            return ""
        return self.cipher().encrypt(value).decode("ascii")

    def decrypt_bytes(self, value: str) -> bytes:
        if not value:
            return b""
        return self.cipher().decrypt(value.encode("ascii"))

    def materialize_pem(self, payload: bytes, filename: str, profile_id: int | None = None) -> str:
        if not payload:
            return ""
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        safe_name = Path(filename or "system_connection.pem").name
        if Path(safe_name).suffix.lower() not in {".pem", ".key", ".crt"}:
            safe_name = "system_connection.pem"
        target_dir = self.runtime_dir / str(profile_id) if profile_id is not None else self.runtime_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / safe_name
        if not target.exists() or target.read_bytes() != payload:
            target.write_bytes(payload)
        try:
            target.chmod(0o600)
        except OSError:
            pass
        return str(target)

    def remove_materialized_pem(self, profile_id: int, filename: str) -> None:
        safe_name = Path(filename or "").name
        if not safe_name:
            return
        profile_dir = self.runtime_dir / str(int(profile_id))
        target = profile_dir / safe_name
        try:
            target.unlink(missing_ok=True)
            profile_dir.rmdir()
        except OSError:
            pass
