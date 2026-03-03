from __future__ import annotations

import json


CREATE_FIELDS: list[dict[str, str]] = [
    {"name": "description", "label": "Description", "group": "Notebook Core", "kind": "text", "placeholder": "Vector store description"},
    {"name": "target_database", "label": "Target Database", "group": "Notebook Core", "kind": "text", "placeholder": "oaf"},
    {"name": "object_names", "label": "Object Names", "group": "Notebook Core", "kind": "textarea", "placeholder": "TokioMarine_pdf_test"},
    {"name": "data_columns", "label": "Data Columns", "group": "Notebook Core", "kind": "text", "placeholder": "chunks"},
    {"name": "vector_column", "label": "Vector Column", "group": "Notebook Core", "kind": "text", "placeholder": "Embedding"},
    {"name": "document_files", "label": "Document Files", "group": "Notebook Core", "kind": "textarea", "placeholder": "Leave empty to use uploaded files"},
    {"name": "chunk_size", "label": "Chunk Size", "group": "Notebook Core", "kind": "number", "placeholder": "500"},
    {"name": "optimized_chunking", "label": "Optimized Chunking", "group": "Notebook Core", "kind": "select", "placeholder": "false,true"},
    {"name": "embeddings_model", "label": "Embeddings Model", "group": "Notebook Core", "kind": "select", "placeholder": "amazon.titan-embed-text-v1,amazon.titan-embed-image-v1,amazon.titan-embed-text-v2:0,text-embedding-ada-002,text-embedding-3-small,text-embedding-3-large"},
    {"name": "search_algorithm", "label": "Search Algorithm", "group": "Notebook Core", "kind": "select", "placeholder": "VECTORDISTANCE,KMEANS,HNSW"},
    {"name": "top_k", "label": "Top K", "group": "Notebook Core", "kind": "number", "placeholder": "5"},
    {"name": "metric", "label": "Metric", "group": "Embedding & Search", "kind": "select", "placeholder": "COSINE,EUCLIDEAN,DOTPRODUCT"},
    {"name": "search_threshold", "label": "Search Threshold", "group": "Embedding & Search", "kind": "text", "placeholder": "0.75"},
    {"name": "search_numcluster", "label": "Search Num Cluster", "group": "Embedding & Search", "kind": "number", "placeholder": "4"},
    {"name": "prompt", "label": "Prompt", "group": "Embedding & Search", "kind": "textarea", "placeholder": "Prompt used by ask/prepare_response"},
    {"name": "chat_completion_model", "label": "Chat Completion Model", "group": "Embedding & Search", "kind": "text", "placeholder": "gpt-4o-mini"},
    {"name": "chat_completion_max_tokens", "label": "Chat Completion Max Tokens", "group": "Embedding & Search", "kind": "number", "placeholder": "512"},
    {"name": "initial_delay_ms", "label": "Initial Delay (ms)", "group": "Embedding & Search", "kind": "number", "placeholder": "5000"},
    {"name": "delay_max_retries", "label": "Delay Max Retries", "group": "Embedding & Search", "kind": "number", "placeholder": "12"},
    {"name": "delay_exp_base", "label": "Delay Exponential Base", "group": "Embedding & Search", "kind": "number", "placeholder": "1"},
    {"name": "delay_jitter", "label": "Delay Jitter", "group": "Embedding & Search", "kind": "select", "placeholder": "false,true"},
    {"name": "ignore_embedding_errors", "label": "Ignore Embedding Errors", "group": "Embedding & Search", "kind": "select", "placeholder": "false,true"},
    {"name": "batch", "label": "Batch", "group": "Embedding & Search", "kind": "select", "placeholder": "false,true"},
    {"name": "embeddings_dims", "label": "Embeddings Dims", "group": "Embedding & Search", "kind": "number", "placeholder": "1536"},
    {"name": "key_columns", "label": "Key Columns", "group": "Extended Create Params", "kind": "text", "placeholder": "id, document_id"},
    {"name": "header_height", "label": "Header Height", "group": "Extended Create Params", "kind": "number", "placeholder": "0"},
    {"name": "footer_height", "label": "Footer Height", "group": "Extended Create Params", "kind": "number", "placeholder": "0"},
    {"name": "initial_centroids_method", "label": "Initial Centroids Method", "group": "HNSW / KMEANS Params", "kind": "select", "placeholder": "RANDOM,KMEANS++"},
    {"name": "train_numcluster", "label": "Train Num Cluster", "group": "HNSW / KMEANS Params", "kind": "number", "placeholder": "8"},
    {"name": "max_iternum", "label": "Max Iter Num", "group": "HNSW / KMEANS Params", "kind": "number", "placeholder": "10"},
    {"name": "stop_threshold", "label": "Stop Threshold", "group": "HNSW / KMEANS Params", "kind": "text", "placeholder": "0.0395"},
    {"name": "seed", "label": "Seed", "group": "HNSW / KMEANS Params", "kind": "number", "placeholder": "10"},
    {"name": "num_init", "label": "Num Init", "group": "HNSW / KMEANS Params", "kind": "number", "placeholder": "1"},
    {"name": "ef_search", "label": "EF Search", "group": "HNSW / KMEANS Params", "kind": "number", "placeholder": "64"},
    {"name": "num_layer", "label": "Num Layer", "group": "HNSW / KMEANS Params", "kind": "number", "placeholder": "2"},
    {"name": "ef_construction", "label": "EF Construction", "group": "HNSW / KMEANS Params", "kind": "number", "placeholder": "64"},
    {"name": "num_connpernode", "label": "Num Conn Per Node", "group": "HNSW / KMEANS Params", "kind": "number", "placeholder": "32"},
    {"name": "maxnum_connpernode", "label": "Max Num Conn Per Node", "group": "HNSW / KMEANS Params", "kind": "number", "placeholder": "32"},
    {"name": "apply_heuristics", "label": "Apply Heuristics", "group": "HNSW / KMEANS Params", "kind": "select", "placeholder": "true,false"},
    {"name": "include_objects", "label": "Include Objects", "group": "Metadata / RAG Params", "kind": "textarea", "placeholder": "db1.*, sales.*"},
    {"name": "exclude_objects", "label": "Exclude Objects", "group": "Metadata / RAG Params", "kind": "textarea", "placeholder": "tmp.*, backup.*"},
    {"name": "include_patterns", "label": "Include Patterns", "group": "Metadata / RAG Params", "kind": "textarea", "placeholder": "finance_pattern"},
    {"name": "exclude_patterns", "label": "Exclude Patterns", "group": "Metadata / RAG Params", "kind": "textarea", "placeholder": "raw_pattern"},
    {"name": "sample_size", "label": "Sample Size", "group": "Metadata / RAG Params", "kind": "number", "placeholder": "1000"},
    {"name": "rerank_weight", "label": "Rerank Weight", "group": "Metadata / RAG Params", "kind": "text", "placeholder": "0.5"},
    {"name": "relevance_top_k", "label": "Relevance Top K", "group": "Metadata / RAG Params", "kind": "number", "placeholder": "5"},
    {"name": "relevance_search_threshold", "label": "Relevance Search Threshold", "group": "Metadata / RAG Params", "kind": "text", "placeholder": "0.2"},
]

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
DOC_PIPELINE_UI_DEFAULTS = {
    "multi_format_strategy": "auto",
    "multi_format_chunk_size": "600",
    "multi_format_chunk_overlap": "80",
    "multi_format_ocr_languages": "ja,en",
    "multi_format_keep_tables": "true",
    "multi_format_extract_images": "false",
}

