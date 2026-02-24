from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable

TERADATA_IDENTIFIER_MAX_LEN = 30
UNSTRUCTURED_CONFIG_FILE_DEFAULT = Path(__file__).resolve().parents[1] / "config" / "unstructured.json"
UNSTRUCTURED_WORKFLOW_API_URL_DEFAULT = "https://platform.unstructuredapp.io/api/v1"
UNSTRUCTURED_WORKFLOW_POLL_SECONDS_DEFAULT = 120
UNSTRUCTURED_WORKFLOW_POLL_INTERVAL_DEFAULT = 2


ExecuteSqlFn = Callable[[str], Any]
ResolvePathFn = Callable[[str], str]


def normalize_document_files_for_create(
    create_payload: dict,
    resolve_path_hint: ResolvePathFn,
) -> tuple[dict, list[str]]:
    exec_payload = dict(create_payload)
    warnings: list[str] = []
    doc_files = exec_payload.get("document_files")
    if not doc_files:
        return exec_payload, warnings

    if isinstance(doc_files, str):
        raw_items = [doc_files]
    elif isinstance(doc_files, (list, tuple, set)):
        raw_items = [str(item).strip() for item in doc_files if str(item).strip()]
    else:
        raw_items = [str(doc_files).strip()]

    resolved_items: list[str] = []
    for raw in raw_items:
        resolved = resolve_path_hint(raw)
        resolved_items.append(resolved)
        if not Path(resolved).exists():
            warnings.append(f"Document file not found on disk: {raw}")

    # Always pass document_files as a list.
    # Some VectorStore runtimes iterate the value and will treat a single
    # string path like "C:\\..." as characters ("C", ":", "\\", ...).
    exec_payload["document_files"] = resolved_items

    return exec_payload, warnings


def _to_bool(raw: str, default: bool = False) -> bool:
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def _to_int(raw: str, default: int, minimum: int = 0, maximum: int | None = None) -> int:
    try:
        value = int(str(raw).strip())
    except Exception:
        return default
    if value < minimum:
        return default
    if maximum is not None and value > maximum:
        return maximum
    return value


def _sanitize_teradata_identifier(raw: str, fallback: str, allow_empty: bool = False) -> str:
    candidate = re.sub(r"[^0-9A-Za-z_]", "_", str(raw or "").strip())
    candidate = re.sub(r"_+", "_", candidate).strip("_")
    if not candidate:
        return "" if allow_empty else fallback
    if candidate[0].isdigit():
        candidate = f"t_{candidate}"
    if len(candidate) <= TERADATA_IDENTIFIER_MAX_LEN:
        return candidate
    digest = hashlib.sha1(candidate.encode("utf-8")).hexdigest()[:6]
    keep = max(1, TERADATA_IDENTIFIER_MAX_LEN - len(digest) - 1)
    return f"{candidate[:keep]}_{digest}"


def _split_object_name_hint(raw_object_name: str) -> tuple[str, str]:
    clean = str(raw_object_name or "").strip()
    if not clean:
        return "", ""
    if "." not in clean:
        return "", clean
    lhs, rhs = clean.rsplit(".", 1)
    return lhs.strip(), rhs.strip()


def _resolve_format_fusion_table_target(
    exec_payload: dict,
    create_values: dict[str, str],
    vector_store_name: str,
) -> tuple[str, str | None, str, list[str]]:
    warnings: list[str] = []
    raw_object_names = exec_payload.get("object_names")
    object_hint = ""
    if isinstance(raw_object_names, list):
        if raw_object_names:
            object_hint = str(raw_object_names[0]).strip()
        if len(raw_object_names) > 1:
            warnings.append("format_fusion uses only the first object_names entry.")
    elif raw_object_names is not None:
        object_hint = str(raw_object_names).strip()

    schema_hint, _table_hint_from_object = _split_object_name_hint(object_hint)
    target_database_raw = str(exec_payload.get("target_database") or create_values.get("target_database", "")).strip()
    if target_database_raw:
        schema_hint = target_database_raw
    table_hint = f"{vector_store_name}_unstructured"

    table_name = _sanitize_teradata_identifier(table_hint, fallback="unstructured")
    schema_name = _sanitize_teradata_identifier(schema_hint, fallback="", allow_empty=True) or None

    if table_name != table_hint:
        warnings.append(f"format_fusion table normalized to '{table_name}'.")
    if schema_hint and schema_name and schema_name != schema_hint:
        warnings.append(f"format_fusion target_database normalized to '{schema_name}'.")

    qualified = f"{schema_name}.{table_name}" if schema_name else table_name
    return table_name, schema_name, qualified, warnings


