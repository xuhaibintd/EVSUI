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

from app.services.teradata_sql import (
    ExecuteSqlFn,
    _count_teradata_rows,
    _qualified_table_sql,
    _sanitize_teradata_text,
    _sql_typed_literal,
    _teradata_table_exists,
)
from app.services.unstructured_runtime import (
    BOOKRAG_CSV_STAGE_DIR_DEFAULT,
    BOOKRAG_PDF_IMAGE_EXTENSIONS,
    BOOKRAG_RAW_STAGE_DIR_DEFAULT,
    EXCEL_EXTENSIONS,
    UNSTRUCTURED_DEBUG_DIR_DEFAULT,
    UNSTRUCTURED_FAST_UNSAFE_IMAGE_EXTENSIONS,
    UNSTRUCTURED_TERADATA_FLUSH_WAIT_INTERVAL_DEFAULT,
    UNSTRUCTURED_TERADATA_FLUSH_WAIT_SECONDS_DEFAULT,
    _env_flag,
    _load_unstructured_runtime_config,
    _load_unstructured_runtime_settings,
    _parse_langs,
    _resolve_bookrag_workflow_poll_config,
    _resolve_unstructured_request_timeout_ms,
    _resolve_multi_format_workflow_poll_config,
    _resolve_partition_strategy,
)

from app.services.bookrag_reconcile import reconcile_unstructured_elements
from app.services.bookrag_graph import build_bookrag_entities
from app.services.bookrag_schema import (
    build_bookrag_table_targets,
    prepare_bookrag_block_table,
    prepare_bookrag_document_table,
    prepare_bookrag_entity_link_table,
    prepare_bookrag_entity_relation_table,
    prepare_bookrag_entity_table,
    prepare_bookrag_node_table,
    prepare_bookrag_raw_table,
)
from app.services.bookrag_tree import build_bookrag_nodes, elements_to_bookrag_blocks
from app.services.bookrag_storage import (
    build_bookrag_document_row,
    build_bookrag_raw_rows,
    load_bookrag_raw_stage_file,
    persist_bookrag_blocks,
    persist_bookrag_entities,
    persist_bookrag_entity_links,
    persist_bookrag_entity_relations,
    persist_bookrag_nodes,
    persist_bookrag_documents,
    persist_bookrag_raw_rows,
    write_bookrag_raw_stage_file,
)
from app.services.unstructured_job_runner import (
    create_unstructured_client as _create_unstructured_client,
    enforce_unstructured_job_submission_spacing as _enforce_unstructured_job_submission_spacing,
    run_unstructured_workflow_job_for_file as _run_unstructured_workflow_job_for_file,
)
from app.services.unstructured_workflow_builder import (
    build_bookrag_reusable_workflow_definition as _workflow_builder_build_bookrag_reusable_workflow_definition,
    build_bookrag_workflow_partition_node as _workflow_builder_build_bookrag_workflow_partition_node,
    build_multi_format_workflow_definition as _workflow_builder_build_multi_format_workflow_definition,
)

TERADATA_IDENTIFIER_MAX_LEN = 30
FILE_BASED_CREATE_KEYS_TO_REMOVE = {
    "chunk_size",
    "chunk_overlap",
    "optimized_chunking",
    "header_height",
    "footer_height",
    "document_files",
    "ingestor",
    "ingest_params",
    "nv_ingestor",
    "ingest_host",
    "ingest_port",
    "display_metadata",
    "extract_text",
    "extract_images",
    "extract_tables",
    "extract_infographics",
    "extract_method",
    "extract_metadata_json",
    "extract_caption",
    "tokenizer",
    "vlm_model",
    "vlm_base_url",
    "hf_access_token",
}


UNSTRUCTURED_CHUNK_COLUMNS: list[tuple[str, str]] = [
    ("text", "VARCHAR(32000) CHARACTER SET UNICODE"),
    ("type", "VARCHAR(50) CHARACTER SET UNICODE"),
    ("filename", "VARCHAR(255) CHARACTER SET UNICODE"),
    ("element_id", "VARCHAR(64) CHARACTER SET UNICODE"),
    ("id", 'VARCHAR(64) NOT NULL'),
    ("table_id", "VARCHAR(128) CHARACTER SET UNICODE"),
    ("chunk_index", "INTEGER"),
    ("is_continuation", "BYTEINT"),
    ("num_carried_over_header_rows", "INTEGER"),
    ("partitioner_type", "VARCHAR(100) CHARACTER SET UNICODE"),
    ("image_description", "VARCHAR(32000) CHARACTER SET UNICODE"),
    ("table_description", "VARCHAR(32000) CHARACTER SET UNICODE"),
    ("generative_ocr", "VARCHAR(32000) CHARACTER SET UNICODE"),
    ("table_to_html", "VARCHAR(32000) CHARACTER SET UNICODE"),
    ("filetype", "VARCHAR(50) CHARACTER SET UNICODE"),
    ("date_processed", "VARCHAR(50)"),
]

BOOKRAG_TABLE_TOGGLE_FIELDS: dict[str, str] = {
    "documents": "multi_format_bookrag_generate_documents",
    "raw": "multi_format_bookrag_generate_raw",
    "blocks": "multi_format_bookrag_generate_blocks",
    "nodes": "multi_format_bookrag_generate_nodes",
    "entities": "multi_format_bookrag_generate_entities",
    "entity_links": "multi_format_bookrag_generate_entity_links",
    "entity_relations": "multi_format_bookrag_generate_entity_relations",
}

BOOKRAG_TABLE_TOGGLE_DEFAULTS: dict[str, bool] = {
    "documents": True,
    "raw": True,
    "blocks": True,
    "nodes": True,
    "entities": False,
    "entity_links": False,
    "entity_relations": False,
}

BOOKRAG_TABLE_TOGGLE_ORDER: tuple[str, ...] = (
    "documents",
    "raw",
    "blocks",
    "nodes",
    "entities",
    "entity_links",
    "entity_relations",
)

BOOKRAG_ENTITY_TABLE_KEYS: tuple[str, ...] = ("entities", "entity_links", "entity_relations")


def _build_unstructured_table_ddl(
    qualified_table: str,
) -> str:
    column_lines = [f'  "{name}" {col_type}' for name, col_type in UNSTRUCTURED_CHUNK_COLUMNS]
    column_lines.append('  PRIMARY KEY ("id")')
    ddl_body = ",\n".join(column_lines)
    return f"""
CREATE SET TABLE {qualified_table} (
{ddl_body}
)
"""


def _resolve_bookrag_table_generation_flags(create_values: dict[str, str]) -> dict[str, bool]:
    flags: dict[str, bool] = {}
    for table_key in BOOKRAG_TABLE_TOGGLE_ORDER:
        field_name = BOOKRAG_TABLE_TOGGLE_FIELDS[table_key]
        default_value = BOOKRAG_TABLE_TOGGLE_DEFAULTS[table_key]
        flags[table_key] = _to_bool(
            create_values.get(field_name, "true" if default_value else "false"),
            default=default_value,
        )
    if not any(flags.values()):
        raise RuntimeError("At least one BookRAG table generation toggle must be enabled.")
    return flags


def _resolve_bookrag_embedding_step_flag(create_values: dict[str, str]) -> bool:
    return _to_bool(create_values.get("multi_format_bookrag_run_embedding", "false"), default=False)


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


def _to_bool(raw: Any, default: bool = False) -> bool:
    if raw is None:
        return default
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off", ""}:
        return False
    return default


def _parse_csv_values(raw: Any) -> list[str]:
    return [chunk.strip() for chunk in str(raw or "").split(",") if chunk.strip()]


