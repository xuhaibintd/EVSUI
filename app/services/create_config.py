from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from app.services.doc_modes.constants import DOC_PIPELINE_UI_DEFAULTS


CREATE_FIELDS: list[dict[str, str]] = [
    {"name": "description", "label": "Description", "group": "Notebook Core", "kind": "text", "placeholder": "Vector store description"},
    {"name": "target_database", "label": "Target Database", "group": "Notebook Core", "kind": "text", "placeholder": "oaf"},
    {"name": "object_names", "label": "object_names", "group": "Notebook Core", "kind": "text", "placeholder": ""},
    {"name": "data_columns", "label": "data_columns (comma separated)", "group": "Notebook Core", "kind": "text", "placeholder": ""},
    {"name": "vector_column", "label": "vector_column", "group": "Notebook Core", "kind": "text", "placeholder": ""},
    {"name": "document_files", "label": "Document Files", "group": "Notebook Core", "kind": "textarea", "placeholder": "Leave empty to use uploaded files"},
    {"name": "chunk_size", "label": "chunk_size", "group": "Notebook Core", "kind": "number", "placeholder": ""},
    {"name": "optimized_chunking", "label": "optimized_chunking", "group": "Notebook Core", "kind": "select", "placeholder": ""},
    {"name": "embeddings_model", "label": "embeddings_model", "group": "Notebook Core", "kind": "select", "placeholder": ""},
    {"name": "search_algorithm", "label": "search_algorithm", "group": "Notebook Core", "kind": "select", "placeholder": ""},
    {"name": "top_k", "label": "top_k", "group": "Notebook Core", "kind": "number", "placeholder": ""},
    {"name": "metric", "label": "metric", "group": "Embedding & Search", "kind": "select", "placeholder": ""},
    {"name": "search_threshold", "label": "search_threshold", "group": "Embedding & Search", "kind": "number", "placeholder": ""},
    {"name": "search_numcluster", "label": "search_numcluster", "group": "Embedding & Search", "kind": "number", "placeholder": ""},
    {"name": "prompt", "label": "Prompt", "group": "Embedding & Search", "kind": "textarea", "placeholder": "Prompt used by ask/prepare_response"},
    {"name": "chat_completion_model", "label": "Chat Completion Model", "group": "Embedding & Search", "kind": "text", "placeholder": "gpt-4o-mini"},
    {"name": "chat_completion_max_tokens", "label": "Chat Completion Max Tokens", "group": "Embedding & Search", "kind": "number", "placeholder": "512"},
    {"name": "initial_delay_ms", "label": "Initial Delay (ms)", "group": "Embedding & Search", "kind": "number", "placeholder": "5000"},
    {"name": "delay_max_retries", "label": "Delay Max Retries", "group": "Embedding & Search", "kind": "number", "placeholder": "12"},
    {"name": "delay_exp_base", "label": "Delay Exponential Base", "group": "Embedding & Search", "kind": "number", "placeholder": "1"},
    {"name": "delay_jitter", "label": "Delay Jitter", "group": "Embedding & Search", "kind": "select", "placeholder": ""},
    {"name": "ignore_embedding_errors", "label": "Ignore Embedding Errors", "group": "Embedding & Search", "kind": "select", "placeholder": ""},
    {"name": "batch", "label": "Batch", "group": "Embedding & Search", "kind": "select", "placeholder": ""},
    {"name": "embeddings_dims", "label": "Embeddings Dims", "group": "Embedding & Search", "kind": "number", "placeholder": "1536"},
    {"name": "key_columns", "label": "key_columns (comma separated)", "group": "Extended Create Params", "kind": "text", "placeholder": ""},
    {"name": "header_height", "label": "header_height", "group": "Extended Create Params", "kind": "number", "placeholder": ""},
    {"name": "footer_height", "label": "footer_height", "group": "Extended Create Params", "kind": "number", "placeholder": ""},
    {"name": "initial_centroids_method", "label": "initial_centroids_method", "group": "HNSW / KMEANS Params", "kind": "select", "placeholder": ""},
    {"name": "train_numcluster", "label": "train_numcluster", "group": "HNSW / KMEANS Params", "kind": "number", "placeholder": ""},
    {"name": "max_iternum", "label": "max_iternum", "group": "HNSW / KMEANS Params", "kind": "number", "placeholder": ""},
    {"name": "stop_threshold", "label": "stop_threshold", "group": "HNSW / KMEANS Params", "kind": "number", "placeholder": ""},
    {"name": "seed", "label": "seed", "group": "HNSW / KMEANS Params", "kind": "number", "placeholder": ""},
    {"name": "num_init", "label": "num_init", "group": "HNSW / KMEANS Params", "kind": "number", "placeholder": ""},
    {"name": "ef_search", "label": "ef_search", "group": "HNSW / KMEANS Params", "kind": "number", "placeholder": ""},
    {"name": "num_layer", "label": "num_layer", "group": "HNSW / KMEANS Params", "kind": "number", "placeholder": ""},
    {"name": "ef_construction", "label": "ef_construction", "group": "HNSW / KMEANS Params", "kind": "number", "placeholder": ""},
    {"name": "num_connpernode", "label": "num_connpernode", "group": "HNSW / KMEANS Params", "kind": "number", "placeholder": ""},
    {"name": "maxnum_connpernode", "label": "maxnum_connpernode", "group": "HNSW / KMEANS Params", "kind": "number", "placeholder": ""},
    {"name": "apply_heuristics", "label": "apply_heuristics", "group": "HNSW / KMEANS Params", "kind": "select", "placeholder": ""},
    {"name": "include_objects", "label": "Include Objects", "group": "Metadata / RAG Params", "kind": "textarea", "placeholder": "db1.*, sales.*"},
    {"name": "exclude_objects", "label": "Exclude Objects", "group": "Metadata / RAG Params", "kind": "textarea", "placeholder": "tmp.*, backup.*"},
    {"name": "include_patterns", "label": "Include Patterns", "group": "Metadata / RAG Params", "kind": "textarea", "placeholder": "finance_pattern"},
    {"name": "exclude_patterns", "label": "Exclude Patterns", "group": "Metadata / RAG Params", "kind": "textarea", "placeholder": "raw_pattern"},
    {"name": "sample_size", "label": "Sample Size", "group": "Metadata / RAG Params", "kind": "number", "placeholder": "1000"},
    {"name": "rerank_weight", "label": "Rerank Weight", "group": "Metadata / RAG Params", "kind": "number", "placeholder": ""},
    {"name": "relevance_top_k", "label": "Relevance Top K", "group": "Metadata / RAG Params", "kind": "number", "placeholder": ""},
    {"name": "relevance_search_threshold", "label": "Relevance Threshold", "group": "Metadata / RAG Params", "kind": "number", "placeholder": ""},
]