def _qualified_table_sql(schema_name: str | None, table_name: str) -> str:
    if schema_name:
        return f'"{schema_name}"."{table_name}"'
    return f'"{table_name}"'


def _cursor_first_scalar(cursor) -> str | int | None:
    if cursor is None:
        return None
    fetchone = getattr(cursor, "fetchone", None)
    if callable(fetchone):
        try:
            row = fetchone()
        except Exception:
            row = None
        if isinstance(row, dict):
            for value in row.values():
                return value
            return None
        if isinstance(row, (list, tuple)) and row:
            return row[0]
        if row is not None:
            return row

    fetchall = getattr(cursor, "fetchall", None)
    if callable(fetchall):
        try:
            rows = fetchall()
        except Exception:
            rows = []
        if not rows:
            return None
        first = rows[0]
        if isinstance(first, dict):
            for value in first.values():
                return value
            return None
        if isinstance(first, (list, tuple)) and first:
            return first[0]
        return first
    return None


def _teradata_table_exists(qualified_table_sql: str, execute_sql_fn: ExecuteSqlFn | None) -> bool:
    if execute_sql_fn is None:
        raise RuntimeError("teradataml.execute_sql is unavailable.")
    try:
        execute_sql_fn(f"SELECT TOP 1 1 FROM {qualified_table_sql}")
        return True
    except Exception as ex:
        msg = str(ex).lower()
        if "3807" in msg or "does not exist" in msg or "not found" in msg:
            return False
        raise


def _ensure_unstructured_teradata_table(
    schema_name: str | None,
    table_name: str,
    execute_sql_fn: ExecuteSqlFn | None,
    clear_rows: bool = True,
) -> list[str]:
    if execute_sql_fn is None:
        raise RuntimeError("teradataml.execute_sql is unavailable.")

    warnings: list[str] = []
    qualified_table = _qualified_table_sql(schema_name, table_name)
    table_exists = _teradata_table_exists(qualified_table, execute_sql_fn=execute_sql_fn)

    if not table_exists:
        create_sql = f"""
CREATE SET TABLE {qualified_table} (
  "id" VARCHAR(64) NOT NULL,
  PRIMARY KEY ("id"),
  "record_id" VARCHAR(64),
  "element_id" VARCHAR(64),
  "text" VARCHAR(32000) CHARACTER SET UNICODE,
  "type" VARCHAR(50),
  "embeddings" VARCHAR(32000),
  "last_modified" VARCHAR(50),
  "languages" VARCHAR(200),
  "file_directory" VARCHAR(500),
  "filename" VARCHAR(255),
  "filetype" VARCHAR(50),
  "record_locator" VARCHAR(1000),
  "date_created" VARCHAR(50),
  "date_modified" VARCHAR(50),
  "date_processed" VARCHAR(50),
  "permissions_data" VARCHAR(1000),
  "filesize_bytes" INTEGER,
  "parent_id" VARCHAR(64)
)
"""
        execute_sql_fn(create_sql)

    if clear_rows:
        try:
            execute_sql_fn(f"DELETE FROM {qualified_table}")
        except Exception as ex:
            warnings.append(f"Failed to clear destination table before run: {ex}")
    return warnings


def _count_teradata_rows(schema_name: str | None, table_name: str, execute_sql_fn: ExecuteSqlFn | None) -> int | None:
    if execute_sql_fn is None:
        return None
    qualified_table = _qualified_table_sql(schema_name, table_name)
    try:
        cursor = execute_sql_fn(f"SELECT COUNT(*) FROM {qualified_table}")
    except Exception:
        return None
    scalar = _cursor_first_scalar(cursor)
    if scalar is None:
        return None
    try:
        return int(scalar)
    except Exception:
        return None


