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
UNSTRUCTURED_TERADATA_FLUSH_WAIT_SECONDS_DEFAULT = 20
UNSTRUCTURED_TERADATA_FLUSH_WAIT_INTERVAL_DEFAULT = 2
UNSTRUCTURED_DEBUG_DIR_DEFAULT = Path(__file__).resolve().parents[2] / "uploads" / "unstructured_debug"
BOOKRAG_PDF_IMAGE_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".bmp",
    ".gif",
    ".webp",
}


ExecuteSqlFn = Callable[[str], Any]
ResolvePathFn = Callable[[str], str]


UNSTRUCTURED_CHUNK_COLUMNS: list[tuple[str, str]] = [
    ("id", 'VARCHAR(64) NOT NULL'),
    ("record_id", "VARCHAR(64)"),
    ("element_id", "VARCHAR(64)"),
    ("text", "VARCHAR(32000) CHARACTER SET UNICODE"),
    ("type", "VARCHAR(50)"),
    ("last_modified", "VARCHAR(50)"),
    ("file_directory", "VARCHAR(500)"),
    ("filename", "VARCHAR(255)"),
    ("filetype", "VARCHAR(50)"),
    ("record_locator", "VARCHAR(1000)"),
    ("date_created", "VARCHAR(50)"),
    ("date_modified", "VARCHAR(50)"),
    ("date_processed", "VARCHAR(50)"),
    ("permissions_data", "VARCHAR(1000)"),
    ("filesize_bytes", "INTEGER"),
    ("parent_id", "VARCHAR(64)"),
]


def _build_unstructured_table_ddl(
    qualified_table: str,
) -> str:
    column_lines: list[str] = ['  "id" VARCHAR(64) NOT NULL', '  PRIMARY KEY ("id")']
    for name, col_type in UNSTRUCTURED_CHUNK_COLUMNS:
        if name == "id":
            continue
        column_lines.append(f'  "{name}" {col_type}')
    ddl_body = ",\n".join(column_lines)
    return f"""
CREATE SET TABLE {qualified_table} (
{ddl_body}
)
"""


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


def _base_vector_store_name(raw_name: str) -> str:
    name = str(raw_name or "").strip()
    if not name:
        return ""
    lowered = name.lower()
    for suffix in ("_unstructured", "_unstractured"):
        if lowered.endswith(suffix):
            trimmed = name[: -len(suffix)].strip().strip("_")
            return trimmed or name
    return name


