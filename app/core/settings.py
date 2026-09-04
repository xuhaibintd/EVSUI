from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be a boolean value.")


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as ex:
        raise RuntimeError(f"{name} must be an integer.") from ex
    if value < minimum:
        raise RuntimeError(f"{name} must be at least {minimum}.")
    return value


def _env_float(name: str, default: float, *, minimum: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as ex:
        raise RuntimeError(f"{name} must be a number.") from ex
    if value < minimum:
        raise RuntimeError(f"{name} must be at least {minimum:g}.")
    return value


@dataclass(frozen=True)
class Settings:
    environment: str
    project_dir: Path
    database_path: Path
    credential_key: str
    credential_key_file: Path
    session_ttl_seconds: int
    external_api_enabled: bool
    external_api_token: str
    web_concurrency: int
    csrf_enabled: bool
    max_upload_bytes: int
    artifact_retention_days: int
    artifact_cleanup_enabled: bool
    job_stale_seconds: int
    vectorstore_ready_timeout_seconds: float
    vectorstore_ready_poll_seconds: float

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @classmethod
    def from_env(cls, *, project_dir: Path | None = None) -> "Settings":
        root = Path(project_dir or Path(__file__).resolve().parents[2]).expanduser().resolve()
        environment = str(os.getenv("EVSUI_ENVIRONMENT", "development")).strip().lower()
        if environment not in {"development", "test", "production"}:
            raise RuntimeError("EVSUI_ENVIRONMENT must be development, test, or production.")

        database_path = Path(
            os.getenv("EVSUI_DATABASE_PATH", str(root / "data" / "evsui.db"))
        ).expanduser().resolve()
        credential_key = str(os.getenv("EVSUI_CREDENTIAL_KEY", "")).strip()
        credential_key_file = Path(
            os.getenv("EVSUI_CREDENTIAL_KEY_FILE", str(database_path.with_suffix(".credentials.key")))
        ).expanduser().resolve()
        external_api_token = str(os.getenv("EVSUI_API_TOKEN", "")).strip()
        external_api_enabled = _env_bool("EVSUI_EXTERNAL_API_ENABLED", bool(external_api_token))

        if external_api_enabled and not external_api_token:
            raise RuntimeError(
                "EVSUI_API_TOKEN is required when EVSUI_EXTERNAL_API_ENABLED is true."
            )
        if environment == "production" and not credential_key and not os.getenv("EVSUI_CREDENTIAL_KEY_FILE"):
            raise RuntimeError(
                "Production requires EVSUI_CREDENTIAL_KEY or an explicit EVSUI_CREDENTIAL_KEY_FILE."
            )

        return cls(
            environment=environment,
            project_dir=root,
            database_path=database_path,
            credential_key=credential_key,
            credential_key_file=credential_key_file,
            session_ttl_seconds=_env_int("EVSUI_SESSION_TTL_SECONDS", 8 * 60 * 60, minimum=300),
            external_api_enabled=external_api_enabled,
            external_api_token=external_api_token,
            web_concurrency=_env_int("WEB_CONCURRENCY", 1),
            csrf_enabled=_env_bool("EVSUI_CSRF_ENABLED", True),
            max_upload_bytes=_env_int("EVSUI_MAX_UPLOAD_BYTES", 100 * 1024 * 1024),
            artifact_retention_days=_env_int("EVSUI_ARTIFACT_RETENTION_DAYS", 30),
            artifact_cleanup_enabled=_env_bool("EVSUI_ARTIFACT_CLEANUP_ENABLED", False),
            job_stale_seconds=_env_int("EVSUI_JOB_STALE_SECONDS", 15 * 60, minimum=60),
            vectorstore_ready_timeout_seconds=_env_float(
                "EVS_VECTORSTORE_READY_TIMEOUT_SECONDS", 7200.0, minimum=60.0
            ),
            vectorstore_ready_poll_seconds=_env_float(
                "EVS_VECTORSTORE_READY_POLL_SECONDS", 5.0, minimum=0.1
            ),
        )

    def validate_runtime(self) -> None:
        if self.web_concurrency != 1:
            raise RuntimeError(
                "EVSUI currently requires WEB_CONCURRENCY=1 because Teradata SDK context and UI session state are process-local."
            )
