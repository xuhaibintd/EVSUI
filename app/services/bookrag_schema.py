from __future__ import annotations

import hashlib
import re
from typing import Any

from app.services.teradata_sql import (
    ExecuteSqlFn,
    _count_teradata_rows,
    _qualified_table_sql,
    _sql_literal,
    _teradata_table_exists,
)

BOOKRAG_EMBEDDING_NODE_TYPES = ("text", "table", "image")

TERADATA_IDENTIFIER_MAX_LEN = 30

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
    ("category_depth", "INTEGER"),
    ("heading_level", "INTEGER"),
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
    ("source_element_id", "VARCHAR(64)"),
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
    ("entity_id", "VARCHAR(64) NOT NULL"),
    ("doc_id", "VARCHAR(64)"),
    ("node_id", "VARCHAR(64) NOT NULL"),
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
    ("source_element_id", "VARCHAR(64) NOT NULL"),
    ("source_node_id", "VARCHAR(64) NOT NULL"),
    ("section_node_id", "VARCHAR(64)"),
    ("from_entity_id", "VARCHAR(64) NOT NULL"),
    ("from_entity_text", "VARCHAR(1000) CHARACTER SET UNICODE"),
    ("relationship", "VARCHAR(100) CHARACTER SET UNICODE NOT NULL"),
    ("to_entity_id", "VARCHAR(64) NOT NULL"),
    ("to_entity_text", "VARCHAR(1000) CHARACTER SET UNICODE"),
    ("page_start", "INTEGER"),
    ("page_end", "INTEGER"),
    ("ordinal", "INTEGER"),
    ("section_path", "VARCHAR(2000) CHARACTER SET UNICODE"),
]

BOOKRAG_DOCUMENT_RELATION_COLUMNS: list[tuple[str, str]] = [
    ("from_doc_id", "VARCHAR(64) NOT NULL"),
    ("from_filename", "VARCHAR(255) CHARACTER SET UNICODE NOT NULL"),
    ("relation_type", "VARCHAR(64) NOT NULL"),
    ("to_doc_id", "VARCHAR(64) NOT NULL"),
    ("to_filename", "VARCHAR(255) CHARACTER SET UNICODE NOT NULL"),
    ("relation_description", "VARCHAR(4000) CHARACTER SET UNICODE"),
    ("source_type", "VARCHAR(32) NOT NULL"),
    ("confidence", "DECIMAL(5,4)"),
    ("created_by", "VARCHAR(128) CHARACTER SET UNICODE"),
    ("created_at", "TIMESTAMP(6)"),
    ("updated_by", "VARCHAR(128) CHARACTER SET UNICODE"),
    ("updated_at", "TIMESTAMP(6)"),
]


BOOKRAG_PRIMARY_KEYS: dict[tuple[str, ...], tuple[str, ...]] = {
    tuple(name for name, _ in BOOKRAG_DOCUMENT_COLUMNS): ("doc_id",),
    tuple(name for name, _ in BOOKRAG_BLOCK_COLUMNS): ("doc_id", "element_id"),
    tuple(name for name, _ in BOOKRAG_RAW_COLUMNS): ("doc_id", "ordinal_raw"),
    tuple(name for name, _ in BOOKRAG_CHUNK_COLUMNS): ("doc_id", "chunk_id"),
    tuple(name for name, _ in BOOKRAG_NODE_COLUMNS): ("doc_id", "node_id"),
    tuple(name for name, _ in BOOKRAG_ENTITY_COLUMNS): ("doc_id", "entity_id"),
    tuple(name for name, _ in BOOKRAG_ENTITY_LINK_COLUMNS): ("doc_id", "link_id"),
    tuple(name for name, _ in BOOKRAG_ENTITY_RELATION_COLUMNS): ("doc_id", "relation_id"),
    tuple(name for name, _ in BOOKRAG_DOCUMENT_RELATION_COLUMNS): (
        "from_doc_id",
        "relation_type",
        "to_doc_id",
    ),
}


BOOKRAG_QUERY_TABLE_PRIMARY_KEYS: dict[str, tuple[str, ...]] = {
    "documents": ("doc_id",),
    "blocks": ("doc_id", "element_id"),
    "nodes": ("doc_id", "node_id"),
    "document_relations": ("from_doc_id", "relation_type", "to_doc_id"),
    "entities": ("doc_id", "entity_id"),
    "entity_links": ("doc_id", "link_id"),
    "entity_relations": ("doc_id", "relation_id"),
}

BOOKRAG_QUERY_TABLE_ROLES: dict[str, str] = {
    "documents": "core",
    "blocks": "core",
    "nodes": "core",
    "document_relations": "core",
    "entities": "graph",
    "entity_links": "graph",
    "entity_relations": "graph",
}