def _resolve_multi_format_table_target(
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
            warnings.append("multi format uses only the first object_names entry.")
    elif raw_object_names is not None:
        object_hint = str(raw_object_names).strip()

    schema_hint, _table_hint_from_object = _split_object_name_hint(object_hint)
    target_database_raw = str(exec_payload.get("target_database") or create_values.get("target_database", "")).strip()
    if target_database_raw:
        schema_hint = target_database_raw
    vs_base_name = _base_vector_store_name(vector_store_name) or vector_store_name
    table_hint = f"{vs_base_name}_unstructured"

    table_name = _sanitize_teradata_identifier(table_hint, fallback="unstructured")
    schema_name = _sanitize_teradata_identifier(schema_hint, fallback="", allow_empty=True) or None

    if table_name != table_hint:
        warnings.append(f"multi format table normalized to '{table_name}'.")
    if schema_hint and schema_name and schema_name != schema_hint:
        warnings.append(f"multi format target_database normalized to '{schema_name}'.")

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
            try:
                return row[0]  # tuple-like row wrappers
            except Exception:
                pass
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
        try:
            return first[0]  # tuple-like row wrappers
        except Exception:
            pass
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


def _teradata_column_exists(
    schema_name: str | None,
    table_name: str,
    column_name: str,
    execute_sql_fn: ExecuteSqlFn | None,
) -> bool:
    if execute_sql_fn is None:
        raise RuntimeError("teradataml.execute_sql is unavailable.")
    qualified_table = _qualified_table_sql(schema_name, table_name)
    quoted_column = column_name.replace('"', '""')
    try:
        execute_sql_fn(f'SELECT TOP 1 "{quoted_column}" FROM {qualified_table}')
        return True
    except Exception as ex:
        msg = str(ex).lower()
        if "3810" in msg or ("column" in msg and ("does not exist" in msg or "not found" in msg)):
            return False
        raise


def _drop_teradata_column_if_exists(
    schema_name: str | None,
    table_name: str,
    column_name: str,
    execute_sql_fn: ExecuteSqlFn | None,
) -> bool:
    if execute_sql_fn is None:
        raise RuntimeError("teradataml.execute_sql is unavailable.")
    if not _teradata_column_exists(
        schema_name=schema_name,
        table_name=table_name,
        column_name=column_name,
        execute_sql_fn=execute_sql_fn,
    ):
        return False
    qualified_table = _qualified_table_sql(schema_name, table_name)
    quoted_column = column_name.replace('"', '""')
    execute_sql_fn(f'ALTER TABLE {qualified_table} DROP "{quoted_column}"')
    return True


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
        create_sql = _build_unstructured_table_ddl(
            qualified_table=qualified_table,
        )
        execute_sql_fn(create_sql)
    else:
        # Remove legacy column from previous schema versions.
        try:
            _drop_teradata_column_if_exists(
                schema_name=schema_name,
                table_name=table_name,
                column_name="languages",
                execute_sql_fn=execute_sql_fn,
            )
        except Exception as ex:
            warnings.append(f'Failed to drop legacy column "languages": {ex}')

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


def _wait_for_table_rows(
    schema_name: str | None,
    table_name: str,
    execute_sql_fn: ExecuteSqlFn | None,
    timeout_seconds: int,
    poll_interval_seconds: int,
) -> int:
    started = time.time()
    last_count = 0
    while True:
        current = _count_teradata_rows(
            schema_name=schema_name,
            table_name=table_name,
            execute_sql_fn=execute_sql_fn,
        )
        if current is not None:
            last_count = current
            if current > 0:
                return current
        if time.time() - started >= timeout_seconds:
            return last_count
        time.sleep(max(1, poll_interval_seconds))


def _parse_langs(raw: str) -> list[str]:
    items = [chunk.strip() for chunk in str(raw or "").replace("\n", ",").split(",") if chunk.strip()]
    return items


def _resolve_partition_strategy(raw: str) -> str:
    value = str(raw or "auto").strip().lower()
    if value == "fast":
        return "fast"
    if value == "layout":
        return "hi_res"
    return "auto"


def _now_ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _safe_stem(src: Path) -> str:
    stem = re.sub(r"[^0-9A-Za-z._-]", "_", src.stem.strip())
    return stem or "document"


def _prepare_unstructured_debug_dir(vector_store_name: str) -> Path:
    vs_name = _sanitize_teradata_identifier(vector_store_name, fallback="bookrag")
    run_id = time.strftime("%Y%m%d_%H%M%S")
    debug_dir = UNSTRUCTURED_DEBUG_DIR_DEFAULT / f"{vs_name}_{run_id}"
    debug_dir.mkdir(parents=True, exist_ok=True)
    return debug_dir


def _write_unstructured_debug_file(
    debug_dir: Path | None,
    src: Path,
    raw_elements: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    request_parameters: dict[str, Any],
) -> str | None:
    if debug_dir is None:
        return None
    payload = {
        "source_file": str(src),
        "saved_at": _now_ts(),
        "raw_element_count": len(raw_elements),
        "row_count": len(rows),
        "request_parameters": _json_safe_value(request_parameters),
        "raw_elements": raw_elements,
        "table_rows": rows,
    }
    out_path = debug_dir / f"{_safe_stem(src)}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(out_path)


def _json_safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return {"type": "bytes", "length": len(value)}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe_value(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe_value(item) for item in value]
    return str(value)


def _bookrag_partition_options_for_file(
    src: Path,
    default_strategy: str,
    default_languages: list[str],
) -> tuple[str, list[str], bool]:
    suffix = src.suffix.lower()
    include_orig_elements = True
    if suffix in BOOKRAG_PDF_IMAGE_EXTENSIONS:
        return "hi_res", ["jpn"], include_orig_elements
    return default_strategy, default_languages or ["jpn"], include_orig_elements


def _as_text(value: Any, max_len: int | None = None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value
    elif isinstance(value, (dict, list, tuple)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)
    text = text.strip()
    if not text:
        return None
    if max_len is not None and len(text) > max_len:
        return text[:max_len]
    return text


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    text = str(value).replace("'", "''")
    return f"'{text}'"


def _element_to_chunk_row(element: dict[str, Any], src: Path, content_type: str) -> dict[str, Any] | None:
    metadata = element.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    text = _as_text(element.get("text"), max_len=32000)
    if not text:
        return None

    row_id = uuid.uuid4().hex
    element_id = _as_text(element.get("element_id") or element.get("id"), max_len=64)
    record_id = _as_text(metadata.get("record_id") or element_id or row_id, max_len=64)
    filetype = _as_text(metadata.get("filetype"), max_len=50) or _as_text(content_type, max_len=50)

    row = {
        "id": row_id,
        "record_id": record_id,
        "element_id": element_id,
        "text": text,
        "type": _as_text(element.get("type"), max_len=50),
        "last_modified": _as_text(metadata.get("last_modified"), max_len=50),
        "file_directory": _as_text(metadata.get("file_directory") or str(src.parent), max_len=500),
        "filename": _as_text(metadata.get("filename") or src.name, max_len=255),
        "filetype": filetype,
        "record_locator": _as_text(metadata.get("record_locator") or metadata.get("url") or metadata.get("source"), max_len=1000),
        "date_created": _as_text(metadata.get("date_created"), max_len=50),
        "date_modified": _as_text(metadata.get("date_modified"), max_len=50),
        "date_processed": _now_ts(),
        "permissions_data": _as_text(metadata.get("permissions_data") or metadata.get("permissions"), max_len=1000),
        "filesize_bytes": _as_int(metadata.get("filesize_bytes") or metadata.get("file_size") or src.stat().st_size),
        "parent_id": _as_text(metadata.get("parent_id"), max_len=64),
    }
    return row


def _partition_document_chunks(
    client,
    src: Path,
    *,
    chunk_size: int,
    chunk_overlap: int,
    partition_strategy: str,
    languages: list[str],
    include_orig_elements: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    from unstructured_client.models import operations

    content_type = mimetypes.guess_type(src.name)[0] or "application/octet-stream"
    partition_parameters: dict[str, Any] = {
        "files": {
            "content": src.read_bytes(),
            "file_name": src.name,
            "content_type": content_type,
        },
        "strategy": partition_strategy,
        "chunking_strategy": "basic",
        "max_characters": chunk_size,
        "new_after_n_chars": chunk_size,
        "overlap": chunk_overlap,
        "overlap_all": False,
        "include_orig_elements": include_orig_elements,
    }
    if languages:
        partition_parameters["languages"] = languages

    resp = client.general.partition(
        request=operations.PartitionRequest(
            partition_parameters=partition_parameters,
        )
    )
    if int(getattr(resp, "status_code", 0) or 0) >= 400:
        raise RuntimeError(f"Unstructured partition failed. status={getattr(resp, 'status_code', '?')}")
    elements = getattr(resp, "elements", None) or []
    rows: list[dict[str, Any]] = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        row = _element_to_chunk_row(element, src=src, content_type=content_type)
        if row:
            rows.append(row)
    return rows, elements, partition_parameters


def _insert_chunk_rows(
    schema_name: str | None,
    table_name: str,
    rows: list[dict[str, Any]],
    execute_sql_fn: ExecuteSqlFn | None,
) -> int:
    if execute_sql_fn is None:
        raise RuntimeError("teradataml.execute_sql is unavailable.")
    if not rows:
        return 0
    qualified_table = _qualified_table_sql(schema_name, table_name)
    columns = [name for name, _ in UNSTRUCTURED_CHUNK_COLUMNS]
    quoted_cols = ", ".join(f'"{name}"' for name in columns)
    inserted = 0
    for row in rows:
        values_sql = ", ".join(_sql_literal(row.get(col)) for col in columns)
        execute_sql_fn(f"INSERT INTO {qualified_table} ({quoted_cols}) VALUES ({values_sql})")
        inserted += 1
    return inserted


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


def apply_multi_format_pipeline(
    exec_payload: dict,
    create_values: dict[str, str],
    vector_store_name: str,
    connection_params: dict | None = None,
    *,
    execute_sql_fn: ExecuteSqlFn | None,
    resolve_path_hint: ResolvePathFn,
    pipeline_mode: str = "multi_format",
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
        raise RuntimeError("multi format requires at least one document file.")

    chunk_size = _to_int(create_values.get("multi_format_chunk_size", "600"), default=600, minimum=100, maximum=8000)
    chunk_overlap = _to_int(create_values.get("multi_format_chunk_overlap", "80"), default=80, minimum=0, maximum=2000)
    if chunk_overlap >= chunk_size:
        chunk_overlap = max(0, chunk_size // 5)
    partition_strategy = _resolve_partition_strategy(create_values.get("multi_format_strategy", "auto"))
    ocr_languages = _parse_langs(create_values.get("multi_format_ocr_languages", ""))
    include_orig_elements = False

    table_name, schema_name, qualified_name, target_warnings = _resolve_multi_format_table_target(
        exec_payload,
        create_values,
        vector_store_name,
    )
    database_name = schema_name or str(create_values.get("target_database", "")).strip()
    if not database_name:
        database_name = str(connection_params.get("username", "")).strip()
        if database_name:
            target_warnings.append(f"multi format target_database not set; fallback to '{database_name}'.")
    if not database_name:
        raise RuntimeError("multi format requires target_database (or object_names with schema prefix).")

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
    debug_dir = _prepare_unstructured_debug_dir(vector_store_name) if pipeline_mode == "multi_format_bookrag" else None
    inserted_rows = 0
    partition_warnings: list[str] = []
    debug_files: list[str] = []
    for path_hint in document_files:
        resolved = resolve_path_hint(path_hint)
        src = Path(resolved)
        if not src.exists() or not src.is_file():
            raise RuntimeError(f"multi format source file is missing: {path_hint}")
        file_partition_strategy = partition_strategy
        file_ocr_languages = ocr_languages
        file_include_orig_elements = include_orig_elements
        if pipeline_mode == "multi_format_bookrag":
            (
                file_partition_strategy,
                file_ocr_languages,
                file_include_orig_elements,
            ) = _bookrag_partition_options_for_file(
                src,
                default_strategy=partition_strategy,
                default_languages=ocr_languages,
            )
        rows, raw_elements, request_parameters = _partition_document_chunks(
            client,
            src,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            partition_strategy=file_partition_strategy,
            languages=file_ocr_languages,
            include_orig_elements=file_include_orig_elements,
        )
        debug_file = _write_unstructured_debug_file(debug_dir, src, raw_elements, rows, request_parameters)
        if debug_file:
            debug_files.append(debug_file)
        if not rows:
            partition_warnings.append(f"No chunks extracted from file: {src.name}")
            continue
        inserted_rows += _insert_chunk_rows(
            schema_name=effective_schema_name,
            table_name=table_name,
            rows=rows,
            execute_sql_fn=execute_sql_fn,
        )

    flush_wait_seconds = _to_int(
        os.getenv("UNSTRUCTURED_TERADATA_FLUSH_WAIT_SECONDS", str(UNSTRUCTURED_TERADATA_FLUSH_WAIT_SECONDS_DEFAULT)),
        default=UNSTRUCTURED_TERADATA_FLUSH_WAIT_SECONDS_DEFAULT,
        minimum=1,
        maximum=300,
    )
    flush_wait_interval_seconds = _to_int(
        os.getenv("UNSTRUCTURED_TERADATA_FLUSH_WAIT_INTERVAL", str(UNSTRUCTURED_TERADATA_FLUSH_WAIT_INTERVAL_DEFAULT)),
        default=UNSTRUCTURED_TERADATA_FLUSH_WAIT_INTERVAL_DEFAULT,
        minimum=1,
        maximum=30,
    )
    chunk_count = _wait_for_table_rows(
        schema_name=effective_schema_name,
        table_name=table_name,
        execute_sql_fn=execute_sql_fn,
        timeout_seconds=flush_wait_seconds,
        poll_interval_seconds=flush_wait_interval_seconds,
    )
    if chunk_count <= 0:
        raise RuntimeError(
            "multi format partition completed but destination table has 0 rows. "
            f"table={qualified_name}"
        )

    patched_payload = dict(exec_payload)
    patched_payload["object_names"] = qualified_name
    patched_payload["data_columns"] = ["text"]
    patched_payload.setdefault("key_columns", ["id"])

    # multi format already writes chunked content into Teradata.
    # For content-based vector store creation, chunking inputs must be omitted.
    patched_payload.pop("chunk_size", None)
    patched_payload.pop("optimized_chunking", None)
    patched_payload.pop("header_height", None)
    patched_payload.pop("footer_height", None)
    patched_payload.pop("document_files", None)

    summary = {
        "table_name": qualified_name,
        "chunk_count": chunk_count,
        "document_count": len(document_files),
        "job_id": "",
        "workflow_id": "",
        "destination_id": "",
        "warnings": target_warnings + partition_warnings,
        "workflow_mode": "partition-api direct insert",
        "inserted_rows": inserted_rows,
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "debug_dir": str(debug_dir) if debug_dir else "",
        "debug_files": debug_files,
        "effective_partition_strategy": partition_strategy,
        "effective_ocr_languages": ocr_languages,
        "include_orig_elements": include_orig_elements,
        "file_mode": (
            "per-extension"
            if pipeline_mode == "multi_format_bookrag"
            else "shared"
        ),
    }
    return patched_payload, summary
