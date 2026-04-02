from __future__ import annotations

from app.services.multi_format import apply_multi_format_pipeline

MODE = "multi_format_bookrag"
LABEL = "Multi-Format BookRAG"
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
        return "Step 2 completed. BookRAG block-table preprocessing finished and VectorStore.create() was skipped."

    table_name = str(summary.get("table_name") or "").strip()
    block_count = summary.get("block_count")
    document_count = summary.get("document_count")
    inserted_rows = summary.get("inserted_rows")
    stats = summary.get("bookrag_insert_stats") or {}
    image_params = summary.get("bookrag_image_partition_parameters") or {}

    parts = ["Step 2 completed. BookRAG block-table test mode finished."]
    if table_name:
        parts.append(f"blocks saved to {table_name}.")
    details: list[str] = []
    if block_count is not None:
        details.append(f"blocks={block_count}")
    if document_count is not None:
        details.append(f"files={document_count}")
    if inserted_rows is not None:
        details.append(f"inserted_rows={inserted_rows}")
    if details:
        parts.append(" ".join(details) + ".")

    stat_parts = []
    for key in (
        "read_csv_calls",
        "read_csv_rows",
        "read_csv_fallbacks",
        "copy_to_sql_calls",
        "copy_to_sql_rows",
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
    parts.append("Later BookRAG pipeline stages are disabled in this mode.")
    return " ".join(parts)
