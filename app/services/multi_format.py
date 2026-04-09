from __future__ import annotations

import hashlib
import httpx
import json
import mimetypes
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from app.services.bookrag_schema import build_bookrag_table_targets, prepare_bookrag_document_table, prepare_bookrag_raw_table
from app.services.bookrag_storage import (
    build_bookrag_document_row,
    build_bookrag_raw_rows,
    load_bookrag_raw_stage_file,
    persist_bookrag_documents,
    persist_bookrag_raw_rows,
    write_bookrag_raw_stage_file,
)

TERADATA_IDENTIFIER_MAX_LEN = 30
UNSTRUCTURED_CONFIG_FILE_DEFAULT = Path(__file__).resolve().parents[1] / "config" / "unstructured.json"
UNSTRUCTURED_WORKFLOW_API_URL_DEFAULT = "https://platform.unstructuredapp.io/api/v1"
UNSTRUCTURED_WORKFLOW_POLL_SECONDS_DEFAULT = 900
UNSTRUCTURED_WORKFLOW_POLL_INTERVAL_DEFAULT = 2
UNSTRUCTURED_TERADATA_FLUSH_WAIT_SECONDS_DEFAULT = 20
UNSTRUCTURED_TERADATA_FLUSH_WAIT_INTERVAL_DEFAULT = 2
UNSTRUCTURED_DEBUG_DIR_DEFAULT = Path(__file__).resolve().parents[2] / "uploads" / "multi_format_stage"
BOOKRAG_RAW_STAGE_DIR_DEFAULT = Path(__file__).resolve().parents[2] / "uploads" / "bookrag_raw_stage"
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
UNSTRUCTURED_FAST_UNSAFE_IMAGE_EXTENSIONS = BOOKRAG_PDF_IMAGE_EXTENSIONS - {".pdf"}
EXCEL_OPENXML_EXTENSIONS = {".xlsx", ".xlsm", ".xltx", ".xltm"}
EXCEL_LEGACY_EXTENSIONS = {".xls"}
EXCEL_EXTENSIONS = EXCEL_OPENXML_EXTENSIONS | EXCEL_LEGACY_EXTENSIONS


ExecuteSqlFn = Callable[[str], Any]
ResolvePathFn = Callable[[str], str]


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