# Logical foreign-key contract used by both the EVSUI query chain and MCP clients.
# Teradata does not need to enforce these as physical FK constraints for the
# relationship to be mandatory at the application boundary.
BOOKRAG_RELATIONSHIP_SPECS: tuple[dict[str, Any], ...] = (
    {
        "name": "document_relation_source",
        "from_table": "document_relations",
        "from_columns": ("from_doc_id",),
        "to_table": "documents",
        "to_columns": ("doc_id",),
        "nullable": False,
        "strength": "required",
    },
    {
        "name": "document_relation_target",
        "from_table": "document_relations",
        "from_columns": ("to_doc_id",),
        "to_table": "documents",
        "to_columns": ("doc_id",),
        "nullable": False,
        "strength": "required",
    },
    {
        "name": "block_document",
        "from_table": "blocks",
        "from_columns": ("doc_id",),
        "to_table": "documents",
        "to_columns": ("doc_id",),
        "nullable": False,
        "strength": "required",
    },
    {
        "name": "node_document",
        "from_table": "nodes",
        "from_columns": ("doc_id",),
        "to_table": "documents",
        "to_columns": ("doc_id",),
        "nullable": False,
        "strength": "required",
    },
    {
        "name": "node_parent",
        "from_table": "nodes",
        "from_columns": ("doc_id", "parent_node_id"),
        "to_table": "nodes",
        "to_columns": ("doc_id", "node_id"),
        "nullable": True,
        "nullable_when": "node_type=document",
        "strength": "required",
    },
    {
        "name": "node_source_block",
        "from_table": "nodes",
        "from_columns": ("doc_id", "source_element_id"),
        "to_table": "blocks",
        "to_columns": ("doc_id", "element_id"),
        "nullable": True,
        "nullable_when": "node_type=document",
        "strength": "required",
    },
    {
        "name": "entity_document",
        "from_table": "entities",
        "from_columns": ("doc_id",),
        "to_table": "documents",
        "to_columns": ("doc_id",),
        "nullable": False,
        "strength": "required",
    },
    {
        "name": "entity_link_document",
        "from_table": "entity_links",
        "from_columns": ("doc_id",),
        "to_table": "documents",
        "to_columns": ("doc_id",),
        "nullable": False,
        "strength": "required",
    },
    {
        "name": "entity_link_node",
        "from_table": "entity_links",
        "from_columns": ("doc_id", "node_id"),
        "to_table": "nodes",
        "to_columns": ("doc_id", "node_id"),
        "nullable": False,
        "strength": "required",
    },
    {
        "name": "entity_link_section",
        "from_table": "entity_links",
        "from_columns": ("doc_id", "section_node_id"),
        "to_table": "nodes",
        "to_columns": ("doc_id", "node_id"),
        "nullable": True,
        "strength": "optional",
    },
    {
        "name": "entity_link_entity",
        "from_table": "entity_links",
        "from_columns": ("doc_id", "entity_id"),
        "to_table": "entities",
        "to_columns": ("doc_id", "entity_id"),
        "nullable": False,
        "strength": "required",
    },
    {
        "name": "relation_document",
        "from_table": "entity_relations",
        "from_columns": ("doc_id",),
        "to_table": "documents",
        "to_columns": ("doc_id",),
        "nullable": False,
        "strength": "required",
    },
    {
        "name": "relation_source_block",
        "from_table": "entity_relations",
        "from_columns": ("doc_id", "source_element_id"),
        "to_table": "blocks",
        "to_columns": ("doc_id", "element_id"),
        "nullable": False,
        "strength": "required",
    },
    {
        "name": "relation_source_node",
        "from_table": "entity_relations",
        "from_columns": ("doc_id", "source_node_id"),
        "to_table": "nodes",
        "to_columns": ("doc_id", "node_id"),
        "nullable": False,
        "strength": "required",
    },
    {
        "name": "relation_section",
        "from_table": "entity_relations",
        "from_columns": ("doc_id", "section_node_id"),
        "to_table": "nodes",
        "to_columns": ("doc_id", "node_id"),
        "nullable": True,
        "strength": "optional",
    },
    {
        "name": "relation_from_entity",
        "from_table": "entity_relations",
        "from_columns": ("doc_id", "from_entity_id"),
        "to_table": "entities",
        "to_columns": ("doc_id", "entity_id"),
        "nullable": False,
        "strength": "required",
    },
    {
        "name": "relation_to_entity",
        "from_table": "entity_relations",
        "from_columns": ("doc_id", "to_entity_id"),
        "to_table": "entities",
        "to_columns": ("doc_id", "entity_id"),
        "nullable": False,
        "strength": "required",
    },
)

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
        "document_relations": _with_suffix(base_name, "bdrel"),
        "entities": _with_suffix(base_name, "bent"),
        "entity_links": _with_suffix(base_name, "belnk"),
        "entity_relations": _with_suffix(base_name, "brel"),
        "leaf_nodes": _with_suffix(base_name, "bleaf"),
    }