def _workflow_file_inputs(document_files: list[str], resolve_path_hint: ResolvePathFn):
    from unstructured_client.models import shared

    inputs = []
    for path_hint in document_files:
        resolved = resolve_path_hint(path_hint)
        src = Path(resolved)
        if not src.exists() or not src.is_file():
            raise RuntimeError(f"format_fusion source file is missing: {path_hint}")
        inputs.append(
            shared.BodyRunWorkflowInputFiles(
                content=src.read_bytes(),
                file_name=src.name,
                content_type=mimetypes.guess_type(src.name)[0] or "application/octet-stream",
            )
        )
    return inputs


def _load_unstructured_runtime_config() -> tuple[str, str]:
    config_path = UNSTRUCTURED_CONFIG_FILE_DEFAULT
    config: dict[str, Any] = {}
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            if not isinstance(config, dict):
                raise RuntimeError("must be a JSON object")
        except Exception as ex:
            raise RuntimeError(f"Invalid Unstructured config at {config_path}: {ex}") from ex

    api_key = str(
        config.get("api_key")
        or config.get("key_id")
        or config.get("UNSTRUCTURED_API_KEY")
        or config.get("UNSTRUCTURED_API_KEY_AUTH")
        or ""
    ).strip()
    api_url = str(
        config.get("api_url")
        or config.get("UNSTRUCTURED_API_URL")
        or config.get("UNSTRUCTURED_PLATFORM_URL")
        or UNSTRUCTURED_WORKFLOW_API_URL_DEFAULT
    ).strip()

    if not api_key:
        raise RuntimeError(
            f"Unstructured API key missing. Set key_id/api_key in {config_path}."
        )
    if not api_url:
        api_url = UNSTRUCTURED_WORKFLOW_API_URL_DEFAULT
    return api_key, api_url


def _new_unstructured_client():
    api_key, api_url = _load_unstructured_runtime_config()
    from unstructured_client import UnstructuredClient

    return UnstructuredClient(api_key_auth=api_key, server_url=api_url.rstrip("/"))


def _create_teradata_destination_connector(client, connection_params: dict, database_name: str, table_name: str) -> str:
    from unstructured_client.models import operations, shared

    host = str(connection_params.get("host", "")).strip()
    username = str(connection_params.get("username", "")).strip()
    password = str(connection_params.get("password", ""))
    missing = []
    if not host:
        missing.append("host")
    if not username:
        missing.append("username")
    if not password:
        missing.append("password")
    if not database_name:
        missing.append("database")
    if missing:
        raise RuntimeError(f"format_fusion connector config missing: {', '.join(missing)}")

    destination_config = {
        "host": host,
        "database": database_name,
        "table_name": table_name,
        "batch_size": _to_int(os.getenv("UNSTRUCTURED_TERADATA_BATCH_SIZE", "200"), default=200, minimum=1, maximum=50000),
        "record_id_key": "record_id",
        "user": username,
        "password": password,
    }
    connector_name = f"evsui_ff_dest_{uuid.uuid4().hex[:10]}"

    resp = client.destinations.create_destination(
        request=operations.CreateDestinationRequest(
            create_destination_connector=shared.CreateDestinationConnector(
                name=connector_name,
                type="teradata",
                config=destination_config,
            )
        )
    )
    info = getattr(resp, "destination_connector_information", None)
    destination_id = str(getattr(info, "id", "")).strip() if info else ""
    if not destination_id:
        raise RuntimeError(f"Failed to create Teradata destination connector. status={getattr(resp, 'status_code', '?')}")
    return destination_id


def _create_unstructured_workflow(client, destination_id: str) -> str:
    from unstructured_client.models import operations, shared

    workflow_name = f"evsui_ff_workflow_{uuid.uuid4().hex[:10]}"
    resp = client.workflows.create_workflow(
        request=operations.CreateWorkflowRequest(
            create_workflow=shared.CreateWorkflow(
                name=workflow_name,
                workflow_type="basic",
                destination_id=destination_id,
            )
        )
    )
    info = getattr(resp, "workflow_information", None)
    workflow_id = str(getattr(info, "id", "")).strip() if info else ""
    if not workflow_id:
        raise RuntimeError(f"Failed to create workflow. status={getattr(resp, 'status_code', '?')}")
    return workflow_id


