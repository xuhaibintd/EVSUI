from __future__ import annotations

import hashlib
import re
from typing import Any

from app.services.teradata_sql import (
    ExecuteSqlFn,
    _qualified_table_sql,
    _sql_literal,
    _sql_typed_literal,
    _teradata_table_exists,
)

BOOKRAG_EMBEDDING_NODE_TYPES = ("text", "table", "image")

TERADATA_IDENTIFIER_MAX_LEN = 30
BOOKRAG_INSERT_BATCH_MAX_ROWS = 32
BOOKRAG_INSERT_BATCH_MAX_SQL_CHARS = 180000

BOOKRAG_DOCUMENT_COLUMNS: list[tuple[str, str]] = [
    ("doc_id", 'VARCHAR(64) NOT NULL'),
    ("vector_store_name", "VARCHAR(255)"),
    ("workflow_id", "VARCHAR(64)"),
    ("workflow_name", "VARCHAR(255) CHARACTER SET UNICODE"),
    ("job_id", "VARCHAR(64)"),
    ("processing_profile", "VARCHAR(100) CHARACTER SET UNICODE"),
    ("source_file", "VARCHAR(2000) CHARACTER SET UNICODE"),
    ("filename", "VARCHAR(255) CHARACTER SET UNICODE"),
    ("filetype", "VARCHAR(100)"),
    ("filesize_bytes", "INTEGER"),
    ("page_count", "INTEGER"),
    ("language_hint", "VARCHAR(200)"),
    ("created_at", "VARCHAR(50)"),
]

BOOKRAG_BLOCK_COLUMNS: list[tuple[str, str]] = [
    ("doc_id", "VARCHAR(64)"),
    ("element_id", "VARCHAR(64)"),
    ("parent_id", "VARCHAR(64)"),
    ("page_number", "INTEGER"),
    ("ordinal", "INTEGER"),
    ("type", "VARCHAR(50)"),
    ("text", "VARCHAR(32000) CHARACTER SET UNICODE"),
    ("text_as_html", "VARCHAR(32000) CHARACTER SET UNICODE"),
    ("image_caption", "VARCHAR(4000) CHARACTER SET UNICODE"),
    ("image_context", "VARCHAR(32000) CHARACTER SET UNICODE"),
]

BOOKRAG_RAW_COLUMNS: list[tuple[str, str]] = [
    ("id", 'VARCHAR(96) CHARACTER SET UNICODE NOT NULL'),
    ("element_id", "VARCHAR(128) CHARACTER SET UNICODE"),
    ("ordinal_raw", "INTEGER"),
    ("parent_id", "VARCHAR(128) CHARACTER SET UNICODE"),
    ("type", "VARCHAR(64) CHARACTER SET UNICODE"),
    ("page_number", "INTEGER"),
    ("category_depth", "INTEGER"),
    ("text", "VARCHAR(32000) CHARACTER SET UNICODE"),
    ("text_as_html", "VARCHAR(32000) CHARACTER SET UNICODE"),
    ("image_caption", "VARCHAR(4000) CHARACTER SET UNICODE"),
    ("image_context", "VARCHAR(32000) CHARACTER SET UNICODE"),
    ("doc_id", "VARCHAR(64)"),
]