def _resolve_bookrag_image_partition_options(create_values: dict[str, str]) -> tuple[dict[str, Any], list[str], dict[str, Any]]:
    runtime = _load_unstructured_runtime_settings()
    warnings: list[str] = []

    raw_extract_types = str(
        create_values.get("multi_format_bookrag_extract_image_block_types", "")
        or runtime.get("bookrag_extract_image_block_types")
        or runtime.get("extract_image_block_types")
        or os.getenv("BOOKRAG_EXTRACT_IMAGE_BLOCK_TYPES", "")
    ).strip()
    extract_mode = raw_extract_types.lower()
    if extract_mode == "auto":
        extract_image_block_types = ["Image", "Table"]
    else:
        extract_image_block_types = _parse_csv_values(raw_extract_types)

    raw_infer_table_structure = str(
        create_values.get("multi_format_bookrag_infer_table_structure", "")
        or runtime.get("bookrag_infer_table_structure")
        or runtime.get("infer_table_structure")
        or os.getenv("BOOKRAG_INFER_TABLE_STRUCTURE", "")
    ).strip()
    infer_table_structure = _to_bool(raw_infer_table_structure, default=False)

    coordinates = _to_bool(
        create_values.get("multi_format_bookrag_coordinates", "true")
        or runtime.get("bookrag_coordinates")
        or os.getenv("BOOKRAG_COORDINATES", "true"),
        default=True,
    )
    unique_element_ids = _to_bool(
        runtime.get("bookrag_unique_element_ids")
        or runtime.get("unique_element_ids")
        or os.getenv("BOOKRAG_UNIQUE_ELEMENT_IDS", "true"),
        default=True,
    )
    hi_res_model_name = str(
        runtime.get("bookrag_hi_res_model_name")
        or runtime.get("hi_res_model_name")
        or os.getenv("BOOKRAG_HI_RES_MODEL_NAME", "")
    ).strip()

    extra: dict[str, Any] = {
        "coordinates": coordinates,
        "unique_element_ids": unique_element_ids,
        "infer_table_structure": infer_table_structure,
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


def _strip_file_based_create_params(payload: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(payload)
    for key in FILE_BASED_CREATE_KEYS_TO_REMOVE:
        cleaned.pop(key, None)
    return cleaned


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_langs(raw: str) -> list[str]:
    items = [chunk.strip() for chunk in str(raw or "").replace("\n", ",").split(",") if chunk.strip()]
    return items


def _resolve_partition_strategy(raw: str) -> str:
    value = str(raw or "auto").strip().lower()
    if value == "fast":
        return "fast"
    if value in {"hi_res", "layout"}:
        return "hi_res"
    if value == "vlm":
        return "vlm"
    if value == "ocr_only":
        return "ocr_only"
    return "auto"


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
    for element in elements:
        if not isinstance(element, dict):
            continue
        row = _element_to_chunk_row(element, src=src, content_type=content_type)
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


def _resolve_bookrag_workflow_poll_config() -> tuple[int, int]:
    runtime = _load_unstructured_runtime_settings()
    timeout_seconds = _to_int(
        runtime.get("bookrag_workflow_poll_seconds")
        or runtime.get("workflow_poll_seconds")
        or os.getenv("BOOKRAG_WORKFLOW_POLL_SECONDS")
        or os.getenv("UNSTRUCTURED_WORKFLOW_POLL_SECONDS"),
        default=UNSTRUCTURED_WORKFLOW_POLL_SECONDS_DEFAULT,
        minimum=10,
        maximum=3600,
    )
    poll_interval_seconds = _to_int(
        runtime.get("bookrag_workflow_poll_interval_seconds")
        or runtime.get("workflow_poll_interval_seconds")
        or os.getenv("BOOKRAG_WORKFLOW_POLL_INTERVAL_SECONDS")
        or os.getenv("UNSTRUCTURED_WORKFLOW_POLL_INTERVAL_SECONDS"),
        default=UNSTRUCTURED_WORKFLOW_POLL_INTERVAL_DEFAULT,
        minimum=1,
        maximum=60,
    )
    return timeout_seconds, min(timeout_seconds, max(1, poll_interval_seconds))


def _resolve_multi_format_workflow_poll_config() -> tuple[int, int]:
    runtime = _load_unstructured_runtime_settings()
    timeout_seconds = _to_int(
        runtime.get("multi_format_workflow_poll_seconds")
        or runtime.get("workflow_poll_seconds")
        or os.getenv("MULTI_FORMAT_WORKFLOW_POLL_SECONDS")
        or os.getenv("UNSTRUCTURED_WORKFLOW_POLL_SECONDS"),
        default=UNSTRUCTURED_WORKFLOW_POLL_SECONDS_DEFAULT,
        minimum=10,
        maximum=3600,
    )
    poll_interval_seconds = _to_int(
        runtime.get("multi_format_workflow_poll_interval_seconds")
        or runtime.get("workflow_poll_interval_seconds")
        or os.getenv("MULTI_FORMAT_WORKFLOW_POLL_INTERVAL_SECONDS")
        or os.getenv("UNSTRUCTURED_WORKFLOW_POLL_INTERVAL_SECONDS"),
        default=UNSTRUCTURED_WORKFLOW_POLL_INTERVAL_DEFAULT,
        minimum=1,
        maximum=60,
    )
    return timeout_seconds, min(timeout_seconds, max(1, poll_interval_seconds))


def _resolve_multi_format_accuracy_options(create_values: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    runtime = _load_unstructured_runtime_settings()
    warnings: list[str] = []

    infer_table_structure = _to_bool(
        create_values.get("multi_format_infer_table_structure", "")
        or runtime.get("multi_format_infer_table_structure")
        or runtime.get("infer_table_structure")
        or os.getenv("MULTI_FORMAT_INFER_TABLE_STRUCTURE", "true"),
        default=True,
    )
    hi_res_model_name = str(
        create_values.get("multi_format_hi_res_model_name", "")
        or runtime.get("multi_format_hi_res_model_name")
        or runtime.get("hi_res_model_name")
        or os.getenv("MULTI_FORMAT_HI_RES_MODEL_NAME", "")
    ).strip()
    vlm_provider = str(
        create_values.get("multi_format_vlm_provider", "")
        or runtime.get("multi_format_vlm_provider")
        or runtime.get("vlm_provider")
        or os.getenv("MULTI_FORMAT_VLM_PROVIDER", "")
    ).strip()
    vlm_model = str(
        create_values.get("multi_format_vlm_model", "")
        or runtime.get("multi_format_vlm_model")
        or runtime.get("vlm_model")
        or os.getenv("MULTI_FORMAT_VLM_MODEL", "")
    ).strip()
    vlm_provider_api_key = str(
        create_values.get("multi_format_vlm_provider_api_key", "")
        or runtime.get("multi_format_vlm_provider_api_key")
        or runtime.get("vlm_provider_api_key")
        or os.getenv("MULTI_FORMAT_VLM_PROVIDER_API_KEY", "")
    ).strip()

    enable_generative_ocr = _to_bool(
        create_values.get("multi_format_enable_generative_ocr", "")
        or runtime.get("multi_format_enable_generative_ocr")
        or os.getenv("MULTI_FORMAT_ENABLE_GENERATIVE_OCR", "true"),
        default=True,
    )
    enable_table_to_html = _to_bool(
        create_values.get("multi_format_enable_table_to_html", "")
        or runtime.get("multi_format_enable_table_to_html")
        or os.getenv("MULTI_FORMAT_ENABLE_TABLE_TO_HTML", "true"),
        default=True,
    )
    enable_table_description = _to_bool(
        create_values.get("multi_format_enable_table_description", "")
        or runtime.get("multi_format_enable_table_description")
        or os.getenv("MULTI_FORMAT_ENABLE_TABLE_DESCRIPTION", "false"),
        default=False,
    )
    enable_image_description = _to_bool(
        create_values.get("multi_format_enable_image_description", "")
        or runtime.get("multi_format_enable_image_description")
        or os.getenv("MULTI_FORMAT_ENABLE_IMAGE_DESCRIPTION", "false"),
        default=False,
    )

    raw_extract_types = str(
        create_values.get("multi_format_extract_image_block_types", "")
        or runtime.get("multi_format_extract_image_block_types")
        or os.getenv("MULTI_FORMAT_EXTRACT_IMAGE_BLOCK_TYPES", "auto")
    ).strip()
    if raw_extract_types.lower() == "auto":
        extract_image_block_types: list[str] = []
        if enable_generative_ocr:
            extract_image_block_types.extend(["NarrativeText", "Title", "ListItem", "UncategorizedText"])
        if enable_table_to_html or enable_table_description:
            extract_image_block_types.append("Table")
        if enable_image_description:
            extract_image_block_types.append("Image")
    else:
        extract_image_block_types = _parse_csv_values(raw_extract_types)
    normalized_extract_types: list[str] = []
    for item in extract_image_block_types:
        value = str(item or "").strip()
        if value and value not in normalized_extract_types:
            normalized_extract_types.append(value)

    partition_options: dict[str, Any] = {
        "infer_table_structure": infer_table_structure,
        "extract_image_block_types": normalized_extract_types,
        "hi_res_model_name": hi_res_model_name or None,
        "vlm_provider": vlm_provider or None,
        "vlm_model": vlm_model or None,
        "vlm_provider_api_key": vlm_provider_api_key or None,
        "unique_element_ids": True,
    }

    def _provider_settings(prefix: str, *, default_subtype: str, default_provider: str, default_model: str) -> tuple[str, dict[str, Any]]:
        subtype = str(
            create_values.get(f"multi_format_{prefix}_subtype", "")
            or runtime.get(f"multi_format_{prefix}_subtype")
            or os.getenv(f"MULTI_FORMAT_{prefix.upper()}_SUBTYPE", default_subtype)
        ).strip() or default_subtype
        provider_type = str(
            create_values.get(f"multi_format_{prefix}_provider_type", "")
            or runtime.get(f"multi_format_{prefix}_provider_type")
            or os.getenv(f"MULTI_FORMAT_{prefix.upper()}_PROVIDER_TYPE", default_provider)
        ).strip() or default_provider
        model = str(
            create_values.get(f"multi_format_{prefix}_model", "")
            or runtime.get(f"multi_format_{prefix}_model")
            or os.getenv(f"MULTI_FORMAT_{prefix.upper()}_MODEL", default_model)
        ).strip() or default_model
        settings: dict[str, Any] = {}
        if subtype != "twopass_table2html":
            if provider_type:
                settings["provider_type"] = provider_type
            if model:
                settings["model"] = model
        return subtype, settings

    enrichment_options = {
        "enable_generative_ocr": enable_generative_ocr,
        "enable_table_to_html": enable_table_to_html,
        "enable_table_description": enable_table_description,
        "enable_image_description": enable_image_description,
    }
    subtype, settings = _provider_settings(
        "generative_ocr",
        default_subtype="openai_ocr",
        default_provider="openai",
        default_model="gpt-5-mini",
    )
    enrichment_options["generative_ocr_subtype"] = subtype
    enrichment_options["generative_ocr_settings"] = settings
    subtype, settings = _provider_settings(
        "table_to_html",
        default_subtype="twopass_table2html",
        default_provider="",
        default_model="",
    )
    enrichment_options["table_to_html_subtype"] = subtype
    enrichment_options["table_to_html_settings"] = settings
    subtype, settings = _provider_settings(
        "table_description",
        default_subtype="openai_table_description",
        default_provider="openai",
        default_model="gpt-5-mini",
    )
    enrichment_options["table_description_subtype"] = subtype
    enrichment_options["table_description_settings"] = settings
    subtype, settings = _provider_settings(
        "image_description",
        default_subtype="openai_image_description",
        default_provider="openai",
        default_model="gpt-5-mini",
    )
    enrichment_options["image_description_subtype"] = subtype
    enrichment_options["image_description_settings"] = settings

    return partition_options, enrichment_options, warnings


def _build_multi_format_workflow_partition_node(
    *,
    src: Path,
    partition_strategy: str,
    languages: list[str],
    partition_options: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    partition_options = partition_options or {}
    extract_image_block_types = partition_options.get("extract_image_block_types") or []
    hi_res_model_name = str(partition_options.get("hi_res_model_name") or "").strip()
    infer_table_structure = bool(partition_options.get("infer_table_structure"))
    unique_element_ids = bool(partition_options.get("unique_element_ids", True))
    vlm_provider = str(partition_options.get("vlm_provider") or "").strip()
    vlm_model = str(partition_options.get("vlm_model") or "").strip()
    vlm_provider_api_key = str(partition_options.get("vlm_provider_api_key") or "").strip()
    requested_strategy = (partition_strategy or "auto").strip().lower() or "auto"

    if requested_strategy == "auto":
        settings: dict[str, Any] = {
            "strategy": "auto",
            "output_format": "application/json",
            "format_html": False,
            "unique_element_ids": unique_element_ids,
            "is_dynamic": True,
            "allow_fast": True,
        }
        if vlm_provider:
            settings["provider"] = vlm_provider
        if vlm_model:
            settings["model"] = vlm_model
        if vlm_provider_api_key:
            settings["provider_api_key"] = vlm_provider_api_key
        return {
            "name": "Partitioner",
            "type": "partition",
            "subtype": "vlm",
            "settings": settings,
        }, warnings

    if requested_strategy == "vlm":
        settings = {
            "strategy": "vlm",
            "output_format": "application/json",
            "format_html": False,
            "unique_element_ids": unique_element_ids,
            "is_dynamic": False,
            "allow_fast": False,
        }
        if vlm_provider:
            settings["provider"] = vlm_provider
        if vlm_model:
            settings["model"] = vlm_model
        if vlm_provider_api_key:
            settings["provider_api_key"] = vlm_provider_api_key
        return {
            "name": "Partitioner",
            "type": "partition",
            "subtype": "vlm",
            "settings": settings,
        }, warnings

    settings = {
        "strategy": requested_strategy,
        "include_page_breaks": False,
        "unique_element_ids": unique_element_ids,
    }
    if languages:
        settings["ocr_languages"] = languages
    if extract_image_block_types:
        settings["extract_image_block_types"] = extract_image_block_types
    if requested_strategy == "hi_res" and infer_table_structure:
        settings["pdf_infer_table_structure"] = True
        settings["infer_table_structure"] = True
    if hi_res_model_name and requested_strategy == "hi_res":
        settings["hi_res_model_name"] = hi_res_model_name
    return {
        "name": "Partitioner",
        "type": "partition",
        "subtype": "unstructured_api",
        "settings": settings,
    }, warnings


def _build_multi_format_enrichment_nodes(*, enrichment_options: dict[str, Any], partition_strategy: str) -> tuple[list[dict[str, Any]], list[str]]:
    requested_strategy = (partition_strategy or "auto").strip().lower() or "auto"
    if requested_strategy not in {"auto", "hi_res"}:
        return [], []

    nodes: list[dict[str, Any]] = []
    if enrichment_options.get("enable_image_description"):
        nodes.append({
            "name": "Image Description",
            "type": "prompter",
            "subtype": str(enrichment_options.get("image_description_subtype") or "openai_image_description"),
            "settings": dict(enrichment_options.get("image_description_settings") or {}),
        })
    if enrichment_options.get("enable_table_to_html"):
        nodes.append({
            "name": "Table to HTML",
            "type": "prompter",
            "subtype": str(enrichment_options.get("table_to_html_subtype") or "twopass_table2html"),
            "settings": dict(enrichment_options.get("table_to_html_settings") or {}),
        })
    if enrichment_options.get("enable_table_description"):
        nodes.append({
            "name": "Table Description",
            "type": "prompter",
            "subtype": str(enrichment_options.get("table_description_subtype") or "openai_table_description"),
            "settings": dict(enrichment_options.get("table_description_settings") or {}),
        })
    if enrichment_options.get("enable_generative_ocr"):
        nodes.append({
            "name": "Generative OCR",
            "type": "prompter",
            "subtype": str(enrichment_options.get("generative_ocr_subtype") or "openai_ocr"),
            "settings": dict(enrichment_options.get("generative_ocr_settings") or {}),
        })

    return nodes, []


def _build_bookrag_workflow_partition_node(
    *,
    src: Path,
    partition_strategy: str,
    languages: list[str],
    image_partition_parameters: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    warnings: list[str] = []
    image_partition_parameters = image_partition_parameters or {}
    extract_image_block_types = image_partition_parameters.get("extract_image_block_types") or []
    normalized_extract_types: list[str] = []
    for item in extract_image_block_types:
        value = str(item or "").strip()
        if not value:
            continue
        normalized = "Image" if value.lower() == "image" else "Table" if value.lower() == "table" else value
        if normalized not in normalized_extract_types:
            normalized_extract_types.append(normalized)

    hi_res_model_name = str(image_partition_parameters.get("hi_res_model_name") or "").strip()
    infer_table_structure = bool(image_partition_parameters.get("infer_table_structure"))
    requested_strategy = (partition_strategy or "auto").strip().lower() or "auto"
    unique_element_ids = bool(image_partition_parameters.get("unique_element_ids", True))

    if requested_strategy == "auto":
        if languages:
            warnings.append(
                f"bookrag ocr_languages for {src.name} are ignored when workflow strategy='auto'; Unstructured auto routing controls OCR internally."
            )
        if normalized_extract_types:
            warnings.append(
                f"bookrag extract_image_block_types for {src.name} are ignored when workflow strategy='auto'; downstream enrichment nodes handle matching elements automatically."
            )
        if infer_table_structure:
            warnings.append(
                f"bookrag infer_table_structure for {src.name} is ignored when workflow strategy='auto'; use the Table to HTML enrichment node instead."
            )
        settings: dict[str, Any] = {
            "strategy": "auto",
            "output_format": "application/json",
            "format_html": False,
            "unique_element_ids": unique_element_ids,
            "is_dynamic": True,
            "allow_fast": True,
        }
        workflow_node = {
            "name": "Partitioner",
            "type": "partition",
            "subtype": "vlm",
            "settings": settings,
        }
    elif requested_strategy == "vlm":
        settings = {
            "strategy": "vlm",
            "output_format": "application/json",
            "format_html": False,
            "unique_element_ids": unique_element_ids,
            "is_dynamic": False,
            "allow_fast": False,
        }
        if infer_table_structure:
            settings["infer_table_structure"] = True
        workflow_node = {
            "name": "Partitioner",
            "type": "partition",
            "subtype": "vlm",
            "settings": settings,
        }
    else:
        settings = {
            "strategy": requested_strategy,
            "include_page_breaks": False,
            "unique_element_ids": unique_element_ids,
        }
        if languages:
            settings["ocr_languages"] = languages
        if normalized_extract_types:
            settings["extract_image_block_types"] = normalized_extract_types
        if requested_strategy == "hi_res" and infer_table_structure:
            settings["pdf_infer_table_structure"] = True
            settings["infer_table_structure"] = True
        if hi_res_model_name and requested_strategy == "hi_res":
            settings["hi_res_model_name"] = hi_res_model_name
        if requested_strategy not in {"hi_res", "vlm"} and infer_table_structure:
            warnings.append(
                f"bookrag infer_table_structure was requested for {src.name} but is only enabled when strategy='hi_res' or 'vlm'."
            )
        workflow_node = {
            "name": "Partitioner",
            "type": "partition",
            "subtype": "unstructured_api",
            "settings": settings,
        }

    request_parameters = {
        "source_file": str(src),
        "workflow_type": "custom",
        "workflow_nodes": [workflow_node],
    }
    return workflow_node, request_parameters, warnings


def _normalize_bookrag_workflow_name(raw_name: str | None) -> str:
    name = str(raw_name or "").strip()
    if not name:
        return "bookrag_raw_prod"
    return re.sub(r"\s+", "_", name)


def _workflow_node_payload(node: Any) -> dict[str, Any]:
    if hasattr(node, "model_dump"):
        data = node.model_dump(by_alias=True, exclude_none=True)
    elif isinstance(node, dict):
        data = dict(node)
    else:
        data = {
            "name": getattr(node, "name", None),
            "type": getattr(node, "type", None),
            "subtype": getattr(node, "subtype", None),
            "settings": getattr(node, "settings", None),
        }
    return {
        "name": str(data.get("name") or "").strip(),
        "type": str(data.get("type") or "").strip(),
        "subtype": str(data.get("subtype") or "").strip(),
        "settings": _json_safe_value(data.get("settings") or {}),
    }


def _workflow_nodes_signature(nodes: list[Any]) -> str:
    normalized = [_workflow_node_payload(node) for node in nodes]
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True)


def _workflow_debug_payload(
    request_parameters: dict[str, Any] | None,
    *,
    processing_profile: str = "",
    workflow_id: str = "",
    workflow_name: str = "",
    job_id: str = "",
    workflow_kind: str = "",
) -> dict[str, Any]:
    request_parameters = dict(request_parameters or {})
    workflow_nodes = [_workflow_node_payload(node) for node in (request_parameters.get("workflow_nodes") or [])]
    partition_node = workflow_nodes[0] if workflow_nodes else {}
    chunk_node = workflow_nodes[1] if len(workflow_nodes) > 1 else {}
    partition_settings = partition_node.get("settings") or {}
    return {
        "workflow_kind": workflow_kind or request_parameters.get("workflow_type") or "custom",
        "workflow_id": str(workflow_id or request_parameters.get("workflow_id") or "").strip(),
        "workflow_name": str(workflow_name or request_parameters.get("workflow_name") or "").strip(),
        "job_id": str(job_id or request_parameters.get("job_id") or "").strip(),
        "job_definition": _json_safe_value(request_parameters),
        "workflow_nodes": workflow_nodes,
        "partition_node": partition_node,
        "chunk_node": chunk_node,
        "partition_subtype": str(partition_node.get("subtype") or "").strip(),
        "partition_strategy": str(partition_settings.get("strategy") or "").strip(),
        "processing_profile": processing_profile,
    }


def _build_bookrag_reusable_workflow_definition(
    *,
    create_values: dict[str, str],
    partition_strategy: str,
    languages: list[str],
    image_partition_parameters: dict[str, Any] | None,
) -> tuple[str, list[dict[str, Any]], dict[str, Any], list[str], str]:
    runtime = _load_unstructured_runtime_settings()
    warnings: list[str] = []
    image_partition_parameters = image_partition_parameters or {}

    workflow_name = _normalize_bookrag_workflow_name(
        create_values.get("multi_format_bookrag_workflow_name")
        or runtime.get("bookrag_workflow_name")
        or os.getenv("BOOKRAG_WORKFLOW_NAME")
        or "bookrag_raw_prod"
    )

    enable_image_description = _to_bool(
        create_values.get("multi_format_bookrag_enable_image_description", "")
        or runtime.get("bookrag_enable_image_description")
        or os.getenv("BOOKRAG_ENABLE_IMAGE_DESCRIPTION", "true"),
        default=True,
    )
    enable_table_to_html = _to_bool(
        create_values.get("multi_format_bookrag_enable_table_to_html", "")
        or runtime.get("bookrag_enable_table_to_html")
        or os.getenv("BOOKRAG_ENABLE_TABLE_TO_HTML", "true"),
        default=True,
    )
    enable_table_description = _to_bool(
        create_values.get("multi_format_bookrag_enable_table_description", "")
        or runtime.get("bookrag_enable_table_description")
        or os.getenv("BOOKRAG_ENABLE_TABLE_DESCRIPTION", "false"),
        default=False,
    )
    enable_generative_ocr = _to_bool(
        create_values.get("multi_format_bookrag_enable_generative_ocr", "")
        or runtime.get("bookrag_enable_generative_ocr")
        or os.getenv("BOOKRAG_ENABLE_GENERATIVE_OCR", "false"),
        default=False,
    )

    image_subtype = str(
        create_values.get("multi_format_bookrag_image_description_subtype", "")
        or runtime.get("bookrag_image_description_subtype")
        or os.getenv("BOOKRAG_IMAGE_DESCRIPTION_SUBTYPE", "openai_image_description")
    ).strip() or "openai_image_description"
    table_to_html_subtype = str(
        create_values.get("multi_format_bookrag_table_to_html_subtype", "")
        or runtime.get("bookrag_table_to_html_subtype")
        or os.getenv("BOOKRAG_TABLE_TO_HTML_SUBTYPE", "openai_table2html")
    ).strip() or "openai_table2html"
    table_description_subtype = str(
        create_values.get("multi_format_bookrag_table_description_subtype", "")
        or runtime.get("bookrag_table_description_subtype")
        or os.getenv("BOOKRAG_TABLE_DESCRIPTION_SUBTYPE", "openai_table_description")
    ).strip() or "openai_table_description"
    generative_ocr_subtype = str(
        create_values.get("multi_format_bookrag_generative_ocr_subtype", "")
        or runtime.get("bookrag_generative_ocr_subtype")
        or os.getenv("BOOKRAG_GENERATIVE_OCR_SUBTYPE", "openai_ocr")
    ).strip() or "openai_ocr"

    partition_node, _, partition_warnings = _build_bookrag_workflow_partition_node(
        src=Path("bookrag_document"),
        partition_strategy=partition_strategy or "auto",
        languages=languages,
        image_partition_parameters=image_partition_parameters,
    )
    warnings.extend(partition_warnings)

    workflow_nodes: list[dict[str, Any]] = [partition_node]
    partition_strategy_label = partition_node['settings'].get('strategy', 'auto')
    partition_subtype_label = partition_node.get('subtype', '') or 'unknown'
    profile_parts = [f"partition:{partition_subtype_label}:{partition_strategy_label}"]
    if enable_image_description:
        workflow_nodes.append({
            "name": "Image Description",
            "type": "prompter",
            "subtype": image_subtype,
            "settings": {},
        })
        profile_parts.append("image_description")
    if enable_table_to_html:
        workflow_nodes.append({
            "name": "Table to HTML",
            "type": "prompter",
            "subtype": table_to_html_subtype,
            "settings": {},
        })
        profile_parts.append("table_to_html")
    if enable_table_description:
        workflow_nodes.append({
            "name": "Table Description",
            "type": "prompter",
            "subtype": table_description_subtype,
            "settings": {},
        })
        profile_parts.append("table_description")
    if enable_generative_ocr:
        workflow_nodes.append({
            "name": "Generative OCR",
            "type": "prompter",
            "subtype": generative_ocr_subtype,
            "settings": {},
        })
        profile_parts.append("generative_ocr")

    request_parameters = {
        "workflow_type": "custom",
        "workflow_name": workflow_name,
        "workflow_nodes": workflow_nodes,
    }
    return workflow_name, workflow_nodes, request_parameters, warnings, ",".join(profile_parts)


def _normalize_multi_format_workflow_name(raw_name: str | None) -> str:
    name = str(raw_name or "").strip()
    if not name:
        return "multi_format_prod"
    return re.sub(r"\s+", "_", name)


def _build_multi_format_workflow_chunk_node(
    *,
    chunk_size: int,
    chunk_overlap: int,
    include_orig_elements: bool,
    overlap_all: bool,
) -> dict[str, Any]:
    return {
        "name": "Chunker",
        "type": "chunk",
        "subtype": "chunk_by_character",
        "settings": {
            "unstructured_api_url": None,
            "unstructured_api_key": None,
            "include_orig_elements": include_orig_elements,
            "new_after_n_chars": chunk_size,
            "max_characters": chunk_size,
            "overlap": chunk_overlap,
            "overlap_all": overlap_all,
        },
    }


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
    runtime = _load_unstructured_runtime_settings()
    warnings: list[str] = []

    workflow_name = _normalize_multi_format_workflow_name(
        create_values.get("multi_format_workflow_name")
        or runtime.get("multi_format_workflow_name")
        or os.getenv("MULTI_FORMAT_WORKFLOW_NAME")
        or "multi_format_prod"
    )

    partition_options, enrichment_options, option_warnings = _resolve_multi_format_accuracy_options(create_values)
    warnings.extend(option_warnings)

    partition_node, partition_warnings = _build_multi_format_workflow_partition_node(
        src=src,
        partition_strategy=partition_strategy or "auto",
        languages=languages,
        partition_options=partition_options,
    )
    warnings.extend(partition_warnings)

    enrichment_nodes, enrichment_warnings = _build_multi_format_enrichment_nodes(
        enrichment_options=enrichment_options,
        partition_strategy=partition_strategy or "auto",
    )
    warnings.extend(enrichment_warnings)

    chunker_node = _build_multi_format_workflow_chunk_node(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        include_orig_elements=include_orig_elements,
        overlap_all=overlap_all,
    )
    workflow_nodes = [partition_node, *enrichment_nodes, chunker_node]
    request_parameters = {
        "workflow_type": "custom",
        "workflow_name": workflow_name,
        "workflow_nodes": workflow_nodes,
    }
    partition_strategy_label = partition_node['settings'].get('strategy', 'auto')
    partition_subtype_label = partition_node.get('subtype', '') or 'unknown'
    profile_parts = [f"partition:{partition_subtype_label}:{partition_strategy_label}"]
    for node in enrichment_nodes:
        node_name = str(node.get('name') or '').strip().lower().replace(' ', '_') or 'enrichment'
        node_subtype = str(node.get('subtype') or '').strip() or 'unknown'
        profile_parts.append(f"{node_name}:{node_subtype}")
    profile_parts.append("chunk:chunk_by_character")
    processing_profile = ",".join(profile_parts)
    return request_parameters, warnings, processing_profile


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


def _create_unstructured_on_demand_job(*, request_parameters: dict[str, Any], src: Path) -> tuple[str, dict[str, Any]]:
    api_key, api_url = _load_unstructured_runtime_config()
    content_type = mimetypes.guess_type(src.name)[0] or "application/octet-stream"
    endpoint = f"{api_url.rstrip('/')}" + "/jobs/"
    request_data = json.dumps({"job_nodes": request_parameters.get("workflow_nodes", [])}, ensure_ascii=False)
    response = httpx.post(
        endpoint,
        headers={
            "unstructured-api-key": api_key,
            "accept": "application/json",
        },
        files=[
            ("request_data", (None, request_data, "application/json")),
            (
                "input_files",
                (src.name, src.read_bytes(), content_type),
            ),
        ],
        timeout=120.0,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Unstructured create_job failed. status={response.status_code} body={response.text}")
    try:
        payload = response.json()
    except Exception as ex:
        raise RuntimeError(f"Unstructured create_job returned non-JSON response. status={response.status_code}") from ex
    job_id = str(payload.get("id") or "").strip()
    if not job_id:
        raise RuntimeError("Unstructured create_job returned no job ID.")
    return job_id, payload


def _wait_for_unstructured_job(client, *, job_id: str, timeout_seconds: int, poll_interval_seconds: int):
    from unstructured_client.models import operations

    started = time.time()
    last_status = ""
    while True:
        response = client.jobs.get_job(request=operations.GetJobRequest(job_id=job_id))
        if int(getattr(response, "status_code", 0) or 0) >= 400:
            raise RuntimeError(f"Unstructured get_job failed. status={getattr(response, 'status_code', '?')}, job_id={job_id}")
        job_info = getattr(response, "job_information", None)
        if job_info is None:
            raise RuntimeError(f"Unstructured get_job returned no job information. job_id={job_id}")
        raw_status = getattr(job_info, "status", "")
        status = str(getattr(raw_status, "value", raw_status) or "").strip().upper()
        if status == "COMPLETED":
            return job_info
        if status in {"FAILED", "STOPPED"}:
            raise RuntimeError(f"Unstructured job ended with status={status}. job_id={job_id}")
        last_status = status or last_status
        if time.time() - started >= timeout_seconds:
            raise RuntimeError(
                "Timed out waiting for Unstructured job completion. "
                f"job_id={job_id}, last_status={last_status or 'UNKNOWN'}, timeout_seconds={timeout_seconds}. "
                "Increase the mode-specific workflow poll timeout or UNSTRUCTURED_WORKFLOW_POLL_SECONDS if this is expected for large files."
            )
        time.sleep(max(1, poll_interval_seconds))


def _download_unstructured_job_output_payload(client, job_info) -> Any:
    from unstructured_client.models import operations

    output_node_files = list(getattr(job_info, "output_node_files", None) or [])
    if output_node_files:
        target = output_node_files[-1]
        request = operations.DownloadJobOutputRequest(
            job_id=str(getattr(job_info, "id", "") or ""),
            file_id=str(getattr(target, "file_id", "") or ""),
            node_id=str(getattr(target, "node_id", "") or ""),
        )
    else:
        input_file_ids = list(getattr(job_info, "input_file_ids", None) or [])
        if not input_file_ids:
            raise RuntimeError(f"Unstructured job returned no downloadable output references. job_id={getattr(job_info, 'id', '')}")
        request = operations.DownloadJobOutputRequest(
            job_id=str(getattr(job_info, "id", "") or ""),
            file_id=str(input_file_ids[0]),
        )

    response = client.jobs.download_job_output(request=request)
    if int(getattr(response, "status_code", 0) or 0) >= 400:
        raise RuntimeError(f"Unstructured download_job_output failed. status={getattr(response, 'status_code', '?')}, job_id={getattr(job_info, 'id', '')}")
    return getattr(response, "any", None)


def _extract_elements_from_unstructured_job_output(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("elements", "output", "data"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, dict)]
        list_values = [value for value in payload.values() if isinstance(value, list)]
        if len(list_values) == 1:
            return [item for item in list_values[0] if isinstance(item, dict)]
    raise RuntimeError("Unsupported Unstructured workflow output format; expected a JSON array or object containing an elements array.")


def _enforce_unstructured_job_submission_spacing(last_submitted_at: float | None) -> float:
    minimum_spacing_seconds = 1.1
    now = time.time()
    if last_submitted_at is not None:
        remaining = minimum_spacing_seconds - (now - last_submitted_at)
        if remaining > 0:
            time.sleep(remaining)
    return time.time()


def _run_unstructured_workflow_job_for_file(
    client,
    *,
    request_parameters: dict[str, Any],
    src: Path,
    timeout_seconds: int,
    poll_interval_seconds: int,
) -> tuple[Any, list[dict[str, Any]], dict[str, Any], str, str, str]:
    job_id, create_job_payload = _create_unstructured_on_demand_job(request_parameters=request_parameters, src=src)
    job_info = _wait_for_unstructured_job(
        client,
        job_id=job_id,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
    payload = _download_unstructured_job_output_payload(client, job_info)
    elements = _extract_elements_from_unstructured_job_output(payload)
    workflow_id = str(getattr(job_info, "workflow_id", "") or create_job_payload.get("workflow_id") or "").strip()
    workflow_name = str(getattr(job_info, "workflow_name", "") or create_job_payload.get("workflow_name") or request_parameters.get("workflow_name") or "").strip()
    file_request_parameters = dict(request_parameters)
    file_request_parameters.update(
        {
            "workflow_id": workflow_id,
            "workflow_name": workflow_name,
            "source_file": str(src),
            "job_id": job_id,
            "poll_timeout_seconds": timeout_seconds,
            "poll_interval_seconds": poll_interval_seconds,
        }
    )
    return payload, elements, file_request_parameters, job_id, workflow_id, workflow_name

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


def _load_unstructured_runtime_settings() -> dict[str, Any]:
    config_path = UNSTRUCTURED_CONFIG_FILE_DEFAULT
    config: dict[str, Any] = {}
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            if not isinstance(config, dict):
                raise RuntimeError("must be a JSON object")
        except Exception as ex:
            raise RuntimeError(f"Invalid Unstructured config at {config_path}: {ex}") from ex
    return config


def _load_unstructured_runtime_config() -> tuple[str, str]:
    config = _load_unstructured_runtime_settings()

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
            f"Unstructured API key missing. Set key_id/api_key in {UNSTRUCTURED_CONFIG_FILE_DEFAULT}."
        )
    if not api_url:
        api_url = UNSTRUCTURED_WORKFLOW_API_URL_DEFAULT
    return api_key, api_url


def _new_unstructured_client():
    api_key, api_url = _load_unstructured_runtime_config()
    from unstructured_client import UnstructuredClient

    return UnstructuredClient(api_key_auth=api_key, server_url=api_url.rstrip("/"))


def _apply_bookrag_tree_pipeline(
    exec_payload: dict,
    create_values: dict[str, str],
    vector_store_name: str,
    *,
    execute_sql_fn: ExecuteSqlFn | None,
    resolve_path_hint: ResolvePathFn,
    effective_schema_name: str | None,
    document_files: list[str],
    partition_strategy: str,
    ocr_languages: list[str],
    target_warnings: list[str],
) -> tuple[dict, dict]:
    bookrag_tables = build_bookrag_table_targets(vector_store_name)
    target_warnings.extend(
        prepare_bookrag_document_table(
            schema_name=effective_schema_name,
            table_targets=bookrag_tables,
            execute_sql_fn=execute_sql_fn,
        )
    )
    target_warnings.extend(
        prepare_bookrag_raw_table(
            schema_name=effective_schema_name,
            table_targets=bookrag_tables,
            execute_sql_fn=execute_sql_fn,
        )
    )
    image_partition_parameters, image_partition_warnings, image_partition_summary = _resolve_bookrag_image_partition_options(create_values)
    target_warnings.extend(image_partition_warnings)

    bookrag_chunk_size = _to_int(create_values.get("multi_format_bookrag_chunk_size", "1200"), default=1200, minimum=100, maximum=32000)
    bookrag_chunk_overlap = _to_int(create_values.get("multi_format_bookrag_chunk_overlap", "120"), default=120, minimum=0, maximum=4000)
    bookrag_new_after = _to_int(create_values.get("multi_format_bookrag_new_after_n_chars", str(min(bookrag_chunk_size, 1000))), default=min(bookrag_chunk_size, 1000), minimum=100, maximum=32000)
    bookrag_combine_under = _to_int(create_values.get("multi_format_bookrag_combine_under_n_chars", str(min(bookrag_chunk_size, 600))), default=min(bookrag_chunk_size, 600), minimum=0, maximum=32000)
    bookrag_multipage_sections = _to_bool(create_values.get("multi_format_bookrag_multipage_sections", "true"), default=True)
    if bookrag_new_after > bookrag_chunk_size:
        bookrag_new_after = bookrag_chunk_size
    if bookrag_combine_under > bookrag_chunk_size:
        bookrag_combine_under = bookrag_chunk_size
    if bookrag_chunk_overlap >= bookrag_chunk_size:
        bookrag_chunk_overlap = max(0, bookrag_chunk_size // 10)

    client = _new_unstructured_client()
    debug_dir = _prepare_unstructured_debug_dir(vector_store_name)
    raw_stage_dir = _prepare_bookrag_raw_stage_dir(vector_store_name)
    partition_warnings: list[str] = []
    debug_files: list[str] = []
    raw_stage_files: list[str] = []
    job_ids: list[str] = []
    document_insert_stats: dict[str, int] = {}
    raw_insert_stats: dict[str, int] = {}
    inserted_rows = 0
    raw_element_count = 0
    document_count = 0
    document_rows: list[dict[str, Any]] = []
    all_raw_rows: list[dict[str, Any]] = []

    qualified_tables = {
        name: (f"{effective_schema_name}.{table_name}" if effective_schema_name else table_name)
        for name, table_name in bookrag_tables.items()
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
        document_rows.append(
            build_bookrag_document_row(
                doc_id=doc_id,
                vector_store_name=vector_store_name,
                workflow_id=workflow_id,
                workflow_name=workflow_name_for_job or workflow_name,
                job_id=job_id,
                processing_profile=processing_profile,
                filename=src.name,
                source_file=str(raw_stage_file),
                filetype=mimetypes.guess_type(src.name)[0] or src.suffix.lower().lstrip("."),
                filesize_bytes=src.stat().st_size,
            )
        )
        raw_rows = build_bookrag_raw_rows(
            doc_id=doc_id,
            elements=staged_raw_elements,
        )
        debug_file = _write_unstructured_debug_file(
            debug_dir,
            src,
            staged_raw_elements,
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
            },
        )
        if debug_file:
            debug_files.append(debug_file)
        if not raw_rows:
            partition_warnings.append(f"No BookRAG raw elements extracted from file: {src.name}")
            continue
        all_raw_rows.extend(raw_rows)
        document_count += 1
        raw_element_count += len(raw_rows)

    inserted_rows += persist_bookrag_documents(
        schema_name=effective_schema_name,
        table_targets=bookrag_tables,
        rows=document_rows,
        execute_sql_fn=execute_sql_fn,
        stats=document_insert_stats,
    )
    inserted_rows += persist_bookrag_raw_rows(
        schema_name=effective_schema_name,
        table_targets=bookrag_tables,
        rows=all_raw_rows,
        execute_sql_fn=execute_sql_fn,
        stats=raw_insert_stats,
    )

    persisted_raw_count = _count_teradata_rows(
        schema_name=effective_schema_name,
        table_name=bookrag_tables["raw"],
        execute_sql_fn=execute_sql_fn,
    )
    if persisted_raw_count is None:
        persisted_raw_count = raw_element_count
    if persisted_raw_count <= 0:
        raise RuntimeError(
            "bookrag workflow completed but destination raw table has 0 rows. "
            f"table={qualified_tables['raw']}"
        )

    patched_payload = _strip_file_based_create_params(exec_payload)
    patched_payload["object_names"] = qualified_tables["raw"]

    summary = {
        "table_name": "",
        "documents_table_name": qualified_tables["documents"],
        "raw_table_name": qualified_tables["raw"],
        "raw_element_count": persisted_raw_count,
        "chunk_count": 0,
        "document_count": document_count,
        "job_id": job_ids[-1] if job_ids else "",
        "job_ids": job_ids,
        "workflow_id": workflow_ids[-1] if workflow_ids else "",
        "workflow_name": workflow_names_seen[-1] if workflow_names_seen else workflow_name,
        "destination_id": "",
        "warnings": target_warnings + partition_warnings,
        "workflow_mode": "bookrag on-demand jobs raw only",
        "inserted_rows": inserted_rows,
        "chunk_size": bookrag_chunk_size,
        "chunk_overlap": bookrag_chunk_overlap,
        "debug_dir": str(debug_dir) if debug_dir else "",
        "debug_files": debug_files,
        "bookrag_raw_stage_dir": str(raw_stage_dir),
        "bookrag_raw_stage_files": raw_stage_files,
        "bookrag_csv_stage_dir": "",
        "bookrag_csv_stage_files": [],
        "effective_partition_strategy": partition_strategy,
        "effective_ocr_languages": ocr_languages,
        "include_orig_elements": False,
        "file_mode": "on-demand-jobs",
        "bookrag_tables": {"documents": qualified_tables["documents"], "raw": qualified_tables["raw"]},
        "bookrag_profile": processing_profile,
        "bookrag_document_insert_stats": document_insert_stats,
        "bookrag_raw_insert_stats": raw_insert_stats,
        "bookrag_chunk_insert_stats": {},
        "bookrag_insert_stats": raw_insert_stats,
        "bookrag_image_partition_parameters": image_partition_summary,
        "bookrag_chunking_strategy": "disabled",
        "bookrag_new_after_n_chars": bookrag_new_after,
        "bookrag_combine_under_n_chars": bookrag_combine_under,
        "bookrag_multipage_sections": bookrag_multipage_sections,
    }
    return patched_payload, summary


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
        )

    target_warnings.extend(
        _ensure_unstructured_teradata_table(
            schema_name=effective_schema_name,
            table_name=table_name,
            execute_sql_fn=execute_sql_fn,
            clear_rows=True,
        )
    )

    client = _new_unstructured_client()
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
        request_parameters, workflow_definition_warnings, processing_profile = _build_multi_format_workflow_definition(
            create_values=create_values,
            src=src,
            partition_strategy=file_partition_strategy,
            languages=file_ocr_languages,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            include_orig_elements=file_include_orig_elements,
            overlap_all=overlap_all,
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
            row = _element_to_chunk_row(element, src=src, content_type=content_type)
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