_CREATE_FIELD_MAP = {field["name"]: field for field in CREATE_FIELDS}

_VECTOR_STORE_UI_FIELD = {
    "name": "vector_store_name",
    "label": "Vector Store Name",
    "kind": "text",
    "placeholder": "",
    "required": True,
}

_REQUIRED_CREATE_FIELDS = {"embeddings_model"}

_SELECT_OPTIONS = {
    "optimized_chunking": [
        {"value": "", "label": "(not set)"},
        {"value": "false", "label": "false"},
        {"value": "true", "label": "true"},
    ],
    "search_algorithm": [
        {"value": "", "label": "(select)"},
        {"value": "VECTORDISTANCE", "label": "VECTORDISTANCE"},
        {"value": "KMEANS", "label": "KMEANS"},
        {"value": "HNSW", "label": "HNSW"},
    ],
    "metric": [
        {"value": "", "label": "(not set)"},
        {"value": "COSINE", "label": "COSINE"},
        {"value": "EUCLIDEAN", "label": "EUCLIDEAN"},
        {"value": "DOTPRODUCT", "label": "DOTPRODUCT"},
    ],
    "initial_centroids_method": [
        {"value": "", "label": "(not set)"},
        {"value": "RANDOM", "label": "RANDOM"},
        {"value": "KMEANS++", "label": "KMEANS++"},
    ],
    "apply_heuristics": [
        {"value": "", "label": "(not set)"},
        {"value": "true", "label": "true"},
        {"value": "false", "label": "false"},
    ],
}

_EMBEDDINGS_MODEL_OPTION_GROUPS = [
    {
        "label": "AWS",
        "options": [
            {"value": "amazon.titan-embed-text-v1", "label": "amazon.titan-embed-text-v1"},
            {"value": "amazon.titan-embed-image-v1", "label": "amazon.titan-embed-image-v1"},
            {"value": "amazon.titan-embed-text-v2:0", "label": "amazon.titan-embed-text-v2:0"},
        ],
    },
    {
        "label": "Azure",
        "options": [
            {"value": "text-embedding-ada-002", "label": "text-embedding-ada-002"},
            {"value": "text-embedding-3-small", "label": "text-embedding-3-small"},
            {"value": "text-embedding-3-large", "label": "text-embedding-3-large"},
        ],
    },
]

_FIELD_OPTION_GROUPS = {
    "embeddings_model": _EMBEDDINGS_MODEL_OPTION_GROUPS,
}