def _run_unstructured_workflow(client, workflow_id: str, document_files: list[str], resolve_path_hint: ResolvePathFn) -> str:
    from unstructured_client.models import operations, shared

    run_inputs = _workflow_file_inputs(document_files, resolve_path_hint=resolve_path_hint)
    resp = client.workflows.run_workflow(
        request=operations.RunWorkflowRequest(
            workflow_id=workflow_id,
            body_run_workflow=shared.BodyRunWorkflow(input_files=run_inputs),
        )
    )
    info = getattr(resp, "job_information", None)
    job_id = str(getattr(info, "id", "")).strip() if info else ""
    if not job_id:
        raise RuntimeError(f"Failed to start workflow run. status={getattr(resp, 'status_code', '?')}")
    return job_id


def _wait_for_unstructured_job(client, job_id: str, timeout_seconds: int, poll_interval_seconds: int) -> str:
    from unstructured_client.models import operations

    def _normalize_job_status(raw_status: Any) -> str:
        # SDK may return enum instances (e.g., JobStatus.COMPLETED) instead of plain strings.
        candidate = getattr(raw_status, "value", raw_status)
        status_text = str(candidate).strip() if candidate is not None else ""
        if not status_text:
            status_text = str(raw_status).strip() if raw_status is not None else "UNKNOWN"
        normalized = status_text.upper()
        if "." in normalized:
            normalized = normalized.rsplit(".", 1)[-1]
        return normalized or "UNKNOWN"

    started = time.time()
    last_status = "UNKNOWN"
    while True:
        resp = client.jobs.get_job(
            request=operations.GetJobRequest(
                job_id=job_id,
            )
        )
        info = getattr(resp, "job_information", None)
        current_status = _normalize_job_status(getattr(info, "status", last_status))
        last_status = current_status
        if current_status in {"COMPLETED", "SUCCESS"}:
            return current_status
        if current_status in {"FAILED", "STOPPED", "ERROR", "CANCELLED", "CANCELED"}:
            raise RuntimeError(f"Workflow job ended with status={current_status}. job_id={job_id}")

        if time.time() - started >= timeout_seconds:
            raise RuntimeError(
                f"Workflow job polling timed out after {timeout_seconds}s. last_status={last_status}, job_id={job_id}"
            )
        time.sleep(max(1, poll_interval_seconds))


def _cleanup_unstructured_resources(client, workflow_id: str, destination_id: str) -> list[str]:
    from unstructured_client.models import operations

    warnings: list[str] = []
    if workflow_id:
        try:
            client.workflows.delete_workflow(
                request=operations.DeleteWorkflowRequest(
                    workflow_id=workflow_id,
                )
            )
        except Exception as ex:
            warnings.append(f"Failed to delete workflow {workflow_id}: {ex}")
    if destination_id:
        try:
            client.destinations.delete_destination(
                request=operations.DeleteDestinationRequest(
                    destination_id=destination_id,
                )
            )
        except Exception as ex:
            warnings.append(f"Failed to delete destination connector {destination_id}: {ex}")
    return warnings


