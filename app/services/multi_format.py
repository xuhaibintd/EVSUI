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

from app.services.bookrag_graph import build_bookrag_entities
from app.services.bookrag_schema import build_bookrag_table_targets, prepare_bookrag_leaf_view, prepare_bookrag_tables
from app.services.bookrag_storage import persist_bookrag_tree
from app.services.bookrag_tree import (
    build_bookrag_document_row,
    build_bookrag_nodes,
    elements_to_bookrag_blocks,
)

TERADATA_IDENTIFIER_MAX_LEN = 30
UNSTRUCTURED_CONFIG_FILE_DEFAULT = Path(__file__).resolve().parents[1] / "config" / "unstructured.json"
UNSTRUCTURED_WORKFLOW_API_URL_DEFAULT = "https://platform.unstructuredapp.io/api/v1"
UNSTRUCTURED_WORKFLOW_POLL_SECONDS_DEFAULT = 120
UNSTRUCTURED_WORKFLOW_POLL_INTERVAL_DEFAULT = 2
UNSTRUCTURED_TERADATA_FLUSH_WAIT_SECONDS_DEFAULT = 20
UNSTRUCTURED_TERADATA_FLUSH_WAIT_INTERVAL_DEFAULT = 2
UNSTRUCTURED_DEBUG_DIR_DEFAULT = Path(__file__).resolve().parents[2] / "uploads" / "unstructured_debug"
BOOKRAG_CSV_STAGE_DIR_DEFAULT = Path(__file__).resolve().parents[2] / "uploads" / "bookrag_csv_stage"
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

    if is_scan_like:
        if resolved_strategy != "hi_res":
            resolved_strategy = "hi_res"
            warnings.append(
                f"multi format forced strategy 'hi_res' for scan-style document {src.name} to improve OCR extraction."
            )
            scan_ocr_fallback_applied = True
        if not resolved_languages:
            resolved_languages = ["jpn"]
            warnings.append(
                f"multi format defaulted OCR languages to 'jpn' for scan-style document {src.name}."
            )
            scan_ocr_fallback_applied = True
    elif resolved_strategy == "fast" and suffix in UNSTRUCTURED_FAST_UNSAFE_IMAGE_EXTENSIONS:
        resolved_strategy = "auto"
        warnings.append(
            f"multi format strategy 'fast' is not supported for image file {src.name}; fallback to 'auto'."
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
        "overlap_all": overlap_all,
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


def _partition_document_elements(
    client,
    src: Path,
    *,
    partition_strategy: str,
    languages: list[str],
    include_orig_elements: bool,
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

    resp = client.general.partition(
        request=operations.PartitionRequest(
            partition_parameters=partition_parameters,
        )
    )
    if int(getattr(resp, "status_code", 0) or 0) >= 400:
        raise RuntimeError(f"Unstructured partition failed. status={getattr(resp, 'status_code', '?')}")
    elements = getattr(resp, "elements", None) or []
    return elements, partition_parameters


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
    include_orig_elements: bool,
    chunk_size: int,
    chunk_overlap: int,
    target_warnings: list[str],
) -> tuple[dict, dict]:
    bookrag_tables = build_bookrag_table_targets(vector_store_name)
    target_warnings.extend(
        prepare_bookrag_tables(
            schema_name=effective_schema_name,
            table_targets=bookrag_tables,
            execute_sql_fn=execute_sql_fn,
        )
    )

    client = _new_unstructured_client()
    debug_dir = _prepare_unstructured_debug_dir(vector_store_name)
    csv_stage_dir = _prepare_bookrag_csv_stage_dir(vector_store_name)
    persist_block_metadata = _env_flag("BOOKRAG_PERSIST_BLOCK_METADATA", False)
    validate_node_flush = _env_flag("BOOKRAG_VALIDATE_NODE_FLUSH", False)
    partition_warnings: list[str] = []
    debug_files: list[str] = []
    inserted_rows = 0
    insert_stats: dict[str, int] = {}
    block_count = 0
    node_count = 0
    entity_count = 0
    entity_link_count = 0
    leaf_node_count = 0
    document_count = 0

    qualified_tables = {
        name: (f"{effective_schema_name}.{table_name}" if effective_schema_name else table_name)
        for name, table_name in bookrag_tables.items()
    }

    for path_hint in document_files:
        resolved = resolve_path_hint(path_hint)
        src = Path(resolved)
        if not src.exists() or not src.is_file():
            raise RuntimeError(f"multi format source file is missing: {path_hint}")

        (
            file_partition_strategy,
            file_ocr_languages,
            file_include_orig_elements,
        ) = _bookrag_partition_options_for_file(
            src,
            default_strategy=partition_strategy,
            default_languages=ocr_languages,
        )
        raw_elements, request_parameters = _partition_document_elements(
            client,
            src,
            partition_strategy=file_partition_strategy,
            languages=file_ocr_languages,
            include_orig_elements=file_include_orig_elements,
        )
        content_type = mimetypes.guess_type(src.name)[0] or "application/octet-stream"
        doc_id = uuid.uuid4().hex
        blocks = elements_to_bookrag_blocks(
            doc_id=doc_id,
            src=src,
            content_type=content_type,
            raw_elements=raw_elements,
            profile="jp",
            persist_metadata=persist_block_metadata,
        )
        if not blocks:
            partition_warnings.append(f"No BookIndex blocks extracted from file: {src.name}")
            continue
        document_row = build_bookrag_document_row(
            doc_id=doc_id,
            vector_store_name=vector_store_name,
            src=src,
            filetype=content_type,
            blocks=blocks,
            languages=file_ocr_languages,
            created_at=_now_ts(),
        )
        nodes = build_bookrag_nodes(document_row, blocks)
        entities, entity_links = build_bookrag_entities(document_row, nodes)
        debug_file = _write_unstructured_debug_file(
            debug_dir,
            src,
            raw_elements,
            blocks,
            request_parameters,
            extra_payload={
                "book_nodes": nodes,
                "book_entities": entities,
                "book_entity_links": entity_links,
            },
        )
        if debug_file:
            debug_files.append(debug_file)
        inserted_rows += persist_bookrag_tree(
            schema_name=effective_schema_name,
            table_targets=bookrag_tables,
            document_row=document_row,
            blocks=blocks,
            nodes=nodes,
            entities=entities,
            entity_links=entity_links,
            execute_sql_fn=execute_sql_fn,
            csv_stage_dir=csv_stage_dir,
            stats=insert_stats,
        )
        document_count += 1
        block_count += len(blocks)
        node_count += len(nodes)
        entity_count += len(entities)
        entity_link_count += len(entity_links)
        leaf_node_count += sum(
            1
            for node in nodes
            if int(node.get("is_leaf") or 0) == 1
            and str(node.get("node_type") or "").strip().lower() in {"text", "table"}
            and str(node.get("content") or "").strip()
        )

    if validate_node_flush:
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
        persisted_node_count = _wait_for_table_rows(
            schema_name=effective_schema_name,
            table_name=bookrag_tables["nodes"],
            execute_sql_fn=execute_sql_fn,
            timeout_seconds=flush_wait_seconds,
            poll_interval_seconds=flush_wait_interval_seconds,
        )
        if persisted_node_count <= 0:
            raise RuntimeError(
                "bookrag tree construction completed but destination node table has 0 rows. "
                f"table={qualified_tables['nodes']}"
            )
    else:
        persisted_node_count = node_count

    prepare_bookrag_leaf_view(
        schema_name=effective_schema_name,
        table_targets=bookrag_tables,
        execute_sql_fn=execute_sql_fn,
    )
    persisted_leaf_count = _count_teradata_rows(
        schema_name=effective_schema_name,
        table_name=bookrag_tables["leaf_nodes"],
        execute_sql_fn=execute_sql_fn,
    )
    if persisted_leaf_count is None:
        persisted_leaf_count = leaf_node_count

    patched_payload = _strip_file_based_create_params(exec_payload)
    patched_payload["object_names"] = qualified_tables["leaf_nodes"]
    patched_payload["data_columns"] = ["content"]
    patched_payload["key_columns"] = ["node_id"]

    summary = {
        "table_name": qualified_tables["leaf_nodes"],
        "chunk_count": persisted_leaf_count,
        "document_count": document_count,
        "job_id": "",
        "workflow_id": "",
        "destination_id": "",
        "warnings": target_warnings + partition_warnings,
        "workflow_mode": "bookindex tree direct insert",
        "inserted_rows": inserted_rows,
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "debug_dir": str(debug_dir),
        "debug_files": debug_files,
        "bookrag_csv_stage_dir": str(csv_stage_dir),
        "bookrag_csv_stage_files": [
            str(csv_stage_dir / f"{bookrag_tables['documents']}.csv"),
            str(csv_stage_dir / f"{bookrag_tables['nodes']}.csv"),
            str(csv_stage_dir / f"{bookrag_tables['entities']}.csv"),
            str(csv_stage_dir / f"{bookrag_tables['entity_links']}.csv"),
            str(csv_stage_dir / f"{bookrag_tables['blocks']}.csv"),
        ],
        "effective_partition_strategy": partition_strategy,
        "effective_ocr_languages": ocr_languages,
        "include_orig_elements": include_orig_elements,
        "file_mode": "per-extension",
        "block_count": block_count,
        "node_count": persisted_node_count,
        "leaf_node_count": persisted_leaf_count,
        "entity_count": entity_count,
        "entity_link_count": entity_link_count,
        "bookrag_tables": qualified_tables,
        "bookrag_profile": "jp",
        "bookrag_persist_block_metadata": persist_block_metadata,
        "bookrag_validate_node_flush": validate_node_flush,
        "bookrag_insert_stats": insert_stats,
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

    chunk_size = _to_int(create_values.get("multi_format_chunk_size", "600"), default=600, minimum=100, maximum=8000)
    chunk_overlap = _to_int(create_values.get("multi_format_chunk_overlap", "80"), default=80, minimum=0, maximum=2000)
    if chunk_overlap >= chunk_size:
        chunk_overlap = max(0, chunk_size // 5)
    partition_strategy = _resolve_partition_strategy(create_values.get("multi_format_strategy", "auto"))
    ocr_languages = _parse_langs(create_values.get("multi_format_ocr_languages", ""))
    include_orig_elements = False
    overlap_all = True

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
            include_orig_elements=include_orig_elements,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
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

    client = None
    debug_dir = _prepare_unstructured_debug_dir(vector_store_name)
    inserted_rows = 0
    partition_warnings: list[str] = []
    debug_files: list[str] = []
    used_partition_strategies: set[str] = set()
    used_ocr_languages: set[tuple[str, ...]] = set()
    scan_ocr_fallback_files: list[str] = []
    excel_structured_files: list[str] = []
    processing_modes: set[str] = set()
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
        if _is_excel_file(src):
            try:
                rows, raw_elements, request_parameters = _partition_excel_chunks(
                    src,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                )
                excel_structured_files.append(src.name)
                processing_modes.add("excel-structured")
            except Exception as ex:
                partition_warnings.append(
                    f"excel structured extraction failed for {src.name}; fallback to partition API: {ex}"
                )
                if client is None:
                    client = _new_unstructured_client()
                used_partition_strategies.add(file_partition_strategy)
                used_ocr_languages.add(tuple(file_ocr_languages))
                if scan_ocr_fallback_applied:
                    scan_ocr_fallback_files.append(src.name)
                rows, raw_elements, request_parameters = _partition_document_chunks(
                    client,
                    src,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    partition_strategy=file_partition_strategy,
                    languages=file_ocr_languages,
                    include_orig_elements=file_include_orig_elements,
                    overlap_all=overlap_all,
                )
                processing_modes.add("partition-api")
        else:
            if client is None:
                client = _new_unstructured_client()
            used_partition_strategies.add(file_partition_strategy)
            used_ocr_languages.add(tuple(file_ocr_languages))
            if scan_ocr_fallback_applied:
                scan_ocr_fallback_files.append(src.name)
            rows, raw_elements, request_parameters = _partition_document_chunks(
                client,
                src,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                partition_strategy=file_partition_strategy,
                languages=file_ocr_languages,
                include_orig_elements=file_include_orig_elements,
                overlap_all=overlap_all,
            )
            processing_modes.add("partition-api")
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

    patched_payload = _strip_file_based_create_params(exec_payload)
    patched_payload["object_names"] = qualified_name
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
        "effective_partition_strategy_label": strategy_label,
        "effective_ocr_languages_label": languages_label,
        "processing_mode_label": processing_mode_label,
        "excel_structured_files": excel_structured_files,
        "scan_ocr_fallback_files": scan_ocr_fallback_files,
        "include_orig_elements": include_orig_elements,
        "overlap_all": overlap_all,
        "file_mode": "per-file",
    }
    return patched_payload, summary
