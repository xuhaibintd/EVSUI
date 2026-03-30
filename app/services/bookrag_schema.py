from __future__ import annotations

import hashlib
import re
from typing import Any, Callable

BOOKRAG_EMBEDDING_NODE_TYPES = ("text", "table")

TERADATA_IDENTIFIER_MAX_LEN = 30
BOOKRAG_INSERT_BATCH_MAX_ROWS = 32
BOOKRAG_INSERT_BATCH_MAX_SQL_CHARS = 180000

ExecuteSqlFn = Callable[[str], Any]

BOOKRAG_DOCUMENT_COLUMNS: list[tuple[str, str]] = [
    ("doc_id", 'VARCHAR(64) NOT NULL'),
    ("vector_store_name", "VARCHAR(255)"),
    ("source_file", "VARCHAR(2000) CHARACTER SET UNICODE"),
    ("filename", "VARCHAR(255) CHARACTER SET UNICODE"),
    ("filetype", "VARCHAR(100)"),
    ("filesize_bytes", "INTEGER"),
    ("page_count", "INTEGER"),
    ("language_hint", "VARCHAR(200)"),
    ("created_at", "VARCHAR(50)"),
]

BOOKRAG_BLOCK_COLUMNS: list[tuple[str, str]] = [
    ("block_id", 'VARCHAR(64) NOT NULL'),
    ("doc_id", "VARCHAR(64)"),
    ("element_id", "VARCHAR(64)"),
    ("parent_block_id", "VARCHAR(64)"),
    ("block_type", "VARCHAR(50)"),
    ("page_number", "INTEGER"),
    ("ordinal", "INTEGER"),
    ("level_hint", "INTEGER"),
    ("is_section", "BYTEINT"),
    ("section_title", "VARCHAR(1000) CHARACTER SET UNICODE"),
    ("text", "VARCHAR(32000) CHARACTER SET UNICODE"),
    ("text_as_html", "VARCHAR(32000) CHARACTER SET UNICODE"),
    ("orig_elements", "VARCHAR(32000) CHARACTER SET UNICODE"),
    ("metadata_json", "VARCHAR(32000) CHARACTER SET UNICODE"),
]

BOOKRAG_NODE_COLUMNS: list[tuple[str, str]] = [
    ("node_id", 'VARCHAR(64) NOT NULL'),
    ("doc_id", "VARCHAR(64)"),
    ("source_block_id", "VARCHAR(64)"),
    ("parent_node_id", "VARCHAR(64)"),
    ("node_type", "VARCHAR(50)"),
    ("level", "INTEGER"),
    ("ordinal", "INTEGER"),
    ("title", "VARCHAR(1000) CHARACTER SET UNICODE"),
    ("content", "VARCHAR(32000) CHARACTER SET UNICODE"),
    ("page_start", "INTEGER"),
    ("page_end", "INTEGER"),
    ("path", "VARCHAR(2000) CHARACTER SET UNICODE"),
    ("is_leaf", "BYTEINT"),
]

BOOKRAG_ENTITY_COLUMNS: list[tuple[str, str]] = [
    ("entity_id", 'VARCHAR(64) NOT NULL'),
    ("doc_id", "VARCHAR(64)"),
    ("canonical_name", "VARCHAR(1000) CHARACTER SET UNICODE"),
    ("display_name", "VARCHAR(1000) CHARACTER SET UNICODE"),
    ("entity_type", "VARCHAR(50)"),
    ("mention_count", "INTEGER"),
    ("node_count", "INTEGER"),
]

BOOKRAG_ENTITY_LINK_COLUMNS: list[tuple[str, str]] = [
    ("link_id", 'VARCHAR(64) NOT NULL'),
    ("entity_id", "VARCHAR(64)"),
    ("doc_id", "VARCHAR(64)"),
    ("node_id", "VARCHAR(64)"),
    ("section_node_id", "VARCHAR(64)"),
    ("source_field", "VARCHAR(50)"),
    ("mention_text", "VARCHAR(1000) CHARACTER SET UNICODE"),
    ("page_start", "INTEGER"),
    ("page_end", "INTEGER"),
    ("ordinal", "INTEGER"),
    ("section_path", "VARCHAR(2000) CHARACTER SET UNICODE"),
]


def _sanitize_identifier(raw: str, fallback: str) -> str:
    candidate = re.sub(r"[^0-9A-Za-z_]", "_", str(raw or "").strip())
    candidate = re.sub(r"_+", "_", candidate).strip("_")
    if not candidate:
        return fallback
    if candidate[0].isdigit():
        candidate = f"t_{candidate}"
    if len(candidate) <= TERADATA_IDENTIFIER_MAX_LEN:
        return candidate
    digest = hashlib.sha1(candidate.encode("utf-8")).hexdigest()[:6]
    keep = max(1, TERADATA_IDENTIFIER_MAX_LEN - len(digest) - 1)
    return f"{candidate[:keep]}_{digest}"


