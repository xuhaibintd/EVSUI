from __future__ import annotations

from typing import Any


TERADATA_IDENTIFIER_MAX_LEN = 30

FILE_BASED_CREATE_KEYS_TO_REMOVE = {
    "chunk_size",
    "chunk_overlap",
    "optimized_chunking",
    "header_height",
    "footer_height",
    "document_files",
    "document_manifest",
    "document_relations",
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
FILE_BASED_CREATE_KEY_PREFIXES_TO_REMOVE = ("ingest_",)
FILE_BASED_CREATE_KEY_SUFFIXES_TO_REMOVE = ("_ingestor",)

UNSTRUCTURED_CHUNK_COLUMNS: list[tuple[str, str]] = [
    ("text", "VARCHAR(32000) CHARACTER SET UNICODE"),
    ("type", "VARCHAR(50) CHARACTER SET UNICODE"),
    ("filename", "VARCHAR(255) CHARACTER SET UNICODE"),
    ("element_id", "VARCHAR(64) CHARACTER SET UNICODE"),
    ("id", "VARCHAR(64) NOT NULL"),
    ("table_id", "VARCHAR(128) CHARACTER SET UNICODE"),
    ("page_number", "INTEGER"),
    ("chunk_index", "INTEGER"),
    ("is_continuation", "BYTEINT"),
    ("num_carried_over_header_rows", "INTEGER"),
    ("partitioner_type", "VARCHAR(100) CHARACTER SET UNICODE"),
    ("image_description", "VARCHAR(32000) CHARACTER SET UNICODE"),
    ("table_description", "VARCHAR(32000) CHARACTER SET UNICODE"),
    ("generative_ocr", "VARCHAR(32000) CHARACTER SET UNICODE"),
    ("text_as_html", "VARCHAR(32000) CHARACTER SET UNICODE"),
    ("table_to_html", "VARCHAR(32000) CHARACTER SET UNICODE"),
    ("filetype", "VARCHAR(50) CHARACTER SET UNICODE"),
    ("date_processed", "VARCHAR(50)"),
]

BOOKRAG_TABLE_TOGGLE_FIELDS = {
    "documents": "multi_format_bookrag_generate_documents",
    "raw": "multi_format_bookrag_generate_raw",
    "blocks": "multi_format_bookrag_generate_blocks",
    "nodes": "multi_format_bookrag_generate_nodes",
    "document_relations": "multi_format_bookrag_generate_document_relations",
    "entities": "multi_format_bookrag_generate_entities",
    "entity_links": "multi_format_bookrag_generate_entity_links",
    "entity_relations": "multi_format_bookrag_generate_entity_relations",
}
BOOKRAG_TABLE_TOGGLE_DEFAULTS = {key: True for key in BOOKRAG_TABLE_TOGGLE_FIELDS}
BOOKRAG_TABLE_TOGGLE_ORDER = tuple(BOOKRAG_TABLE_TOGGLE_FIELDS)
BOOKRAG_ENTITY_TABLE_KEYS = ("entities", "entity_links", "entity_relations")
BOOKRAG_GRAPH_TOGGLE_FIELD = "multi_format_bookrag_generate_graph"
BOOKRAG_LEGACY_GRAPH_TOGGLE_FIELDS = (
    "multi_format_bookrag_generate_entities",
    "multi_format_bookrag_generate_entity_links",
    "multi_format_bookrag_generate_entity_relations",
)

BOOKRAG_UNSTRUCTURED_WORKERS_DEFAULT = 5
BOOKRAG_CSV_PREPARE_WORKERS_DEFAULT = 5
BOOKRAG_CSV_LOAD_WORKERS_DEFAULT = 5
BOOKRAG_PARSE_MANIFEST_FILENAME = "manifest.json"
BOOKRAG_PARSE_MANIFEST_SCHEMA_VERSION = 1
BOOKRAG_CSV_MANIFEST_SCHEMA_VERSION = 1
BOOKRAG_CSV_MANIFEST_FILENAME = "manifest.json"
BOOKRAG_TRANSFORM_VERSION = "bookrag-json-to-csv-v1"
BOOKRAG_COMPLETE_TABLE_CONTRACT = "core-audit-graph-v1"
MULTI_FORMAT_PARSE_MANIFEST_FILENAME = "manifest.json"
MULTI_FORMAT_PARSE_MANIFEST_SCHEMA_VERSION = 1
MULTI_FORMAT_CSV_MANIFEST_FILENAME = "manifest.json"
MULTI_FORMAT_CSV_MANIFEST_SCHEMA_VERSION = 1
MULTI_FORMAT_TRANSFORM_VERSION = "multi-format-json-to-unstructured-csv-v1"
MULTI_FORMAT_UNSTRUCTURED_WORKERS_DEFAULT = 5
MULTI_FORMAT_CSV_PREPARE_WORKERS_DEFAULT = 5
MULTI_FORMAT_CSV_LOAD_WORKERS_DEFAULT = 5


def to_int(raw: Any, default: int, minimum: int = 0, maximum: int | None = None) -> int:
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        value = default
    value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def to_bool(raw: Any, default: bool = False) -> bool:
    if isinstance(raw, bool):
        return raw
    value = str(raw or "").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def parse_csv_values(raw: Any) -> list[str]:
    return [part.strip() for part in str(raw or "").split(",") if part.strip()]


def first_defined(*values: Any) -> Any:
    for value in values:
        if value is not None and str(value).strip() != "":
            return value
    return None


def strip_file_based_create_params(payload: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(payload)
    for key in list(cleaned):
        normalized_key = str(key or "").strip().lower()
        if (
            normalized_key in FILE_BASED_CREATE_KEYS_TO_REMOVE
            or normalized_key.startswith(FILE_BASED_CREATE_KEY_PREFIXES_TO_REMOVE)
            or normalized_key.endswith(FILE_BASED_CREATE_KEY_SUFFIXES_TO_REMOVE)
        ):
            cleaned.pop(key, None)
    return cleaned


def strip_create_ingestor_params(payload: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(payload)
    for key in list(cleaned):
        normalized_key = str(key or "").strip().lower()
        if (
            normalized_key in {"ingestor", "ingest_params", "nv_ingestor", "ingest_host", "ingest_port"}
            or normalized_key.startswith(FILE_BASED_CREATE_KEY_PREFIXES_TO_REMOVE)
            or normalized_key.endswith(FILE_BASED_CREATE_KEY_SUFFIXES_TO_REMOVE)
        ):
            cleaned.pop(key, None)
    return cleaned