def apply_format_fusion_pipeline(
    exec_payload: dict,
    create_values: dict[str, str],
    vector_store_name: str,
    connection_params: dict | None = None,
    *,
    execute_sql_fn: ExecuteSqlFn | None,
    resolve_path_hint: ResolvePathFn,
) -> tuple[dict, dict]:
    connection_params = connection_params or {}

    raw_doc_files = exec_payload.get("document_files")
    if isinstance(raw_doc_files, str):
        document_files = [raw_doc_files]
    elif isinstance(raw_doc_files, (list, tuple, set)):
        document_files = [str(item).strip() for item in raw_doc_files if str(item).strip()]
    else:
        document_files = []
    if not document_files:
        raise RuntimeError("format_fusion requires at least one document file.")

    chunk_size = _to_int(create_values.get("fusion_chunk_size", "600"), default=600, minimum=100, maximum=8000)
    chunk_overlap = _to_int(create_values.get("fusion_chunk_overlap", "80"), default=80, minimum=0, maximum=2000)
    if chunk_overlap >= chunk_size:
        chunk_overlap = max(0, chunk_size // 5)

    table_name, schema_name, qualified_name, target_warnings = _resolve_format_fusion_table_target(
        exec_payload,
        create_values,
        vector_store_name,
    )
    database_name = schema_name or str(create_values.get("target_database", "")).strip()
    if not database_name:
        database_name = str(connection_params.get("username", "")).strip()
        if database_name:
            target_warnings.append(f"format_fusion target_database not set; fallback to '{database_name}'.")
    if not database_name:
        raise RuntimeError("format_fusion requires target_database (or object_names with schema prefix).")

    effective_schema_name = schema_name
    if not effective_schema_name:
        effective_schema_name = _sanitize_teradata_identifier(database_name, fallback="", allow_empty=True) or None
        if effective_schema_name:
            qualified_name = f"{effective_schema_name}.{table_name}"

    target_warnings.extend(
        _ensure_unstructured_teradata_table(
            schema_name=effective_schema_name,
            table_name=table_name,
            execute_sql_fn=execute_sql_fn,
            clear_rows=True,
        )
    )

    client = _new_unstructured_client()
    destination_id = ""
    workflow_id = ""
    job_id = ""
    cleanup_warnings: list[str] = []
    try:
        destination_id = _create_teradata_destination_connector(
            client,
            connection_params=connection_params,
            database_name=database_name,
            table_name=table_name,
        )
        workflow_id = _create_unstructured_workflow(client, destination_id=destination_id)
        job_id = _run_unstructured_workflow(
            client,
            workflow_id=workflow_id,
            document_files=document_files,
            resolve_path_hint=resolve_path_hint,
        )

        timeout_seconds = _to_int(
            os.getenv("UNSTRUCTURED_WORKFLOW_POLL_SECONDS", str(UNSTRUCTURED_WORKFLOW_POLL_SECONDS_DEFAULT)),
            default=UNSTRUCTURED_WORKFLOW_POLL_SECONDS_DEFAULT,
            minimum=10,
            maximum=1800,
        )
        poll_interval_seconds = _to_int(
            os.getenv("UNSTRUCTURED_WORKFLOW_POLL_INTERVAL", str(UNSTRUCTURED_WORKFLOW_POLL_INTERVAL_DEFAULT)),
            default=UNSTRUCTURED_WORKFLOW_POLL_INTERVAL_DEFAULT,
            minimum=1,
            maximum=30,
        )
        _wait_for_unstructured_job(
            client,
            job_id=job_id,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
    finally:
        keep_resources = _to_bool(os.getenv("UNSTRUCTURED_KEEP_WORKFLOW_RESOURCES", "false"), default=False)
        if not keep_resources and (workflow_id or destination_id):
            cleanup_warnings.extend(
                _cleanup_unstructured_resources(
                    client,
                    workflow_id=workflow_id,
                    destination_id=destination_id,
                )
            )

    row_count = _count_teradata_rows(schema_name=effective_schema_name, table_name=table_name, execute_sql_fn=execute_sql_fn)
    chunk_count = row_count if row_count is not None else 0

    patched_payload = dict(exec_payload)
    patched_payload["object_names"] = qualified_name
    patched_payload["data_columns"] = ["text"]
    patched_payload.setdefault("key_columns", ["id"])
    patched_payload["chunk_size"] = chunk_size
    patched_payload["optimized_chunking"] = False
    patched_payload.pop("document_files", None)

    summary = {
        "table_name": qualified_name,
        "chunk_count": chunk_count,
        "document_count": len(document_files),
        "job_id": job_id,
        "workflow_id": workflow_id,
        "destination_id": destination_id,
        "warnings": target_warnings + cleanup_warnings,
        "workflow_mode": "teradata-sql destination",
        "chunk_overlap": chunk_overlap,
    }
    return patched_payload, summary
