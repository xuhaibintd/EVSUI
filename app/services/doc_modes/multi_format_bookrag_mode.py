from __future__ import annotations

from app.services.multi_format import (
    apply_multi_format_pipeline,
    get_ready_bookrag_csv_load_summary,
    strip_file_based_create_params,
    update_bookrag_csv_vector_store_status,
)

MODE = "multi_format_bookrag"
LABEL = "Multi-Format BookRAG"
SKIP_VECTORSTORE_CREATE = False


def should_run_vectorstore_create(create_values: dict[str, str]) -> bool:
    if str(create_values.get("bookrag_loaded_csv_run_id") or "").strip():
        return True
    return str(create_values.get("multi_format_bookrag_run_embedding", "false")).strip().lower() == "true"


def preprocess_create_payload(**kwargs) -> tuple[dict, dict | None]:
    csv_run_id = str(kwargs["create_values"].get("bookrag_loaded_csv_run_id") or "").strip()
    if csv_run_id:
        load_summary = get_ready_bookrag_csv_load_summary(csv_run_id=csv_run_id)
        vector_store_name = str(load_summary.get("vector_store_name") or "").strip()
        if vector_store_name != str(kwargs["vector_store_name"] or "").strip():
            raise RuntimeError("Selected loaded-table run does not match the Vector Store name.")
        payload = strip_file_based_create_params(dict(kwargs["exec_payload"]))
        description = str(payload.get("description") or "").strip()
        marker = "unstructured_bookrag_flg"
        if marker not in description.lower():
            description = f"{description} {marker}".strip()
        payload.update(
            {
                "target_database": str(load_summary["target_database"]),
                "object_names": str(load_summary["node_table"]),
                "data_columns": ["content"],
                "key_columns": ["doc_id", "node_id"],
                "description": description,
                "nv_ingestor": None,
            }
        )
        persisted_counts = load_summary.get("persisted_row_counts") or {}
        return payload, {
            **load_summary,
            "source": "loaded_csv_tables",
            "skip_vectorstore_create": False,
            "nodes_table_name": str(load_summary["node_table"]),
            "node_count": persisted_counts.get("nodes"),
            "entity_count": persisted_counts.get("entities"),
            "entity_relation_count": persisted_counts.get("entity_relations"),
        }
    return apply_multi_format_pipeline(
        exec_payload=kwargs["exec_payload"],
        create_values=kwargs["create_values"],
        vector_store_name=kwargs["vector_store_name"],
        connection_params=kwargs.get("connection_params"),
        execute_sql_fn=kwargs.get("execute_sql_fn"),
        resolve_path_hint=kwargs["resolve_path_hint"],
        pipeline_mode=MODE,
    )


def mark_vectorstore_status(
    summary: dict | None,
    *,
    status: str,
    error: str = "",
    create_payload: dict | None = None,
) -> None:
    if not summary or summary.get("source") != "loaded_csv_tables":
        return
    update_bookrag_csv_vector_store_status(
        csv_run_id=str(summary["csv_run_id"]),
        status=status,
        error=error,
        create_payload=create_payload,
    )


def _insert_timing_message(summary: dict) -> str:
    timing_items: list[str] = []
    for label, summary_key in (
        ("bdoc", "bookrag_document_insert_stats"),
        ("braw", "bookrag_raw_insert_stats"),
        ("bblk", "bookrag_block_insert_stats"),
        ("bnode", "bookrag_node_insert_stats"),
    ):
        stats = summary.get(summary_key)
        if not isinstance(stats, dict) or not stats:
            continue
        methods: list[str] = []
        if int(stats.get("native_csv_batch_calls", 0) or 0) > 0:
            methods.append("csv-batch")
        if int(stats.get("native_csv_fastload_calls", 0) or 0) > 0:
            methods.append("fastload-csv")
        method_label = "->".join(methods) or str(stats.get("insert_mode") or "unknown")
        row_count = int(stats.get("input_rows", 0) or 0)
        elapsed = float(stats.get("insert_total_seconds", 0.0) or 0.0)
        timing_items.append(f"{label}={elapsed:.2f}s/{row_count}rows/{method_label}")
    if not timing_items:
        return ""
    return "BookRAG insert timing: " + ", ".join(timing_items) + "."