def build_bookrag_relationship_contract(vector_store_name: str) -> dict[str, Any]:
    """Return physical table names plus the document-scoped join contract."""
    targets = build_bookrag_table_targets(vector_store_name)
    return {
        "tables": {
            table_key: {
                "name": targets[table_key],
                "primary_key": list(primary_key),
                "role": BOOKRAG_QUERY_TABLE_ROLES[table_key],
            }
            for table_key, primary_key in BOOKRAG_QUERY_TABLE_PRIMARY_KEYS.items()
        },
        "relationships": [
            {
                **spec,
                "from_table_key": spec["from_table"],
                "to_table_key": spec["to_table"],
                "from_table": targets[str(spec["from_table"])],
                "to_table": targets[str(spec["to_table"])],
                "from_columns": list(spec["from_columns"]),
                "to_columns": list(spec["to_columns"]),
            }
            for spec in BOOKRAG_RELATIONSHIP_SPECS
        ],
    }

def _build_table_ddl(qualified_table: str, columns: list[tuple[str, str]]) -> str:
    column_signature = tuple(name for name, _ in columns)
    primary_key = BOOKRAG_PRIMARY_KEYS.get(column_signature)
    if not primary_key:
        raise RuntimeError(f"BookRAG primary key is undefined for table {qualified_table}.")
    column_lines: list[str] = []
    for name, column_type in columns:
        effective_type = column_type
        if name in primary_key and not re.search(r"\bNOT\s+NULL\b", effective_type, flags=re.IGNORECASE):
            effective_type = f"{effective_type} NOT NULL"
        column_lines.append(f'  "{name}" {effective_type}')
    quoted_keys = ", ".join(f'"{name}"' for name in primary_key)
    column_lines.append(f"  PRIMARY KEY ({quoted_keys})")
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
        row_count = _count_teradata_rows(schema_name, table_name, execute_sql_fn)
        if row_count is None:
            raise RuntimeError(
                f"BookRAG target table already exists, but its row count could not be verified: "
                f"{qualified_table}. Refusing to reuse it."
            )
        if row_count > 0:
            raise RuntimeError(
                f"BookRAG target table already exists and contains {row_count} row(s): "
                f"{qualified_table}. Use a new vector_store_name to create a new table set."
            )

        quoted_columns = ", ".join(f'"{name}"' for name, _ in columns)
        try:
            execute_sql_fn(f"SELECT {quoted_columns} FROM {qualified_table} WHERE 1 = 0")
        except Exception as ex:
            raise RuntimeError(
                f"BookRAG target table already exists and is empty, but its columns are "
                f"incompatible with the current schema: {qualified_table}. Refusing to reuse it."
            ) from ex
        return [f"Reused empty BookRAG target table after schema validation: {qualified_table}."]
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
    warnings.extend(prepare_bookrag_document_relation_table(schema_name, table_targets, execute_sql_fn))
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


def prepare_bookrag_document_relation_table(
    schema_name: str | None,
    table_targets: dict[str, str],
    execute_sql_fn: ExecuteSqlFn | None,
) -> list[str]:
    warnings: list[str] = []
    table_name = table_targets["document_relations"]
    table_existed = _teradata_table_exists(
        _qualified_table_sql(schema_name, table_name),
        execute_sql_fn,
    )
    warnings.extend(
        _ensure_table(
            schema_name,
            table_name,
            BOOKRAG_DOCUMENT_RELATION_COLUMNS,
            execute_sql_fn,
        )
    )
    if table_existed and migrate_legacy_document_relation_table(
        schema_name=schema_name,
        table_name=table_name,
        execute_sql_fn=execute_sql_fn,
    ):
        warnings.append(
            "Removed legacy is_active from the document relationship table; every stored relationship is effective."
        )
    return warnings


def migrate_legacy_document_relation_table(
    *,
    schema_name: str | None,
    table_name: str,
    execute_sql_fn: ExecuteSqlFn | None,
) -> bool:
    """Drop the obsolete activity flag while preserving every relationship row."""
    if execute_sql_fn is None:
        raise RuntimeError("teradataml.execute_sql is unavailable.")
    qualified_table = _qualified_table_sql(schema_name, table_name)
    if not _teradata_table_exists(qualified_table, execute_sql_fn):
        return False
    try:
        execute_sql_fn(f'SELECT TOP 1 "is_active" FROM {qualified_table}')
    except Exception as ex:
        message = str(ex).lower()
        if "3810" in message or (
            "column" in message and ("does not exist" in message or "not found" in message)
        ):
            return False
        raise
    execute_sql_fn(f'ALTER TABLE {qualified_table} DROP "is_active"')
    return True


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