_SELECT_OPTIONS["embeddings_model"] = [{"value": "", "label": "(select)"}]

_FIELD_INPUT_ATTRS = {
    "search_threshold": {"step": "any"},
    "stop_threshold": {"step": "any"},
    "rerank_weight": {"step": "any"},
    "relevance_search_threshold": {"step": "any"},
    "header_height": {"min": "0", "step": "1"},
    "footer_height": {"min": "0", "step": "1"},
}

_UI_DEFAULTS: dict[str, Any] = {
    "vector_store_name": "",
    "create_preset": "auto",
    "search_algorithm": "",
    "doc_pipeline_mode": "",
    "vector_column": "",
    "metric": "",
    "chunk_size": "",
    "top_k": "",
    "initial_centroids_method": "",
    "max_iternum": "",
    "stop_threshold": "",
    "num_init": "",
    "ef_search": "",
    "ef_construction": "",
    "num_connpernode": "",
    "maxnum_connpernode": "",
    "apply_heuristics": "",
    "rerank_weight": "",
    "relevance_top_k": "",
}

_APPLIED_CREATE_DEFAULTS: dict[str, Any] = {}

_BASIC_SECONDARY_FIELDS = [
    "embeddings_model",
    "search_algorithm",
    "top_k",
    "metric",
    "key_columns",
]


_ALGORITHM_SECTION_FIELDS = [
    ("search_threshold", "VECTORDISTANCE KMEANS"),
    ("initial_centroids_method", "KMEANS"),
    ("train_numcluster", "KMEANS"),
    ("max_iternum", "KMEANS"),
    ("stop_threshold", "KMEANS"),
    ("seed", "KMEANS HNSW"),
    ("num_init", "KMEANS"),
    ("search_numcluster", "KMEANS"),
    ("ef_search", "HNSW"),
    ("num_layer", "HNSW"),
    ("ef_construction", "HNSW"),
    ("num_connpernode", "HNSW"),
    ("maxnum_connpernode", "HNSW"),
    ("apply_heuristics", "HNSW"),
]

_RERANK_FIELDS = [
    "rerank_weight",
    "relevance_top_k",
    "relevance_search_threshold",
]

_TEXT_CORE_FIELDS = [
    "chunk_size",
    "optimized_chunking",
    "header_height",
    "footer_height",
    "object_names",
    "data_columns",
    "vector_column",
]

_TEXT_CORE_WRAPPER_CLASS = {
    "chunk_size": "field doc-field-short",
    "optimized_chunking": "field doc-field-short",
    "header_height": "field doc-field-short",
    "footer_height": "field doc-field-short",
    "object_names": "field doc-field-medium",
    "data_columns": "field doc-field-long",
    "vector_column": "field doc-field-medium",
}

_BOOL_FIELDS = {"optimized_chunking", "delay_jitter", "ignore_embedding_errors", "batch", "apply_heuristics"}
CREATE_FIELD_MAX_LEN = 50
ALLOWED_VALIDATION_TARGETS = {"vectorstore.ask", "vectorstore.similarity_search"}
_INT_FIELDS = {
    "chunk_size",
    "header_height",
    "footer_height",
    "embeddings_dims",
    "initial_delay_ms",
    "delay_max_retries",
    "delay_exp_base",
    "top_k",
    "search_numcluster",
    "relevance_top_k",
    "chat_completion_max_tokens",
    "train_numcluster",
    "max_iternum",
    "seed",
    "num_init",
    "ef_search",
    "num_layer",
    "ef_construction",
    "num_connpernode",
    "maxnum_connpernode",
    "sample_size",
}
NON_NEGATIVE_INT_FIELDS = {"header_height", "footer_height"}
_FLOAT_FIELDS = {"search_threshold", "rerank_weight", "relevance_search_threshold", "stop_threshold"}
_CSV_FIELDS = {
    "object_names",
    "key_columns",
    "data_columns",
    "document_files",
    "include_objects",
    "exclude_objects",
    "include_patterns",
    "exclude_patterns",
}
_FORCE_LIST_CSV_FIELDS = {"data_columns"}
CORE_CREATE_FIELDS = {
    "document_files",
    "chunk_size",
    "optimized_chunking",
    "header_height",
    "footer_height",
    "embeddings_model",
    "search_algorithm",
    "top_k",
    "object_names",
    "data_columns",
    "vector_column",
    "metric",
    "key_columns",
    "search_threshold",
    "initial_centroids_method",
    "train_numcluster",
    "max_iternum",
    "stop_threshold",
    "seed",
    "num_init",
    "search_numcluster",
    "ef_search",
    "num_layer",
    "ef_construction",
    "num_connpernode",
    "maxnum_connpernode",
    "apply_heuristics",
    "rerank_weight",
    "relevance_top_k",
    "relevance_search_threshold",
}


