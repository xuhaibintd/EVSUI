from __future__ import annotations

import re

from app.utils.table_state import format_preview, row_value_by_header, table_from_result


_TERADATA_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def classify_vectorstore_status(status_output) -> tuple[str, str, str]:
    preview = format_preview(status_output, max_chars=None)
    headers, rows = table_from_result(status_output)
    status_text = ""
    for row in rows:
        status_text = row_value_by_header(
            headers,
            row,
            ("status", "state", "lifecycle", "operationstatus", "collectionstatus"),
        )
        if status_text:
            break
    normalized = status_text.strip().lower()
    retry_after_text = ""
    for row in rows:
        retry_after_text = row_value_by_header(headers, row, ("retryafter",))
        if retry_after_text:
            break
    if not normalized and isinstance(status_output, str):
        status_text = status_output.strip()
        normalized = status_text.lower()
    if retry_after_text:
        return "in_progress", status_text or retry_after_text, preview
    if not normalized:
        return "unknown", status_text, preview
    if "ready" in normalized:
        return "ready", status_text, preview
    if "failed" in normalized or "error" in normalized:
        return "failed", status_text, preview
    markers = (
        "initialized",
        "ingested",
        "ingested_partially",
        "create_load_data_completed",
        "create_generating_embeddings_completed",
        "generate_embeddings_completed",
        "create_index_completed",
        "creating",
        "initializing",
        "pending",
        "processing",
        "ingesting",
        "loading",
        "generating",
        "indexing",
        "submitted",
        "updating",
        "create_",
        "update_",
        "create ",
        "update ",
    )
    return ("in_progress" if any(marker in normalized for marker in markers) else "unknown"), status_text, preview


def read_vectorstore_status(vector_store) -> tuple[str, str, str, str]:
    status_fn = getattr(vector_store, "status", None)
    if not callable(status_fn):
        return "unknown", "", "", "VectorStore.status() is not callable."
    try:
        status_output = status_fn()
    except Exception as ex:
        error_text = str(ex)
        normalized_error = error_text.lower()
        if "failed" in normalized_error and any(
            marker in normalized_error
            for marker in ("create", "update", "initialize", "vector store", "vectorstore")
        ):
            return "failed", error_text, "", ""
        return "unknown", "", "", f"Status check failed: {ex}"
    state, status_text, preview = classify_vectorstore_status(status_output)
    return state, status_text, preview, ""


def quote_teradata_identifier(value: str) -> str:
    identifier = str(value or "").strip()
    if not _TERADATA_IDENTIFIER_RE.match(identifier):
        raise ValueError(f"unsafe Teradata identifier: {identifier!r}")
    return f'"{identifier}"'


def first_scalar(value):
    if isinstance(value, dict):
        return next(iter(value.values()), None)
    if isinstance(value, (str, bytes, bytearray)):
        return value
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    try:
        return value[0]
    except Exception:
        return value


def int_or_none(value) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def scalar_from_sql_result(result) -> int | None:
    if result is None:
        return None
    fetchone = getattr(result, "fetchone", None)
    fetchall = getattr(result, "fetchall", None)
    if callable(fetchone) or callable(fetchall):
        parsed = None
        try:
            if callable(fetchone):
                row = fetchone()
                parsed = int_or_none(first_scalar(row)) if row is not None else None
            if parsed is None and callable(fetchall):
                remaining_rows = fetchall() or []
                if remaining_rows:
                    parsed = int_or_none(first_scalar(remaining_rows[0]))
        except Exception:
            parsed = None
        finally:
            close = getattr(result, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        return parsed
    if hasattr(result, "iloc"):
        try:
            parsed = int_or_none(result.iloc[0, 0])
            if parsed is not None:
                return parsed
        except Exception:
            pass
    if isinstance(result, dict):
        parsed = int_or_none(first_scalar(result))
        if parsed is not None:
            return parsed
    if isinstance(result, (list, tuple)) and result:
        parsed = int_or_none(first_scalar(result[0]))
        if parsed is not None:
            return parsed
    headers, rows = table_from_result(result)
    if rows and rows[0]:
        value_index = 1 if headers and headers[0] == "#" and len(rows[0]) > 1 else 0
        return int_or_none(rows[0][value_index])
    return None


def source_embedding_row_count(
    *,
    source_table_name: str,
    target_database: str,
    data_column: str,
    execute_sql_fn,
) -> tuple[int | None, str]:
    if execute_sql_fn is None:
        return None, "execute_sql is unavailable"
    try:
        schema_sql = quote_teradata_identifier(target_database)
        table_sql = quote_teradata_identifier(source_table_name)
        data_column_sql = quote_teradata_identifier(data_column)
    except ValueError as ex:
        return None, str(ex)
    sql = (
        f"SELECT COUNT(*) FROM {schema_sql}.{table_sql} "
        f"WHERE {data_column_sql} IS NOT NULL AND TRIM({data_column_sql}) <> ''"
    )
    try:
        result = execute_sql_fn(sql)
    except Exception as ex:
        return None, str(ex)
    count = scalar_from_sql_result(result)
    if count is None:
        return None, f"could not parse source row count from {format_preview(result, max_chars=300)}"
    return count, ""


def bookrag_vector_index_row_count(
    *, vector_store_name: str, target_database: str, execute_sql_fn
) -> tuple[int | None, str]:
    if execute_sql_fn is None:
        return None, "execute_sql is unavailable"
    try:
        schema_sql = quote_teradata_identifier(target_database)
        table_sql = quote_teradata_identifier(f"vectorstore_{vector_store_name}_index")
    except ValueError as ex:
        return None, str(ex)
    try:
        result = execute_sql_fn(f"SELECT COUNT(*) FROM {schema_sql}.{table_sql}")
    except Exception as ex:
        return None, str(ex)
    count = scalar_from_sql_result(result)
    if count is None:
        return None, f"could not parse row count from {format_preview(result, max_chars=300)}"
    return count, ""


def bookrag_source_embedding_row_count(**kwargs) -> tuple[int | None, str]:
    return source_embedding_row_count(data_column="content", **kwargs)


def multi_format_source_embedding_row_count(**kwargs) -> tuple[int | None, str]:
    return source_embedding_row_count(data_column="text", **kwargs)
