from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from app.core.security import redact_sensitive_text, sensitive_values
from app.teradata_runtime import (
    TERADATA_IMPORT_ERROR,
    VSManager,
    create_context,
    execute_sql,
    remove_context,
    set_auth_token,
)


def _cleanup_runtime() -> None:
    if VSManager is not None:
        try:
            VSManager.disconnect(raise_error=False)
        except Exception:
            pass
    if remove_context is not None:
        try:
            remove_context()
        except Exception:
            pass


def _base_url(ues_url: str) -> str:
    value = str(ues_url or "").strip().rstrip("/")
    suffix = "/open-analytics"
    return value[: -len(suffix)] if value.endswith(suffix) else value


@contextmanager
def activated_connection(auth_store, profile_id: int | None) -> Iterator[dict[str, Any]]:
    """Activate exactly one stored profile inside a dedicated worker process."""
    if profile_id is None:
        raise RuntimeError("The queued operation has no database connection profile.")
    if create_context is None or set_auth_token is None or execute_sql is None:
        raise RuntimeError(f"Teradata runtime is unavailable: {TERADATA_IMPORT_ERROR}")
    profile = auth_store.get_connection_profile(int(profile_id))
    if profile is None:
        raise RuntimeError("The database connection selected for this job no longer exists.")
    required = ("host", "username", "password", "ues_url", "pat_token")
    missing = [name for name in required if not str(profile.get(name) or "").strip()]
    if missing:
        raise RuntimeError("The selected database connection is incomplete: " + ", ".join(missing))

    auth_kwargs = {
        "base_url": _base_url(str(profile["ues_url"])),
        "pat_token": str(profile["pat_token"]),
    }
    pem_file = str(profile.get("pem_file") or "").strip()
    if pem_file:
        auth_kwargs["pem_file"] = pem_file

    _cleanup_runtime()
    try:
        create_context(
            host=str(profile["host"]),
            username=str(profile["username"]),
            password=str(profile["password"]),
        )
        set_auth_token(**auth_kwargs)
        yield {"profile": profile, "execute_sql": execute_sql}
    except Exception as ex:
        raise RuntimeError(
            redact_sensitive_text(ex, secrets=sensitive_values(profile))
        ) from None
    finally:
        _cleanup_runtime()
