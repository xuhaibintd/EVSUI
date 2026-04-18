from __future__ import annotations

from app.services.multi_format import apply_multi_format_pipeline

MODE = "multi_format_bookrag"
LABEL = "Multi-Format BookRAG"
SKIP_VECTORSTORE_CREATE = False


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
    parts.append("VectorStore.create() uses bnode.content with key_columns=node_id.")
    return " ".join(parts)


def build_skip_create_message(summary: dict | None) -> str:
    if not summary:
        return "Step 2 completed. BookRAG tree tables finished and VectorStore.create() was skipped."

    raw_table_name = str(summary.get("raw_table_name") or "").strip()
    documents_table_name = str(summary.get("documents_table_name") or "").strip()
    blocks_table_name = str(summary.get("blocks_table_name") or "").strip()
    nodes_table_name = str(summary.get("nodes_table_name") or "").strip()
    raw_element_count = summary.get("raw_element_count")
    document_count = summary.get("document_count")
    block_count = summary.get("block_count")
    node_count = summary.get("node_count")

    parts = ["Step 2 completed. BookRAG tree tables finished."]
    table_parts: list[str] = []
    if documents_table_name:
        table_parts.append(f"bdoc={documents_table_name}")
    if raw_table_name:
        table_parts.append(f"braw={raw_table_name}")
    if blocks_table_name:
        table_parts.append(f"bblk={blocks_table_name}")
    if nodes_table_name:
        table_parts.append(f"bnode={nodes_table_name}")
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
    if count_parts:
        parts.append("Counts: " + ", ".join(count_parts) + ".")
    return " ".join(parts)
