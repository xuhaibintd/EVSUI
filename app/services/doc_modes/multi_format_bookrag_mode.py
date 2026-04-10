from __future__ import annotations

from app.services.multi_format import apply_multi_format_pipeline

MODE = "multi_format_bookrag"
LABEL = "Unstructured BookRAG"
SKIP_VECTORSTORE_CREATE = True


def preprocess_create_payload(**kwargs) -> tuple[dict, dict | None]:
    return apply_multi_format_pipeline(
        exec_payload=kwargs["exec_payload"],
        create_values=kwargs["create_values"],
        vector_store_name=kwargs["vector_store_name"],
        connection_params=kwargs.get("connection_params"),
        execute_sql_fn=kwargs.get("execute_sql_fn"),
        resolve_path_hint=kwargs["resolve_path_hint"],
        pipeline_mode=MODE,
    )


def build_skip_create_message(summary: dict | None) -> str:
    if not summary:
        return "Step 2 completed. BookRAG raw extraction finished and VectorStore.create() was skipped."

    raw_table_name = str(summary.get("raw_table_name") or "").strip()
    documents_table_name = str(summary.get("documents_table_name") or "").strip()
    raw_element_count = summary.get("raw_element_count")
    document_count = summary.get("document_count")
    inserted_rows = summary.get("inserted_rows")
    raw_stage_dir = str(summary.get("bookrag_raw_stage_dir") or "").strip()
    raw_stage_files = summary.get("bookrag_raw_stage_files") or []
    stats = summary.get("bookrag_raw_insert_stats") or summary.get("bookrag_insert_stats") or {}
    image_params = summary.get("bookrag_image_partition_parameters") or {}

    parts = ["Step 2 completed. BookRAG raw extraction mode finished."]
    if documents_table_name:
        parts.append(f"documents saved to {documents_table_name}.")
    if raw_table_name:
        parts.append(f"raw elements saved to {raw_table_name}.")
    details: list[str] = []
    if raw_element_count is not None:
        details.append(f"raw_elements={raw_element_count}")
    if document_count is not None:
        details.append(f"files={document_count}")
    if inserted_rows is not None:
        details.append(f"inserted_rows={inserted_rows}")
    if details:
        parts.append(" ".join(details) + ".")
    if raw_stage_dir:
        parts.append(f"raw_stage_dir={raw_stage_dir}.")
    if raw_stage_files:
        parts.append(f"raw_stage_files={len(raw_stage_files)}.")

    stat_parts = []
    for key in (
        "fastload_calls",
        "fastload_rows",
        "fastload_fallbacks",
        "copy_to_sql_calls",
        "copy_to_sql_rows",
        "copy_to_sql_fallbacks",
        "batch_statements",
        "single_row_statements",
    ):
        value = stats.get(key)
        if value:
            stat_parts.append(f"{key}={value}")
    if stat_parts:
        parts.append("insert_stats=" + ", ".join(stat_parts) + ".")
    image_parts = []
    if image_params.get("coordinates") is not None:
        image_parts.append(f"coordinates={image_params.get('coordinates')}")
    extract_types = image_params.get("extract_image_block_types") or []
    if extract_types:
        image_parts.append("extract_image_block_types=" + ",".join(str(item) for item in extract_types))
    if image_params.get("unique_element_ids") is not None:
        image_parts.append(f"unique_element_ids={image_params.get('unique_element_ids')}")
    if image_params.get("hi_res_model_name"):
        image_parts.append(f"hi_res_model_name={image_params.get('hi_res_model_name')}")
    if image_parts:
        parts.append("image_partition=" + ", ".join(image_parts) + ".")
    parts.append("Chunk table generation is disabled in this mode.")
    parts.append("Later BookRAG pipeline stages are disabled in this mode.")
    return " ".join(parts)