def _first_defined(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _format_chunk_row_id(row_sequence: int | None) -> str:
    if row_sequence is None or row_sequence <= 0:
        return uuid.uuid4().hex
    return f"{row_sequence:012d}"


def _resolve_bookrag_image_partition_options(create_values: dict[str, str]) -> tuple[dict[str, Any], list[str], dict[str, Any]]:
    runtime = _load_unstructured_runtime_settings()
    warnings: list[str] = []

    raw_extract_types = str(
        _first_defined(
            create_values.get("multi_format_bookrag_extract_image_block_types", ""),
            runtime.get("bookrag_extract_image_block_types"),
            os.getenv("BOOKRAG_EXTRACT_IMAGE_BLOCK_TYPES", ""),
        )
        or ""
    ).strip()
    extract_mode = raw_extract_types.lower()
    if extract_mode == "auto":
        extract_image_block_types = ["Image", "Table"]
    else:
        extract_image_block_types = _parse_csv_values(raw_extract_types)

    raw_infer_table_structure = str(
        _first_defined(
            create_values.get("multi_format_bookrag_infer_table_structure", ""),
            runtime.get("bookrag_infer_table_structure"),
            os.getenv("BOOKRAG_INFER_TABLE_STRUCTURE", ""),
        )
        or ""
    ).strip()
    infer_table_structure = _to_bool(raw_infer_table_structure, default=False)

    coordinates = _to_bool(
        _first_defined(
            create_values.get("multi_format_bookrag_coordinates", "true"),
            runtime.get("bookrag_coordinates"),
            os.getenv("BOOKRAG_COORDINATES", "true"),
        ),
        default=True,
    )
    unique_element_ids = _to_bool(
        _first_defined(
            runtime.get("bookrag_unique_element_ids"),
            os.getenv("BOOKRAG_UNIQUE_ELEMENT_IDS", "true"),
        ),
        default=True,
    )
    hi_res_model_name = str(
        _first_defined(
            create_values.get("multi_format_bookrag_hi_res_model_name", ""),
            runtime.get("bookrag_hi_res_model_name"),
            os.getenv("BOOKRAG_HI_RES_MODEL_NAME", ""),
        )
        or ""
    ).strip()
    vlm_provider = str(
        _first_defined(
            create_values.get("multi_format_bookrag_vlm_provider", ""),
            runtime.get("bookrag_vlm_provider"),
            os.getenv("BOOKRAG_VLM_PROVIDER", ""),
        )
        or ""
    ).strip()
    vlm_model = str(
        _first_defined(
            create_values.get("multi_format_bookrag_vlm_model", ""),
            runtime.get("bookrag_vlm_model"),
            os.getenv("BOOKRAG_VLM_MODEL", ""),
        )
        or ""
    ).strip()
    vlm_provider_api_key = str(
        _first_defined(
            create_values.get("multi_format_bookrag_vlm_provider_api_key", ""),
            runtime.get("bookrag_vlm_provider_api_key"),
            os.getenv("BOOKRAG_VLM_PROVIDER_API_KEY", ""),
        )
        or ""
    ).strip()

    extra: dict[str, Any] = {
        "coordinates": coordinates,
        "unique_element_ids": unique_element_ids,
        "infer_table_structure": infer_table_structure,
        "vlm_provider": vlm_provider or None,
        "vlm_model": vlm_model or None,
        "vlm_provider_api_key": vlm_provider_api_key or None,
    }
    if extract_image_block_types:
        extra["extract_image_block_types"] = extract_image_block_types
    else:
        warnings.append("bookrag extract_image_block_types is off; image/table block extraction is disabled by default for faster raw ingestion.")
    if hi_res_model_name:
        extra["hi_res_model_name"] = hi_res_model_name

    summary = {
        "coordinates": coordinates,
        "extract_image_block_mode": raw_extract_types or None,
        "extract_image_block_types": extract_image_block_types,
        "unique_element_ids": unique_element_ids,
        "hi_res_model_name": hi_res_model_name or None,
        "infer_table_structure": infer_table_structure,
        "vlm_provider": vlm_provider or None,
        "vlm_model": vlm_model or None,
        "vlm_provider_api_key_configured": bool(vlm_provider_api_key),
    }
    return extra, warnings, summary


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


def _ensure_unstructured_unicode_columns(
    schema_name: str | None,
    table_name: str,
    execute_sql_fn: ExecuteSqlFn | None,
) -> list[str]:
    if execute_sql_fn is None:
        raise RuntimeError("teradataml.execute_sql is unavailable.")
    qualified_table = _qualified_table_sql(schema_name, table_name)
    warnings: list[str] = []
    for column_name, column_type in UNSTRUCTURED_CHUNK_COLUMNS:
        if "CHARACTER SET UNICODE" not in column_type.upper():
            continue
        if not _teradata_column_exists(
            schema_name=schema_name,
            table_name=table_name,
            column_name=column_name,
            execute_sql_fn=execute_sql_fn,
        ):
            continue
        quoted_column = column_name.replace('"', '""')
        try:
            execute_sql_fn(f'ALTER TABLE {qualified_table} MODIFY "{quoted_column}" {column_type}')
        except Exception as ex:
            raise RuntimeError(
                f'Existing Multi-Format target table {qualified_table} has a non-UNICODE-compatible column "{column_name}". '
                "Drop/recreate that table or use a new vector store name, then rerun Multi-Format preprocessing."
            ) from ex
        warnings.append(f'Ensured Multi-Format column "{column_name}" uses CHARACTER SET UNICODE.')
    return warnings


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
    table_created = False

    if table_exists and clear_rows:
        try:
            execute_sql_fn(f"DROP TABLE {qualified_table}")
            warnings.append(f"Recreated Multi-Format target table {qualified_table} to apply the latest UNICODE schema.")
            table_exists = False
        except Exception as ex:
            raise RuntimeError(
                f"Failed to recreate existing Multi-Format target table {qualified_table}. "
                "Drop that table manually or use a new vector store name, then rerun Multi-Format preprocessing."
            ) from ex

    if not table_exists:
        create_sql = _build_unstructured_table_ddl(
            qualified_table=qualified_table,
        )
        execute_sql_fn(create_sql)
        table_created = True
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
        warnings.extend(
            _ensure_unstructured_unicode_columns(
                schema_name=schema_name,
                table_name=table_name,
                execute_sql_fn=execute_sql_fn,
            )
        )

    if clear_rows and not table_created:
        try:
            execute_sql_fn(f"DELETE FROM {qualified_table}")
        except Exception as ex:
            warnings.append(f"Failed to clear destination table before run: {ex}")
    return warnings


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


def _strip_file_based_create_params(payload: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(payload)
    for key in FILE_BASED_CREATE_KEYS_TO_REMOVE:
        cleaned.pop(key, None)
    return cleaned


def _now_ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _safe_stem(src: Path) -> str:
    stem = re.sub(r"[^0-9A-Za-z._-]", "_", src.stem.strip())
    return stem or "document"


def _prepare_unstructured_debug_dir(vector_store_name: str) -> Path | None:
    if not _env_flag("UNSTRUCTURED_WRITE_DEBUG_JSON", True):
        return None
    vs_name = _sanitize_teradata_identifier(vector_store_name, fallback="bookrag")
    run_id = time.strftime("%Y%m%d_%H%M%S")
    debug_dir = UNSTRUCTURED_DEBUG_DIR_DEFAULT / f"{vs_name}_{run_id}"
    debug_dir.mkdir(parents=True, exist_ok=True)
    return debug_dir


def _prepare_bookrag_raw_stage_dir(vector_store_name: str) -> Path:
    vs_name = _sanitize_teradata_identifier(vector_store_name, fallback="bookrag")
    run_id = time.strftime("%Y%m%d_%H%M%S")
    raw_stage_dir = BOOKRAG_RAW_STAGE_DIR_DEFAULT / f"{vs_name}_{run_id}"
    raw_stage_dir.mkdir(parents=True, exist_ok=True)
    return raw_stage_dir


def _prepare_bookrag_csv_stage_dir(vector_store_name: str) -> Path:
    vs_name = _sanitize_teradata_identifier(vector_store_name, fallback="bookrag")
    run_id = time.strftime("%Y%m%d_%H%M%S")
    csv_stage_dir = BOOKRAG_CSV_STAGE_DIR_DEFAULT / f"{vs_name}_{run_id}"
    csv_stage_dir.mkdir(parents=True, exist_ok=True)
    return csv_stage_dir


def _write_unstructured_debug_file(
    debug_dir: Path | None,
    src: Path,
    raw_elements: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    request_parameters: dict[str, Any],
    extra_payload: dict[str, Any] | None = None,
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
    if extra_payload:
        payload.update(_json_safe_value(extra_payload))
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

def _workflow_debug_payload(
    request_parameters: dict[str, Any],
    *,
    processing_profile: str,
    workflow_id: str = "",
    workflow_name: str = "",
    job_id: str = "",
    workflow_kind: str = "",
) -> dict[str, Any]:
    workflow_nodes = list(request_parameters.get("workflow_nodes") or [])
    return {
        "workflow_kind": workflow_kind or "workflow",
        "processing_profile": processing_profile,
        "workflow_id": workflow_id,
        "workflow_name": workflow_name or str(request_parameters.get("workflow_name") or "").strip(),
        "job_id": job_id or str(request_parameters.get("job_id") or "").strip(),
        "workflow_node_count": len(workflow_nodes),
        "workflow_nodes": _json_safe_value(workflow_nodes),
    }


def _bookrag_partition_options_for_file(
    src: Path,
    default_strategy: str,
    default_languages: list[str],
    include_orig_elements: bool,
) -> tuple[str, list[str], bool]:
    suffix = src.suffix.lower()
    if suffix in (BOOKRAG_PDF_IMAGE_EXTENSIONS - {".pdf"}):
        return "hi_res", ["jpn"], include_orig_elements
    if suffix == ".pdf" and _looks_like_scanned_pdf(src):
        return "hi_res", ["jpn"], include_orig_elements
    return default_strategy or "auto", list(default_languages or []), include_orig_elements


def _looks_like_scanned_pdf(src: Path) -> bool:
    if src.suffix.lower() != ".pdf":
        return False
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(src))
        sampled_pages = reader.pages[: min(3, len(reader.pages))]
        total_text_len = 0
        image_only_pages = 0
        for page in sampled_pages:
            text = (page.extract_text() or "").strip()
            total_text_len += len(text)
            resources = page.get("/Resources")
            xobjects = resources.get("/XObject") if resources else None
            has_image = False
            if xobjects:
                for key in xobjects.keys():
                    try:
                        obj = xobjects[key].get_object()
                    except Exception:
                        continue
                    if str(obj.get("/Subtype")) == "/Image":
                        has_image = True
                        break
            if has_image and len(text) < 24:
                image_only_pages += 1
        if not sampled_pages:
            return False
        return image_only_pages == len(sampled_pages) or total_text_len < 24
    except Exception:
        return False


def _multi_format_partition_options_for_file(
    src: Path,
    default_strategy: str,
    default_languages: list[str],
    include_orig_elements: bool,
) -> tuple[str, list[str], bool, list[str], bool]:
    warnings: list[str] = []
    resolved_strategy = default_strategy
    resolved_languages = list(default_languages)
    suffix = src.suffix.lower()
    scan_ocr_fallback_applied = False

    is_scan_like = suffix in (BOOKRAG_PDF_IMAGE_EXTENSIONS - {".pdf"})
    if suffix == ".pdf":
        is_scan_like = _looks_like_scanned_pdf(src)

    if is_scan_like and resolved_strategy == "fast":
        resolved_strategy = "auto"
        warnings.append(
            f"multi format strategy 'fast' is not recommended for scan-style document {src.name}; fallback to 'auto'."
        )
        scan_ocr_fallback_applied = True

    if resolved_strategy == "fast" and suffix in UNSTRUCTURED_FAST_UNSAFE_IMAGE_EXTENSIONS:
        resolved_strategy = "auto"
        warnings.append(
            f"multi format strategy 'fast' is not supported for image file {src.name}; fallback to 'auto'."
        )
        scan_ocr_fallback_applied = True

    if is_scan_like and resolved_strategy == "hi_res" and not resolved_languages:
        resolved_languages = ["jpn"]
        warnings.append(
            f"multi format auto-assigned OCR language 'jpn' for hi_res scan-style document {src.name}."
        )

    return resolved_strategy, resolved_languages, include_orig_elements, warnings, scan_ocr_fallback_applied


def _as_text(value: Any, max_len: int | None = None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value
    elif isinstance(value, (dict, list, tuple)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)
    text = _sanitize_teradata_text(text)
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


def _is_excel_file(src: Path) -> bool:
    return src.suffix.lower() in EXCEL_EXTENSIONS


def _excel_column_name(index: int) -> str:
    label = ""
    value = max(1, int(index))
    while value > 0:
        value, rem = divmod(value - 1, 26)
        label = chr(65 + rem) + label
    return label or "A"


def _normalize_excel_cell_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return format(value, "g")
    if hasattr(value, "isoformat") and not isinstance(value, str):
        try:
            return str(value.isoformat(sep=" "))
        except TypeError:
            try:
                return str(value.isoformat())
            except Exception:
                pass
    return str(value).strip()


def _trim_excel_cells(values: list[str]) -> list[str]:
    trimmed = list(values)
    while trimmed and not trimmed[-1]:
        trimmed.pop()
    return trimmed


def _should_use_excel_headers(rows: list[tuple[int, list[str]]]) -> bool:
    if len(rows) < 2:
        return False
    first_values = rows[0][1]
    non_empty = [value for value in first_values if value]
    if len(non_empty) < 2:
        return False
    mostly_label_like = sum(1 for value in non_empty if not any(ch.isdigit() for ch in value[:24]))
    return mostly_label_like >= max(1, len(non_empty) // 2)


def _build_excel_headers(values: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    headers: list[str] = []
    for idx, value in enumerate(values, start=1):
        candidate = re.sub(r"\s+", " ", value).strip() or f"Column {_excel_column_name(idx)}"
        count = seen.get(candidate, 0) + 1
        seen[candidate] = count
        if count > 1:
            candidate = f"{candidate} ({count})"
        headers.append(candidate)
    return headers


def _split_text_with_overlap(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    normalized = str(text or "").strip()
    if not normalized:
        return []
    if max_chars <= 0 or len(normalized) <= max_chars:
        return [normalized]

    overlap_chars = max(0, min(overlap_chars, max_chars - 1))
    parts: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(len(normalized), start + max_chars)
        if end < len(normalized):
            newline_break = normalized.rfind("\n", start, end)
            space_break = normalized.rfind(" ", start, end)
            break_at = max(newline_break, space_break)
            if break_at > start + (max_chars // 2):
                end = break_at
        piece = normalized[start:end].strip()
        if piece:
            parts.append(piece)
        if end >= len(normalized):
            break
        start = max(end - overlap_chars, start + 1)
        while start < len(normalized) and normalized[start].isspace():
            start += 1
    return parts or [normalized[:max_chars].strip()]


def _read_excel_sheet_rows(src: Path) -> list[tuple[str, list[tuple[int, list[str]]]]]:
    import pandas as pd

    workbook = pd.read_excel(src, sheet_name=None, header=None, dtype=object)
    sheets: list[tuple[str, list[tuple[int, list[str]]]]] = []
    for sheet_name, frame in workbook.items():
        rows: list[tuple[int, list[str]]] = []
        for row_number, row in enumerate(frame.itertuples(index=False, name=None), start=1):
            values: list[str] = []
            for cell in row:
                if pd.isna(cell):
                    values.append("")
                else:
                    values.append(_normalize_excel_cell_value(cell))
            values = _trim_excel_cells(values)
            if any(values):
                rows.append((row_number, values))
        if rows:
            sheets.append((str(sheet_name), rows))
    return sheets


def _partition_excel_chunks(
    src: Path,
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    content_type = mimetypes.guess_type(src.name)[0] or "application/octet-stream"
    sheet_rows = _read_excel_sheet_rows(src)
    raw_elements: list[dict[str, Any]] = []
    table_rows: list[dict[str, Any]] = []
    sheet_names: list[str] = []
    logical_row_count = 0

    chunk_sequence = 0
    for sheet_name, rows in sheet_rows:
        sheet_names.append(sheet_name)
        use_headers = _should_use_excel_headers(rows)
        headers = _build_excel_headers(rows[0][1]) if use_headers else []
        data_rows = rows[1:] if use_headers and len(rows) > 1 else rows
        for row_number, values in data_rows:
            logical_row_count += 1
            parts: list[str] = []
            for idx, value in enumerate(values, start=1):
                if not value:
                    continue
                header = headers[idx - 1] if idx - 1 < len(headers) else f"Column {_excel_column_name(idx)}"
                parts.append(f"{header}: {value}")
            if not parts:
                continue

            full_text = f"Workbook: {src.name}\nSheet: {sheet_name}\nRow: {row_number}\n" + "\n".join(parts)
            record_id = uuid.uuid4().hex
            record_locator = f"{src.name}#sheet={sheet_name}#row={row_number}"
            metadata = {
                "record_id": record_id,
                "filename": src.name,
                "file_directory": str(src.parent),
                "filetype": content_type,
                "record_locator": record_locator,
                "sheet_name": sheet_name,
                "row_number": row_number,
                "row_kind": "excel_structured",
            }
            raw_elements.append(
                {
                    "id": record_id,
                    "element_id": record_id,
                    "type": "TableRow",
                    "text": full_text,
                    "metadata": metadata,
                }
            )

            segments = _split_text_with_overlap(full_text, chunk_size, chunk_overlap)
            segment_total = len(segments)
            for segment_index, segment in enumerate(segments, start=1):
                element_id = uuid.uuid4().hex
                element_metadata = dict(metadata)
                if segment_total > 1:
                    element_metadata["segment_index"] = segment_index
                    element_metadata["segment_total"] = segment_total
                chunk_sequence += 1
                row = _element_to_chunk_row(
                    {
                        "id": element_id,
                        "element_id": element_id,
                        "type": "TableRow",
                        "text": segment,
                        "metadata": element_metadata,
                    },
                    src=src,
                    content_type=content_type,
                    row_sequence=chunk_sequence,
                )
                if row:
                    table_rows.append(row)

    request_parameters = {
        "mode": "excel-structured",
        "file_name": src.name,
        "content_type": content_type,
        "sheet_names": sheet_names,
        "sheet_count": len(sheet_names),
        "logical_row_count": logical_row_count,
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
    }
    return table_rows, raw_elements, request_parameters


def _element_to_chunk_row(
    element: dict[str, Any],
    src: Path,
    content_type: str,
    *,
    row_sequence: int | None = None,
) -> dict[str, Any] | None:
    metadata = element.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    text = _as_text(element.get("text"), max_len=32000)
    if not text:
        return None

    row_id = _format_chunk_row_id(row_sequence)
    element_id = _as_text(element.get("element_id") or element.get("id"), max_len=64)
    filetype = _as_text(metadata.get("filetype"), max_len=50) or _as_text(content_type, max_len=50)

    row = {
        "text": text,
        "type": _as_text(element.get("type"), max_len=50),
        "filename": _as_text(metadata.get("filename"), max_len=255) or _as_text(src.name, max_len=255),
        "element_id": element_id,
        "id": row_id,
        "table_id": _as_text(metadata.get("table_id"), max_len=128),
        "chunk_index": _as_int(metadata.get("chunk_index")),
        "is_continuation": bool(metadata.get("is_continuation")) if metadata.get("is_continuation") is not None else None,
        "num_carried_over_header_rows": _as_int(metadata.get("num_carried_over_header_rows")),
        "partitioner_type": _as_text(metadata.get("partitioner_type"), max_len=100),
        "image_description": _as_text(metadata.get("image_description"), max_len=32000),
        "table_description": _as_text(metadata.get("table_description"), max_len=32000),
        "generative_ocr": _as_text(metadata.get("generative_ocr"), max_len=32000),
        "table_to_html": _as_text(metadata.get("table_to_html") or metadata.get("text_as_html"), max_len=32000),
        "filetype": filetype,
        "date_processed": _now_ts(),
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
    overlap_all: bool,
    chunking_strategy: str = "basic",
    new_after_n_chars: int | None = None,
    combine_under_n_chars: int | None = None,
    multipage_sections: bool | None = None,
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
        "chunking_strategy": chunking_strategy,
        "max_characters": chunk_size,
        "new_after_n_chars": chunk_size if new_after_n_chars is None else new_after_n_chars,
        "overlap": chunk_overlap,
        "overlap_all": overlap_all,
        "include_orig_elements": include_orig_elements,
    }
    if combine_under_n_chars is not None:
        partition_parameters["combine_under_n_chars"] = combine_under_n_chars
    if multipage_sections is not None:
        partition_parameters["multipage_sections"] = multipage_sections
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
    chunk_sequence = 0
    for element in elements:
        if not isinstance(element, dict):
            continue
        chunk_sequence += 1
        row = _element_to_chunk_row(element, src=src, content_type=content_type, row_sequence=chunk_sequence)
        if row:
            rows.append(row)
    return rows, elements, partition_parameters


def _partition_document_elements(
    client,
    src: Path,
    *,
    partition_strategy: str,
    languages: list[str],
    include_orig_elements: bool,
    extra_partition_parameters: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from unstructured_client.models import operations

    content_type = mimetypes.guess_type(src.name)[0] or "application/octet-stream"
    partition_parameters: dict[str, Any] = {
        "files": {
            "content": src.read_bytes(),
            "file_name": src.name,
            "content_type": content_type,
        },
        "strategy": partition_strategy,
        "include_orig_elements": include_orig_elements,
    }
    if languages:
        partition_parameters["languages"] = languages
    if extra_partition_parameters:
        partition_parameters.update({key: value for key, value in extra_partition_parameters.items() if value is not None})

    resp = client.general.partition(
        request=operations.PartitionRequest(
            partition_parameters=partition_parameters,
        )
    )
    if int(getattr(resp, "status_code", 0) or 0) >= 400:
        raise RuntimeError(f"Unstructured partition failed. status={getattr(resp, 'status_code', '?')}")
    elements = getattr(resp, "elements", None) or []
    return elements, partition_parameters



def _build_bookrag_workflow_partition_node(
    *,
    src: Path,
    partition_strategy: str,
    languages: list[str],
    image_partition_parameters: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    return _workflow_builder_build_bookrag_workflow_partition_node(
        src=src,
        partition_strategy=partition_strategy,
        languages=languages,
        image_partition_parameters=image_partition_parameters,
    )


def _build_bookrag_reusable_workflow_definition(
    *,
    create_values: dict[str, str],
    partition_strategy: str,
    languages: list[str],
    image_partition_parameters: dict[str, Any] | None,
) -> tuple[str, list[dict[str, Any]], dict[str, Any], list[str], str]:
    return _workflow_builder_build_bookrag_reusable_workflow_definition(
        create_values=create_values,
        partition_strategy=partition_strategy,
        languages=languages,
        image_partition_parameters=image_partition_parameters,
        runtime=_load_unstructured_runtime_settings(),
    )


def _build_multi_format_workflow_definition(
    *,
    create_values: dict[str, str],
    src: Path,
    partition_strategy: str,
    languages: list[str],
    chunk_size: int,
    chunk_overlap: int,
    include_orig_elements: bool,
    overlap_all: bool,
) -> tuple[dict[str, Any], list[str], str]:
    return _workflow_builder_build_multi_format_workflow_definition(
        create_values=create_values,
        src=src,
        partition_strategy=partition_strategy,
        languages=languages,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        include_orig_elements=include_orig_elements,
        overlap_all=overlap_all,
        runtime=_load_unstructured_runtime_settings(),
    )


def _find_bookrag_workflow_by_name(client, workflow_name: str):
    from unstructured_client.models import operations

    response = client.workflows.list_workflows(request=operations.ListWorkflowsRequest())
    if int(getattr(response, "status_code", 0) or 0) >= 400:
        raise RuntimeError(f"Unstructured list_workflows failed. status={getattr(response, 'status_code', '?')}")
    for info in getattr(response, "response_list_workflows", None) or []:
        if str(getattr(info, "name", "") or "").strip() == workflow_name:
            return info
    return None


def _ensure_bookrag_reusable_workflow(
    client,
    *,
    workflow_name: str,
    workflow_nodes: list[dict[str, Any]],
    create_values: dict[str, str],
) -> tuple[str, str, list[str]]:
    from unstructured_client.models import operations, shared

    warnings: list[str] = []
    runtime = _load_unstructured_runtime_settings()
    configured_workflow_id = str(
        create_values.get("multi_format_bookrag_workflow_id", "")
        or runtime.get("bookrag_workflow_id")
        or os.getenv("BOOKRAG_WORKFLOW_ID", "")
    ).strip()
    desired_signature = _workflow_nodes_signature(workflow_nodes)
    desired_models = [shared.WorkflowNode(**node) for node in workflow_nodes]

    existing = None
    workflow_id = configured_workflow_id
    if workflow_id:
        response = client.workflows.get_workflow(request=operations.GetWorkflowRequest(workflow_id=workflow_id))
        if int(getattr(response, "status_code", 0) or 0) >= 400:
            raise RuntimeError(f"Unstructured get_workflow failed. status={getattr(response, 'status_code', '?')}, workflow_id={workflow_id}")
        existing = getattr(response, "workflow_information", None)
        if existing is None:
            raise RuntimeError(f"Unstructured get_workflow returned no workflow information. workflow_id={workflow_id}")
    else:
        existing = _find_bookrag_workflow_by_name(client, workflow_name)
        workflow_id = str(getattr(existing, "id", "") or "").strip() if existing is not None else ""

    if existing is not None:
        current_signature = _workflow_nodes_signature(list(getattr(existing, "workflow_nodes", None) or []))
        current_name = str(getattr(existing, "name", "") or "").strip()
        current_type = str(getattr(getattr(existing, "workflow_type", ""), "value", getattr(existing, "workflow_type", "")) or "").strip().lower()
        if current_signature != desired_signature or current_name != workflow_name or current_type != "custom":
            update = shared.UpdateWorkflow(
                name=workflow_name,
                workflow_type=shared.WorkflowType.CUSTOM,
                workflow_nodes=desired_models,
            )
            response = client.workflows.update_workflow(
                request=operations.UpdateWorkflowRequest(
                    workflow_id=workflow_id,
                    update_workflow=update,
                )
            )
            if int(getattr(response, "status_code", 0) or 0) >= 400:
                raise RuntimeError(f"Unstructured update_workflow failed. status={getattr(response, 'status_code', '?')}, workflow_id={workflow_id}")
            warnings.append(f"Updated reusable BookRAG workflow '{workflow_name}' ({workflow_id}).")
        else:
            warnings.append(f"Reused existing BookRAG workflow '{workflow_name}' ({workflow_id}).")
        return workflow_id, workflow_name, warnings

    workflow = shared.CreateWorkflow(
        name=workflow_name,
        workflow_type=shared.WorkflowType.CUSTOM,
        workflow_nodes=desired_models,
    )
    response = client.workflows.create_workflow(
        request=operations.CreateWorkflowRequest(
            create_workflow=workflow,
        )
    )
    if int(getattr(response, "status_code", 0) or 0) >= 400:
        raise RuntimeError(f"Unstructured workflow creation failed. status={getattr(response, 'status_code', '?')}")
    info = getattr(response, "workflow_information", None)
    workflow_id = str(getattr(info, "id", "") or "").strip()
    if not workflow_id:
        raise RuntimeError("Unstructured workflow creation returned no workflow ID.")
    warnings.append(f"Created reusable BookRAG workflow '{workflow_name}' ({workflow_id}).")
    return workflow_id, workflow_name, warnings


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
        values_sql = ", ".join(_sql_typed_literal(row.get(name), column_type) for name, column_type in UNSTRUCTURED_CHUNK_COLUMNS)
        execute_sql_fn(f"INSERT INTO {qualified_table} ({quoted_cols}) VALUES ({values_sql})")
        inserted += 1
    return inserted


def _new_unstructured_client():
    api_key, api_url = _load_unstructured_runtime_config()
    return _create_unstructured_client(api_key=api_key, api_url=api_url)


def _apply_bookrag_tree_pipeline(
    exec_payload: dict,
    create_values: dict[str, str],
    vector_store_name: str,
    *,
    execute_sql_fn: ExecuteSqlFn | None,
    resolve_path_hint: Callable[[str], str],
    effective_schema_name: str | None,
    document_files: list[str],
    partition_strategy: str,
    ocr_languages: list[str],
    target_warnings: list[str],
    connection_params: dict | None = None,
) -> tuple[dict, dict]:
    bookrag_tables = build_bookrag_table_targets(vector_store_name)
    table_generation = _resolve_bookrag_table_generation_flags(create_values)
    run_embedding_step = _resolve_bookrag_embedding_step_flag(create_values)
    if run_embedding_step and not table_generation["nodes"]:
        raise RuntimeError("BookRAG embedding step requires bnode generation to be enabled.")
    if table_generation["documents"]:
        target_warnings.extend(
            prepare_bookrag_document_table(
                schema_name=effective_schema_name,
                table_targets=bookrag_tables,
                execute_sql_fn=execute_sql_fn,
            )
        )
    if table_generation["raw"]:
        target_warnings.extend(
            prepare_bookrag_raw_table(
                schema_name=effective_schema_name,
                table_targets=bookrag_tables,
                execute_sql_fn=execute_sql_fn,
            )
        )
    if table_generation["blocks"]:
        target_warnings.extend(
            prepare_bookrag_block_table(
                schema_name=effective_schema_name,
                table_targets=bookrag_tables,
                execute_sql_fn=execute_sql_fn,
            )
        )
    if table_generation["nodes"]:
        target_warnings.extend(
            prepare_bookrag_node_table(
                schema_name=effective_schema_name,
                table_targets=bookrag_tables,
                execute_sql_fn=execute_sql_fn,
            )
        )
    if table_generation["entities"]:
        target_warnings.extend(
            prepare_bookrag_entity_table(
                schema_name=effective_schema_name,
                table_targets=bookrag_tables,
                execute_sql_fn=execute_sql_fn,
            )
        )
    if table_generation["entity_links"]:
        target_warnings.extend(
            prepare_bookrag_entity_link_table(
                schema_name=effective_schema_name,
                table_targets=bookrag_tables,
                execute_sql_fn=execute_sql_fn,
            )
        )
    if table_generation["entity_relations"]:
        target_warnings.extend(
            prepare_bookrag_entity_relation_table(
                schema_name=effective_schema_name,
                table_targets=bookrag_tables,
                execute_sql_fn=execute_sql_fn,
            )
        )
    selected_entity_tables = any(table_generation[key] for key in BOOKRAG_ENTITY_TABLE_KEYS)
    image_partition_parameters, image_partition_warnings, image_partition_summary = _resolve_bookrag_image_partition_options(create_values)
    target_warnings.extend(image_partition_warnings)


    api_key, api_url = _load_unstructured_runtime_config(connection_params)
    request_timeout_ms = _resolve_unstructured_request_timeout_ms()
    client = _create_unstructured_client(api_key=api_key, api_url=api_url, timeout_ms=request_timeout_ms)
    debug_dir = _prepare_unstructured_debug_dir(vector_store_name)
    raw_stage_dir = _prepare_bookrag_raw_stage_dir(vector_store_name)
    csv_stage_dir = _prepare_bookrag_csv_stage_dir(vector_store_name)
    partition_warnings: list[str] = []
    debug_files: list[str] = []
    raw_stage_files: list[str] = []
    job_ids: list[str] = []
    document_insert_stats: dict[str, int] = {}
    raw_insert_stats: dict[str, int] = {}
    block_insert_stats: dict[str, int] = {}
    node_insert_stats: dict[str, int] = {}
    entity_insert_stats: dict[str, int] = {}
    entity_link_insert_stats: dict[str, int] = {}
    entity_relation_insert_stats: dict[str, int] = {}
    inserted_rows = 0
    raw_element_count = 0
    block_count = 0
    node_count = 0
    entity_count: int | None = 0 if selected_entity_tables else None
    entity_link_count: int | None = 0 if selected_entity_tables else None
    entity_relation_count: int | None = 0 if selected_entity_tables else None
    document_count = 0
    document_rows: list[dict[str, Any]] = []
    all_raw_rows: list[dict[str, Any]] = []
    all_blocks: list[dict[str, Any]] = []
    all_nodes: list[dict[str, Any]] = []
    all_entities: list[dict[str, Any]] = []
    all_entity_links: list[dict[str, Any]] = []
    all_entity_relations: list[dict[str, Any]] = []

    qualified_tables = {
        name: (f"{effective_schema_name}.{table_name}" if effective_schema_name else table_name)
        for name, table_name in bookrag_tables.items()
    }
    persisted_bookrag_tables = {
        name: qualified_tables[name]
        for name in BOOKRAG_TABLE_TOGGLE_ORDER
        if table_generation[name]
    }

    workflow_name, workflow_nodes, request_parameters, workflow_definition_warnings, processing_profile = _build_bookrag_reusable_workflow_definition(
        create_values=create_values,
        partition_strategy=partition_strategy,
        languages=ocr_languages,
        image_partition_parameters=image_partition_parameters,
    )
    partition_warnings.extend(workflow_definition_warnings)

    workflow_ids: list[str] = []
    workflow_names_seen: list[str] = []
    timeout_seconds, poll_interval_seconds = _resolve_bookrag_workflow_poll_config()
    last_job_submitted_at: float | None = None
    for path_hint in document_files:
        resolved = resolve_path_hint(path_hint)
        src = Path(resolved)
        if not src.exists() or not src.is_file():
            raise RuntimeError(f"multi format source file is missing: {path_hint}")

        last_job_submitted_at = _enforce_unstructured_job_submission_spacing(last_job_submitted_at)
        raw_output_payload, raw_elements, file_request_parameters, job_id, workflow_id, workflow_name_for_job = _run_unstructured_workflow_job_for_file(
            client,
            request_parameters=request_parameters,
            src=src,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            api_key=api_key,
            api_url=api_url,
        )
        job_ids.append(job_id)
        if workflow_id:
            workflow_ids.append(workflow_id)
        if workflow_name_for_job:
            workflow_names_seen.append(workflow_name_for_job)

        doc_id = uuid.uuid4().hex
        raw_stage_file = write_bookrag_raw_stage_file(
            raw_stage_dir,
            src.name,
            doc_id,
            raw_output_payload,
        )
        raw_stage_files.append(str(raw_stage_file))
        staged_raw_elements = load_bookrag_raw_stage_file(raw_stage_file)
        reconciled_elements = reconcile_unstructured_elements(staged_raw_elements, src=src)
        filetype = mimetypes.guess_type(src.name)[0] or src.suffix.lower().lstrip(".")
        document_row = build_bookrag_document_row(
            doc_id=doc_id,
            vector_store_name=vector_store_name,
            workflow_id=workflow_id,
            workflow_name=workflow_name_for_job or workflow_name,
            job_id=job_id,
            processing_profile=processing_profile,
            filename=src.name,
            source_file=str(raw_stage_file),
            filetype=filetype,
            filesize_bytes=src.stat().st_size,
        )
        raw_rows = build_bookrag_raw_rows(
            doc_id=doc_id,
            elements=staged_raw_elements,
        )
        blocks = elements_to_bookrag_blocks(
            doc_id=doc_id,
            src=src,
            content_type=filetype,
            raw_elements=reconciled_elements,
        )
        nodes = build_bookrag_nodes(document_row, blocks)
        entities: list[dict[str, Any]] = []
        entity_links: list[dict[str, Any]] = []
        entity_relations: list[dict[str, Any]] = []
        if selected_entity_tables:
            entities, entity_links, entity_relations = build_bookrag_entities(document_row, reconciled_elements, nodes)
        debug_file = _write_unstructured_debug_file(
            debug_dir,
            src,
            reconciled_elements,
            [],
            file_request_parameters,
            extra_payload={
                **_workflow_debug_payload(
                    file_request_parameters,
                    processing_profile=processing_profile,
                    workflow_id=workflow_id,
                    workflow_name=workflow_name_for_job or workflow_name,
                    job_id=job_id,
                    workflow_kind="bookrag",
                ),
                "bookrag_image_partition_parameters": image_partition_summary,
                "workflow_nodes": workflow_nodes,
                "raw_element_count_before_reconcile": len(staged_raw_elements),
                "raw_element_count_after_reconcile": len(reconciled_elements),
                "block_count": len(blocks),
                "node_count": len(nodes),
                "entity_count": len(entities),
                "entity_link_count": len(entity_links),
                "entity_relation_count": len(entity_relations),
                "bookrag_table_generation": table_generation,
            },
        )
        if debug_file:
            debug_files.append(debug_file)
        if not raw_rows:
            partition_warnings.append(f"No BookRAG raw elements extracted from file: {src.name}")
            continue

        document_rows.append(document_row)
        all_raw_rows.extend(raw_rows)
        all_blocks.extend(blocks)
        all_nodes.extend(nodes)
        all_entities.extend(entities)
        all_entity_links.extend(entity_links)
        all_entity_relations.extend(entity_relations)
        document_count += 1
        raw_element_count += len(raw_rows)
        block_count += len(blocks)
        node_count += len(nodes)
        if selected_entity_tables:
            entity_count = (entity_count or 0) + len(entities)
            entity_link_count = (entity_link_count or 0) + len(entity_links)
            entity_relation_count = (entity_relation_count or 0) + len(entity_relations)

    if table_generation["documents"]:
        inserted_rows += persist_bookrag_documents(
            schema_name=effective_schema_name,
            table_targets=bookrag_tables,
            rows=document_rows,
            execute_sql_fn=execute_sql_fn,
            csv_stage_dir=csv_stage_dir,
            stats=document_insert_stats,
        )
    if table_generation["raw"]:
        inserted_rows += persist_bookrag_raw_rows(
            schema_name=effective_schema_name,
            table_targets=bookrag_tables,
            rows=all_raw_rows,
            execute_sql_fn=execute_sql_fn,
            csv_stage_dir=csv_stage_dir,
            stats=raw_insert_stats,
        )
    if table_generation["blocks"]:
        inserted_rows += persist_bookrag_blocks(
            schema_name=effective_schema_name,
            table_targets=bookrag_tables,
            blocks=all_blocks,
            execute_sql_fn=execute_sql_fn,
            csv_stage_dir=csv_stage_dir,
            stats=block_insert_stats,
        )
    if table_generation["nodes"]:
        inserted_rows += persist_bookrag_nodes(
            schema_name=effective_schema_name,
            table_targets=bookrag_tables,
            nodes=all_nodes,
            execute_sql_fn=execute_sql_fn,
            csv_stage_dir=csv_stage_dir,
            stats=node_insert_stats,
        )
    if table_generation["entities"]:
        inserted_rows += persist_bookrag_entities(
            schema_name=effective_schema_name,
            table_targets=bookrag_tables,
            entities=all_entities,
            execute_sql_fn=execute_sql_fn,
            csv_stage_dir=csv_stage_dir,
            stats=entity_insert_stats,
        )
    if table_generation["entity_links"]:
        inserted_rows += persist_bookrag_entity_links(
            schema_name=effective_schema_name,
            table_targets=bookrag_tables,
            entity_links=all_entity_links,
            execute_sql_fn=execute_sql_fn,
            csv_stage_dir=csv_stage_dir,
            stats=entity_link_insert_stats,
        )
    if table_generation["entity_relations"]:
        inserted_rows += persist_bookrag_entity_relations(
            schema_name=effective_schema_name,
            table_targets=bookrag_tables,
            entity_relations=all_entity_relations,
            execute_sql_fn=execute_sql_fn,
            csv_stage_dir=csv_stage_dir,
            stats=entity_relation_insert_stats,
        )

    persisted_table_row_counts: dict[str, int] = {}
    for table_key in BOOKRAG_TABLE_TOGGLE_ORDER:
        if not table_generation[table_key]:
            continue
        row_count = _count_teradata_rows(
            schema_name=effective_schema_name,
            table_name=bookrag_tables[table_key],
            execute_sql_fn=execute_sql_fn,
        )
        if row_count is not None:
            persisted_table_row_counts[table_key] = row_count

    persisted_raw_count = persisted_table_row_counts.get("raw", raw_element_count)
    if inserted_rows <= 0:
        enabled_tables = ", ".join(table_key for table_key in BOOKRAG_TABLE_TOGGLE_ORDER if table_generation[table_key])
        raise RuntimeError(f"bookrag workflow completed but selected tables received 0 inserted rows. tables={enabled_tables}")
    if persisted_table_row_counts and max(persisted_table_row_counts.values()) <= 0:
        enabled_tables = ", ".join(persisted_bookrag_tables.values())
        raise RuntimeError(f"bookrag workflow completed but selected tables have 0 persisted rows. tables={enabled_tables}")

    patched_payload = _strip_file_based_create_params(exec_payload)
    if table_generation["nodes"]:
        patched_payload["object_names"] = qualified_tables["nodes"]
        patched_payload["data_columns"] = ["content"]
        patched_payload["key_columns"] = ["node_id"]
        patched_payload.pop("vector_column", None)
    description_text = str(patched_payload.get("description") or "").strip()
    description_low = description_text.lower()
    if "unstructured_bookrag_flg" not in description_low:
        patched_payload["description"] = (
            f"{description_text} unstructured_bookrag_flg".strip() if description_text else "unstructured_bookrag_flg"
        )
    else:
        patched_payload["description"] = description_text

    summary = {
        "table_name": "",
        "documents_table_name": persisted_bookrag_tables.get("documents", ""),
        "raw_table_name": persisted_bookrag_tables.get("raw", ""),
        "blocks_table_name": persisted_bookrag_tables.get("blocks", ""),
        "nodes_table_name": persisted_bookrag_tables.get("nodes", ""),
        "entities_table_name": persisted_bookrag_tables.get("entities", ""),
        "entity_links_table_name": persisted_bookrag_tables.get("entity_links", ""),
        "entity_relations_table_name": persisted_bookrag_tables.get("entity_relations", ""),
        "vectorstore_source_object": persisted_bookrag_tables.get("nodes", ""),
        "vectorstore_data_columns": ["content"] if table_generation["nodes"] else [],
        "vectorstore_key_columns": ["node_id"] if table_generation["nodes"] else [],
        "skip_vectorstore_create": not run_embedding_step,
        "run_embedding_step": run_embedding_step,
        "raw_element_count": persisted_raw_count,
        "block_count": block_count,
        "node_count": node_count,
        "entity_count": entity_count,
        "entity_link_count": entity_link_count,
        "entity_relation_count": entity_relation_count,
        "document_count": document_count,
        "job_id": job_ids[-1] if job_ids else "",
        "job_ids": job_ids,
        "workflow_id": workflow_ids[-1] if workflow_ids else "",
        "workflow_name": workflow_names_seen[-1] if workflow_names_seen else workflow_name,
        "destination_id": "",
        "warnings": target_warnings + partition_warnings,
        "workflow_mode": "bookrag on-demand jobs selected tables debug",
        "inserted_rows": inserted_rows,
        "debug_dir": str(debug_dir) if debug_dir else "",
        "debug_files": debug_files,
        "bookrag_raw_stage_dir": str(raw_stage_dir),
        "bookrag_raw_stage_files": raw_stage_files,
        "bookrag_csv_stage_dir": str(csv_stage_dir),
        "bookrag_csv_stage_files": sorted(str(path) for path in csv_stage_dir.glob("*.csv")),
        "effective_partition_strategy": partition_strategy,
        "effective_ocr_languages": ocr_languages,
        "include_orig_elements": False,
        "file_mode": "on-demand-jobs",
        "bookrag_tables": persisted_bookrag_tables,
        "bookrag_table_generation": table_generation,
        "bookrag_persisted_table_row_counts": persisted_table_row_counts,
        "bookrag_profile": processing_profile,
        "bookrag_document_insert_stats": document_insert_stats,
        "bookrag_raw_insert_stats": raw_insert_stats,
        "bookrag_block_insert_stats": block_insert_stats,
        "bookrag_node_insert_stats": node_insert_stats,
        "bookrag_entity_insert_stats": entity_insert_stats,
        "bookrag_entity_link_insert_stats": entity_link_insert_stats,
        "bookrag_entity_relation_insert_stats": entity_relation_insert_stats,
        "bookrag_insert_stats": raw_insert_stats,
        "bookrag_image_partition_parameters": image_partition_summary,
        "bookrag_chunking_strategy": "disabled_for_tree_debug",
    }
    return patched_payload, summary


def apply_multi_format_pipeline(
    exec_payload: dict,
    create_values: dict[str, str],
    vector_store_name: str,
    connection_params: dict | None = None,
    *,
    execute_sql_fn: ExecuteSqlFn | None,
    resolve_path_hint: Callable[[str], str],
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

    include_orig_elements = False
    overlap_all = True

    if pipeline_mode == "multi_format_bookrag":
        partition_strategy = _resolve_partition_strategy(create_values.get("multi_format_bookrag_strategy", "auto"))
        ocr_languages = _parse_langs(create_values.get("multi_format_bookrag_ocr_languages", ""))
    else:
        partition_strategy = _resolve_partition_strategy(create_values.get("multi_format_strategy", "auto"))
        if partition_strategy == "ocr_only":
            raise RuntimeError(
                "Multi-Format does not expose 'ocr_only' as a supported workflow route because the current Unstructured workflow docs do not document it as an official workflow partition route. Use hi_res or vlm instead."
            )
        ocr_languages = _parse_langs(create_values.get("multi_format_ocr_languages", ""))
        chunk_size = _to_int(create_values.get("multi_format_chunk_size", "600"), default=600, minimum=100, maximum=8000)
        chunk_overlap = _to_int(create_values.get("multi_format_chunk_overlap", "80"), default=80, minimum=0, maximum=2000)
        if chunk_overlap >= chunk_size:
            chunk_overlap = max(0, chunk_size // 5)

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

    if pipeline_mode == "multi_format_bookrag":
        return _apply_bookrag_tree_pipeline(
            exec_payload=exec_payload,
            create_values=create_values,
            vector_store_name=vector_store_name,
            execute_sql_fn=execute_sql_fn,
            resolve_path_hint=resolve_path_hint,
            effective_schema_name=effective_schema_name,
            document_files=document_files,
            partition_strategy=partition_strategy,
            ocr_languages=ocr_languages,
            target_warnings=target_warnings,
            connection_params=connection_params,
        )

    target_warnings.extend(
        _ensure_unstructured_teradata_table(
            schema_name=effective_schema_name,
            table_name=table_name,
            execute_sql_fn=execute_sql_fn,
            clear_rows=True,
        )
    )

    api_key, api_url = _load_unstructured_runtime_config(connection_params)
    request_timeout_ms = _resolve_unstructured_request_timeout_ms()
    client = _create_unstructured_client(api_key=api_key, api_url=api_url, timeout_ms=request_timeout_ms)
    runtime_settings = _load_unstructured_runtime_settings()
    timeout_seconds, poll_interval_seconds = _resolve_multi_format_workflow_poll_config()
    debug_dir = _prepare_unstructured_debug_dir(vector_store_name)
    inserted_rows = 0
    partition_warnings: list[str] = []
    debug_files: list[str] = []
    used_partition_strategies: set[str] = set()
    used_ocr_languages: set[tuple[str, ...]] = set()
    scan_ocr_fallback_files: list[str] = []
    excel_structured_files: list[str] = []
    processing_modes: set[str] = set()
    job_ids: list[str] = []
    workflow_ids: list[str] = []
    workflow_names_seen: list[str] = []
    last_workflow_name = ""
    last_job_submitted_at: float | None = None
    chunk_sequence = 0
    for path_hint in document_files:
        resolved = resolve_path_hint(path_hint)
        src = Path(resolved)
        if not src.exists() or not src.is_file():
            raise RuntimeError(f"multi format source file is missing: {path_hint}")
        (
            file_partition_strategy,
            file_ocr_languages,
            file_include_orig_elements,
            file_partition_warnings,
            scan_ocr_fallback_applied,
        ) = _multi_format_partition_options_for_file(
            src,
            default_strategy=partition_strategy,
            default_languages=ocr_languages,
            include_orig_elements=include_orig_elements,
        )
        partition_warnings.extend(file_partition_warnings)
        request_parameters, workflow_definition_warnings, processing_profile = _workflow_builder_build_multi_format_workflow_definition(
            create_values=create_values,
            src=src,
            partition_strategy=file_partition_strategy,
            languages=file_ocr_languages,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            include_orig_elements=file_include_orig_elements,
            overlap_all=overlap_all,
            runtime=runtime_settings,
        )
        partition_warnings.extend(workflow_definition_warnings)
        last_workflow_name = str(request_parameters.get("workflow_name") or "").strip()
        used_partition_strategies.add(file_partition_strategy)
        used_ocr_languages.add(tuple(file_ocr_languages))
        if scan_ocr_fallback_applied:
            scan_ocr_fallback_files.append(src.name)

        last_job_submitted_at = _enforce_unstructured_job_submission_spacing(last_job_submitted_at)
        raw_output_payload, raw_elements, request_parameters_with_job, job_id, workflow_id, workflow_name_for_job = _run_unstructured_workflow_job_for_file(
            client,
            request_parameters=request_parameters,
            src=src,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            api_key=api_key,
            api_url=api_url,
        )
        job_ids.append(job_id)
        if workflow_id:
            workflow_ids.append(workflow_id)
        if workflow_name_for_job:
            workflow_names_seen.append(workflow_name_for_job)

        rows: list[dict[str, Any]] = []
        content_type = mimetypes.guess_type(src.name)[0] or "application/octet-stream"
        for element in raw_elements:
            if not isinstance(element, dict):
                continue
            chunk_sequence += 1
            row = _element_to_chunk_row(element, src=src, content_type=content_type, row_sequence=chunk_sequence)
            if row:
                rows.append(row)

        debug_file = _write_unstructured_debug_file(
            debug_dir,
            src,
            raw_elements,
            rows,
            request_parameters_with_job,
            extra_payload={
                **_workflow_debug_payload(
                    request_parameters_with_job,
                    processing_profile=processing_profile,
                    workflow_id=workflow_id,
                    workflow_name=workflow_name_for_job or last_workflow_name,
                    job_id=job_id,
                    workflow_kind="multi_format",
                ),
                "job_output_payload": raw_output_payload,
            },
        )
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
        processing_modes.add("workflow-jobs")

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

    patched_payload = _strip_file_based_create_params(exec_payload)
    patched_payload["target_database"] = effective_schema_name or database_name
    patched_payload["object_names"] = table_name
    patched_payload["data_columns"] = ["text"]
    patched_payload.setdefault("key_columns", ["id"])

    # multi format already writes chunked content into Teradata.
    # For content-based vector store creation, chunking inputs must be omitted.

    strategy_label = (
        next(iter(used_partition_strategies))
        if len(used_partition_strategies) == 1
        else ("mixed" if used_partition_strategies else "")
    )
    languages_label = ""
    if len(used_ocr_languages) == 1:
        languages_label = ",".join(next(iter(used_ocr_languages)))
    elif used_ocr_languages:
        languages_label = "mixed"
    processing_mode_label = (
        next(iter(processing_modes))
        if len(processing_modes) == 1
        else ("mixed" if processing_modes else "")
    )

    summary = {
        "table_name": qualified_name,
        "chunk_count": chunk_count,
        "document_count": len(document_files),
        "job_id": job_ids[-1] if job_ids else "",
        "workflow_id": workflow_ids[-1] if workflow_ids else "",
        "workflow_name": workflow_names_seen[-1] if workflow_names_seen else last_workflow_name,
        "destination_id": "",
        "warnings": target_warnings + partition_warnings,
        "workflow_mode": "multi format on-demand jobs direct insert",
        "inserted_rows": inserted_rows,
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "debug_dir": str(debug_dir) if debug_dir else "",
        "debug_files": debug_files,
        "effective_partition_strategy": partition_strategy,
        "effective_ocr_languages": ocr_languages,
        "effective_partition_strategy_label": strategy_label,
        "effective_ocr_languages_label": languages_label,
        "processing_mode_label": processing_mode_label,
        "excel_structured_files": excel_structured_files,
        "scan_ocr_fallback_files": scan_ocr_fallback_files,
        "include_orig_elements": include_orig_elements,
        "overlap_all": overlap_all,
        "file_mode": "on-demand-jobs",
    }
    return patched_payload, summary