def _with_suffix(base_name: str, suffix: str) -> str:
    suffix = f"_{suffix.strip('_')}"
    candidate = f"{base_name}{suffix}"
    if len(candidate) <= TERADATA_IDENTIFIER_MAX_LEN:
        return candidate
    digest = hashlib.sha1(candidate.encode("utf-8")).hexdigest()[:6]
    keep = max(1, TERADATA_IDENTIFIER_MAX_LEN - len(suffix) - len(digest) - 1)
    return f"{base_name[:keep]}_{digest}{suffix}"


def build_bookrag_table_targets(vector_store_name: str) -> dict[str, str]:
    base_name = _sanitize_identifier(f"{vector_store_name}_bk", fallback="bookrag_bk")
    return {
        "documents": _with_suffix(base_name, "bdoc"),
        "blocks": _with_suffix(base_name, "bblk"),
        "nodes": _with_suffix(base_name, "bnode"),
        "entities": _with_suffix(base_name, "bent"),
        "entity_links": _with_suffix(base_name, "belnk"),
        "leaf_nodes": _with_suffix(base_name, "bleaf"),
    }


def _qualified_table_sql(schema_name: str | None, table_name: str) -> str:
    if schema_name:
        return f'"{schema_name}"."{table_name}"'
    return f'"{table_name}"'


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    text = str(value).replace("'", "''")
    return f"'{text}'"


def _column_cast_type(column_type: str) -> str:
    return re.sub(r"\s+NOT\s+NULL\s*$", "", column_type, flags=re.IGNORECASE).strip()


def _sql_typed_literal(value: Any, column_type: str) -> str:
    return f"CAST({_sql_literal(value)} AS {_column_cast_type(column_type)})"


def _build_table_ddl(qualified_table: str, columns: list[tuple[str, str]]) -> str:
    first_name, first_type = columns[0]
    column_lines: list[str] = [f'  "{first_name}" {first_type}', f'  PRIMARY KEY ("{first_name}")']
    for name, col_type in columns[1:]:
        column_lines.append(f'  "{name}" {col_type}')
    ddl_body = ",\n".join(column_lines)
    return f"""
CREATE SET TABLE {qualified_table} (
{ddl_body}
)
"""


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


def _ensure_table(
    schema_name: str | None,
    table_name: str,
    columns: list[tuple[str, str]],
    execute_sql_fn: ExecuteSqlFn | None,
) -> list[str]:
    if execute_sql_fn is None:
        raise RuntimeError("teradataml.execute_sql is unavailable.")
    qualified_table = _qualified_table_sql(schema_name, table_name)
    if _teradata_table_exists(qualified_table, execute_sql_fn):
        raise RuntimeError(
            f"BookRAG target table already exists: {qualified_table}. "
            "Use a new vector_store_name to create a new table set."
        )
    execute_sql_fn(_build_table_ddl(qualified_table, columns))
    return []


def prepare_bookrag_tables(
    schema_name: str | None,
    table_targets: dict[str, str],
    execute_sql_fn: ExecuteSqlFn | None,
) -> list[str]:
    warnings: list[str] = []
    warnings.extend(_ensure_table(schema_name, table_targets["documents"], BOOKRAG_DOCUMENT_COLUMNS, execute_sql_fn))
    warnings.extend(_ensure_table(schema_name, table_targets["blocks"], BOOKRAG_BLOCK_COLUMNS, execute_sql_fn))
    warnings.extend(_ensure_table(schema_name, table_targets["nodes"], BOOKRAG_NODE_COLUMNS, execute_sql_fn))
    warnings.extend(_ensure_table(schema_name, table_targets["entities"], BOOKRAG_ENTITY_COLUMNS, execute_sql_fn))
    warnings.extend(_ensure_table(schema_name, table_targets["entity_links"], BOOKRAG_ENTITY_LINK_COLUMNS, execute_sql_fn))
    return warnings


def prepare_bookrag_leaf_view(
    schema_name: str | None,
    table_targets: dict[str, str],
    execute_sql_fn: ExecuteSqlFn | None,
) -> None:
    if execute_sql_fn is None:
        raise RuntimeError("teradataml.execute_sql is unavailable.")
    qualified_nodes = _qualified_table_sql(schema_name, table_targets["nodes"])
    qualified_leaf_view = _qualified_table_sql(schema_name, table_targets["leaf_nodes"])
    node_types_sql = ", ".join(_sql_literal(value) for value in BOOKRAG_EMBEDDING_NODE_TYPES)
    execute_sql_fn(
        f"""
REPLACE VIEW {qualified_leaf_view} AS
SELECT *
FROM {qualified_nodes}
WHERE "is_leaf" = 1
  AND "content" IS NOT NULL
  AND "node_type" IN ({node_types_sql})
"""
    )