def _stringify_default(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def _clone_ui_field(name: str, **overrides: Any) -> dict[str, Any]:
    base = deepcopy(_VECTOR_STORE_UI_FIELD if name == "vector_store_name" else _CREATE_FIELD_MAP[name])
    base["default"] = _stringify_default(_UI_DEFAULTS.get(name))
    if name in _REQUIRED_CREATE_FIELDS:
        base["required"] = True
    if name in _SELECT_OPTIONS:
        base["options"] = deepcopy(_SELECT_OPTIONS[name])
    if name in _FIELD_OPTION_GROUPS:
        base["option_groups"] = deepcopy(_FIELD_OPTION_GROUPS[name])
    if name in _FIELD_INPUT_ATTRS:
        base["input_attrs"] = dict(_FIELD_INPUT_ATTRS[name])
    base.update(overrides)
    return base


def build_create_ui_sections() -> list[dict[str, Any]]:
    basic_fields = [_clone_ui_field("vector_store_name")]
    basic_fields.extend(_clone_ui_field(name) for name in _BASIC_SECONDARY_FIELDS)
    algorithm_fields = [
        _clone_ui_field(name, wrapper_attrs={"data-algo-for": targets})
        for name, targets in _ALGORITHM_SECTION_FIELDS
    ]
    rerank_fields = [_clone_ui_field(name) for name in _RERANK_FIELDS]
    return [
        {
            "title": "Basic",
            "rows": [
                {"class": "basic-row basic-row-single", "fields": basic_fields},
            ],
        },
        {
            "title": "Search Algorithm",
            "hint": True,
            "grid_class": "param-grid compact compact-tight",
            "fields": algorithm_fields,
        },
        {
            "title": "Rerank",
            "grid_class": "param-grid compact rerank-grid",
            "fields": rerank_fields,
        },
    ]


def build_text_core_ui_fields() -> list[dict[str, Any]]:
    return [
        _clone_ui_field(name, wrapper_class=_TEXT_CORE_WRAPPER_CLASS.get(name, "field"))
        for name in _TEXT_CORE_FIELDS
    ]


def group_create_fields() -> list[tuple[str, list[dict[str, str]]]]:
    groups: dict[str, list[dict[str, str]]] = {}
    for field in CREATE_FIELDS:
        groups.setdefault(field["group"], []).append(field)
    return list(groups.items())


def _split_csv(value: str) -> list[str]:
    return [chunk.strip() for chunk in value.replace("\n", ",").split(",") if chunk.strip()]


def coerce_create_param(name: str, raw: str):
    if name in _CSV_FIELDS:
        chunks = _split_csv(raw)
        if name in _FORCE_LIST_CSV_FIELDS:
            return chunks
        if len(chunks) == 1:
            return chunks[0]
        return chunks
    if name in _BOOL_FIELDS:
        return raw.lower() == "true"
    if name in _INT_FIELDS:
        value = int(raw)
        if name in NON_NEGATIVE_INT_FIELDS and value < 0:
            raise ValueError(f"Field [{name}] must be >= 0.")
        return value
    if name in _FLOAT_FIELDS:
        return float(raw)
    return raw


def default_create_values() -> dict[str, str]:
    data = {name: _stringify_default(value) for name, value in _UI_DEFAULTS.items()}
    data.update(DOC_PIPELINE_UI_DEFAULTS)
    for field in CREATE_FIELDS:
        data.setdefault(field["name"], "")
    return data


def apply_create_preset(payload: dict, preset: str, vector_store_name: str) -> None:
    for key, value in _APPLIED_CREATE_DEFAULTS.items():
        payload.setdefault(key, value)

    if preset == "vectordistance":
        payload["search_algorithm"] = "VECTORDISTANCE"
    elif preset == "kmeans":
        payload["search_algorithm"] = "KMEANS"
    elif preset == "hnsw":
        payload["search_algorithm"] = "HNSW"


def build_create_call_preview(vector_store_name: str, payload: dict) -> str:
    payload_json = json.dumps(payload, indent=2, ensure_ascii=False)
    return (
        f"pdf_vs = VectorStore('{vector_store_name}')\n"
        f"create_kwargs = {payload_json}\n"
        "pdf_vs.create(**create_kwargs)\n"
        "pdf_vs.status()\n\n"
        "# Notebook next calls:\n"
        "pdf_vs.ask(question='...', prompt='...')\n"
        "response = pdf_vs.similarity_search(question='...')\n"
        "pdf_vs.destroy()\n"
        "VSManager.disconnect()"
    )