BOOKRAG_CHUNK_COLUMNS: list[tuple[str, str]] = [
    ("chunk_id", 'VARCHAR(64) NOT NULL'),
    ("doc_id", "VARCHAR(64)"),
    ("filename", "VARCHAR(255) CHARACTER SET UNICODE"),
    ("ordinal", "INTEGER"),
    ("chunk_type", "VARCHAR(32) CHARACTER SET UNICODE"),
    ("page_start", "INTEGER"),
    ("page_end", "INTEGER"),
    ("section_title", "VARCHAR(2000) CHARACTER SET UNICODE"),
    ("title_path", "VARCHAR(4000) CHARACTER SET UNICODE"),
    ("source_element_ids", "VARCHAR(32000) CHARACTER SET UNICODE"),
    ("text", "VARCHAR(32000) CHARACTER SET UNICODE"),
    ("text_for_embedding", "VARCHAR(32000) CHARACTER SET UNICODE"),
    ("text_as_html", "VARCHAR(32000) CHARACTER SET UNICODE"),
    ("table_html", "VARCHAR(32000) CHARACTER SET UNICODE"),
    ("image_caption", "VARCHAR(4000) CHARACTER SET UNICODE"),
    ("image_context", "VARCHAR(32000) CHARACTER SET UNICODE"),
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

BOOKRAG_ENTITY_RELATION_COLUMNS: list[tuple[str, str]] = [
    ("relation_id", 'VARCHAR(64) NOT NULL'),
    ("doc_id", "VARCHAR(64)"),
    ("source_block_id", "VARCHAR(64)"),
    ("source_node_id", "VARCHAR(64)"),
    ("section_node_id", "VARCHAR(64)"),
    ("from_entity_id", "VARCHAR(64)"),
    ("from_entity_text", "VARCHAR(1000) CHARACTER SET UNICODE"),
    ("relationship", "VARCHAR(100) CHARACTER SET UNICODE"),
    ("to_entity_id", "VARCHAR(64)"),
    ("to_entity_text", "VARCHAR(1000) CHARACTER SET UNICODE"),
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
        "raw": _with_suffix(base_name, "braw"),
        "chunks": _with_suffix(base_name, "bchk"),
        "nodes": _with_suffix(base_name, "bnode"),
        "entities": _with_suffix(base_name, "bent"),
        "entity_links": _with_suffix(base_name, "belnk"),
        "entity_relations": _with_suffix(base_name, "brel"),
        "leaf_nodes": _with_suffix(base_name, "bleaf"),
    }


def _build_table_ddl(qualified_table: str, columns: list[tuple[str, str]]) -> str:
    first_name, first_type = columns[0]
    column_lines: list[str] = [f'  "{first_name}" {first_type}']
    if re.search(r"\bNOT\s+NULL\b", first_type, flags=re.IGNORECASE):
        column_lines.append(f'  PRIMARY KEY ("{first_name}")')
    for name, col_type in columns[1:]:
        column_lines.append(f'  "{name}" {col_type}')
    ddl_body = ",\n".join(column_lines)
    return f"""
CREATE SET TABLE {qualified_table} (
{ddl_body}
)
"""


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
    warnings.extend(_ensure_table(schema_name, table_targets["entity_relations"], BOOKRAG_ENTITY_RELATION_COLUMNS, execute_sql_fn))
    return warnings


def prepare_bookrag_block_table(
    schema_name: str | None,
    table_targets: dict[str, str],
    execute_sql_fn: ExecuteSqlFn | None,
) -> list[str]:
    warnings: list[str] = []
    warnings.extend(_ensure_table(schema_name, table_targets["blocks"], BOOKRAG_BLOCK_COLUMNS, execute_sql_fn))
    return warnings


def prepare_bookrag_node_table(
    schema_name: str | None,
    table_targets: dict[str, str],
    execute_sql_fn: ExecuteSqlFn | None,
) -> list[str]:
    warnings: list[str] = []
    warnings.extend(_ensure_table(schema_name, table_targets["nodes"], BOOKRAG_NODE_COLUMNS, execute_sql_fn))
    return warnings


def prepare_bookrag_entity_table(
    schema_name: str | None,
    table_targets: dict[str, str],
    execute_sql_fn: ExecuteSqlFn | None,
) -> list[str]:
    warnings: list[str] = []
    warnings.extend(_ensure_table(schema_name, table_targets["entities"], BOOKRAG_ENTITY_COLUMNS, execute_sql_fn))
    return warnings


def prepare_bookrag_entity_link_table(
    schema_name: str | None,
    table_targets: dict[str, str],
    execute_sql_fn: ExecuteSqlFn | None,
) -> list[str]:
    warnings: list[str] = []
    warnings.extend(_ensure_table(schema_name, table_targets["entity_links"], BOOKRAG_ENTITY_LINK_COLUMNS, execute_sql_fn))
    return warnings


def prepare_bookrag_entity_relation_table(
    schema_name: str | None,
    table_targets: dict[str, str],
    execute_sql_fn: ExecuteSqlFn | None,
) -> list[str]:
    warnings: list[str] = []
    warnings.extend(_ensure_table(schema_name, table_targets["entity_relations"], BOOKRAG_ENTITY_RELATION_COLUMNS, execute_sql_fn))
    return warnings


def prepare_bookrag_document_table(
    schema_name: str | None,
    table_targets: dict[str, str],
    execute_sql_fn: ExecuteSqlFn | None,
) -> list[str]:
    warnings: list[str] = []
    warnings.extend(_ensure_table(schema_name, table_targets["documents"], BOOKRAG_DOCUMENT_COLUMNS, execute_sql_fn))
    return warnings


def prepare_bookrag_raw_table(
    schema_name: str | None,
    table_targets: dict[str, str],
    execute_sql_fn: ExecuteSqlFn | None,
) -> list[str]:
    warnings: list[str] = []
    warnings.extend(_ensure_table(schema_name, table_targets["raw"], BOOKRAG_RAW_COLUMNS, execute_sql_fn))
    return warnings


def prepare_bookrag_chunk_table(
    schema_name: str | None,
    table_targets: dict[str, str],
    execute_sql_fn: ExecuteSqlFn | None,
) -> list[str]:
    warnings: list[str] = []
    warnings.extend(_ensure_table(schema_name, table_targets["chunks"], BOOKRAG_CHUNK_COLUMNS, execute_sql_fn))
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