CORE_CREATE_FIELDS = {
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
    data = {
        "vector_store_name": "TokioMarine",
        "create_preset": "vectordistance",
        "search_algorithm": "VECTORDISTANCE",
        "doc_pipeline_mode": "text_core",
    }
    data.update(DOC_PIPELINE_UI_DEFAULTS)
    for field in CREATE_FIELDS:
        data.setdefault(field["name"], "")
    return data


def apply_create_preset(payload: dict, preset: str, vector_store_name: str) -> None:
    if "object_names" not in payload:
        payload["object_names"] = f"{vector_store_name}_pdf_test"
    payload.setdefault("data_columns", ["chunks"])
    payload.setdefault("vector_column", "Embedding")
    payload.setdefault("chunk_size", 500)
    payload.setdefault("optimized_chunking", False)
    payload.setdefault("embeddings_model", "amazon.titan-embed-text-v2:0")
    payload.setdefault("top_k", 5)

    if preset == "vectordistance":
        payload["search_algorithm"] = "VECTORDISTANCE"
    elif preset == "kmeans":
        payload["search_algorithm"] = "KMEANS"
    elif preset == "hnsw":
        payload["search_algorithm"] = "HNSW"
        payload.setdefault("metric", "COSINE")
        payload.setdefault("seed", 10)
        payload.setdefault("ef_construction", 64)
        payload.setdefault("ef_search", 64)
        payload.setdefault("num_connpernode", 32)
        payload.setdefault("maxnum_connpernode", 32)
        payload.setdefault("apply_heuristics", True)


def build_create_call_preview(vector_store_name: str, payload: dict) -> str:
    payload_json = json.dumps(payload, indent=2, ensure_ascii=False)
    return (
        f"pdf_vs = VectorStore('{vector_store_name}')\\n"
        f"create_kwargs = {payload_json}\\n"
        "pdf_vs.create(**create_kwargs)\\n"
        "pdf_vs.status()\\n\\n"
        "# Notebook next calls:\\n"
        "pdf_vs.ask(question='...', prompt='...')\\n"
        "response = pdf_vs.similarity_search(question='...')\\n"
        "pdf_vs.destroy()\\n"
        "VSManager.disconnect()"
    )