def append_success_message(message: str, summary: dict | None) -> str:
    if not summary:
        return message

    nodes_table_name = str(summary.get("nodes_table_name") or "").strip()
    node_count = summary.get("node_count")
    entity_count = summary.get("entity_count")
    entity_relation_count = summary.get("entity_relation_count")
    parts = [message]
    if nodes_table_name:
        if node_count is not None:
            parts.append(f"BookRAG nodes source={nodes_table_name} ({node_count} rows).")
        else:
            parts.append(f"BookRAG nodes source={nodes_table_name}.")
    if entity_count is not None or entity_relation_count is not None:
        detail = []
        if entity_count is not None:
            detail.append(f"entities={entity_count}")
        if entity_relation_count is not None:
            detail.append(f"relations={entity_relation_count}")
        if detail:
            parts.append("BookRAG graph: " + ", ".join(detail) + ".")
    timing_message = _insert_timing_message(summary)
    if timing_message:
        parts.append(timing_message)
    parts.append("VectorStore.create() uses bnode.content with key_columns=doc_id,node_id.")
    return " ".join(parts)


def build_skip_create_message(summary: dict | None) -> str:
    if not summary:
        return "Step 2 completed. BookRAG tree tables finished and VectorStore.create() was skipped."

    raw_table_name = str(summary.get("raw_table_name") or "").strip()
    documents_table_name = str(summary.get("documents_table_name") or "").strip()
    blocks_table_name = str(summary.get("blocks_table_name") or "").strip()
    nodes_table_name = str(summary.get("nodes_table_name") or "").strip()
    entities_table_name = str(summary.get("entities_table_name") or "").strip()
    entity_links_table_name = str(summary.get("entity_links_table_name") or "").strip()
    entity_relations_table_name = str(summary.get("entity_relations_table_name") or "").strip()
    document_relations_table_name = str(summary.get("document_relations_table_name") or "").strip()
    raw_element_count = summary.get("raw_element_count")
    document_count = summary.get("document_count")
    block_count = summary.get("block_count")
    node_count = summary.get("node_count")
    entity_count = summary.get("entity_count")
    entity_link_count = summary.get("entity_link_count")
    entity_relation_count = summary.get("entity_relation_count")
    document_relation_count = summary.get("document_relation_count")

    run_embedding_step = bool(summary.get("run_embedding_step"))
    parts = ["Step 2 completed. BookRAG selected tables finished."]
    table_parts: list[str] = []
    if documents_table_name:
        table_parts.append(f"bdoc={documents_table_name}")
    if raw_table_name:
        table_parts.append(f"braw={raw_table_name}")
    if blocks_table_name:
        table_parts.append(f"bblk={blocks_table_name}")
    if nodes_table_name:
        table_parts.append(f"bnode={nodes_table_name}")
    if document_relations_table_name:
        table_parts.append(f"bdrel={document_relations_table_name}")
    if entities_table_name:
        table_parts.append(f"bent={entities_table_name}")
    if entity_links_table_name:
        table_parts.append(f"belnk={entity_links_table_name}")
    if entity_relations_table_name:
        table_parts.append(f"brel={entity_relations_table_name}")
    if table_parts:
        parts.append("Tables: " + ", ".join(table_parts) + ".")

    count_parts: list[str] = []
    if document_count is not None:
        count_parts.append(f"files={document_count}")
    if raw_element_count is not None:
        count_parts.append(f"raw={raw_element_count}")
    if block_count is not None:
        count_parts.append(f"blocks={block_count}")
    if node_count is not None:
        count_parts.append(f"nodes={node_count}")
    if entity_count is not None:
        count_parts.append(f"entities={entity_count}")
    if entity_link_count is not None:
        count_parts.append(f"entity_links={entity_link_count}")
    if entity_relation_count is not None:
        count_parts.append(f"relations={entity_relation_count}")
    if document_relation_count is not None:
        count_parts.append(f"document_relations={document_relation_count}")
    if count_parts:
        parts.append("Counts: " + ", ".join(count_parts) + ".")
    timing_message = _insert_timing_message(summary)
    if timing_message:
        parts.append(timing_message)
    parts.append("Embedding: enabled." if run_embedding_step else "Embedding: skipped.")
    return " ".join(parts)
